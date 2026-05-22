from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest


class ArmsError(RuntimeError):
    pass


def _required_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise ArmsError(f"Missing env var: {key}")
    return value


def extract_trace_id_from_event_url(event_url: str | None) -> str | None:
    if not event_url:
        return None
    parsed = urlparse(event_url)
    qs = parse_qs(parsed.query)
    return qs.get("traceId", [None])[0] or qs.get("trace_id", [None])[0]


def sanitize_response(data: dict[str, Any]) -> dict[str, Any]:
    sensitive_patterns = [
        r"(phone|mobile|tel)[:\s]*['\"]?\d{11}",
        r"(token|password|secret|key|auth)[:\s]*['\"]?[\w\-]{8,}",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    ]
    text = json.dumps(data, ensure_ascii=False)
    for pattern in sensitive_patterns:
        text = re.sub(pattern, r"\1: [REDACTED]", text, flags=re.IGNORECASE)
    return json.loads(text)


def _call_arms_api(action: str, params: dict[str, Any]) -> dict[str, Any]:
    client = AcsClient(
        _required_env("ARMS_ACCESS_KEY_ID"),
        _required_env("ARMS_ACCESS_KEY_SECRET"),
        _required_env("ARMS_REGION_ID"),
    )
    request = CommonRequest()
    request.set_accept_format("json")
    request.set_domain("arms.aliyuncs.com")
    request.set_method("POST")
    request.set_protocol_type("https")
    request.set_version("2019-08-08")
    request.set_action_name(action)
    for key, value in params.items():
        if value is not None:
            request.add_query_param(key, str(value))
    response = client.do_action_with_exception(request)
    return json.loads(response)


def parse_source_mapped(raw_stack: str | None) -> dict[str, Any] | None:
    if not raw_stack:
        return None
    pattern = r"at\s+(\w+)\s+\(([^)]+)\)"
    matches = re.findall(pattern, raw_stack)
    for func_name, location in matches:
        if "node_modules" in location or "webpack/bootstrap" in location:
            continue
        loc_match = re.search(r"([^/\\]+\.(tsx?|jsx?|vue)):(\d+):(\d+)", location)
        if loc_match:
            return {
                "file": loc_match.group(1),
                "line": int(loc_match.group(3)),
                "column": int(loc_match.group(4)),
                "function": func_name,
                "raw_location": location,
            }
    return None


def get_error_detail(
    app: str,
    page: str = "",
    error_message: str = "",
    version: str = "",
    event_url: str = "",
) -> dict[str, Any]:
    now = datetime.utcnow()
    start_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_time = (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    trace_id = extract_trace_id_from_event_url(event_url)
    if not trace_id:
        search_params = {
            "RegionId": _required_env("ARMS_REGION_ID"),
            "AppName": app,
            "StartTime": start_time,
            "EndTime": end_time,
            "PageNumber": 1,
            "PageSize": 10,
            "PagePath": page or None,
            "ErrorMsg": error_message or None,
            "Version": version or None,
        }
        search_resp = _call_arms_api("SearchRumErrors", search_params)
        items = search_resp.get("Data", {}).get("Items", [])
        if not items:
            raise ArmsError("No matching RUM error found")
        trace_id = items[0].get("TraceId")

    detail_params = {
        "RegionId": _required_env("ARMS_REGION_ID"),
        "TraceId": trace_id,
        "AppName": app,
    }
    detail = _call_arms_api("GetRumError", detail_params).get("Data", {})
    raw_stack = detail.get("Stack", "")
    source_mapped = parse_source_mapped(raw_stack)

    user_behavior: list[dict[str, Any]] = []
    for event in detail.get("Events", [])[:5]:
        user_behavior.append(
            {
                "type": event.get("Type", "unknown"),
                "page": event.get("Page", page),
                "timestamp": event.get("Timestamp"),
            }
        )

    result = {
        "trace_id": trace_id,
        "source_mapped": source_mapped,
        "original_stack": raw_stack,
        "user_behavior": user_behavior,
        "browser": detail.get("Browser", "Unknown"),
        "device": detail.get("Device", "Unknown"),
        "first_occur_time": detail.get("FirstOccurTime"),
        "error_count": detail.get("ErrorCount", 1),
        "impact_users": detail.get("ImpactUserCount", 1),
        "app": app,
        "page": page,
        "version": version,
    }
    return sanitize_response(result)


def get_related_api(trace_id: str, app: str) -> dict[str, Any]:
    now = datetime.utcnow()
    start_time = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "RegionId": _required_env("ARMS_REGION_ID"),
        "TraceId": trace_id,
        "AppName": app,
        "StartTime": start_time,
        "EndTime": end_time,
    }
    records = _call_arms_api("GetRumApiRecords", params).get("Data", {}).get("Records", [])

    error_time = None
    for record in records:
        if record.get("IsError"):
            error_time = record.get("Timestamp")
            break

    related = None
    previous: list[dict[str, Any]] = []
    if error_time:
        for record in records:
            timestamp = record.get("Timestamp", "")
            if timestamp <= error_time and record.get("Url"):
                if not related and record.get("IsError"):
                    related = {
                        "url": record.get("Url"),
                        "method": record.get("Method", "GET"),
                        "status": record.get("Status", 0),
                        "response_preview": record.get("ResponsePreview", {}),
                        "request_time": timestamp,
                    }
                elif len(previous) < 3:
                    previous.append(
                        {
                            "url": record.get("Url"),
                            "method": record.get("Method", "GET"),
                            "status": record.get("Status", 0),
                            "response_preview": record.get("ResponsePreview", {}),
                            "request_time": timestamp,
                        }
                    )

    return {
        "related_api": related,
        "previous_api": previous,
        "total_records": len(records),
    }

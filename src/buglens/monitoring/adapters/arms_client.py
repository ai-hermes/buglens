from __future__ import annotations

import json
import random
import re
import threading
import time
from typing import Any

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_openapi.client import Client as OpenApiClient
from darabonba.runtime import RuntimeOptions

from buglens.monitoring.schemas.common import (
    AdapterResult,
    AtomicFilterDSL,
    MonitoringAdapterError,
    UnifiedErrorCode,
    decode_page_token,
    encode_page_token,
)


class ARMSClient:
    """Read-only ARMS API adapter via ARMS OpenAPI (2019-08-08)."""

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        region_id: str,
        security_token: str | None = None,
        endpoint: str = "arms.aliyuncs.com",
        read_timeout: int = 10,
        connect_timeout: int = 5,
        max_retries: int = 2,
        base_backoff_seconds: float = 0.25,
        max_backoff_seconds: float = 5.0,
        max_concurrency: int = 4,
    ) -> None:
        credentials_config = CredentialConfig(
            type="sts" if security_token else "access_key",
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            security_token=security_token or '',
        )
        credentials_client = CredentialClient(credentials_config)
        config = open_api_models.Config(credential=credentials_client)
        config.endpoint = endpoint
        config.read_timeout = read_timeout * 1000
        config.connect_timeout = connect_timeout * 1000
        self._client = OpenApiClient(config)
        self._runtime = RuntimeOptions()
        self._region_id = region_id
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._semaphore = threading.BoundedSemaphore(value=max(1, int(max_concurrency)))

    def search_traces(
        self,
        *,
        resource_group_id: str | None = None,
        time_from_ms: int,
        time_to_ms: int,
        page_size: int = 20,
        page_token: str | None = None,
        filters: AtomicFilterDSL | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> AdapterResult:
        token = decode_page_token(page_token)
        page = int(token.get("page", 1))
        query: dict[str, Any] = {
            "RegionId": self._region_id,
            "StartTime": time_from_ms,
            "EndTime": time_to_ms,
            "PageNumber": max(1, page),
            "PageSize": max(1, min(page_size, 100)),
        }
        if resource_group_id:
            query["ResourceGroupId"] = resource_group_id
        query.update(self._dsl_to_params(filters))
        if extra_params:
            query.update(extra_params)

        payload = self._call_action("SearchTraces", query)
        data = payload.get("Data", payload)
        items = data.get("Traces") or data.get("Items") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and query["PageNumber"] * query["PageSize"] < total:
            next_token = encode_page_token({"page": query["PageNumber"] + 1})

        return AdapterResult(
            data={"items": items, "total": total},
            request_id=payload.get("RequestId"),
            next_page_token=next_token,
        )

    def get_trace(self, *, trace_id: str, extra_params: dict[str, Any] | None = None) -> AdapterResult:
        query: dict[str, Any] = {"RegionId": self._region_id, "TraceID": trace_id}
        if extra_params:
            query.update(extra_params)
        payload = self._call_action("GetTrace", query)
        data = payload.get("Data", payload)
        return AdapterResult(data=data, request_id=payload.get("RequestId"))

    def get_multiple_traces(
        self,
        *,
        trace_ids: list[str],
        extra_params: dict[str, Any] | None = None,
    ) -> AdapterResult:
        if not trace_ids:
            return AdapterResult(data={"items": []})

        query: dict[str, Any] = {"RegionId": self._region_id, "TraceIDs": json.dumps(trace_ids)}
        if extra_params:
            query.update(extra_params)
        payload = self._call_action("GetMultipleTrace", query)
        data = payload.get("Data", payload)
        items = data.get("MultiCallChainInfos") or data.get("Items") or []
        return AdapterResult(data={"items": items, "failures": []}, request_id=payload.get("RequestId"))

    def query_metric_by_page(
        self,
        *,
        metric: str,
        time_from_ms: int,
        time_to_ms: int,
        page_size: int = 100,
        page_token: str | None = None,
        filters: AtomicFilterDSL | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> AdapterResult:
        token = decode_page_token(page_token)
        page = int(token.get("page", 1))
        query: dict[str, Any] = {
            "RegionId": self._region_id,
            "Metric": metric,
            "StartTime": time_from_ms,
            "EndTime": time_to_ms,
            "PageNumber": max(1, page),
            "PageSize": max(1, min(page_size, 200)),
        }
        query.update(self._dsl_to_params(filters))
        if extra_params:
            query.update(extra_params)

        payload = self._call_action("QueryMetricByPage", query)
        data = payload.get("Data", payload)
        items = data.get("Items") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and query["PageNumber"] * query["PageSize"] < total:
            next_token = encode_page_token({"page": query["PageNumber"] + 1})

        return AdapterResult(
            data={"items": items, "total": total},
            request_id=payload.get("RequestId"),
            next_page_token=next_token,
        )

    def list_insights_events(
        self,
        *,
        time_from_ms: int,
        time_to_ms: int,
        page_size: int = 20,
        page_token: str | None = None,
        filters: AtomicFilterDSL | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> AdapterResult:
        token = decode_page_token(page_token)
        page = int(token.get("page", 1))
        query: dict[str, Any] = {
            "RegionId": self._region_id,
            "StartTime": time_from_ms,
            "EndTime": time_to_ms,
            "PageNumber": max(1, page),
            "PageSize": max(1, min(page_size, 100)),
        }
        query.update(self._dsl_to_params(filters))
        if extra_params:
            query.update(extra_params)

        payload = self._call_action("ListInsightsEvents", query)
        data = payload.get("Data", payload)
        items = data.get("InsightsEvents") or data.get("Items") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and query["PageNumber"] * query["PageSize"] < total:
            next_token = encode_page_token({"page": query["PageNumber"] + 1})

        return AdapterResult(
            data={"items": items, "total": total},
            request_id=payload.get("RequestId"),
            next_page_token=next_token,
        )

    def _call_action(self, action_name: str, query: dict[str, Any]) -> dict[str, Any]:
        attempts = self._max_retries + 1
        last_error: MonitoringAdapterError | None = None
        params = open_api_models.Params(
            action=action_name,
            version="2019-08-08",
            protocol="HTTPS",
            method="POST",
            auth_type="AK",
            style="V3",
            pathname="/",
            req_body_type="json",
            body_type="json",
        )

        for idx in range(attempts):
            try:
                request = open_api_models.OpenApiRequest(query=self._normalize_query(query))
                with self._semaphore:
                    resp = self._client.call_api(params, request, self._runtime)
                payload = self._normalize_api_payload(resp)
                if not isinstance(payload, dict):
                    raise MonitoringAdapterError(
                        code=UnifiedErrorCode.UPSTREAM_ERROR,
                        message="ARMS response payload must be JSON object",
                    )
                return payload
            except MonitoringAdapterError as exc:
                last_error = exc
                if not exc.retriable or idx == attempts - 1:
                    raise
                self._backoff_sleep(idx, exc)
            except Exception as exc:  # noqa: BLE001
                mapped = self._map_exception(exc)
                last_error = mapped
                if not mapped.retriable or idx == attempts - 1:
                    raise mapped from exc
                self._backoff_sleep(idx, mapped)

        if last_error:
            raise last_error
        raise MonitoringAdapterError(
            code=UnifiedErrorCode.UPSTREAM_ERROR,
            message="ARMS request failed unexpectedly",
        )

    @staticmethod
    def _normalize_api_payload(resp: Any) -> dict[str, Any]:
        if hasattr(resp, "to_map"):
            resp = resp.to_map()
        if isinstance(resp, dict):
            body = resp.get("body", resp)
            if isinstance(body, dict):
                return body
            if isinstance(body, str):
                try:
                    parsed = json.loads(body)
                    return parsed if isinstance(parsed, dict) else {"data": parsed}
                except json.JSONDecodeError:
                    return {"data": body}
        if isinstance(resp, str):
            try:
                parsed = json.loads(resp)
                return parsed if isinstance(parsed, dict) else {"data": parsed}
            except json.JSONDecodeError:
                return {"data": resp}
        return {"data": resp}

    @staticmethod
    def _normalize_query(query: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in query.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                normalized[str(key)] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            else:
                normalized[str(key)] = str(value)
        return normalized

    def _map_exception(self, exc: Exception) -> MonitoringAdapterError:
        message = str(exc)
        code_text = (
            getattr(exc, "code", None)
            or getattr(exc, "error_code", None)
            or getattr(exc, "get_error_code", lambda: None)()
        )
        request_id = (
            getattr(exc, "request_id", None)
            or getattr(exc, "requestId", None)
            or self._extract_request_id_from_message(message)
        )
        upstream_status = (
            getattr(exc, "status_code", None)
            or getattr(exc, "statusCode", None)
            or getattr(exc, "http_status", None)
            or self._extract_http_status_from_message(message)
        )
        return self._map_error_meta(
            code_text=str(code_text) if code_text else None,
            message=message,
            request_id=request_id,
            upstream_status=upstream_status,
        )

    def _map_error_meta(
        self,
        *,
        code_text: str | None,
        message: str,
        request_id: str | None,
        upstream_status: int | None,
    ) -> MonitoringAdapterError:
        code_upper = str(code_text or "").upper()
        message_upper = message.upper()
        if "INVALIDACCESSKEY" in code_upper or "SIGNATURE" in code_upper or "SIGNATURE" in message_upper:
            code = UnifiedErrorCode.AUTH_FAILED
            retriable = False
        elif "FORBIDDEN" in code_upper or "NOAUTH" in code_upper or "ACCESSDENIED" in code_upper:
            code = UnifiedErrorCode.PERMISSION_DENIED
            retriable = False
        elif "THROTTL" in code_upper or "LIMIT" in code_upper or "TOOMANYREQUEST" in code_upper:
            code = UnifiedErrorCode.RATE_LIMITED
            retriable = True
        elif upstream_status in (429, 503):
            code = UnifiedErrorCode.RATE_LIMITED if upstream_status == 429 else UnifiedErrorCode.UPSTREAM_ERROR
            retriable = True
        elif "TIMEOUT" in code_upper or "TIMEOUT" in message_upper:
            code = UnifiedErrorCode.TIMEOUT
            retriable = True
        elif "INVALID" in code_upper or "MISSING" in code_upper:
            code = UnifiedErrorCode.INVALID_PARAM
            retriable = False
        else:
            code = UnifiedErrorCode.UPSTREAM_ERROR
            retriable = bool(upstream_status and upstream_status >= 500)

        return MonitoringAdapterError(
            code=code,
            message=message,
            request_id=request_id,
            retriable=retriable,
            upstream_status=upstream_status,
            upstream_code=code_text,
        )

    @staticmethod
    def _extract_http_status_from_message(message: str) -> int | None:
        matched = re.search(r"HTTP Status:\s*(\d{3})", message, re.IGNORECASE)
        if not matched:
            return None
        return int(matched.group(1))

    @staticmethod
    def _extract_request_id_from_message(message: str) -> str | None:
        matched = re.search(r"RequestID:\s*([A-Za-z0-9-]+)", message, re.IGNORECASE)
        if not matched:
            return None
        return matched.group(1)

    def _dsl_to_params(self, filters: AtomicFilterDSL | None) -> dict[str, Any]:
        if not filters:
            return {}
        params: dict[str, Any] = {}
        if filters.service:
            params["ServiceName"] = filters.service
        if filters.instance:
            params["InstanceId"] = filters.instance
        if filters.env:
            params["Environment"] = filters.env
        if filters.keyword:
            params["KeyWord"] = filters.keyword
        if filters.status_code is not None:
            params["StatusCode"] = str(filters.status_code)
        if filters.duration_range:
            lower, upper = filters.duration_range
            if lower is not None:
                params["MinDuration"] = int(lower)
            if upper is not None:
                params["MaxDuration"] = int(upper)
        if filters.tags:
            params["Tags"] = json.dumps(filters.tags, ensure_ascii=True, separators=(",", ":"))
        if filters.level:
            params["Level"] = filters.level
        return params

    def _backoff_sleep(self, attempt_idx: int, error: MonitoringAdapterError | None = None) -> None:
        aggressive = bool(
            error
            and (
                error.code == UnifiedErrorCode.RATE_LIMITED
                or error.upstream_status in (429, 503)
            )
        )
        backoff_base = self._base_backoff * (2 if aggressive else 1)
        jitter = random.uniform(0, backoff_base)
        delay = min(self._max_backoff, backoff_base * (2**attempt_idx) + jitter)
        time.sleep(delay)

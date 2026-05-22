from __future__ import annotations

import json
import random
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


class SLSClient:
    """RUM log adapter backed by ARMS OpenAPI (GetRumApps/GetRumDataForPage)."""

    def __init__(
        self,
        *,
        access_key_id: str,
        access_key_secret: str,
        region_id: str,
        security_token: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: int = 10,
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
        config.endpoint = endpoint or f"arms.{region_id}.aliyuncs.com"
        config.read_timeout = timeout_seconds * 1000
        config.connect_timeout = timeout_seconds * 1000
        self._client = OpenApiClient(config)
        self._runtime = RuntimeOptions()
        self._region_id = region_id
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._semaphore = threading.BoundedSemaphore(value=max(1, int(max_concurrency)))

    def list_projects(self, *, page_token: str | None = None, page_size: int = 100) -> AdapterResult:
        token = decode_page_token(page_token)
        offset = int(token.get("offset", 0))
        apps_payload = self._call_action("GetRumApps", {"RegionId": self._region_id})
        apps = apps_payload.get("AppList") or apps_payload.get("Data", {}).get("AppList") or []
        projects = sorted(
            {
                str(item.get("SlsProject"))
                for item in apps
                if isinstance(item, dict) and item.get("SlsProject")
            }
        )
        sliced = projects[offset : offset + max(1, min(page_size, 500))]
        next_token = None
        if offset + len(sliced) < len(projects):
            next_token = encode_page_token({"offset": offset + len(sliced)})
        return AdapterResult(
            data={"items": sliced, "total": len(projects)},
            request_id=apps_payload.get("RequestId"),
            next_page_token=next_token,
        )

    def list_logstores(
        self,
        *,
        project: str,
        page_token: str | None = None,
        page_size: int = 100,
    ) -> AdapterResult:
        token = decode_page_token(page_token)
        offset = int(token.get("offset", 0))
        apps_payload = self._call_action("GetRumApps", {"RegionId": self._region_id})
        apps = apps_payload.get("AppList") or apps_payload.get("Data", {}).get("AppList") or []
        logstores = sorted(
            {
                str(item.get("SlsLogstore"))
                for item in apps
                if isinstance(item, dict)
                and str(item.get("SlsProject", "")) == project
                and item.get("SlsLogstore")
            }
        )
        sliced = logstores[offset : offset + max(1, min(page_size, 500))]
        next_token = None
        if offset + len(sliced) < len(logstores):
            next_token = encode_page_token({"offset": offset + len(sliced)})
        return AdapterResult(
            data={"items": sliced, "total": len(logstores)},
            request_id=apps_payload.get("RequestId"),
            next_page_token=next_token,
        )

    def search_logs(
        self,
        *,
        project: str,
        logstore: str,
        time_from_ms: int,
        time_to_ms: int,
        filters: AtomicFilterDSL | None = None,
        page_token: str | None = None,
        page_size: int = 100,
        reverse: bool = False,
        extra_query: dict[str, Any] | None = None,
    ) -> AdapterResult:
        token = decode_page_token(page_token)
        page = int(token.get("page", 1))
        query_text = self._build_log_query(filters)
        if extra_query and extra_query.get("query"):
            query_text = str(extra_query["query"])

        query: dict[str, Any] = {
            "RegionId": self._region_id,
            "SlsProject": project,
            "SlsLogstore": logstore,
            "StartTime": int(time_from_ms / 1000),
            "EndTime": int(time_to_ms / 1000),
            "PageSize": max(1, min(page_size, 100)),
            "CurrentPage": max(1, page),
            "Query": query_text,
        }
        if reverse:
            query["Order"] = "desc"
        if extra_query:
            for key, value in extra_query.items():
                if key == "query" or value is None:
                    continue
                query[key] = value

        payload = self._call_action("GetRumDataForPage", query)
        data = payload.get("Data", payload)
        items = data.get("Items") or data.get("Logs") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and page * query["PageSize"] < total:
            next_token = encode_page_token({"page": page + 1})
        return AdapterResult(
            data={"items": items, "count": total if total else len(items)},
            request_id=payload.get("RequestId"),
            next_page_token=next_token,
        )

    def get_log_context(
        self,
        *,
        project: str,
        logstore: str,
        pack_id: str,
        pack_meta: str,
        back_lines: int = 20,
        forward_lines: int = 20,
    ) -> AdapterResult:
        # ARMS does not expose a dedicated context-log API. Query by pack hints as a best effort.
        query_parts = [f'"{pack_id}"', f'"{pack_meta}"']
        query = " and ".join(query_parts)
        page_size = max(1, min(back_lines + forward_lines + 1, 100))
        return self.search_logs(
            project=project,
            logstore=logstore,
            time_from_ms=int((time.time() - 3600) * 1000),
            time_to_ms=int(time.time() * 1000),
            page_size=page_size,
            extra_query={"query": query},
            reverse=False,
        )

    def get_log_histogram(
        self,
        *,
        project: str,
        logstore: str,
        time_from_ms: int,
        time_to_ms: int,
        filters: AtomicFilterDSL | None = None,
        extra_query: dict[str, Any] | None = None,
    ) -> AdapterResult:
        result = self.search_logs(
            project=project,
            logstore=logstore,
            time_from_ms=time_from_ms,
            time_to_ms=time_to_ms,
            filters=filters,
            page_size=100,
            extra_query=extra_query,
            reverse=False,
        )
        items = (result.data or {}).get("items") if isinstance(result.data, dict) else []
        if not isinstance(items, list):
            items = []
        bucket_size_ms = max(60_000, int((time_to_ms - time_from_ms) / 20)) if time_to_ms > time_from_ms else 60_000
        buckets: dict[int, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            ts = item.get("time") or item.get("timestamp") or item.get("__time__")
            if ts is None:
                continue
            try:
                ts_float = float(ts)
                ts_ms = int(ts_float) * (1000 if ts_float < 1e12 else 1)
            except Exception:  # noqa: BLE001
                continue
            bucket = ((ts_ms - time_from_ms) // bucket_size_ms) * bucket_size_ms + time_from_ms
            buckets[int(bucket)] = buckets.get(int(bucket), 0) + 1
        histogram = [{"time": k, "count": v} for k, v in sorted(buckets.items(), key=lambda x: x[0])]
        return AdapterResult(
            data={"histograms": histogram, "count": len(items)},
            request_id=result.request_id,
            next_page_token=None,
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
                        message="RUM response payload must be JSON object",
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
        raise MonitoringAdapterError(code=UnifiedErrorCode.UPSTREAM_ERROR, message="RUM request failed unexpectedly")

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

    @staticmethod
    def _map_exception(exc: Exception) -> MonitoringAdapterError:
        message = str(exc)
        status = (
            getattr(exc, "status_code", None)
            or getattr(exc, "statusCode", None)
            or (503 if "503" in message else 429 if "429" in message else None)
        )
        code_text = (
            getattr(exc, "code", None)
            or getattr(exc, "error_code", None)
            or "SignatureNotMatch"
            if "SIGNATURE" in message.upper()
            else None
        )
        if "SIGNATURE" in message.upper() or "INVALIDACCESSKEY" in str(code_text).upper():
            return MonitoringAdapterError(
                code=UnifiedErrorCode.AUTH_FAILED,
                message=message,
                retriable=False,
                upstream_status=status,
                upstream_code=str(code_text) if code_text else None,
            )
        if status == 429:
            return MonitoringAdapterError(
                code=UnifiedErrorCode.RATE_LIMITED,
                message=message,
                retriable=True,
                upstream_status=status,
                upstream_code=str(code_text) if code_text else None,
            )
        if status and status >= 500:
            return MonitoringAdapterError(
                code=UnifiedErrorCode.UPSTREAM_ERROR,
                message=message,
                retriable=True,
                upstream_status=status,
                upstream_code=str(code_text) if code_text else None,
            )
        return MonitoringAdapterError(
            code=UnifiedErrorCode.UPSTREAM_ERROR,
            message=message,
            retriable=False,
            upstream_status=status,
            upstream_code=str(code_text) if code_text else None,
        )

    @staticmethod
    def _build_log_query(filters: AtomicFilterDSL | None) -> str:
        if not filters:
            return "*"
        parts: list[str] = []
        if filters.keyword:
            parts.append(filters.keyword)
        if filters.service:
            parts.append(filters.service)
        if filters.instance:
            parts.append(filters.instance)
        if filters.env:
            parts.append(filters.env)
        if filters.level:
            parts.append(filters.level)
        if filters.status_code is not None:
            parts.append(str(filters.status_code))
        if filters.duration_range:
            lower, upper = filters.duration_range
            if lower is not None:
                parts.append(f"duration>={lower}")
            if upper is not None:
                parts.append(f"duration<={upper}")
        for key, value in filters.tags.items():
            parts.append(f"{key}:{value}")
        return " and ".join(parts) if parts else "*"

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

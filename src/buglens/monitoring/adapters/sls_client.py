from __future__ import annotations

import base64
import hashlib
import hmac
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any

import requests

from buglens.monitoring.schemas.common import (
    AdapterResult,
    AtomicFilterDSL,
    MonitoringAdapterError,
    UnifiedErrorCode,
    decode_page_token,
    encode_page_token,
)


class SLSClient:
    """Read-only SLS OpenAPI adapter (2020-12-30 ROA style endpoints)."""

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
        self._ak = access_key_id
        self._sk = access_key_secret
        self._sts = security_token
        self._region_id = region_id
        self._endpoint = endpoint or f"{region_id}.log.aliyuncs.com"
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._semaphore = threading.BoundedSemaphore(value=max(1, int(max_concurrency)))

    def list_projects(self, *, page_token: str | None = None, page_size: int = 100) -> AdapterResult:
        token = decode_page_token(page_token)
        offset = int(token.get("offset", 0))
        query = {
            "offset": max(0, offset),
            "size": max(1, min(page_size, 500)),
        }
        payload, request_id = self._request_json(method="GET", host=self._endpoint, path="/", query=query)
        items = payload.get("projects") or payload.get("Projects") or []
        next_token = None
        if len(items) >= query["size"]:
            next_token = encode_page_token({"offset": query["offset"] + query["size"]})

        return AdapterResult(
            data={"items": items, "total": payload.get("count")},
            request_id=request_id,
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
        query = {
            "offset": max(0, offset),
            "size": max(1, min(page_size, 500)),
        }
        payload, request_id = self._request_json(
            method="GET",
            host=self._project_host(project),
            path="/logstores",
            query=query,
        )
        items = payload.get("logstores") or payload.get("Logstores") or []
        next_token = None
        if len(items) >= query["size"]:
            next_token = encode_page_token({"offset": query["offset"] + query["size"]})

        return AdapterResult(
            data={"items": items, "total": payload.get("count")},
            request_id=request_id,
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
        offset = int(token.get("offset", 0))
        line = max(1, min(page_size, 100))
        query: dict[str, Any] = {
            "type": "log",
            "from": int(time_from_ms / 1000),
            "to": int(time_to_ms / 1000),
            "query": self._build_log_query(filters),
            "line": line,
            "offset": max(0, offset),
            "reverse": str(reverse).lower(),
        }
        if extra_query:
            query.update(extra_query)

        payload, request_id = self._request_json(
            method="GET",
            host=self._project_host(project),
            path=f"/logstores/{logstore}",
            query=query,
        )
        items = payload.get("logs") or payload.get("Logs") or payload.get("items") or []
        next_token = None
        if len(items) >= line:
            next_token = encode_page_token({"offset": query["offset"] + line})

        return AdapterResult(
            data={"items": items, "count": payload.get("count", len(items))},
            request_id=request_id,
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
        query = {
            "type": "context_log",
            "pack_id": pack_id,
            "pack_meta": pack_meta,
            "back_lines": max(0, back_lines),
            "forward_lines": max(0, forward_lines),
        }
        payload, request_id = self._request_json(
            method="GET",
            host=self._project_host(project),
            path=f"/logstores/{logstore}",
            query=query,
        )
        return AdapterResult(data=payload, request_id=request_id)

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
        query: dict[str, Any] = {
            "type": "histogram",
            "from": int(time_from_ms / 1000),
            "to": int(time_to_ms / 1000),
            "query": self._build_log_query(filters),
        }
        if extra_query:
            query.update(extra_query)

        payload, request_id = self._request_json(
            method="GET",
            host=self._project_host(project),
            path=f"/logstores/{logstore}",
            query=query,
        )
        return AdapterResult(data=payload, request_id=request_id)

    def _request_json(
        self,
        *,
        method: str,
        host: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[dict[str, Any], str | None]:
        query = query or {}
        ordered_query = {k: v for k, v in sorted(query.items(), key=lambda item: str(item[0]))}
        body = body or b""
        attempts = self._max_retries + 1
        last_error: MonitoringAdapterError | None = None

        for idx in range(attempts):
            headers = self._build_headers(
                method=method,
                host=host,
                path=path,
                query=ordered_query,
                body=body,
                content_type=content_type,
            )
            url = f"https://{host}{path}"
            try:
                with self._semaphore:
                    resp = requests.request(
                        method,
                        url,
                        params=ordered_query,
                        data=body,
                        headers=headers,
                        timeout=self._timeout,
                    )
            except requests.Timeout as exc:
                last_error = MonitoringAdapterError(code=UnifiedErrorCode.TIMEOUT, message="SLS request timeout", retriable=True)
                if idx == attempts - 1:
                    raise last_error from exc
                self._backoff_sleep(idx, last_error)
                continue

            request_id = resp.headers.get("x-log-requestid") or resp.headers.get("x-acs-request-id")
            if resp.status_code >= 400:
                mapped = self._map_http_error(resp.status_code, resp.text, request_id)
                last_error = mapped
                if not mapped.retriable or idx == attempts - 1:
                    raise mapped
                self._backoff_sleep(idx, mapped)
                continue

            if not resp.text:
                return {}, request_id
            try:
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001
                raise MonitoringAdapterError(
                    code=UnifiedErrorCode.UPSTREAM_ERROR,
                    message="SLS response is not valid JSON",
                    request_id=request_id,
                ) from exc

            if isinstance(payload, list):
                payload = {"items": payload}
            if not isinstance(payload, dict):
                raise MonitoringAdapterError(
                    code=UnifiedErrorCode.UPSTREAM_ERROR,
                    message="SLS response payload must be JSON object",
                    request_id=request_id,
                )
            return payload, request_id

        if last_error:
            raise last_error
        raise MonitoringAdapterError(code=UnifiedErrorCode.UPSTREAM_ERROR, message="SLS request failed unexpectedly")

    def _build_headers(
        self,
        *,
        method: str,
        host: str,
        path: str,
        query: dict[str, Any],
        body: bytes,
        content_type: str,
    ) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        date_header = format_datetime(now, usegmt=True)

        md5 = hashlib.md5(body).digest() if body else b""
        content_md5 = base64.b64encode(md5).decode("ascii") if body else ""

        headers: dict[str, str] = {
            "Host": host,
            "Date": date_header,
            "x-log-apiversion": "0.6.0",
            "x-log-signaturemethod": "hmac-sha1",
            "x-log-bodyrawsize": str(len(body)),
            "Content-Type": content_type,
        }
        if content_md5:
            headers["Content-MD5"] = content_md5
        if self._sts:
            headers["x-acs-security-token"] = self._sts

        canonical_headers = self._canonical_headers(headers)
        canonical_resource = self._canonical_resource(path, query)
        sign_text = "\n".join(
            [
                method.upper(),
                content_md5,
                content_type,
                date_header,
                canonical_headers + canonical_resource,
            ]
        )
        signature = base64.b64encode(
            hmac.new(self._sk.encode("utf-8"), sign_text.encode("utf-8"), hashlib.sha1).digest()
        ).decode("ascii")
        headers["Authorization"] = f"LOG {self._ak}:{signature}"
        return headers

    @staticmethod
    def _canonical_headers(headers: dict[str, str]) -> str:
        parts: list[str] = []
        for key, value in sorted(headers.items(), key=lambda x: x[0].lower()):
            lower = key.lower()
            if lower.startswith("x-log-") or lower.startswith("x-acs-"):
                parts.append(f"{lower}:{value.strip()}\n")
        return "".join(parts)

    @staticmethod
    def _canonical_resource(path: str, query: dict[str, Any]) -> str:
        if not query:
            return path
        items = [(str(k), str(v)) for k, v in query.items() if v is not None]
        items.sort(key=lambda x: x[0])
        # SLS signatures are generated against decoded canonical query pairs.
        query_str = "&".join(f"{k}={v}" for k, v in items)
        return f"{path}?{query_str}"

    @staticmethod
    def _map_http_error(status: int, body: str, request_id: str | None) -> MonitoringAdapterError:
        if status == 401:
            return MonitoringAdapterError(
                code=UnifiedErrorCode.AUTH_FAILED,
                message=f"SLS auth failed (401): {body[:300]}",
                request_id=request_id,
                upstream_status=status,
            )
        if status == 403:
            return MonitoringAdapterError(
                code=UnifiedErrorCode.PERMISSION_DENIED,
                message=f"SLS permission denied (403): {body[:300]}",
                request_id=request_id,
                upstream_status=status,
            )
        if status == 429:
            return MonitoringAdapterError(
                code=UnifiedErrorCode.RATE_LIMITED,
                message=f"SLS rate limited (429): {body[:300]}",
                request_id=request_id,
                retriable=True,
                upstream_status=status,
            )
        if status == 400:
            return MonitoringAdapterError(
                code=UnifiedErrorCode.INVALID_PARAM,
                message=f"SLS invalid parameter (400): {body[:300]}",
                request_id=request_id,
                upstream_status=status,
            )
        return MonitoringAdapterError(
            code=UnifiedErrorCode.UPSTREAM_ERROR,
            message=f"SLS upstream error ({status}): {body[:300]}",
            request_id=request_id,
            retriable=status >= 500,
            upstream_status=status,
        )

    @staticmethod
    def _build_log_query(filters: AtomicFilterDSL | None) -> str:
        if not filters:
            return "*"

        parts: list[str] = []
        if filters.keyword:
            parts.append(filters.keyword)
        if filters.service:
            parts.append(f"service:{filters.service}")
        if filters.instance:
            parts.append(f"instance:{filters.instance}")
        if filters.env:
            parts.append(f"env:{filters.env}")
        if filters.level:
            parts.append(f"level:{filters.level}")
        if filters.status_code is not None:
            parts.append(f"status:{filters.status_code}")
        if filters.duration_range:
            lower, upper = filters.duration_range
            if lower is not None:
                parts.append(f"duration>={lower}")
            if upper is not None:
                parts.append(f"duration<={upper}")
        for key, value in filters.tags.items():
            parts.append(f"{key}:{value}")

        return " and ".join(parts) if parts else "*"

    def _project_host(self, project: str) -> str:
        return f"{project}.{self._endpoint}"

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

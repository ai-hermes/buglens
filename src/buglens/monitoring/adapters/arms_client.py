from __future__ import annotations

import json
import random
import re
import threading
import time
from typing import Any

from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkcore.auth.credentials import StsTokenCredential
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest

from buglens.monitoring.schemas.common import (
    AdapterResult,
    AtomicFilterDSL,
    MonitoringAdapterError,
    UnifiedErrorCode,
    decode_page_token,
    encode_page_token,
)


class ARMSClient:
    """Read-only ARMS API adapter (2019-08-08 RPC)."""

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
        if security_token:
            credential = StsTokenCredential(access_key_id, access_key_secret, security_token)
            self._client = AcsClient(region_id=region_id, credential=credential)
        else:
            self._client = AcsClient(ak=access_key_id, secret=access_key_secret, region_id=region_id)
        self._region_id = region_id
        self._endpoint = endpoint
        self._read_timeout = read_timeout
        self._connect_timeout = connect_timeout
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
        params: dict[str, Any] = {
            "RegionId": self._region_id,
            "StartTime": time_from_ms,
            "EndTime": time_to_ms,
            "PageNumber": max(1, page),
            "PageSize": max(1, min(page_size, 100)),
        }
        if resource_group_id:
            params["ResourceGroupId"] = resource_group_id
        params.update(self._dsl_to_params(filters))
        if extra_params:
            params.update(extra_params)

        payload = self._call("SearchTraces", params)
        data = payload.get("Data", payload)
        items = data.get("Traces") or data.get("Items") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and params["PageNumber"] * params["PageSize"] < total:
            next_token = encode_page_token({"page": params["PageNumber"] + 1})

        return AdapterResult(data={"items": items, "total": total}, request_id=payload.get("RequestId"), next_page_token=next_token)

    def get_trace(self, *, trace_id: str, extra_params: dict[str, Any] | None = None) -> AdapterResult:
        params: dict[str, Any] = {"RegionId": self._region_id, "TraceID": trace_id}
        if extra_params:
            params.update(extra_params)
        payload = self._call("GetTrace", params)
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

        items: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        request_ids: list[str] = []
        for trace_id in trace_ids:
            try:
                result = self.get_trace(trace_id=trace_id, extra_params=extra_params)
                if result.request_id:
                    request_ids.append(result.request_id)
                if isinstance(result.data, dict):
                    items.append(result.data)
                else:
                    items.append({"trace_id": trace_id, "raw": result.data})
            except MonitoringAdapterError as exc:
                failures.append(
                    {
                        "trace_id": trace_id,
                        "code": exc.code.value,
                        "message": exc.message,
                        "request_id": exc.request_id,
                    }
                )

        return AdapterResult(
            data={"items": items, "failures": failures},
            request_id=request_ids[-1] if request_ids else None,
            partial_success=bool(failures),
        )

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
        params: dict[str, Any] = {
            "RegionId": self._region_id,
            "Metric": metric,
            "StartTime": time_from_ms,
            "EndTime": time_to_ms,
            "PageNumber": max(1, page),
            "PageSize": max(1, min(page_size, 200)),
        }
        params.update(self._dsl_to_params(filters))
        if extra_params:
            params.update(extra_params)

        payload = self._call("QueryMetricByPage", params)
        data = payload.get("Data", payload)
        items = data.get("Items") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and params["PageNumber"] * params["PageSize"] < total:
            next_token = encode_page_token({"page": params["PageNumber"] + 1})

        return AdapterResult(data={"items": items, "total": total}, request_id=payload.get("RequestId"), next_page_token=next_token)

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
        params: dict[str, Any] = {
            "RegionId": self._region_id,
            "StartTime": time_from_ms,
            "EndTime": time_to_ms,
            "PageNumber": max(1, page),
            "PageSize": max(1, min(page_size, 100)),
        }
        params.update(self._dsl_to_params(filters))
        if extra_params:
            params.update(extra_params)

        payload = self._call("ListInsightsEvents", params)
        data = payload.get("Data", payload)
        items = data.get("Items") or data.get("List") or []
        total = int(data.get("Total", 0) or 0)
        next_token = None
        if items and params["PageNumber"] * params["PageSize"] < total:
            next_token = encode_page_token({"page": params["PageNumber"] + 1})

        return AdapterResult(data={"items": items, "total": total}, request_id=payload.get("RequestId"), next_page_token=next_token)

    def _call(self, action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        request = CommonRequest()
        request.set_accept_format("json")
        request.set_domain(self._endpoint)
        request.set_version("2019-08-08")
        request.set_product("ARMS")
        request.set_protocol_type("https")
        request.set_method("POST")
        request.set_action_name(action_name)
        request.set_read_timeout(self._read_timeout)
        request.set_connect_timeout(self._connect_timeout)

        for key, value in params.items():
            if value is None:
                continue
            request.add_query_param(key, value)

        attempts = self._max_retries + 1
        last_error: MonitoringAdapterError | None = None
        for idx in range(attempts):
            try:
                with self._semaphore:
                    raw = self._client.do_action_with_exception(request)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise MonitoringAdapterError(
                        code=UnifiedErrorCode.UPSTREAM_ERROR,
                        message="ARMS response payload must be JSON object",
                    )
                return payload
            except (ServerException, ClientException) as exc:
                mapped = self._map_aliyun_error(exc)
                last_error = mapped
                if not mapped.retriable or idx == attempts - 1:
                    raise mapped
                self._backoff_sleep(idx, mapped)
            except TimeoutError as exc:
                last_error = MonitoringAdapterError(
                    code=UnifiedErrorCode.TIMEOUT,
                    message="ARMS request timeout",
                    retriable=True,
                )
                if idx == attempts - 1:
                    raise last_error from exc
                self._backoff_sleep(idx, last_error)

        if last_error:
            raise last_error
        raise MonitoringAdapterError(
            code=UnifiedErrorCode.UPSTREAM_ERROR,
            message="ARMS request failed unexpectedly",
        )

    def _map_aliyun_error(self, exc: ServerException | ClientException) -> MonitoringAdapterError:
        code_text = getattr(exc, "error_code", None) or getattr(exc, "get_error_code", lambda: None)()
        message = str(exc)
        request_id = getattr(exc, "request_id", None) or getattr(exc, "get_request_id", lambda: None)()
        upstream_status = (
            getattr(exc, "http_status", None)
            or getattr(exc, "status", None)
            or self._extract_http_status_from_message(message)
        )

        code_upper = str(code_text or "").upper()
        if "INVALIDACCESSKEY" in code_upper or "SIGNATURE" in code_upper:
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
        elif "TIMEOUT" in code_upper:
            code = UnifiedErrorCode.TIMEOUT
            retriable = True
        elif "INVALID" in code_upper or "MISSING" in code_upper:
            code = UnifiedErrorCode.INVALID_PARAM
            retriable = False
        else:
            code = UnifiedErrorCode.UPSTREAM_ERROR
            retriable = isinstance(exc, ServerException)

        return MonitoringAdapterError(
            code=code,
            message=message,
            request_id=request_id,
            retriable=retriable,
            upstream_status=upstream_status,
            upstream_code=str(code_text) if code_text else None,
        )

    @staticmethod
    def _extract_http_status_from_message(message: str) -> int | None:
        matched = re.search(r"HTTP Status:\s*(\d{3})", message, re.IGNORECASE)
        if not matched:
            return None
        return int(matched.group(1))

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
            # ARMS RPC accepts JSON-like string for mixed tag filters in multiple APIs.
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

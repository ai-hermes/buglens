from __future__ import annotations

import random
import threading
import time
from typing import Any

from alibabacloud_arms20190808 import models as arms_models
from alibabacloud_arms20190808.client import Client as ARMS20190808Client
from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_credentials.models import Config as CredentialConfig
from alibabacloud_tea_openapi import models as open_api_models
from darabonba.runtime import RuntimeOptions

from buglens.monitoring.schemas.common import (
    AdapterResult,
    MonitoringAdapterError,
    UnifiedErrorCode,
    decode_page_token,
    encode_page_token,
)


class ARMSClient:
    """RUM-focused ARMS adapter via OpenAPI (2019-08-08)."""

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
            security_token=security_token or "",
        )
        credentials_client = CredentialClient(credentials_config)
        config = open_api_models.Config(credential=credentials_client)
        config.endpoint = endpoint
        config.read_timeout = read_timeout * 1000
        config.connect_timeout = connect_timeout * 1000
        self._client = ARMS20190808Client(config)
        self._runtime = RuntimeOptions()
        self._region_id = region_id
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._semaphore = threading.BoundedSemaphore(value=max(1, int(max_concurrency)))

    def get_rum_apps(
        self,
        *,
        page_token: str | None = None,
        page_size: int = 100,
        extra_params: dict[str, Any] | None = None,
    ) -> AdapterResult:
        token = decode_page_token(page_token)
        page = int(token.get("page", 1))
        query: dict[str, Any] = {
            "RegionId": self._region_id,
            "CurrentPage": max(1, page),
            "PageSize": max(1, min(page_size, 100)),
        }
        if extra_params:
            query.update(extra_params)

        payload = self._call_get_rum_apps(query)
        data = payload.get("Data", payload)
        items = data.get("AppList") or payload.get("AppList") or []
        total = int(data.get("Total", 0) or payload.get("Total", 0) or 0)
        next_token = None
        if items and total and page * query["PageSize"] < total:
            next_token = encode_page_token({"page": page + 1})

        return AdapterResult(
            data={"items": items, "total": total if total else len(items)},
            request_id=payload.get("RequestId"),
            next_page_token=next_token,
        )

    def _call_get_rum_apps(self, query: dict[str, Any]) -> dict[str, Any]:
        attempts = self._max_retries + 1
        last_error: MonitoringAdapterError | None = None

        for idx in range(attempts):
            try:
                request = arms_models.GetRumAppsRequest()
                if hasattr(request, "from_map"):
                    request.from_map(query)
                else:
                    request.region_id = str(query.get("RegionId", self._region_id))
                    request.current_page = int(query.get("CurrentPage", 1))
                    request.page_size = int(query.get("PageSize", 100))
                with self._semaphore:
                    resp = self._client.get_rum_apps_with_options(request, self._runtime)
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
        return {"data": resp}

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

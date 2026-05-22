from __future__ import annotations

import base64
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class UnifiedErrorCode(str, Enum):
    AUTH_FAILED = "AUTH_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    INVALID_PARAM = "INVALID_PARAM"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"


class UnifiedError(BaseModel):
    code: UnifiedErrorCode
    message: str
    request_id: str | None = None
    retriable: bool = False
    upstream_status: int | None = None
    upstream_code: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class Envelope(BaseModel):
    success: bool
    request_id: str | None = None
    latency_ms: int = 0
    data: dict[str, Any] | list[Any] | None = None
    error: UnifiedError | None = None
    next_page_token: str | None = None
    partial_success: bool = False


class AtomicFilterDSL(BaseModel):
    service: str | None = None
    instance: str | None = None
    env: str | None = None
    level: str | None = None
    keyword: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    status_code: str | int | None = None
    duration_range: tuple[int | None, int | None] | None = None


class AdapterResult(BaseModel):
    data: dict[str, Any] | list[Any] | None = None
    request_id: str | None = None
    next_page_token: str | None = None
    partial_success: bool = False


class MonitoringAdapterError(RuntimeError):
    def __init__(
        self,
        *,
        code: UnifiedErrorCode,
        message: str,
        request_id: str | None = None,
        retriable: bool = False,
        upstream_status: int | None = None,
        upstream_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id
        self.retriable = retriable
        self.upstream_status = upstream_status
        self.upstream_code = upstream_code
        self.details = details or {}

    def to_error(self) -> UnifiedError:
        return UnifiedError(
            code=self.code,
            message=self.message,
            request_id=self.request_id,
            retriable=self.retriable,
            upstream_status=self.upstream_status,
            upstream_code=self.upstream_code,
            details=self.details,
        )


def encode_page_token(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_page_token(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    padded = token + "=" * ((4 - len(token) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        obj = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise MonitoringAdapterError(
            code=UnifiedErrorCode.INVALID_PARAM,
            message="Invalid page_token",
            details={"page_token": token},
        ) from exc
    if not isinstance(obj, dict):
        raise MonitoringAdapterError(
            code=UnifiedErrorCode.INVALID_PARAM,
            message="Invalid page_token payload",
            details={"page_token": token},
        )
    return obj

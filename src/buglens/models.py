from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InvokeRequest(BaseModel):
    task: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class InvokeResponse(BaseModel):
    output: str
    model: str
    session_id: str | None = None
    usage: dict[str, Any] | None = None
    raw_result: str | None = None

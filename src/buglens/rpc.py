from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .agent import SubAgent
from .models import InvokeRequest


class RpcError(BaseModel):
    code: int
    message: str
    data: dict[str, Any] | None = None


class RpcRequest(BaseModel):
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class RpcSuccessResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: dict[str, Any]


class RpcErrorResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    error: RpcError


def build_error(
    request_id: str | int | None,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return RpcErrorResponse(
        id=request_id, error=RpcError(code=code, message=message, data=data)
    ).model_dump(exclude_none=True)


async def dispatch_request(agent: SubAgent, payload: dict[str, Any]) -> dict[str, Any] | None:
    request_id = payload.get("id")
    try:
        request = RpcRequest.model_validate(payload)
    except ValidationError as exc:
        return build_error(
            request_id=request_id,
            code=-32600,
            message="Invalid Request",
            data={"errors": exc.errors()},
        )

    try:
        if request.method == "initialize":
            metadata = await agent.initialize(request.params.get("config", {}))
            result = {
                "name": metadata.name,
                "version": metadata.version,
                "capabilities": metadata.capabilities,
            }
        elif request.method == "health":
            result = await agent.health()
        elif request.method == "invoke":
            invoke_request = InvokeRequest.model_validate(request.params)
            invoke_result = await agent.invoke(invoke_request)
            result = invoke_result.model_dump(exclude_none=True)
        elif request.method == "shutdown":
            result = await agent.shutdown()
        else:
            return build_error(request.id, -32601, f"Method not found: {request.method}")
    except ValidationError as exc:
        return build_error(
            request.id,
            -32602,
            "Invalid params",
            data={"errors": exc.errors()},
        )
    except TimeoutError as exc:
        return build_error(request.id, -32001, "Request timed out", data={"detail": str(exc)})
    except Exception as exc:  # pragma: no cover - generic guard
        return build_error(request.id, -32000, "Internal error", data={"detail": str(exc)})

    if request.id is None:
        return None
    return RpcSuccessResponse(id=request.id, result=result).model_dump(exclude_none=True)

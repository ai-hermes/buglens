from buglens.agent import SubAgent
from buglens.rpc import dispatch_request


async def test_rpc_method_not_found() -> None:
    response = await dispatch_request(
        SubAgent(), {"jsonrpc": "2.0", "id": 1, "method": "unknown", "params": {}}
    )
    assert response is not None
    assert response["error"]["code"] == -32601


async def test_rpc_initialize_health_shutdown() -> None:
    agent = SubAgent()
    init_response = await dispatch_request(
        agent,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"config": {"mock_response": "ok"}},
        },
    )
    assert init_response is not None
    assert init_response["result"]["name"] == "buglens"

    health_response = await dispatch_request(
        agent, {"jsonrpc": "2.0", "id": 2, "method": "health", "params": {}}
    )
    assert health_response is not None
    assert health_response["result"]["status"] == "ok"

    shutdown_response = await dispatch_request(
        agent, {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}
    )
    assert shutdown_response is not None
    assert shutdown_response["result"]["stopped"] is True

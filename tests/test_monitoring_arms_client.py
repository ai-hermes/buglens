from __future__ import annotations

from buglens.monitoring.adapters.arms_client import ARMSClient
from buglens.monitoring.schemas.common import AtomicFilterDSL, MonitoringAdapterError, UnifiedErrorCode


def _build_client() -> ARMSClient:
    return ARMSClient(
        access_key_id="ak",
        access_key_secret="sk",
        region_id="cn-hangzhou",
    )


def test_search_traces_maps_and_paginates(monkeypatch) -> None:
    client = _build_client()

    def fake_call_action(_action: str, _query: dict) -> dict:
        return {
            "RequestId": "req-1",
            "Data": {
                "Traces": [{"traceId": "t1"}, {"traceId": "t2"}],
                "Total": 3,
            },
        }

    monkeypatch.setattr(client, "_call_action", fake_call_action)

    result = client.search_traces(
        time_from_ms=1,
        time_to_ms=2,
        page_size=2,
        filters=AtomicFilterDSL(service="svc", tags={"env": "prod"}),
    )

    assert result.request_id == "req-1"
    assert result.data["total"] == 3
    assert result.next_page_token is not None


def test_get_multiple_traces_maps_payload(monkeypatch) -> None:
    client = _build_client()

    def fake_call_action(_action: str, _query: dict) -> dict:
        return {
            "RequestId": "req-multi",
            "Data": {"MultiCallChainInfos": [{"traceId": "a"}, {"traceId": "b"}]},
        }

    monkeypatch.setattr(client, "_call_action", fake_call_action)
    result = client.get_multiple_traces(trace_ids=["a", "b"])

    assert result.request_id == "req-multi"
    assert result.data == {"items": [{"traceId": "a"}, {"traceId": "b"}], "failures": []}


def test_map_exception_503_as_retriable_upstream_error() -> None:
    client = _build_client()
    mapped = client._map_exception(RuntimeError("HTTP Status: 503 ServiceUnavailable RequestID: rid-1"))  # noqa: SLF001
    assert mapped.code == UnifiedErrorCode.UPSTREAM_ERROR
    assert mapped.retriable is True
    assert mapped.upstream_status == 503


def test_map_exception_signature_as_auth_failed() -> None:
    client = _build_client()
    mapped = client._map_exception(RuntimeError("SignatureNotMatch request rejected"))  # noqa: SLF001
    assert mapped.code == UnifiedErrorCode.AUTH_FAILED
    assert mapped.retriable is False


def test_call_action_retries_when_retriable(monkeypatch) -> None:
    client = _build_client()
    attempts = {"n": 0}

    def fake_call_api(*_args, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("HTTP Status: 503 service busy")
        return {"body": {"RequestId": "ok"}}

    monkeypatch.setattr(client._client, "call_api", fake_call_api)  # noqa: SLF001
    monkeypatch.setattr(client, "_backoff_sleep", lambda *_a, **_k: None)

    payload = client._call_action("SearchTraces", {"RegionId": "cn-hangzhou"})  # noqa: SLF001
    assert attempts["n"] == 2
    assert payload["RequestId"] == "ok"


def test_call_action_raises_non_retriable(monkeypatch) -> None:
    client = _build_client()

    def fake_call_api(*_args, **_kwargs):
        raise RuntimeError("SignatureNotMatch")

    monkeypatch.setattr(client._client, "call_api", fake_call_api)  # noqa: SLF001

    try:
        client._call_action("SearchTraces", {"RegionId": "cn-hangzhou"})  # noqa: SLF001
    except MonitoringAdapterError as exc:
        assert exc.code == UnifiedErrorCode.AUTH_FAILED
    else:  # pragma: no cover
        raise AssertionError("expected MonitoringAdapterError")

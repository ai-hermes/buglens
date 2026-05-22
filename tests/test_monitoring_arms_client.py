from __future__ import annotations

from aliyunsdkcore.acs_exception.exceptions import ServerException

from buglens.monitoring.adapters.arms_client import ARMSClient
from buglens.monitoring.schemas.common import AtomicFilterDSL, AdapterResult, MonitoringAdapterError, UnifiedErrorCode


class _FakeAcsClient:
    def __init__(self, payload: dict):
        self.payload = payload

    def do_action_with_exception(self, _request):
        import json

        return json.dumps(self.payload).encode("utf-8")


def _build_client(payload: dict) -> ARMSClient:
    client = ARMSClient(
        access_key_id="ak",
        access_key_secret="sk",
        region_id="cn-hangzhou",
    )
    client._client = _FakeAcsClient(payload)  # noqa: SLF001
    return client


def test_search_traces_maps_and_paginates() -> None:
    client = _build_client(
        {
            "RequestId": "req-1",
            "Data": {
                "Traces": [{"traceId": "t1"}, {"traceId": "t2"}],
                "Total": 3,
            },
        }
    )

    result = client.search_traces(
        time_from_ms=1,
        time_to_ms=2,
        page_size=2,
        filters=AtomicFilterDSL(service="svc", tags={"env": "prod"}),
    )

    assert result.request_id == "req-1"
    assert result.data["total"] == 3
    assert result.next_page_token is not None


def test_get_multiple_traces_partial_success() -> None:
    client = _build_client({"RequestId": "req", "Data": {"traceId": "ok"}})

    def fake_get_trace(*, trace_id: str, extra_params=None):
        if trace_id == "bad":
            raise MonitoringAdapterError(code=UnifiedErrorCode.UPSTREAM_ERROR, message="boom")
        return AdapterResult(data={"traceId": trace_id}, request_id=f"req-{trace_id}")

    client.get_trace = fake_get_trace  # type: ignore[method-assign]

    result = client.get_multiple_traces(trace_ids=["ok", "bad"])

    assert result.partial_success is True
    assert len(result.data["items"]) == 1
    assert len(result.data["failures"]) == 1


def test_map_aliyun_503_as_retriable_upstream_error() -> None:
    client = _build_client({"RequestId": "req"})
    exc = ServerException("ServiceUnavailable", "HTTP Status: 503 service busy", 503, "req-503")

    mapped = client._map_aliyun_error(exc)  # noqa: SLF001

    assert mapped.code == UnifiedErrorCode.UPSTREAM_ERROR
    assert mapped.retriable is True
    assert mapped.upstream_status == 503

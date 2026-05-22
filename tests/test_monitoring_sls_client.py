from __future__ import annotations

from buglens.monitoring.adapters.sls_client import SLSClient
from buglens.monitoring.schemas.common import MonitoringAdapterError, UnifiedErrorCode


def _build_client() -> SLSClient:
    return SLSClient(
        access_key_id="ak",
        access_key_secret="sk",
        region_id="cn-hangzhou",
        max_retries=1,
        base_backoff_seconds=0.001,
        max_backoff_seconds=0.001,
    )


def test_list_projects_from_rum_apps(monkeypatch) -> None:
    client = _build_client()

    def fake_call_action(_action: str, _query: dict) -> dict:
        return {
            "RequestId": "rid-1",
            "AppList": [
                {"SlsProject": "p1", "SlsLogstore": "l1"},
                {"SlsProject": "p2", "SlsLogstore": "l2"},
                {"SlsProject": "p1", "SlsLogstore": "l3"},
            ],
        }

    monkeypatch.setattr(client, "_call_action", fake_call_action)
    result = client.list_projects()
    assert result.request_id == "rid-1"
    assert result.data == {"items": ["p1", "p2"], "total": 2}


def test_list_logstores_filters_by_project(monkeypatch) -> None:
    client = _build_client()

    def fake_call_action(_action: str, _query: dict) -> dict:
        return {
            "RequestId": "rid-2",
            "Data": {
                "AppList": [
                    {"SlsProject": "p1", "SlsLogstore": "l1"},
                    {"SlsProject": "p2", "SlsLogstore": "l2"},
                    {"SlsProject": "p1", "SlsLogstore": "l3"},
                ]
            },
        }

    monkeypatch.setattr(client, "_call_action", fake_call_action)
    result = client.list_logstores(project="p1")
    assert result.request_id == "rid-2"
    assert result.data == {"items": ["l1", "l3"], "total": 2}


def test_search_logs_maps_rum_data_for_page(monkeypatch) -> None:
    client = _build_client()

    def fake_call_action(action: str, query: dict) -> dict:
        assert action == "GetRumDataForPage"
        assert query["SlsProject"] == "p1"
        assert query["SlsLogstore"] == "l1"
        return {
            "RequestId": "rid-3",
            "Data": {"Items": [{"msg": "boom"}], "Total": 1},
        }

    monkeypatch.setattr(client, "_call_action", fake_call_action)
    result = client.search_logs(
        project="p1",
        logstore="l1",
        time_from_ms=1000,
        time_to_ms=2000,
        extra_query={"query": "RUM_SYNC_ERROR"},
    )
    assert result.request_id == "rid-3"
    assert result.data == {"items": [{"msg": "boom"}], "count": 1}


def test_sls_retries_on_503_then_succeeds(monkeypatch) -> None:
    client = _build_client()
    calls = {"count": 0}

    def fake_call_api(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("HTTP Status: 503 busy")
        return {"body": {"RequestId": "rid-ok", "Data": {"Items": []}}}

    monkeypatch.setattr(client._client, "call_api", fake_call_api)  # noqa: SLF001
    monkeypatch.setattr(client, "_backoff_sleep", lambda *_a, **_k: None)

    payload = client._call_action("GetRumDataForPage", {"RegionId": "cn-hangzhou"})  # noqa: SLF001
    assert calls["count"] == 2
    assert payload["RequestId"] == "rid-ok"


def test_sls_map_signature_to_auth_failed() -> None:
    client = _build_client()
    mapped = client._map_exception(RuntimeError("SignatureNotMatch"))  # noqa: SLF001
    assert mapped.code == UnifiedErrorCode.AUTH_FAILED
    assert mapped.retriable is False


def test_sls_call_action_raises_non_retriable(monkeypatch) -> None:
    client = _build_client()

    def fake_call_api(*_args, **_kwargs):
        raise RuntimeError("SignatureNotMatch")

    monkeypatch.setattr(client._client, "call_api", fake_call_api)  # noqa: SLF001

    try:
        client._call_action("GetRumDataForPage", {"RegionId": "cn-hangzhou"})  # noqa: SLF001
    except MonitoringAdapterError as exc:
        assert exc.code == UnifiedErrorCode.AUTH_FAILED
    else:  # pragma: no cover
        raise AssertionError("expected MonitoringAdapterError")

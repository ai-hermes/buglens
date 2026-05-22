from __future__ import annotations

from buglens.monitoring.adapters.arms_client import ARMSClient
from buglens.monitoring.schemas.common import MonitoringAdapterError, UnifiedErrorCode


def _build_client() -> ARMSClient:
    return ARMSClient(
        access_key_id="ak",
        access_key_secret="sk",
        region_id="cn-hangzhou",
    )


def test_get_rum_apps_maps_and_paginates(monkeypatch) -> None:
    client = _build_client()

    def fake_call_get_rum_apps(_query: dict) -> dict:
        return {
            "RequestId": "req-1",
            "Data": {
                "AppList": [{"pid": "a"}, {"pid": "b"}],
                "Total": 3,
            },
        }

    monkeypatch.setattr(client, "_call_get_rum_apps", fake_call_get_rum_apps)

    result = client.get_rum_apps(page_size=2)

    assert result.request_id == "req-1"
    assert result.data["total"] == 3
    assert result.next_page_token is not None


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


def test_call_get_rum_apps_retries_when_retriable(monkeypatch) -> None:
    client = _build_client()
    attempts = {"n": 0}

    def fake_get_rum_apps_with_options(*_args, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("HTTP Status: 503 service busy")
        return {"body": {"RequestId": "ok"}}

    monkeypatch.setattr(client._client, "get_rum_apps_with_options", fake_get_rum_apps_with_options)  # noqa: SLF001
    monkeypatch.setattr(client, "_backoff_sleep", lambda *_a, **_k: None)

    payload = client._call_get_rum_apps({"RegionId": "cn-hangzhou"})  # noqa: SLF001
    assert attempts["n"] == 2
    assert payload["RequestId"] == "ok"


def test_call_get_rum_apps_raises_non_retriable(monkeypatch) -> None:
    client = _build_client()

    def fake_get_rum_apps_with_options(*_args, **_kwargs):
        raise RuntimeError("SignatureNotMatch")

    monkeypatch.setattr(client._client, "get_rum_apps_with_options", fake_get_rum_apps_with_options)  # noqa: SLF001

    try:
        client._call_get_rum_apps({"RegionId": "cn-hangzhou"})  # noqa: SLF001
    except MonitoringAdapterError as exc:
        assert exc.code == UnifiedErrorCode.AUTH_FAILED
    else:  # pragma: no cover
        raise AssertionError("expected MonitoringAdapterError")

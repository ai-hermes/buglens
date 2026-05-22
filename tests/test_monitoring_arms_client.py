from __future__ import annotations

from types import SimpleNamespace

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
                "AppList": [
                    {
                        "AppType": "web",
                        "Description": "app-a",
                        "Endpoint": "https://example-a",
                        "Pid": "a",
                        "RegionId": "cn-hangzhou",
                        "SlsLogstore": "rum-a",
                        "SlsProject": "proj-a",
                        "Type": "rum",
                    },
                    {"Pid": "b"},
                ],
                "Total": 3,
            },
        }

    monkeypatch.setattr(client, "_call_get_rum_apps", fake_call_get_rum_apps)

    result = client.get_rum_apps(page_size=2)

    assert result.request_id == "req-1"
    assert result.data["total"] == 3
    assert result.data["items"][0] == {
        "app_type": "web",
        "description": "app-a",
        "endpoint": "https://example-a",
        "pid": "a",
        "region_id": "cn-hangzhou",
        "sls_logstore": "rum-a",
        "sls_project": "proj-a",
        "type": "rum",
    }
    assert result.data["items"][1]["pid"] == "b"
    assert set(result.data["items"][1].keys()) == {
        "app_type",
        "description",
        "endpoint",
        "pid",
        "region_id",
        "sls_logstore",
        "sls_project",
        "type",
    }
    assert result.next_page_token is not None


def test_normalize_api_payload_supports_body_app_list_objects() -> None:
    resp = SimpleNamespace(
        body=SimpleNamespace(
            app_list=[
                SimpleNamespace(
                    app_type="web",
                    description="desc",
                    endpoint="https://example.local",
                    pid="pid-1",
                    region_id="cn-hangzhou",
                    sls_logstore="logstore-1",
                    sls_project="project-1",
                    type="rum",
                )
            ],
            total=1,
            request_id="req-obj-1",
        )
    )

    payload = ARMSClient._normalize_api_payload(resp)  # noqa: SLF001
    assert payload["RequestId"] == "req-obj-1"
    assert payload["Total"] == 1
    assert payload["AppList"] == [
        {
            "AppType": "web",
            "Description": "desc",
            "Endpoint": "https://example.local",
            "Pid": "pid-1",
            "RegionId": "cn-hangzhou",
            "SlsLogstore": "logstore-1",
            "SlsProject": "project-1",
            "Type": "rum",
        }
    ]


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


def test_get_rum_exception_stack_builds_fixed_stack(monkeypatch) -> None:
    client = _build_client()
    seen_query: dict[str, object] = {}

    def fake_call_get_rum_exception_stack(query: dict) -> dict:
        seen_query.update(query)
        return {"RequestId": "stack-1", "Data": {"Resolved": True}}

    monkeypatch.setattr(client, "_call_get_rum_exception_stack", fake_call_get_rum_exception_stack)

    result = client.get_rum_exception_stack(pid="pid-1", line=245, column=16085)

    assert seen_query["Pid"] == "pid-1"
    assert seen_query["ExceptionStack"] == "245,16085,20"
    assert seen_query["SourcemapType"] == "js"
    assert (
        seen_query["ExceptionBinaryImages"] == ARMSClient.DEFAULT_EXCEPTION_BINARY_IMAGES
    )
    assert result.request_id == "stack-1"
    assert result.data == {
        "result": {"Resolved": True},
        "exception_stack": "245,16085,20",
    }


def test_get_rum_exception_stack_allows_override(monkeypatch) -> None:
    client = _build_client()
    seen_query: dict[str, object] = {}

    def fake_call_get_rum_exception_stack(query: dict) -> dict:
        seen_query.update(query)
        return {"RequestId": "stack-2"}

    monkeypatch.setattr(client, "_call_get_rum_exception_stack", fake_call_get_rum_exception_stack)

    result = client.get_rum_exception_stack(
        pid="pid-2",
        line=1,
        column=2,
        sourcemap_type="miniapp",
        exception_binary_images='{"custom":"yes"}',
    )

    assert seen_query["ExceptionStack"] == "1,2,20"
    assert seen_query["SourcemapType"] == "miniapp"
    assert seen_query["ExceptionBinaryImages"] == '{"custom":"yes"}'
    assert result.request_id == "stack-2"

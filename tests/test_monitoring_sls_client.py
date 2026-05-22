from __future__ import annotations

import requests

from buglens.monitoring.adapters.sls_client import SLSClient
from buglens.monitoring.schemas.common import UnifiedErrorCode


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str,
        payload: dict | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}
        self.headers = {}
        if request_id:
            self.headers["x-log-requestid"] = request_id

    def json(self) -> dict:
        return self._payload


def test_sls_retries_on_503_then_succeeds(monkeypatch) -> None:
    client = SLSClient(
        access_key_id="ak",
        access_key_secret="sk",
        region_id="cn-hangzhou",
        max_retries=1,
        base_backoff_seconds=0.001,
        max_backoff_seconds=0.001,
    )

    calls = {"count": 0}

    def fake_request(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["count"] += 1
        if calls["count"] == 1:
            return _FakeResponse(status_code=503, text="busy", request_id="rid-1")
        return _FakeResponse(
            status_code=200,
            text='{"projects":["p1"],"count":1}',
            payload={"projects": ["p1"], "count": 1},
            request_id="rid-2",
        )

    monkeypatch.setattr(requests, "request", fake_request)
    monkeypatch.setattr(client, "_backoff_sleep", lambda *_args, **_kwargs: None)

    result = client.list_projects()

    assert calls["count"] == 2
    assert result.request_id == "rid-2"
    assert result.data == {"items": ["p1"], "total": 1}


def test_sls_map_503_is_retriable_upstream_error() -> None:
    mapped = SLSClient._map_http_error(503, "service unavailable", "rid-503")  # noqa: SLF001
    assert mapped.code == UnifiedErrorCode.UPSTREAM_ERROR
    assert mapped.retriable is True
    assert mapped.upstream_status == 503

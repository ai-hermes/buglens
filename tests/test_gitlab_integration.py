from __future__ import annotations

import json

from buglens.integrations import gitlab


class _FakeResponse:
    def __init__(self, status_code: int, data: object):
        self.status_code = status_code
        self._data = data
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self):
        return self._data


def test_list_projects_calls_global_projects_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")

    captured: dict[str, object] = {}

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["params"] = params
        captured["timeout"] = timeout
        return _FakeResponse(
            200,
            [
                {
                    "id": 101,
                    "name": "demo",
                    "path_with_namespace": "team/demo",
                    "default_branch": "main",
                    "visibility": "private",
                    "web_url": "https://gitlab.example.com/team/demo",
                    "last_activity_at": "2026-01-01T00:00:00Z",
                }
            ],
        )

    monkeypatch.setattr(gitlab.requests, "request", fake_request)

    result = gitlab.list_projects(search="demo", page=1, per_page=20)

    assert captured["method"] == "GET"
    assert captured["url"] == "https://gitlab.example.com/api/v4/projects"
    assert captured["params"]["search"] == "demo"
    assert result["count"] == 1
    assert result["projects"][0]["path_with_namespace"] == "team/demo"

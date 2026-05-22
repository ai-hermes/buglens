from __future__ import annotations

import base64
import os
import urllib.parse
from typing import Any

import requests


class GitLabError(RuntimeError):
    pass


class GitLabAuthError(GitLabError):
    pass


class GitLabPermissionError(GitLabError):
    pass


class GitLabNotFoundError(GitLabError):
    pass


class GitLabRateLimitError(GitLabError):
    pass


class GitLabValidationError(GitLabError):
    pass


def _required_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise GitLabError(f"Missing env var: {key}")
    return value


def _gitlab_base() -> str:
    return _required_env("GITLAB_URL").rstrip("/")


def _gitlab_headers() -> dict[str, str]:
    return {"PRIVATE-TOKEN": _required_env("GITLAB_TOKEN")}


def _resolve_project_id(project_id: str | None = None) -> str:
    if project_id:
        return project_id
    value = os.environ.get("GITLAB_PROJECT_ID")
    if value:
        return value
    raise GitLabError("Missing project_id argument and GITLAB_PROJECT_ID env var")


def _sanitize_pagination(page: int, per_page: int) -> tuple[int, int]:
    safe_page = max(1, int(page))
    safe_per_page = min(100, max(1, int(per_page)))
    return safe_page, safe_per_page


def _raise_response_error(response: requests.Response) -> None:
    status = response.status_code
    body = response.text[:400]
    if status == 401:
        raise GitLabAuthError(f"GitLab auth failed (401): {body}")
    if status == 403:
        raise GitLabPermissionError(f"GitLab permission denied (403): {body}")
    if status == 404:
        raise GitLabNotFoundError(f"GitLab resource not found (404): {body}")
    if status == 429:
        raise GitLabRateLimitError(f"GitLab rate limited (429): {body}")
    if status == 400:
        raise GitLabValidationError(f"GitLab validation error (400): {body}")
    raise GitLabError(f"GitLab API error status={status}: {body}")


def _request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> requests.Response:
    response = requests.request(
        method,
        url,
        headers=_gitlab_headers(),
        params=params,
        json=json_body,
        timeout=timeout,
    )
    if response.status_code >= 400:
        _raise_response_error(response)
    return response


def _request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    return _request(method, url, params=params, json_body=json_body, timeout=timeout).json()


def _project_api_base(project_id: str | None = None) -> str:
    project = urllib.parse.quote(str(_resolve_project_id(project_id)), safe="")
    return f"{_gitlab_base()}/api/v4/projects/{project}"


def _global_api_base() -> str:
    return f"{_gitlab_base()}/api/v4"


def list_projects(
    search: str = "",
    membership: bool = False,
    owned: bool = False,
    page: int = 1,
    per_page: int = 20,
    simple: bool = True,
    archived: bool | None = None,
    visibility: str = "",
) -> dict[str, Any]:
    page, per_page = _sanitize_pagination(page, per_page)
    params: dict[str, Any] = {
        "page": page,
        "per_page": per_page,
        "simple": simple,
        "membership": membership,
        "owned": owned,
    }
    if search:
        params["search"] = search
    if archived is not None:
        params["archived"] = archived
    if visibility:
        params["visibility"] = visibility

    data = _request_json("GET", f"{_global_api_base()}/projects", params=params)
    items = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "path_with_namespace": item.get("path_with_namespace"),
            "default_branch": item.get("default_branch"),
            "visibility": item.get("visibility"),
            "web_url": item.get("web_url"),
            "last_activity_at": item.get("last_activity_at"),
        }
        for item in data
    ]
    return {"projects": items, "page": page, "per_page": per_page, "count": len(items)}


def search_projects(query: str, page: int = 1, per_page: int = 20) -> dict[str, Any]:
    return list_projects(search=query, page=page, per_page=per_page)


def get_project(project_id: str | int) -> dict[str, Any]:
    encoded = urllib.parse.quote(str(project_id), safe="")
    item = _request_json("GET", f"{_global_api_base()}/projects/{encoded}")
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "path_with_namespace": item.get("path_with_namespace"),
        "default_branch": item.get("default_branch"),
        "visibility": item.get("visibility"),
        "web_url": item.get("web_url"),
        "ssh_url_to_repo": item.get("ssh_url_to_repo"),
        "http_url_to_repo": item.get("http_url_to_repo"),
        "last_activity_at": item.get("last_activity_at"),
    }


def get_file(file_path: str, ref: str = "main", project_id: str | None = None) -> dict[str, Any]:
    encoded_path = urllib.parse.quote(file_path, safe="")
    data = _request_json(
        "GET",
        f"{_project_api_base(project_id)}/repository/files/{encoded_path}",
        params={"ref": ref},
    )
    content = data.get("content", "")
    decoded = ""
    if isinstance(content, str) and data.get("encoding") == "base64":
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    return {
        "file_path": data.get("file_path", file_path),
        "ref": ref,
        "size": data.get("size"),
        "encoding": data.get("encoding"),
        "content": decoded,
        "blob_id": data.get("blob_id"),
        "last_commit_id": data.get("last_commit_id"),
    }


def list_branches(project_id: str | None = None, search: str = "") -> dict[str, Any]:
    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    data = _request_json("GET", f"{_project_api_base(project_id)}/repository/branches", params=params)
    branches = [
        {
            "name": item.get("name"),
            "protected": item.get("protected"),
            "default": item.get("default"),
            "merged": item.get("merged"),
            "web_url": item.get("web_url"),
            "commit": {
                "id": (item.get("commit", {}).get("id") or "")[:8],
                "title": item.get("commit", {}).get("title"),
                "committed_date": item.get("commit", {}).get("committed_date"),
            },
        }
        for item in data
    ]
    return {"branches": branches, "count": len(branches)}


def get_branch(branch: str, project_id: str | None = None) -> dict[str, Any]:
    encoded = urllib.parse.quote(branch, safe="")
    item = _request_json("GET", f"{_project_api_base(project_id)}/repository/branches/{encoded}")
    return {
        "name": item.get("name"),
        "protected": item.get("protected"),
        "default": item.get("default"),
        "merged": item.get("merged"),
        "can_push": item.get("can_push"),
        "web_url": item.get("web_url"),
        "commit": item.get("commit", {}),
    }


def find_page_code(
    file_path: str,
    line: int,
    branch: str = "main",
    context: int = 10,
    project_id: str | None = None,
) -> dict[str, Any]:
    encoded_path = urllib.parse.quote(file_path, safe="")
    response = _request(
        "GET",
        f"{_project_api_base(project_id)}/repository/files/{encoded_path}/raw",
        params={"ref": branch},
    )

    lines = response.text.splitlines()
    total = len(lines)
    if line < 1 or line > max(total, 1):
        raise GitLabError(f"Line out of range: {line} for file with {total} lines")

    start = max(0, line - context - 1)
    end = min(total, line + context)
    context_lines: list[str] = []
    for idx in range(start, end):
        line_num = idx + 1
        prefix = ">>> " if line_num == line else "    "
        context_lines.append(f"{prefix}{line_num:4d}: {lines[idx]}")

    blame_data: list[dict[str, Any]] = []
    try:
        blame_data = _request_json(
            "GET",
            f"{_project_api_base(project_id)}/repository/files/{encoded_path}/blame",
            params={"ref": branch},
        )
    except GitLabError:
        blame_data = []

    line_blame = None
    if blame_data and line <= len(blame_data):
        commit = blame_data[line - 1].get("commit", {})
        line_blame = {
            "commit": (commit.get("id") or "")[:8],
            "author": commit.get("author_name"),
        }

    ext = os.path.splitext(file_path)[1].lower()
    language = {
        ".tsx": "typescript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".js": "javascript",
        ".vue": "vue",
        ".css": "css",
        ".scss": "scss",
        ".less": "less",
    }.get(ext, "text")

    return {
        "file_path": file_path,
        "branch": branch,
        "line": line,
        "total_lines": total,
        "context": {"start": start + 1, "end": end, "lines": context_lines},
        "language": language,
        "blame": line_blame,
    }


def get_commits(
    file_path: str,
    branch: str = "main",
    since: str = "",
    limit: int = 3,
    project_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "path": file_path,
        "per_page": min(100, max(1, limit)),
        "ref_name": branch,
    }
    if since:
        params["since"] = f"{since}T00:00:00Z"

    commits = _request_json("GET", f"{_project_api_base(project_id)}/repository/commits", params=params)
    formatted = [
        {
            "id": (item.get("id") or "")[:8],
            "author": item.get("author_name"),
            "author_email": item.get("author_email"),
            "message": item.get("title"),
            "committed_date": item.get("committed_date"),
            "web_url": item.get("web_url"),
        }
        for item in commits
    ]
    return {
        "commits": formatted,
        "suggested_owner": formatted[0]["author"] if formatted else None,
        "file_path": file_path,
        "branch": branch,
    }


def list_merge_requests(
    state: str = "opened",
    source_branch: str = "",
    target_branch: str = "",
    search: str = "",
    page: int = 1,
    per_page: int = 20,
    project_id: str | None = None,
) -> dict[str, Any]:
    page, per_page = _sanitize_pagination(page, per_page)
    params: dict[str, Any] = {"state": state, "page": page, "per_page": per_page}
    if source_branch:
        params["source_branch"] = source_branch
    if target_branch:
        params["target_branch"] = target_branch
    if search:
        params["search"] = search
    data = _request_json("GET", f"{_project_api_base(project_id)}/merge_requests", params=params)
    items = [
        {
            "iid": item.get("iid"),
            "id": item.get("id"),
            "title": item.get("title"),
            "state": item.get("state"),
            "source_branch": item.get("source_branch"),
            "target_branch": item.get("target_branch"),
            "author": item.get("author", {}).get("username"),
            "web_url": item.get("web_url"),
            "updated_at": item.get("updated_at"),
        }
        for item in data
    ]
    return {"merge_requests": items, "page": page, "per_page": per_page, "count": len(items)}


def get_merge_request(iid: int, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json("GET", f"{_project_api_base(project_id)}/merge_requests/{iid}")
    return {
        "iid": item.get("iid"),
        "id": item.get("id"),
        "title": item.get("title"),
        "description": item.get("description"),
        "state": item.get("state"),
        "source_branch": item.get("source_branch"),
        "target_branch": item.get("target_branch"),
        "author": item.get("author", {}).get("username"),
        "web_url": item.get("web_url"),
        "merge_status": item.get("merge_status"),
        "updated_at": item.get("updated_at"),
    }


def create_merge_request(
    title: str,
    source_branch: str,
    target_branch: str,
    description: str = "",
    draft: bool = False,
    remove_source_branch: bool = False,
    project_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "title": title,
        "source_branch": source_branch,
        "target_branch": target_branch,
        "description": description,
        "remove_source_branch": remove_source_branch,
    }
    if draft:
        payload["title"] = f"Draft: {title}"
    item = _request_json("POST", f"{_project_api_base(project_id)}/merge_requests", json_body=payload)
    return {"iid": item.get("iid"), "id": item.get("id"), "title": item.get("title"), "state": item.get("state"), "web_url": item.get("web_url")}


def update_merge_request(
    iid: int,
    title: str = "",
    description: str = "",
    target_branch: str = "",
    state_event: str = "",
    project_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if title:
        payload["title"] = title
    if description:
        payload["description"] = description
    if target_branch:
        payload["target_branch"] = target_branch
    if state_event:
        payload["state_event"] = state_event
    item = _request_json("PUT", f"{_project_api_base(project_id)}/merge_requests/{iid}", json_body=payload)
    return {"iid": item.get("iid"), "title": item.get("title"), "state": item.get("state"), "web_url": item.get("web_url"), "updated_at": item.get("updated_at")}


def merge_merge_request(
    iid: int,
    merge_when_pipeline_succeeds: bool = False,
    should_remove_source_branch: bool = False,
    squash: bool = False,
    project_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "merge_when_pipeline_succeeds": merge_when_pipeline_succeeds,
        "should_remove_source_branch": should_remove_source_branch,
        "squash": squash,
    }
    item = _request_json("PUT", f"{_project_api_base(project_id)}/merge_requests/{iid}/merge", json_body=payload)
    return {"iid": item.get("iid"), "state": item.get("state"), "merged_at": item.get("merged_at"), "web_url": item.get("web_url")}


def get_mr_changes(iid: int, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json("GET", f"{_project_api_base(project_id)}/merge_requests/{iid}/changes")
    changes = [
        {
            "old_path": c.get("old_path"),
            "new_path": c.get("new_path"),
            "new_file": c.get("new_file"),
            "renamed_file": c.get("renamed_file"),
            "deleted_file": c.get("deleted_file"),
            "diff": c.get("diff", "")[:4000],
        }
        for c in item.get("changes", [])
    ]
    return {"iid": item.get("iid"), "changes_count": len(changes), "changes": changes}


def get_mr_discussions(iid: int, project_id: str | None = None) -> dict[str, Any]:
    discussions = _request_json("GET", f"{_project_api_base(project_id)}/merge_requests/{iid}/discussions")
    formatted = []
    for disc in discussions:
        notes = [
            {
                "id": note.get("id"),
                "author": note.get("author", {}).get("username"),
                "body": note.get("body"),
                "created_at": note.get("created_at"),
            }
            for note in disc.get("notes", [])
        ]
        formatted.append({"id": disc.get("id"), "notes": notes})
    return {"iid": iid, "discussions": formatted, "count": len(formatted)}


def create_mr_note(iid: int, body: str, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json(
        "POST",
        f"{_project_api_base(project_id)}/merge_requests/{iid}/notes",
        json_body={"body": body},
    )
    return {
        "id": item.get("id"),
        "body": item.get("body"),
        "author": item.get("author", {}).get("username"),
        "created_at": item.get("created_at"),
    }


def list_issues(
    state: str = "opened",
    search: str = "",
    labels: str = "",
    assignee_username: str = "",
    page: int = 1,
    per_page: int = 20,
    project_id: str | None = None,
) -> dict[str, Any]:
    page, per_page = _sanitize_pagination(page, per_page)
    params: dict[str, Any] = {"state": state, "page": page, "per_page": per_page}
    if search:
        params["search"] = search
    if labels:
        params["labels"] = labels
    if assignee_username:
        params["assignee_username"] = assignee_username
    issues = _request_json("GET", f"{_project_api_base(project_id)}/issues", params=params)
    formatted = [
        {
            "iid": item.get("iid"),
            "title": item.get("title"),
            "state": item.get("state"),
            "author": item.get("author", {}).get("username"),
            "assignees": [a.get("username") for a in item.get("assignees", [])],
            "labels": item.get("labels", []),
            "web_url": item.get("web_url"),
            "updated_at": item.get("updated_at"),
        }
        for item in issues
    ]
    return {"issues": formatted, "page": page, "per_page": per_page, "count": len(formatted)}


def get_issue(iid: int, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json("GET", f"{_project_api_base(project_id)}/issues/{iid}")
    return {
        "iid": item.get("iid"),
        "title": item.get("title"),
        "description": item.get("description"),
        "state": item.get("state"),
        "labels": item.get("labels", []),
        "author": item.get("author", {}).get("username"),
        "assignees": [a.get("username") for a in item.get("assignees", [])],
        "web_url": item.get("web_url"),
        "updated_at": item.get("updated_at"),
    }


def _resolve_assignee(username_or_id: str) -> int | None:
    if not username_or_id:
        return None
    try:
        return int(username_or_id)
    except ValueError:
        pass

    resp = _request("GET", f"{_global_api_base()}/users", params={"username": username_or_id}, timeout=10)
    users = resp.json()
    if not users:
        return None
    return users[0]["id"]


def create_issue(
    title: str,
    description: str,
    labels: list[str] | None = None,
    assignee: str = "",
    milestone: str = "",
    project_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "description": description,
        "labels": ",".join(labels or ["ARMS", "frontend", "bug"]),
    }
    assignee_id = _resolve_assignee(assignee)
    if assignee_id:
        payload["assignee_ids"] = [assignee_id]
    if milestone:
        payload["milestone_id"] = milestone

    issue = _request_json("POST", f"{_project_api_base(project_id)}/issues", json_body=payload)
    return {
        "issue_id": issue.get("iid"),
        "issue_url": issue.get("web_url"),
        "title": issue.get("title"),
        "state": issue.get("state"),
    }


def update_issue(
    iid: int,
    title: str = "",
    description: str = "",
    state_event: str = "",
    labels: list[str] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if title:
        payload["title"] = title
    if description:
        payload["description"] = description
    if state_event:
        payload["state_event"] = state_event
    if labels is not None:
        payload["labels"] = ",".join(labels)
    issue = _request_json("PUT", f"{_project_api_base(project_id)}/issues/{iid}", json_body=payload)
    return {
        "iid": issue.get("iid"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "web_url": issue.get("web_url"),
        "updated_at": issue.get("updated_at"),
    }


def create_issue_note(iid: int, body: str, project_id: str | None = None) -> dict[str, Any]:
    note = _request_json(
        "POST",
        f"{_project_api_base(project_id)}/issues/{iid}/notes",
        json_body={"body": body},
    )
    return {
        "id": note.get("id"),
        "body": note.get("body"),
        "author": note.get("author", {}).get("username"),
        "created_at": note.get("created_at"),
    }


def list_issue_notes(iid: int, project_id: str | None = None) -> dict[str, Any]:
    notes = _request_json("GET", f"{_project_api_base(project_id)}/issues/{iid}/notes")
    formatted = [
        {
            "id": item.get("id"),
            "body": item.get("body"),
            "author": item.get("author", {}).get("username"),
            "created_at": item.get("created_at"),
        }
        for item in notes
    ]
    return {"iid": iid, "notes": formatted, "count": len(formatted)}


def list_pipelines(
    ref: str = "",
    status: str = "",
    page: int = 1,
    per_page: int = 20,
    project_id: str | None = None,
) -> dict[str, Any]:
    page, per_page = _sanitize_pagination(page, per_page)
    params: dict[str, Any] = {"page": page, "per_page": per_page}
    if ref:
        params["ref"] = ref
    if status:
        params["status"] = status
    pipelines = _request_json("GET", f"{_project_api_base(project_id)}/pipelines", params=params)
    formatted = [
        {
            "id": item.get("id"),
            "iid": item.get("iid"),
            "ref": item.get("ref"),
            "status": item.get("status"),
            "source": item.get("source"),
            "web_url": item.get("web_url"),
            "updated_at": item.get("updated_at"),
        }
        for item in pipelines
    ]
    return {"pipelines": formatted, "page": page, "per_page": per_page, "count": len(formatted)}


def get_pipeline(pipeline_id: int, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json("GET", f"{_project_api_base(project_id)}/pipelines/{pipeline_id}")
    return {
        "id": item.get("id"),
        "iid": item.get("iid"),
        "ref": item.get("ref"),
        "status": item.get("status"),
        "source": item.get("source"),
        "web_url": item.get("web_url"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def retry_pipeline(pipeline_id: int, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json("POST", f"{_project_api_base(project_id)}/pipelines/{pipeline_id}/retry")
    return {"id": item.get("id"), "status": item.get("status"), "web_url": item.get("web_url")}


def cancel_pipeline(pipeline_id: int, project_id: str | None = None) -> dict[str, Any]:
    item = _request_json("POST", f"{_project_api_base(project_id)}/pipelines/{pipeline_id}/cancel")
    return {"id": item.get("id"), "status": item.get("status"), "web_url": item.get("web_url")}


def list_pipeline_jobs(pipeline_id: int, project_id: str | None = None) -> dict[str, Any]:
    jobs = _request_json("GET", f"{_project_api_base(project_id)}/pipelines/{pipeline_id}/jobs")
    formatted = [
        {
            "id": job.get("id"),
            "name": job.get("name"),
            "status": job.get("status"),
            "stage": job.get("stage"),
            "web_url": job.get("web_url"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
        }
        for job in jobs
    ]
    return {"pipeline_id": pipeline_id, "jobs": formatted, "count": len(formatted)}


def get_job_log(job_id: int, project_id: str | None = None) -> dict[str, Any]:
    resp = _request("GET", f"{_project_api_base(project_id)}/jobs/{job_id}/trace", timeout=60)
    log_text = resp.text
    return {
        "job_id": job_id,
        "length": len(log_text),
        "trace_preview": log_text[-5000:],
    }


def list_labels(page: int = 1, per_page: int = 100, project_id: str | None = None) -> dict[str, Any]:
    page, per_page = _sanitize_pagination(page, per_page)
    labels = _request_json(
        "GET",
        f"{_project_api_base(project_id)}/labels",
        params={"page": page, "per_page": per_page},
    )
    formatted = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "color": item.get("color"),
            "description": item.get("description"),
            "is_project_label": item.get("is_project_label"),
        }
        for item in labels
    ]
    return {"labels": formatted, "count": len(formatted), "page": page, "per_page": per_page}


def create_label(
    name: str,
    color: str,
    description: str = "",
    project_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "color": color}
    if description:
        payload["description"] = description
    item = _request_json("POST", f"{_project_api_base(project_id)}/labels", json_body=payload)
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "color": item.get("color"),
        "description": item.get("description"),
    }


def update_label(
    name: str,
    new_name: str = "",
    color: str = "",
    description: str = "",
    project_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if new_name:
        payload["new_name"] = new_name
    if color:
        payload["color"] = color
    if description:
        payload["description"] = description
    item = _request_json("PUT", f"{_project_api_base(project_id)}/labels", json_body=payload)
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "color": item.get("color"),
        "description": item.get("description"),
    }


def delete_label(name: str, project_id: str | None = None) -> dict[str, Any]:
    _request("DELETE", f"{_project_api_base(project_id)}/labels", params={"name": name})
    return {"deleted": True, "name": name}

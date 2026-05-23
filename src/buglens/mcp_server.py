from __future__ import annotations

import argparse
import inspect
import logging
import os

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in envs without mcp
    FastMCP = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR = exc
else:
    _MCP_IMPORT_ERROR = None

from .config import bootstrap_process_env_from_dotenv
from .integrations.gitlab import (
    GitLabError,
    cancel_pipeline,
    create_issue,
    create_issue_note,
    create_label,
    create_merge_request,
    create_mr_note,
    delete_label,
    find_page_code,
    get_branch,
    get_commits,
    get_file,
    get_issue,
    get_job_log,
    get_merge_request,
    get_mr_changes,
    get_mr_discussions,
    get_pipeline,
    get_project,
    list_branches,
    list_issue_notes,
    list_issues,
    list_labels,
    list_merge_requests,
    list_pipeline_jobs,
    list_pipelines,
    list_projects,
    merge_merge_request,
    retry_pipeline,
    search_projects,
    update_issue,
    update_label,
    update_merge_request,
)

logger = logging.getLogger(__name__)


def _configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def _debug_preview(value: object, max_chars: int = 800) -> str:
    text = repr(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...(truncated)"


def _registered_tool_names() -> list[str]:
    names: list[str] = []
    for name, fn in inspect.getmembers(inspect.getmodule(_registered_tool_names), inspect.isfunction):
        if fn.__module__ == __name__ and name.startswith("gitlab_"):
            names.append(name)
    return sorted(names)


class _NoopMCP:
    def tool(self):
        def _decorator(fn):
            return fn

        return _decorator

    def run(self) -> None:
        raise ModuleNotFoundError(
            "Missing optional dependency 'mcp'. Install it to run buglens-mcp."
        ) from _MCP_IMPORT_ERROR


mcp = FastMCP("buglens-mcp") if FastMCP is not None else _NoopMCP()


def _gitlab_wrap(fn, **kwargs):
    logger.info("mcp tool_call_start tool=%s", fn.__name__)
    logger.debug("mcp tool_call_input tool=%s kwargs=%s", fn.__name__, _debug_preview(kwargs))
    try:
        result = fn(**kwargs)
        logger.info("mcp tool_call_complete tool=%s", fn.__name__)
        logger.debug(
            "mcp tool_call_output tool=%s result=%s", fn.__name__, _debug_preview(result)
        )
        return result
    except GitLabError as exc:
        logger.warning("mcp tool_call_error tool=%s error=%s", fn.__name__, exc)
        return {"error": str(exc)}


@mcp.tool()
def gitlab_list_projects(
    search: str = "",
    membership: bool = False,
    owned: bool = False,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """List accessible GitLab projects."""
    return _gitlab_wrap(
        list_projects,
        search=search,
        membership=membership,
        owned=owned,
        page=page,
        per_page=per_page,
    )


@mcp.tool()
def gitlab_search_projects(query: str, page: int = 1, per_page: int = 20) -> dict:
    """Search GitLab projects by keyword."""
    return _gitlab_wrap(search_projects, query=query, page=page, per_page=per_page)


@mcp.tool()
def gitlab_get_project(project_id: str | int) -> dict:
    """Get GitLab project metadata."""
    return _gitlab_wrap(get_project, project_id=project_id)


@mcp.tool()
def gitlab_get_file(file_path: str, ref: str = "main", project_id: str | None = None) -> dict:
    """Get GitLab file content and metadata."""
    return _gitlab_wrap(get_file, file_path=file_path, ref=ref, project_id=project_id)


@mcp.tool()
def gitlab_list_branches(project_id: str | None = None, search: str = "") -> dict:
    """List branches in a GitLab project."""
    return _gitlab_wrap(list_branches, project_id=project_id, search=search)


@mcp.tool()
def gitlab_get_branch(branch: str, project_id: str | None = None) -> dict:
    """Get branch details by branch name."""
    return _gitlab_wrap(get_branch, branch=branch, project_id=project_id)


@mcp.tool()
def gitlab_find_page_code(
    file_path: str,
    line: int,
    branch: str = "main",
    context: int = 10,
    project_id: str | None = None,
) -> dict:
    """Get GitLab file snippet around a line."""
    return _gitlab_wrap(
        find_page_code,
        file_path=file_path,
        line=line,
        branch=branch,
        context=context,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_get_commits(
    file_path: str,
    branch: str = "main",
    since: str = "",
    limit: int = 3,
    project_id: str | None = None,
) -> dict:
    """Get recent commits for a file path."""
    return _gitlab_wrap(
        get_commits,
        file_path=file_path,
        branch=branch,
        since=since,
        limit=limit,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_list_merge_requests(
    state: str = "opened",
    source_branch: str = "",
    target_branch: str = "",
    search: str = "",
    page: int = 1,
    per_page: int = 20,
    project_id: str | None = None,
) -> dict:
    """List merge requests for project."""
    return _gitlab_wrap(
        list_merge_requests,
        state=state,
        source_branch=source_branch,
        target_branch=target_branch,
        search=search,
        page=page,
        per_page=per_page,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_get_merge_request(iid: int, project_id: str | None = None) -> dict:
    """Get merge request details by IID."""
    return _gitlab_wrap(get_merge_request, iid=iid, project_id=project_id)


@mcp.tool()
def gitlab_create_merge_request(
    title: str,
    source_branch: str,
    target_branch: str,
    description: str = "",
    draft: bool = False,
    remove_source_branch: bool = False,
    project_id: str | None = None,
) -> dict:
    """Create a merge request."""
    return _gitlab_wrap(
        create_merge_request,
        title=title,
        source_branch=source_branch,
        target_branch=target_branch,
        description=description,
        draft=draft,
        remove_source_branch=remove_source_branch,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_update_merge_request(
    iid: int,
    title: str = "",
    description: str = "",
    target_branch: str = "",
    state_event: str = "",
    project_id: str | None = None,
) -> dict:
    """Update merge request fields/state."""
    return _gitlab_wrap(
        update_merge_request,
        iid=iid,
        title=title,
        description=description,
        target_branch=target_branch,
        state_event=state_event,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_merge_merge_request(
    iid: int,
    merge_when_pipeline_succeeds: bool = False,
    should_remove_source_branch: bool = False,
    squash: bool = False,
    project_id: str | None = None,
) -> dict:
    """Merge a merge request."""
    return _gitlab_wrap(
        merge_merge_request,
        iid=iid,
        merge_when_pipeline_succeeds=merge_when_pipeline_succeeds,
        should_remove_source_branch=should_remove_source_branch,
        squash=squash,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_get_mr_changes(iid: int, project_id: str | None = None) -> dict:
    """Get merge request changes/diffs."""
    return _gitlab_wrap(get_mr_changes, iid=iid, project_id=project_id)


@mcp.tool()
def gitlab_get_mr_discussions(iid: int, project_id: str | None = None) -> dict:
    """Get merge request discussion threads."""
    return _gitlab_wrap(get_mr_discussions, iid=iid, project_id=project_id)


@mcp.tool()
def gitlab_create_mr_note(iid: int, body: str, project_id: str | None = None) -> dict:
    """Create note/comment on merge request."""
    return _gitlab_wrap(create_mr_note, iid=iid, body=body, project_id=project_id)


@mcp.tool()
def gitlab_list_issues(
    state: str = "opened",
    search: str = "",
    labels: str = "",
    assignee_username: str = "",
    page: int = 1,
    per_page: int = 20,
    project_id: str | None = None,
) -> dict:
    """List issues in project."""
    return _gitlab_wrap(
        list_issues,
        state=state,
        search=search,
        labels=labels,
        assignee_username=assignee_username,
        page=page,
        per_page=per_page,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_get_issue(iid: int, project_id: str | None = None) -> dict:
    """Get issue details by IID."""
    return _gitlab_wrap(get_issue, iid=iid, project_id=project_id)


@mcp.tool()
def gitlab_create_issue(
    title: str,
    description: str,
    labels: list[str] | None = None,
    assignee: str = "",
    milestone: str = "",
    project_id: str | None = None,
) -> dict:
    """Create a GitLab issue for diagnostics."""
    return _gitlab_wrap(
        create_issue,
        title=title,
        description=description,
        labels=labels,
        assignee=assignee,
        milestone=milestone,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_update_issue(
    iid: int,
    title: str = "",
    description: str = "",
    state_event: str = "",
    labels: list[str] | None = None,
    project_id: str | None = None,
) -> dict:
    """Update issue fields/state."""
    return _gitlab_wrap(
        update_issue,
        iid=iid,
        title=title,
        description=description,
        state_event=state_event,
        labels=labels,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_create_issue_note(iid: int, body: str, project_id: str | None = None) -> dict:
    """Create note/comment on issue."""
    return _gitlab_wrap(create_issue_note, iid=iid, body=body, project_id=project_id)


@mcp.tool()
def gitlab_list_issue_notes(iid: int, project_id: str | None = None) -> dict:
    """List issue notes/comments."""
    return _gitlab_wrap(list_issue_notes, iid=iid, project_id=project_id)


@mcp.tool()
def gitlab_list_pipelines(
    ref: str = "",
    status: str = "",
    page: int = 1,
    per_page: int = 20,
    project_id: str | None = None,
) -> dict:
    """List pipelines for project."""
    return _gitlab_wrap(
        list_pipelines,
        ref=ref,
        status=status,
        page=page,
        per_page=per_page,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_get_pipeline(pipeline_id: int, project_id: str | None = None) -> dict:
    """Get pipeline detail by ID."""
    return _gitlab_wrap(get_pipeline, pipeline_id=pipeline_id, project_id=project_id)


@mcp.tool()
def gitlab_retry_pipeline(pipeline_id: int, project_id: str | None = None) -> dict:
    """Retry pipeline by ID."""
    return _gitlab_wrap(retry_pipeline, pipeline_id=pipeline_id, project_id=project_id)


@mcp.tool()
def gitlab_cancel_pipeline(pipeline_id: int, project_id: str | None = None) -> dict:
    """Cancel pipeline by ID."""
    return _gitlab_wrap(cancel_pipeline, pipeline_id=pipeline_id, project_id=project_id)


@mcp.tool()
def gitlab_list_pipeline_jobs(pipeline_id: int, project_id: str | None = None) -> dict:
    """List jobs in pipeline."""
    return _gitlab_wrap(list_pipeline_jobs, pipeline_id=pipeline_id, project_id=project_id)


@mcp.tool()
def gitlab_get_job_log(job_id: int, project_id: str | None = None) -> dict:
    """Get job log trace (preview)."""
    return _gitlab_wrap(get_job_log, job_id=job_id, project_id=project_id)


@mcp.tool()
def gitlab_list_labels(page: int = 1, per_page: int = 100, project_id: str | None = None) -> dict:
    """List labels in project."""
    return _gitlab_wrap(list_labels, page=page, per_page=per_page, project_id=project_id)


@mcp.tool()
def gitlab_create_label(
    name: str,
    color: str,
    description: str = "",
    project_id: str | None = None,
) -> dict:
    """Create project label."""
    return _gitlab_wrap(
        create_label,
        name=name,
        color=color,
        description=description,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_update_label(
    name: str,
    new_name: str = "",
    color: str = "",
    description: str = "",
    project_id: str | None = None,
) -> dict:
    """Update project label."""
    return _gitlab_wrap(
        update_label,
        name=name,
        new_name=new_name,
        color=color,
        description=description,
        project_id=project_id,
    )


@mcp.tool()
def gitlab_delete_label(name: str, project_id: str | None = None) -> dict:
    """Delete project label by name."""
    return _gitlab_wrap(delete_label, name=name, project_id=project_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="buglens MCP server")
    parser.add_argument(
        "--log-level",
        default=os.getenv("BUGLENS_MCP_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging level (logs write to stderr)",
    )
    args = parser.parse_args()
    _configure_logging(args.log_level)

    logger.info("bootstrapping dotenv for mcp server")
    bootstrap_process_env_from_dotenv()
    tool_names = _registered_tool_names()
    logger.info(
        "starting mcp server name=buglens-mcp tools=%d mcp_installed=%s gitlab_url_set=%s gitlab_token_set=%s",
        len(tool_names),
        FastMCP is not None,
        bool(os.getenv("GITLAB_URL")),
        bool(os.getenv("GITLAB_TOKEN")),
    )
    logger.debug("registered tools=%s", tool_names)
    mcp.run()


if __name__ == "__main__":
    main()

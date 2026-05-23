from __future__ import annotations

import argparse
import inspect
import logging
import os
import time
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in envs without mcp
    FastMCP = None  # type: ignore[assignment]
    TransportSecuritySettings = None  # type: ignore[assignment]
    _MCP_IMPORT_ERROR = exc
else:
    _MCP_IMPORT_ERROR = None

from .config import SubAgentConfig, bootstrap_process_env_from_dotenv
from .monitoring import ARMSClient, AtomicMonitoringService, SLSClient
from .monitoring.query_builder import build_rum_search_query, resolve_time_range
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
        if fn.__module__ == __name__ and (
            name.startswith("gitlab_") or name.startswith("arms_")
        ):
            names.append(name)
    return sorted(names)


class _NoopMCP:
    def tool(self, *args, **kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    def run(self, *args, **kwargs) -> None:
        raise ModuleNotFoundError(
            "Missing optional dependency 'mcp'. Install it to run buglens-mcp."
        ) from _MCP_IMPORT_ERROR


mcp = FastMCP("buglens") if FastMCP is not None else _NoopMCP()


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


def _monitoring_wrap(fn, **kwargs):
    logger.info("mcp tool_call_start tool=%s", fn.__name__)
    logger.debug("mcp tool_call_input tool=%s kwargs=%s", fn.__name__, _debug_preview(kwargs))
    started = time.monotonic()
    try:
        result = fn(**kwargs)
        logger.info(
            "mcp tool_call_complete tool=%s latency_ms=%d",
            fn.__name__,
            int((time.monotonic() - started) * 1000),
        )
        logger.debug(
            "mcp tool_call_output tool=%s result=%s", fn.__name__, _debug_preview(result)
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp tool_call_error tool=%s error=%s", fn.__name__, exc)
        return {"error": str(exc)}


def _build_monitoring_service() -> AtomicMonitoringService:
    config = SubAgentConfig()
    if not config.enable_mcp_tools:
        raise RuntimeError("BUGLENS_ENABLE_MCP_TOOLS=false, monitoring tools are disabled.")
    if not config.has_monitoring_credentials():
        raise RuntimeError(
            "Missing monitoring credentials: BUGLENS_ALIBABA_ACCESS_KEY_ID/SECRET/REGION_ID."
        )

    sls = SLSClient(
        access_key_id=str(config.alibaba_access_key_id),
        access_key_secret=str(config.alibaba_access_key_secret),
        security_token=config.alibaba_security_token,
        region_id=str(config.alibaba_region_id),
        endpoint=config.sls_endpoint,
        max_retries=config.monitoring_max_retries,
        base_backoff_seconds=config.monitoring_base_backoff_seconds,
        max_backoff_seconds=config.monitoring_max_backoff_seconds,
        max_concurrency=config.monitoring_max_concurrency,
    )
    arms_kwargs: dict[str, Any] = {
        "access_key_id": str(config.alibaba_access_key_id),
        "access_key_secret": str(config.alibaba_access_key_secret),
        "security_token": config.alibaba_security_token,
        "region_id": str(config.alibaba_region_id),
        "max_retries": config.monitoring_max_retries,
        "base_backoff_seconds": config.monitoring_base_backoff_seconds,
        "max_backoff_seconds": config.monitoring_max_backoff_seconds,
        "max_concurrency": config.monitoring_max_concurrency,
    }
    if config.arms_endpoint:
        arms_kwargs["endpoint"] = config.arms_endpoint
    arms = ARMSClient(**arms_kwargs)
    return AtomicMonitoringService(sls_client=sls, arms_client=arms)


def _resolve_rum_sls_target(
    *,
    project: str | None,
    logstore: str | None,
    config: SubAgentConfig,
) -> tuple[str, str]:
    final_project = project or config.rum_sls_project
    final_logstore = logstore or config.rum_sls_logstore
    if not final_project or not final_logstore:
        raise ValueError(
            "RUM queries require project/logstore (set params or BUGLENS_RUM_SLS_PROJECT/BUGLENS_RUM_SLS_LOGSTORE)."
        )
    return str(final_project), str(final_logstore)


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


@mcp.tool()
def arms_rum_list_apps(page_token: str | None = None, page_size: int = 100) -> dict:
    """List ARMS RUM apps with normalized fields."""

    def _call() -> dict:
        monitoring = _build_monitoring_service()
        result = monitoring.arms_list_rum_apps(
            page_token=page_token,
            page_size=page_size,
        )
        return result.model_dump(mode="json", exclude_none=True)

    return _monitoring_wrap(_call)


@mcp.tool()
def arms_rum_search_errors(
    project: str | None = None,
    logstore: str | None = None,
    last: str | None = None,
    time_from_ms: int | None = None,
    time_to_ms: int | None = None,
    query: str | None = None,
    event_type: str = "exception",
    app_id: str | None = None,
    app_types: list[str] | None = None,
    exception_message: str | None = None,
    keyword: str | None = None,
    page_token: str | None = None,
    page_size: int = 50,
    reverse: bool = True,
) -> dict:
    """Search ARMS frontend (RUM) errors by structured filters or raw query."""

    def _call() -> dict:
        config = SubAgentConfig()
        monitoring = _build_monitoring_service()
        final_project, final_logstore = _resolve_rum_sls_target(
            project=project,
            logstore=logstore,
            config=config,
        )
        from_ms, to_ms = resolve_time_range(from_ms=time_from_ms, to_ms=time_to_ms, last=last)
        resolved_query = build_rum_search_query(
            query=query,
            event_type=event_type,
            app_id=app_id,
            app_types=app_types,
            exception_message=exception_message,
            keyword=keyword,
        )
        result = monitoring.sls_search_logs(
            project=final_project,
            logstore=final_logstore,
            time_from_ms=from_ms,
            time_to_ms=to_ms,
            page_token=page_token,
            page_size=page_size,
            reverse=reverse,
            extra_query={"query": resolved_query},
        )
        payload = result.model_dump(mode="json", exclude_none=True)
        payload["query"] = resolved_query
        return payload

    return _monitoring_wrap(_call)


@mcp.tool()
def arms_rum_get_error_context(
    pack_id: str,
    pack_meta: str,
    project: str | None = None,
    logstore: str | None = None,
    back_lines: int = 30,
    forward_lines: int = 30,
) -> dict:
    """Get ARMS/SLS error context lines around a log pack record."""

    def _call() -> dict:
        config = SubAgentConfig()
        monitoring = _build_monitoring_service()
        final_project, final_logstore = _resolve_rum_sls_target(
            project=project,
            logstore=logstore,
            config=config,
        )
        result = monitoring.sls_get_log_context(
            project=final_project,
            logstore=final_logstore,
            pack_id=pack_id,
            pack_meta=pack_meta,
            back_lines=back_lines,
            forward_lines=forward_lines,
        )
        return result.model_dump(mode="json", exclude_none=True)

    return _monitoring_wrap(_call)


@mcp.tool()
def arms_rum_resolve_exception_stack(
    pid: str,
    line: int,
    column: int,
    sourcemap_type: str = "js",
    exception_binary_images: str | None = None,
) -> dict:
    """Resolve frontend exception stack with source map by pid + line + column."""

    def _call() -> dict:
        monitoring = _build_monitoring_service()
        result = monitoring.arms_resolve_exception_stack(
            pid=pid,
            line=line,
            column=column,
            sourcemap_type=sourcemap_type,
            exception_binary_images=exception_binary_images,
        )
        payload = result.model_dump(mode="json", exclude_none=True)
        payload["exception_stack"] = f"{line},{column},20"
        return payload

    return _monitoring_wrap(_call)


@mcp.tool()
def arms_exception_stack_tool(
    pid: str,
    line: int,
    column: int,
    sourcemap_type: str = "js",
    exception_binary_images: str | None = None,
) -> dict:
    """Compatibility alias of arms_rum_resolve_exception_stack."""
    return arms_rum_resolve_exception_stack(
        pid=pid,
        line=line,
        column=column,
        sourcemap_type=sourcemap_type,
        exception_binary_images=exception_binary_images,
    )


@mcp.tool()
def arms_get_error_detail(
    app: str | None = None,
    page: str | None = None,
    version: str | None = None,
    error_message: str | None = None,
    project: str | None = None,
    logstore: str | None = None,
    time_from_ms: int | None = None,
    time_to_ms: int | None = None,
    query: str | None = None,
    page_size: int = 20,
) -> dict:
    """Get detailed error logs by app/page/version/message filters."""

    def _call() -> dict:
        config = SubAgentConfig()
        monitoring = _build_monitoring_service()
        final_project, final_logstore = _resolve_rum_sls_target(
            project=project,
            logstore=logstore,
            config=config,
        )
        from_ms, to_ms = resolve_time_range(from_ms=time_from_ms, to_ms=time_to_ms, last=None)
        query_parts: list[str] = []
        for value in (app, page, version, error_message):
            if value:
                query_parts.append(str(value))
        if query:
            query_parts.append(str(query))
        resolved_query = " and ".join(query_parts) if query_parts else "*"
        result = monitoring.sls_search_logs(
            project=final_project,
            logstore=final_logstore,
            time_from_ms=from_ms,
            time_to_ms=to_ms,
            page_size=page_size,
            reverse=True,
            extra_query={"query": resolved_query},
        )
        payload = result.model_dump(mode="json", exclude_none=True)
        payload["query"] = resolved_query
        return payload

    return _monitoring_wrap(_call)


def main() -> None:
    parser = argparse.ArgumentParser(description="buglens MCP server")
    parser.add_argument(
        "--log-level",
        default=os.getenv("BUGLENS_MCP_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="logging level (logs write to stderr)",
    )
    parser.add_argument(
        "--transport",
        default=os.getenv("BUGLENS_MCP_TRANSPORT", "stdio"),
        choices=["stdio", "streamable-http"],
        help="MCP transport mode. Use streamable-http for remote URL integration.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("BUGLENS_MCP_HOST", "127.0.0.1"),
        help="HTTP bind host when --transport=streamable-http",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("BUGLENS_MCP_PORT", "8000")),
        help="HTTP bind port when --transport=streamable-http",
    )
    parser.add_argument(
        "--streamable-path",
        default=os.getenv("BUGLENS_MCP_STREAMABLE_HTTP_PATH", "/mcp"),
        help="HTTP path for streamable MCP endpoint when --transport=streamable-http",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=None,
        help=(
            "Allowed Host header (repeatable, e.g. 10.37.25.80:*). "
            "If omitted with non-local host, DNS rebinding protection is disabled."
        ),
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help=(
            "Allowed Origin header (repeatable, e.g. http://10.37.25.80:*). "
            "Used when DNS rebinding protection is enabled."
        ),
    )
    parser.add_argument(
        "--disable-dns-rebinding-protection",
        action="store_true",
        help="Disable DNS rebinding protection for streamable-http transport.",
    )
    args = parser.parse_args()
    _configure_logging(args.log_level)

    logger.info("bootstrapping dotenv for mcp server")
    bootstrap_process_env_from_dotenv()
    tool_names = _registered_tool_names()
    logger.info(
        "starting mcp server name=buglens-mcp tools=%d mcp_installed=%s gitlab_url_set=%s gitlab_token_set=%s transport=%s",
        len(tool_names),
        FastMCP is not None,
        bool(os.getenv("GITLAB_URL")),
        bool(os.getenv("GITLAB_TOKEN")),
        args.transport,
    )
    logger.debug("registered tools=%s", tool_names)
    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.streamable_http_path = args.streamable_path
        is_local_bind = args.host in {"127.0.0.1", "localhost", "::1"}
        if args.disable_dns_rebinding_protection:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
            logger.warning("DNS rebinding protection disabled by CLI flag.")
        elif args.allow_host:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=args.allow_host,
                allowed_origins=args.allow_origin or [],
            )
        elif not is_local_bind:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
            logger.warning(
                "non-local bind host=%s without --allow-host; disabling DNS rebinding protection "
                "to avoid Invalid Host header errors.",
                args.host,
            )
        logger.info(
            "streamable endpoint ready url=http://%s:%d%s",
            args.host,
            args.port,
            args.streamable_path,
        )
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

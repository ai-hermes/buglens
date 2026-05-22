from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from .config import SubAgentConfig
from .monitoring import ARMSClient, SLSClient, AtomicMonitoringService
from .monitoring.query_builder import build_rum_search_query, resolve_time_range
from .mcp_server import (
    gitlab_get_project,
    gitlab_get_file,
    gitlab_list_branches,
    gitlab_get_branch,
    gitlab_list_projects,
    gitlab_search_projects,
    gitlab_list_merge_requests,
    gitlab_get_merge_request,
    gitlab_create_merge_request,
    gitlab_update_merge_request,
    gitlab_merge_merge_request,
    gitlab_get_mr_changes,
    gitlab_get_mr_discussions,
    gitlab_create_mr_note,
    gitlab_list_issues,
    gitlab_get_issue,
    gitlab_update_issue,
    gitlab_create_issue_note,
    gitlab_list_issue_notes,
    gitlab_list_pipelines,
    gitlab_get_pipeline,
    gitlab_retry_pipeline,
    gitlab_cancel_pipeline,
    gitlab_list_pipeline_jobs,
    gitlab_get_job_log,
    gitlab_list_labels,
    gitlab_create_label,
    gitlab_update_label,
    gitlab_delete_label,
    gitlab_create_issue,
    gitlab_find_page_code,
    gitlab_get_commits,
)
from .models import InvokeRequest, InvokeResponse

logger = logging.getLogger(__name__)


@dataclass
class AgentMetadata:
    name: str
    version: str
    capabilities: list[str]


class Runner(Protocol):
    async def run(
        self,
        request: InvokeRequest,
        config: SubAgentConfig,
        on_text: Callable[[str], None] | None = None,
    ) -> InvokeResponse:
        ...


class LiteLLMGraphState(TypedDict):
    messages: list[dict[str, Any]]
    output: str
    usage: dict[str, Any] | None
    streamed: bool
    finish_reason: str | None


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


class LangGraphRunner:
    _GITLAB_HINT_KEYWORDS = (
        "gitlab",
        "merge request",
        "mr ",
        "pipeline",
        "commit",
        "branch",
        "issue",
        "repo",
        "repository",
        "project_id",
        "git ",
    )

    def _summarize_exception(self, exc: BaseException) -> str:
        # Python 3.11 ExceptionGroup often wraps the real transport error.
        if isinstance(exc, BaseExceptionGroup):
            flattened: list[str] = []
            stack: list[BaseException] = list(exc.exceptions)
            while stack:
                current = stack.pop(0)
                if isinstance(current, BaseExceptionGroup):
                    stack = list(current.exceptions) + stack
                    continue
                message = str(current).strip() or current.__class__.__name__
                flattened.append(f"{current.__class__.__name__}: {message}")
            if flattened:
                return "; ".join(flattened)
        message = str(exc).strip() or exc.__class__.__name__
        return f"{exc.__class__.__name__}: {message}"

    def _build_messages(
        self, request: InvokeRequest, config: SubAgentConfig
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})
        if request.context:
            context_json = json.dumps(request.context, ensure_ascii=False, indent=2)
            user_content = f"{request.task}\n\nContext:\n{context_json}"
        else:
            user_content = request.task
        messages.append({"role": "user", "content": user_content})
        return messages

    @staticmethod
    def _debug_preview(value: Any, max_chars: int = 4000) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:  # noqa: BLE001
            text = repr(value)
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}...(truncated)"

    def _should_enable_gitlab_tools(self, request: InvokeRequest) -> bool:
        task_blob = request.task
        if request.context:
            task_blob += "\n" + json.dumps(request.context, ensure_ascii=False)
        lower = task_blob.lower()
        return any(keyword in lower for keyword in self._GITLAB_HINT_KEYWORDS)

    def _build_mcp_tools(self, config: SubAgentConfig) -> list[MCPTool]:
        if not config.enable_mcp_tools:
            return []
        return [
            MCPTool(
                name="gitlab_list_projects",
                description="List accessible GitLab projects.",
                parameters={
                    "type": "object",
                    "properties": {
                        "search": {"type": "string"},
                        "membership": {"type": "boolean"},
                        "owned": {"type": "boolean"},
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                    },
                },
                handler=gitlab_list_projects,
            ),
            MCPTool(
                name="gitlab_search_projects",
                description="Search GitLab projects by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                handler=gitlab_search_projects,
            ),
            MCPTool(
                name="gitlab_get_project",
                description="Get GitLab project metadata.",
                parameters={
                    "type": "object",
                    "properties": {"project_id": {"type": "string"}},
                    "required": ["project_id"],
                },
                handler=gitlab_get_project,
            ),
            MCPTool(
                name="gitlab_get_file",
                description="Get GitLab file content and metadata.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "ref": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["file_path"],
                },
                handler=gitlab_get_file,
            ),
            MCPTool(
                name="gitlab_list_branches",
                description="List branches in a GitLab project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string"},
                        "search": {"type": "string"},
                    },
                },
                handler=gitlab_list_branches,
            ),
            MCPTool(
                name="gitlab_get_branch",
                description="Get branch details by name.",
                parameters={
                    "type": "object",
                    "properties": {
                        "branch": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["branch"],
                },
                handler=gitlab_get_branch,
            ),
            MCPTool(
                name="gitlab_find_page_code",
                description="Get GitLab file snippet around a line.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "line": {"type": "integer"},
                        "branch": {"type": "string"},
                        "context": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["file_path", "line"],
                },
                handler=gitlab_find_page_code,
            ),
            MCPTool(
                name="gitlab_get_commits",
                description="Get recent commits for a file path.",
                parameters={
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "branch": {"type": "string"},
                        "since": {"type": "string"},
                        "limit": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["file_path"],
                },
                handler=gitlab_get_commits,
            ),
            MCPTool(
                name="gitlab_list_merge_requests",
                description="List merge requests for a project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "state": {"type": "string"},
                        "source_branch": {"type": "string"},
                        "target_branch": {"type": "string"},
                        "search": {"type": "string"},
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                },
                handler=gitlab_list_merge_requests,
            ),
            MCPTool(
                name="gitlab_get_merge_request",
                description="Get merge request details by IID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_get_merge_request,
            ),
            MCPTool(
                name="gitlab_create_merge_request",
                description="Create a merge request.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "source_branch": {"type": "string"},
                        "target_branch": {"type": "string"},
                        "description": {"type": "string"},
                        "draft": {"type": "boolean"},
                        "remove_source_branch": {"type": "boolean"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["title", "source_branch", "target_branch"],
                },
                handler=gitlab_create_merge_request,
            ),
            MCPTool(
                name="gitlab_update_merge_request",
                description="Update merge request fields/state.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "target_branch": {"type": "string"},
                        "state_event": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_update_merge_request,
            ),
            MCPTool(
                name="gitlab_merge_merge_request",
                description="Merge a merge request.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "merge_when_pipeline_succeeds": {"type": "boolean"},
                        "should_remove_source_branch": {"type": "boolean"},
                        "squash": {"type": "boolean"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_merge_merge_request,
            ),
            MCPTool(
                name="gitlab_get_mr_changes",
                description="Get merge request changes/diffs.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_get_mr_changes,
            ),
            MCPTool(
                name="gitlab_get_mr_discussions",
                description="Get merge request discussion threads.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_get_mr_discussions,
            ),
            MCPTool(
                name="gitlab_create_mr_note",
                description="Create a note on merge request.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "body": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid", "body"],
                },
                handler=gitlab_create_mr_note,
            ),
            MCPTool(
                name="gitlab_list_issues",
                description="List issues in project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "state": {"type": "string"},
                        "search": {"type": "string"},
                        "labels": {"type": "string"},
                        "assignee_username": {"type": "string"},
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                },
                handler=gitlab_list_issues,
            ),
            MCPTool(
                name="gitlab_get_issue",
                description="Get issue details by IID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_get_issue,
            ),
            MCPTool(
                name="gitlab_create_issue",
                description="Create a GitLab issue for frontend diagnostics.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                        "assignee": {"type": "string"},
                        "milestone": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["title", "description"],
                },
                handler=gitlab_create_issue,
            ),
            MCPTool(
                name="gitlab_update_issue",
                description="Update issue fields/state.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "state_event": {"type": "string"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_update_issue,
            ),
            MCPTool(
                name="gitlab_create_issue_note",
                description="Create note/comment on issue.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "body": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid", "body"],
                },
                handler=gitlab_create_issue_note,
            ),
            MCPTool(
                name="gitlab_list_issue_notes",
                description="List issue notes/comments.",
                parameters={
                    "type": "object",
                    "properties": {
                        "iid": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["iid"],
                },
                handler=gitlab_list_issue_notes,
            ),
            MCPTool(
                name="gitlab_list_pipelines",
                description="List pipelines in project.",
                parameters={
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "status": {"type": "string"},
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                },
                handler=gitlab_list_pipelines,
            ),
            MCPTool(
                name="gitlab_get_pipeline",
                description="Get pipeline details by ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pipeline_id": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["pipeline_id"],
                },
                handler=gitlab_get_pipeline,
            ),
            MCPTool(
                name="gitlab_retry_pipeline",
                description="Retry pipeline by ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pipeline_id": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["pipeline_id"],
                },
                handler=gitlab_retry_pipeline,
            ),
            MCPTool(
                name="gitlab_cancel_pipeline",
                description="Cancel pipeline by ID.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pipeline_id": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["pipeline_id"],
                },
                handler=gitlab_cancel_pipeline,
            ),
            MCPTool(
                name="gitlab_list_pipeline_jobs",
                description="List jobs for a pipeline.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pipeline_id": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["pipeline_id"],
                },
                handler=gitlab_list_pipeline_jobs,
            ),
            MCPTool(
                name="gitlab_get_job_log",
                description="Get job log trace preview.",
                parameters={
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["job_id"],
                },
                handler=gitlab_get_job_log,
            ),
            MCPTool(
                name="gitlab_list_labels",
                description="List project labels.",
                parameters={
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer"},
                        "per_page": {"type": "integer"},
                        "project_id": {"type": "string"},
                    },
                },
                handler=gitlab_list_labels,
            ),
            MCPTool(
                name="gitlab_create_label",
                description="Create project label.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "color": {"type": "string"},
                        "description": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["name", "color"],
                },
                handler=gitlab_create_label,
            ),
            MCPTool(
                name="gitlab_update_label",
                description="Update project label.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "new_name": {"type": "string"},
                        "color": {"type": "string"},
                        "description": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["name"],
                },
                handler=gitlab_update_label,
            ),
            MCPTool(
                name="gitlab_delete_label",
                description="Delete project label by name.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "project_id": {"type": "string"},
                    },
                    "required": ["name"],
                },
                handler=gitlab_delete_label,
            ),
        ]

    def _build_monitoring_service(
        self,
        config: SubAgentConfig,
    ) -> AtomicMonitoringService | None:
        if not config.has_monitoring_credentials():
            logger.debug(
                "LangGraph monitoring tools disabled: missing BUGLENS_ALIBABA_ACCESS_KEY_ID/SECRET/REGION_ID"
            )
            return None

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

    def _build_monitoring_mcp_tools(self, config: SubAgentConfig) -> list[MCPTool]:
        if not config.enable_mcp_tools:
            return []
        monitoring = self._build_monitoring_service(config)
        if monitoring is None:
            return []

        def _arms_rum_list_apps(**kwargs: Any) -> dict[str, Any]:
            result = monitoring.arms_list_rum_apps(
                page_token=kwargs.get("page_token"),
                page_size=kwargs.get("page_size", 100),
            )
            return result.model_dump(mode="json", exclude_none=True)

        def _resolve_rum_sls_target(kwargs: dict[str, Any]) -> tuple[str, str]:
            project = kwargs.get("project") or config.rum_sls_project
            logstore = kwargs.get("logstore") or config.rum_sls_logstore
            if not project or not logstore:
                raise ValueError(
                    "RUM queries require project/logstore (set params or BUGLENS_RUM_SLS_PROJECT + BUGLENS_RUM_SLS_LOGSTORE)"
                )
            return str(project), str(logstore)

        def _arms_rum_search_errors(**kwargs: Any) -> dict[str, Any]:
            project, logstore = _resolve_rum_sls_target(kwargs)
            time_from_ms, time_to_ms = resolve_time_range(
                from_ms=kwargs.get("time_from_ms"),
                to_ms=kwargs.get("time_to_ms"),
                last=kwargs.get("last"),
            )
            query = build_rum_search_query(
                query=kwargs.get("query"),
                event_type=kwargs.get("event_type", "exception"),
                app_id=kwargs.get("app_id"),
                app_types=kwargs.get("app_types"),
                exception_message=kwargs.get("exception_message"),
                keyword=kwargs.get("keyword"),
            )
            result = monitoring.sls_search_logs(
                project=project,
                logstore=logstore,
                time_from_ms=time_from_ms,
                time_to_ms=time_to_ms,
                page_token=kwargs.get("page_token"),
                page_size=kwargs.get("page_size", 50),
                reverse=kwargs.get("reverse", True),
                extra_query={"query": query},
            )
            payload = result.model_dump(mode="json", exclude_none=True)
            payload["query"] = query
            return payload

        def _arms_rum_resolve_exception_stack(**kwargs: Any) -> dict[str, Any]:
            result = monitoring.arms_resolve_exception_stack(
                pid=str(kwargs["pid"]),
                line=int(kwargs["line"]),
                column=int(kwargs["column"]),
                sourcemap_type=str(kwargs.get("sourcemap_type", "js")),
                exception_binary_images=(
                    str(kwargs["exception_binary_images"])
                    if kwargs.get("exception_binary_images") is not None
                    else None
                ),
            )
            payload = result.model_dump(mode="json", exclude_none=True)
            payload["exception_stack"] = f'{int(kwargs["line"])},{int(kwargs["column"])},20'
            return payload

        return [
            MCPTool(
                name="arms_rum_list_apps",
                description="List ARMS RUM apps with normalized fields: app_type, description, endpoint, pid, region_id, sls_logstore, sls_project, type.",
                parameters={
                    "type": "object",
                    "properties": {
                        "page_token": {"type": "string"},
                        "page_size": {"type": "integer"},
                    },
                },
                handler=_arms_rum_list_apps,
            ),
            MCPTool(
                name="arms_rum_search_errors",
                description="Search ARMS frontend (RUM) errors with structured filters (event_type/app_id/app_types/exception_message) or raw query.",
                parameters={
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "logstore": {"type": "string"},
                        "last": {"type": "string"},
                        "time_from_ms": {"type": "integer"},
                        "time_to_ms": {"type": "integer"},
                        "query": {"type": "string"},
                        "event_type": {"type": "string"},
                        "app_id": {"type": "string"},
                        "app_types": {"type": "array", "items": {"type": "string"}},
                        "exception_message": {"type": "string"},
                        "keyword": {"type": "string"},
                        "page_token": {"type": "string"},
                        "page_size": {"type": "integer"},
                        "reverse": {"type": "boolean"},
                    },
                },
                handler=_arms_rum_search_errors,
            ),
            MCPTool(
                name="arms_rum_resolve_exception_stack",
                description="Resolve frontend exception stack using source map by pid + line + column.",
                parameters={
                    "type": "object",
                    "properties": {
                        "pid": {"type": "string"},
                        "line": {"type": "integer"},
                        "column": {"type": "integer"},
                        "sourcemap_type": {"type": "string"},
                        "exception_binary_images": {"type": "string"},
                    },
                    "required": ["pid", "line", "column"],
                },
                handler=_arms_rum_resolve_exception_stack,
            ),
        ]

    async def _discover_external_mcp_tools(self, config: SubAgentConfig) -> list[MCPTool]:
        if not config.mcp_servers:
            return []

        discovered: list[MCPTool] = []
        for server_name, server_config in config.mcp_servers.items():
            if not isinstance(server_name, str) or not server_name.strip():
                logger.warning("Skip external MCP server with invalid name: %r", server_name)
                continue
            if not isinstance(server_config, dict):
                logger.warning(
                    "Skip external MCP server %s: config must be an object",
                    server_name,
                )
                continue
            url = server_config.get("url")
            if not isinstance(url, str) or not url.strip():
                logger.warning(
                    "Skip external MCP server %s: only url-based config is supported in langgraph",
                    server_name,
                )
                continue
            try:
                server_tools = await self._discover_external_mcp_tools_from_url(
                    server_name=server_name,
                    server_url=url.strip(),
                )
                discovered.extend(server_tools)
                logger.info(
                    "LangGraph external MCP discovered server=%s tools=%d",
                    server_name,
                    len(server_tools),
                )
            except Exception as exc:
                logger.warning(
                    "LangGraph external MCP discovery failed server=%s url=%s error=%s",
                    server_name,
                    url.strip(),
                    self._summarize_exception(exc),
                )
        return discovered

    async def _discover_external_mcp_tools_from_url(
        self,
        server_name: str,
        server_url: str,
    ) -> list[MCPTool]:
        try:
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"mcp client import failed: {exc}") from exc

        tools: list[MCPTool] = []
        async with streamable_http_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                cursor: str | None = None
                while True:
                    listed = await session.list_tools(cursor=cursor)
                    for item in listed.tools:
                        schema = item.inputSchema or {"type": "object", "properties": {}}
                        if hasattr(schema, "model_dump"):
                            schema = schema.model_dump(mode="json", exclude_none=True)
                        if not isinstance(schema, dict):
                            schema = {"type": "object", "properties": {}}
                        name = str(item.name or "").strip()
                        if not name:
                            continue
                        description = (
                            item.description
                            or item.title
                            or f"External MCP tool from {server_name}"
                        )
                        tools.append(
                            MCPTool(
                                name=name,
                                description=description,
                                parameters=schema,
                                handler=self._build_external_mcp_handler(
                                    server_name=server_name,
                                    server_url=server_url,
                                    tool_name=name,
                                ),
                            )
                        )
                    cursor = listed.nextCursor
                    if not cursor:
                        break
        return tools

    def _build_external_mcp_handler(
        self,
        server_name: str,
        server_url: str,
        tool_name: str,
    ) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def _handler(**arguments: Any) -> dict[str, Any]:
            return await self._call_external_mcp_tool(
                server_name=server_name,
                server_url=server_url,
                tool_name=tool_name,
                arguments=arguments,
            )

        return _handler

    async def _call_external_mcp_tool(
        self,
        server_name: str,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from mcp.client.session import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"mcp client import failed: {exc}") from exc

        async with streamable_http_client(server_url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                logger.debug(
                    "LangGraph external_mcp_call_input server=%s tool=%s arguments=%s",
                    server_name,
                    tool_name,
                    self._debug_preview(arguments),
                )
                result = await session.call_tool(name=tool_name, arguments=arguments or {})
                logger.debug(
                    "LangGraph external_mcp_call_output server=%s tool=%s result=%s",
                    server_name,
                    tool_name,
                    self._debug_preview(result),
                )
                return self._normalize_external_mcp_result(
                    server_name=server_name,
                    tool_name=tool_name,
                    result=result,
                )

    def _normalize_external_mcp_result(
        self,
        server_name: str,
        tool_name: str,
        result: Any,
    ) -> dict[str, Any]:
        def _to_jsonable(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json", exclude_none=True)
            if isinstance(value, dict):
                return {str(k): _to_jsonable(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [_to_jsonable(v) for v in value]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return str(value)

        return {
            "source": "external_mcp",
            "server": server_name,
            "tool": tool_name,
            "is_error": bool(getattr(result, "isError", False)),
            "structured_content": _to_jsonable(getattr(result, "structuredContent", None)),
            "content": _to_jsonable(getattr(result, "content", [])),
        }

    def _merge_mcp_tools(
        self,
        builtin_tools: list[MCPTool],
        external_tools: list[MCPTool],
    ) -> tuple[list[MCPTool], int]:
        merged: dict[str, MCPTool] = {tool.name: tool for tool in builtin_tools}
        overridden = 0
        for tool in external_tools:
            if tool.name in merged:
                overridden += 1
            merged[tool.name] = tool
        return list(merged.values()), overridden

    def _tool_payload(self, tools: list[MCPTool]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": item.name,
                    "description": item.description,
                    "parameters": item.parameters,
                },
            }
            for item in tools
        ]

    async def _call_litellm_json(
        self,
        messages: list[dict[str, Any]],
        config: SubAgentConfig,
        tools: list[MCPTool],
    ) -> dict[str, Any]:
        url = config.resolve_litellm_url()
        if not url:
            raise RuntimeError("BUGLENS_ANTHROPIC_BASE_URL is required for langgraph runner")
        api_key = config.resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "BUGLENS_ANTHROPIC_API_KEY or BUGLENS_ANTHROPIC_AUTH_TOKEN is required for langgraph runner"
            )
        model = config.resolve_model()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = self._tool_payload(tools)
            payload["tool_choice"] = "auto"

        logger.debug(
            "LiteLLM request summary: %s",
            json.dumps(
                {
                    "runner": "langgraph",
                    "provider": config.llm_provider,
                    "url": url,
                    "model": model,
                    "stream": False,
                    "tools_enabled": bool(tools),
                    "tool_count": len(tools),
                    "timeout_seconds": config.timeout_seconds,
                    "first_packet_timeout_seconds": config.first_packet_timeout_seconds,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

        timeout = httpx.Timeout(
            timeout=config.timeout_seconds,
            connect=min(config.first_packet_timeout_seconds, config.timeout_seconds),
        )

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def _call_litellm_stream(
        self,
        messages: list[dict[str, Any]],
        config: SubAgentConfig,
        on_text: Callable[[str], None],
    ) -> tuple[str, dict[str, Any] | None]:
        url = config.resolve_litellm_url()
        if not url:
            raise RuntimeError("BUGLENS_ANTHROPIC_BASE_URL is required for langgraph runner")
        api_key = config.resolve_api_key()
        if not api_key:
            raise RuntimeError(
                "BUGLENS_ANTHROPIC_API_KEY or BUGLENS_ANTHROPIC_AUTH_TOKEN is required for langgraph runner"
            )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = {
            "model": config.resolve_model(),
            "messages": messages,
            "stream": True,
        }
        timeout = httpx.Timeout(
            timeout=config.timeout_seconds,
            connect=min(config.first_packet_timeout_seconds, config.timeout_seconds),
        )

        started_at = time.monotonic()
        first_token_at: float | None = None
        output_parts: list[str] = []
        usage: dict[str, Any] | None = None
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async with asyncio.timeout(config.first_packet_timeout_seconds):
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_line = line[len("data:") :].strip()
                        if not data_line:
                            continue
                        if data_line == "[DONE]":
                            break
                        event = json.loads(data_line)
                        delta = event.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content")
                        if token:
                            if first_token_at is None:
                                first_token_at = time.monotonic()
                                logger.info(
                                    "LiteLLM phase=first_token elapsed_ms=%d",
                                    int((first_token_at - started_at) * 1000),
                                )
                            token_text = str(token)
                            output_parts.append(token_text)
                            on_text(token_text)
                        if event.get("usage"):
                            usage = event.get("usage")

        output = "".join(output_parts).strip()
        if not output:
            raise RuntimeError("LiteLLM stream finished with empty output")
        return output, usage

    async def _execute_tool_call(
        self,
        tool_map: dict[str, MCPTool],
        tool_call: dict[str, Any],
    ) -> tuple[str, str]:
        tool_name = tool_call.get("function", {}).get("name", "")
        call_id = str(tool_call.get("id", ""))
        tool = tool_map.get(tool_name)
        if tool is None:
            payload = {"error": f"Unknown tool: {tool_name}"}
            return call_id, json.dumps(payload, ensure_ascii=False)

        arguments_raw = tool_call.get("function", {}).get("arguments", "{}")
        try:
            arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else {}
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}

        logger.info("LangGraph tool_call_start name=%s call_id=%s", tool_name, call_id)
        logger.debug(
            "LangGraph tool_call_input name=%s call_id=%s arguments=%s",
            tool_name,
            call_id,
            self._debug_preview(arguments),
        )
        logger.debug(
            "LangGraph mcp_tool_call_input name=%s call_id=%s arguments=%s",
            tool_name,
            call_id,
            self._debug_preview(arguments),
        )
        started = time.monotonic()
        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**arguments)
            else:
                result = await asyncio.to_thread(tool.handler, **arguments)
            if not isinstance(result, dict):
                result = {"result": result}
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.info(
                "LangGraph tool_call_complete name=%s call_id=%s elapsed_ms=%d",
                tool_name,
                call_id,
                elapsed_ms,
            )
            logger.debug(
                "LangGraph tool_call_output name=%s call_id=%s result=%s",
                tool_name,
                call_id,
                self._debug_preview(result),
            )
            logger.debug(
                "LangGraph mcp_tool_call_output name=%s call_id=%s result=%s",
                tool_name,
                call_id,
                self._debug_preview(result),
            )
            return call_id, json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "LangGraph tool_call_error name=%s call_id=%s elapsed_ms=%d err=%s",
                tool_name,
                call_id,
                elapsed_ms,
                exc,
            )
            logger.debug(
                "LangGraph tool_call_error_input name=%s call_id=%s arguments=%s",
                tool_name,
                call_id,
                self._debug_preview(arguments),
            )
            return call_id, json.dumps({"error": str(exc)}, ensure_ascii=False)

    async def run(
        self,
        request: InvokeRequest,
        config: SubAgentConfig,
        on_text: Callable[[str], None] | None = None,
    ) -> InvokeResponse:
        if config.mock_response is not None:
            return InvokeResponse(output=config.mock_response, model=config.resolve_model())

        messages = self._build_messages(request, config)
        gitlab_tools = self._build_mcp_tools(config)
        if gitlab_tools and not self._should_enable_gitlab_tools(request):
            logger.debug(
                "LangGraph tool gating: skip built-in GitLab tools for non-GitLab task"
            )
            gitlab_tools = []
        monitoring_tools = self._build_monitoring_mcp_tools(config)
        builtin_tools = gitlab_tools + monitoring_tools
        external_tools = await self._discover_external_mcp_tools(config)
        tools, overridden_count = self._merge_mcp_tools(builtin_tools, external_tools)
        logger.info(
            "LangGraph tools prepared gitlab=%d monitoring=%d builtin=%d external=%d merged=%d overridden=%d",
            len(gitlab_tools),
            len(monitoring_tools),
            len(builtin_tools),
            len(external_tools),
            len(tools),
            overridden_count,
        )
        logger.debug(
            "LangGraph tools prepared names=%s",
            self._debug_preview([tool.name for tool in tools], max_chars=8000),
        )
        tool_map = {tool.name: tool for tool in tools}

        async def _invoke_node(state: LiteLLMGraphState) -> LiteLLMGraphState:
            local_messages = list(state["messages"])
            usage: dict[str, Any] | None = None
            output = ""
            streamed = False
            finish_reason: str | None = None
            max_steps = min(config.mcp_tool_call_max_steps, config.max_turns)
            reached_max_steps = True

            for step in range(max_steps):
                data = await self._call_litellm_json(local_messages, config, tools)
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else usage
                choice = data.get("choices", [{}])[0]
                assistant_message = choice.get("message", {})
                tool_calls = assistant_message.get("tool_calls") or []
                content = assistant_message.get("content")

                assistant_payload: dict[str, Any] = {
                    "role": "assistant",
                    "content": content if isinstance(content, str) else "",
                }
                if tool_calls:
                    assistant_payload["tool_calls"] = tool_calls
                local_messages.append(assistant_payload)

                logger.info(
                    "LangGraph tool_selection step=%d tool_calls=%d",
                    step + 1,
                    len(tool_calls),
                )
                if not tool_calls:
                    logger.debug(
                        "LangGraph mcp_tool_call_skipped step=%d reason=no_tool_calls assistant_content=%s",
                        step + 1,
                        self._debug_preview(assistant_payload.get("content", "")),
                    )

                if tool_calls and tools:
                    for tool_call in tool_calls:
                        call_id, tool_output = await self._execute_tool_call(tool_map, tool_call)
                        local_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": tool_output,
                            }
                        )
                    continue

                output = assistant_payload["content"].strip()
                reached_max_steps = False
                finish_reason = "assistant_response"
                break

            if not output and on_text is not None:
                try:
                    output, usage = await self._call_litellm_stream(local_messages, config, on_text)
                    streamed = True
                    finish_reason = "stream_fallback"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LangGraph stream fallback failed: %s", exc)

            if not output:
                if reached_max_steps:
                    finish_reason = "max_tool_steps_reached"
                    output = (
                        "No final answer was produced before reaching the max tool-call steps "
                        f"({max_steps}). Consider increasing BUGLENS_MCP_TOOL_CALL_MAX_STEPS "
                        "or narrowing the task scope."
                    )
                else:
                    finish_reason = finish_reason or "empty_model_response"
                    output = (
                        "No final answer was produced by the model. "
                        "Please retry with more specific context."
                    )

            return {
                "messages": local_messages,
                "output": output,
                "usage": usage,
                "streamed": streamed,
                "finish_reason": finish_reason,
            }

        graph = StateGraph(LiteLLMGraphState)
        graph.add_node("invoke", _invoke_node)
        graph.set_entry_point("invoke")
        graph.add_edge("invoke", END)
        app = graph.compile()

        started_at = time.monotonic()
        try:
            async with asyncio.timeout(config.timeout_seconds):
                result = await app.ainvoke(
                    {
                        "messages": messages,
                        "output": "",
                        "usage": None,
                        "streamed": False,
                        "finish_reason": None,
                    }
                )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body_snippet = exc.response.text[:400]
            raise RuntimeError(
                f"LiteLLM HTTP error status={status}, body={body_snippet}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"LiteLLM request failed: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"LangGraph runner timed out after {config.timeout_seconds}s"
            ) from exc

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        logger.info(
            "LangGraph invoke phase=complete elapsed_ms=%d finish_reason=%s",
            elapsed_ms,
            result.get("finish_reason"),
        )

        output = str(result.get("output", "")).strip()
        if on_text is not None and not result.get("streamed", False):
            on_text(output)

        usage = result.get("usage")
        usage_dict = usage if isinstance(usage, dict) else None
        return InvokeResponse(
            output=output,
            model=config.resolve_model(),
            usage=usage_dict,
            raw_result=output,
        )


class SubAgent:
    def __init__(
        self,
        config: SubAgentConfig | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.config = config or SubAgentConfig()
        if runner is not None:
            self.runner = runner
        else:
            self.runner = LangGraphRunner()
        self.initialized = False

    async def initialize(self, overrides: dict | None = None) -> AgentMetadata:
        if overrides:
            merged = self.config.model_dump()
            merged.update(overrides)
            self.config = SubAgentConfig.model_validate(merged)
            self.runner = LangGraphRunner()
        logger.info(
            "SubAgent initialized runner=%s model=%s anthropic_model=%s base_url_set=%s auth_token_set=%s mock_response_set=%s",
            self.config.runner,
            self.config.model,
            self.config.anthropic_model,
            bool(self.config.anthropic_base_url),
            bool(self.config.resolve_api_key()),
            self.config.mock_response is not None,
        )
        self.initialized = True
        return AgentMetadata(
            name=self.config.name,
            version=self.config.version,
            capabilities=["health", "invoke"],
        )

    async def health(self) -> dict[str, str]:
        return {"status": "ok" if self.initialized else "not_initialized"}

    async def invoke(
        self, request: InvokeRequest, on_text: Callable[[str], None] | None = None
    ) -> InvokeResponse:
        if not self.initialized:
            await self.initialize()
        return await self.runner.run(request, self.config, on_text=on_text)

    async def shutdown(self) -> dict[str, bool]:
        self.initialized = False
        return {"stopped": True}

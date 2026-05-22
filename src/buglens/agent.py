from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypedDict

import httpx
from claude_code_sdk import (
    AssistantMessage,
    ClaudeCodeOptions,
    ResultMessage,
    TextBlock,
    query,
)
from langgraph.graph import END, StateGraph

from .config import SubAgentConfig
from .mcp_server import (
    arms_get_error_detail,
    arms_get_related_api,
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


def _safe_serialize(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _safe_serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_serialize(v) for v in value]
    return str(value)


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


class ClaudeCodeSDKRunner:
    async def run(
        self,
        request: InvokeRequest,
        config: SubAgentConfig,
        on_text: Callable[[str], None] | None = None,
    ) -> InvokeResponse:
        if config.mock_response is not None:
            return InvokeResponse(output=config.mock_response, model=config.resolve_model())

        prompt = request.task
        if request.context:
            context_json = json.dumps(request.context, ensure_ascii=False, indent=2)
            prompt = f"{request.task}\n\nContext:\n{context_json}"

        sdk_env = config.build_sdk_env()
        cli_model = config.model if config.pass_model_to_cli else None
        options = ClaudeCodeOptions(
            model=cli_model,
            system_prompt=config.system_prompt,
            max_turns=config.max_turns,
            allowed_tools=config.allowed_tools,
            permission_mode=config.permission_mode,
            cwd=config.cwd,
            mcp_servers=config.mcp_servers,
            env=sdk_env,
        )
        redacted_env = {
            key: (
                "***redacted***"
                if any(
                    flag in key.upper()
                    for flag in ("TOKEN", "SECRET", "KEY", "AUTH", "PASSWORD")
                )
                else value
            )
            for key, value in sdk_env.items()
        }
        options_log_payload = {
            "runner": "claude_sdk",
            "model": config.resolve_model(),
            "cli_model": cli_model,
            "pass_model_to_cli": config.pass_model_to_cli,
            "system_prompt": config.system_prompt,
            "max_turns": config.max_turns,
            "allowed_tools": config.allowed_tools,
            "permission_mode": config.permission_mode,
            "cwd": str(config.cwd),
            "mcp_servers": config.mcp_servers,
            "timeout_seconds": config.timeout_seconds,
            "first_packet_timeout_seconds": config.first_packet_timeout_seconds,
            "env": redacted_env,
        }
        logger.info(
            "ClaudeCodeSDK options(summary): %s",
            json.dumps(options_log_payload, ensure_ascii=False, sort_keys=True),
        )
        if logger.isEnabledFor(logging.DEBUG):
            raw_options_payload = {
                field.name: _safe_serialize(getattr(options, field.name))
                for field in dataclasses.fields(options)
            }
            logger.debug(
                "ClaudeCodeSDK options(full): %s",
                json.dumps(raw_options_payload, ensure_ascii=False, sort_keys=True, default=str),
            )

        session_id: str | None = None
        usage: dict | None = None
        raw_result: str | None = None
        collected_text: list[str] = []
        message_count = 0
        text_block_count = 0
        message_type_counts: dict[str, int] = {}
        invoke_started_at = time.monotonic()
        first_message_at: float | None = None
        first_text_at: float | None = None
        last_api_error: dict[str, object] | None = None

        logger.info("Claude invoke phase=connect_start")

        def _process_message(message: object) -> None:
            nonlocal raw_result, usage, session_id, first_message_at, first_text_at
            nonlocal message_count, text_block_count, last_api_error
            message_count += 1
            message_type = type(message).__name__
            message_type_counts[message_type] = message_type_counts.get(message_type, 0) + 1
            if first_message_at is None:
                first_message_at = time.monotonic()
                logger.info(
                    "Claude invoke phase=connected elapsed_ms=%d",
                    int((first_message_at - invoke_started_at) * 1000),
                )

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_block_count += 1
                        collected_text.append(block.text)
                        if first_text_at is None and block.text:
                            first_text_at = time.monotonic()
                            logger.info(
                                "Claude invoke phase=first_token elapsed_ms=%d",
                                int((first_text_at - invoke_started_at) * 1000),
                            )
                        if on_text is not None and block.text:
                            on_text(block.text)
            elif type(message).__name__ == "StreamEvent":
                event = message.event or {}
                if event.get("type") == "content_block_delta":
                    delta = event.get("delta") or {}
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        text = str(delta.get("text", ""))
                        if text:
                            text_block_count += 1
                            collected_text.append(text)
                            if first_text_at is None:
                                first_text_at = time.monotonic()
                                logger.info(
                                    "Claude invoke phase=first_token elapsed_ms=%d",
                                    int((first_text_at - invoke_started_at) * 1000),
                                )
                            if on_text is not None:
                                on_text(text)
            elif type(message).__name__ == "SystemMessage":
                subtype = getattr(message, "subtype", None)
                data = getattr(message, "data", {}) or {}
                if subtype == "api_retry":
                    error = data.get("error")
                    status = data.get("error_status")
                    attempt = data.get("attempt")
                    max_retries = data.get("max_retries")
                    last_api_error = {
                        "error": error,
                        "error_status": status,
                        "attempt": attempt,
                        "max_retries": max_retries,
                    }
                    logger.warning(
                        "Claude invoke system api_retry error=%s status=%s attempt=%s/%s",
                        error,
                        status,
                        attempt,
                        max_retries,
                    )
            elif isinstance(message, ResultMessage):
                raw_result = message.result
                usage = message.usage
                session_id = message.session_id
                logger.debug(
                    "Received result message session_id=%s is_error=%s",
                    session_id,
                    message.is_error,
                )
                if message.is_error:
                    detail = raw_result or "Claude SDK returned an error result"
                    raise RuntimeError(detail)

        async def _collect() -> None:
            stream = query(prompt=prompt, options=options)
            iterator = stream.__aiter__()
            try:
                async with asyncio.timeout(config.first_packet_timeout_seconds):
                    first_message = await iterator.__anext__()
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                logger.error(
                    "Claude invoke phase=first_packet_timeout elapsed_ms=%d timeout_seconds=%d",
                    int((time.monotonic() - invoke_started_at) * 1000),
                    config.first_packet_timeout_seconds,
                )
                raise RuntimeError(
                    f"Timed out waiting for first packet after "
                    f"{config.first_packet_timeout_seconds}s"
                ) from exc

            _process_message(first_message)
            async for message in iterator:
                _process_message(message)

        try:
            async with asyncio.timeout(config.timeout_seconds):
                await _collect()
        except asyncio.TimeoutError as exc:
            elapsed_ms = int((time.monotonic() - invoke_started_at) * 1000)
            logger.error(
                "Claude invoke phase=timeout elapsed_ms=%d timeout_seconds=%d first_message_received=%s first_token_received=%s",
                elapsed_ms,
                config.timeout_seconds,
                first_message_at is not None,
                first_text_at is not None,
            )
            if last_api_error is not None:
                raise RuntimeError(
                    "Invoke timed out while upstream kept retrying API calls. "
                    f"last_api_error={json.dumps(last_api_error, ensure_ascii=False)}"
                ) from exc
            raise RuntimeError(
                f"Invoke timed out after {config.timeout_seconds}s (elapsed {elapsed_ms}ms)"
            ) from exc
        finally:
            finished_at = time.monotonic()
            logger.info(
                "Claude invoke phase=complete elapsed_ms=%d connect_ms=%s first_token_ms=%s messages=%d text_blocks=%d type_counts=%s",
                int((finished_at - invoke_started_at) * 1000),
                (
                    int((first_message_at - invoke_started_at) * 1000)
                    if first_message_at is not None
                    else "n/a"
                ),
                (
                    int((first_text_at - invoke_started_at) * 1000)
                    if first_text_at is not None
                    else "n/a"
                ),
                message_count,
                text_block_count,
                json.dumps(message_type_counts, ensure_ascii=False, sort_keys=True),
            )

        output = (raw_result or "\n".join(collected_text)).strip()
        if not output:
            raise RuntimeError("Claude SDK returned an empty response")

        return InvokeResponse(
            output=output,
            model=config.resolve_model(),
            session_id=session_id,
            usage=usage,
            raw_result=raw_result,
        )


class LiteLLMGraphState(TypedDict):
    messages: list[dict[str, Any]]
    output: str
    usage: dict[str, Any] | None
    streamed: bool


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


class LangGraphRunner:
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

    def _build_mcp_tools(self, config: SubAgentConfig) -> list[MCPTool]:
        if not config.enable_mcp_tools:
            return []
        return [
            MCPTool(
                name="arms_get_error_detail",
                description="Get ARMS RUM error detail with sourcemap location.",
                parameters={
                    "type": "object",
                    "properties": {
                        "app": {"type": "string"},
                        "page": {"type": "string"},
                        "error_message": {"type": "string"},
                        "version": {"type": "string"},
                        "event_url": {"type": "string"},
                    },
                    "required": ["app"],
                },
                handler=arms_get_error_detail,
            ),
            MCPTool(
                name="arms_get_related_api",
                description="Get ARMS API records around error time by trace id.",
                parameters={
                    "type": "object",
                    "properties": {
                        "trace_id": {"type": "string"},
                        "app": {"type": "string"},
                    },
                    "required": ["trace_id", "app"],
                },
                handler=arms_get_related_api,
            ),
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

        logger.info(
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
        started = time.monotonic()
        try:
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
        tools = self._build_mcp_tools(config)
        tool_map = {tool.name: tool for tool in tools}

        async def _invoke_node(state: LiteLLMGraphState) -> LiteLLMGraphState:
            local_messages = list(state["messages"])
            usage: dict[str, Any] | None = None
            output = ""
            streamed = False
            max_steps = min(config.mcp_tool_call_max_steps, config.max_turns)

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
                break

            if not output and on_text is not None:
                output, usage = await self._call_litellm_stream(local_messages, config, on_text)
                streamed = True

            return {
                "messages": local_messages,
                "output": output,
                "usage": usage,
                "streamed": streamed,
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
                    {"messages": messages, "output": "", "usage": None, "streamed": False}
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
        logger.info("LangGraph invoke phase=complete elapsed_ms=%d", elapsed_ms)

        output = str(result.get("output", "")).strip()
        if not output:
            raise RuntimeError("LangGraph runner returned an empty response")
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
        elif self.config.runner == "claude_sdk":
            self.runner = ClaudeCodeSDKRunner()
        else:
            self.runner = LangGraphRunner()
        self.initialized = False

    async def initialize(self, overrides: dict | None = None) -> AgentMetadata:
        if overrides:
            merged = self.config.model_dump()
            merged.update(overrides)
            self.config = SubAgentConfig.model_validate(merged)
            if self.config.runner == "claude_sdk":
                self.runner = ClaudeCodeSDKRunner()
            else:
                self.runner = LangGraphRunner()
        logger.info(
            "SubAgent initialized runner=%s model=%s pass_model_to_cli=%s anthropic_model=%s base_url_set=%s auth_token_set=%s mock_response_set=%s",
            self.config.runner,
            self.config.model,
            self.config.pass_model_to_cli,
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

# buglens

`buglens` is a Python sub-agent runtime built with `uv`, `pydantic`, and `langgraph`.
It runs as a STDIO JSON-RPC server so OpenClaw can spawn it as a child agent process.
It also provides an MCP server (`buglens-mcp`) for GitLab diagnostic tools.
It now includes a read-only monitoring atomic capability layer for Alibaba Cloud ARMS + SLS.

## Requirements

- Python `3.11+`
- `uv` installed
- LiteLLM/OpenAI-compatible endpoint credentials

## Setup

```bash
uv sync
```

## Run

```bash
uv run buglens
```

`buglens` reads one JSON-RPC request per line from `stdin` and writes one response line to
`stdout`.

Example requests:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"config":{"model":"deepseek-v3.2"}}}
{"jsonrpc":"2.0","id":2,"method":"health","params":{}}
{"jsonrpc":"2.0","id":3,"method":"invoke","params":{"task":"Summarize this issue","context":{"issue_id":"123"}}}
{"jsonrpc":"2.0","id":4,"method":"shutdown","params":{}}
```

Quick debugging without JSON-RPC:

```bash
uv run buglens invoke --task "summarize this error" --mock-response "debug-ok"
uv run buglens repl --mock-response "debug-ok"
uv run buglens invoke --task "summarize this error" --stream
uv run buglens --log-level INFO repl --stream
```

Notes:

- `--stream`: stream assistant text to `stdout` as it arrives (works in `invoke` and `repl`).
- `--log-level`: write runtime logs to `stderr` (`DEBUG|INFO|WARNING|ERROR`), so it will not break STDOUT parsing.

## OpenClaw integration shape

OpenClaw can register this sub-agent by launching the command below and exchanging JSON-RPC
messages over STDIO:

```bash
uv run buglens
```

Expected methods:

- `initialize`
- `health`
- `invoke`
- `shutdown`

## Skill mode (Codex + OpenClaw)

This repo now ships a unified `buglens` skill package under `skills/buglens`:

- `SKILL.md`: orchestration contract (frontend incident diagnosis -> GitLab issue workflow)
- `agents/openai.yaml`: Codex-facing UI metadata (`display_name`, `short_description`, `default_prompt`)

Export local distribution artifacts:

```bash
uv run buglens skills export --output ./dist/openclaw-skills
```

Install into OpenClaw from local directory:

```bash
openclaw skills install ./dist/openclaw-skills/buglens
```

Codex can also consume the same folder as a project/local skill source in environments where local skill directories are enabled.

Build a full third-party bundle (skill + runtime wheel + MCP config templates):

```bash
uv run buglens skills release --output ./dist/release-bundle
```

This is the recommended path for environments that do not have buglens source code.

## MCP tools (recommended integration backbone)

Run MCP server:

```bash
uv run buglens-mcp
```

Exposed tools:

- GitLab Project/Repo: `gitlab_list_projects`, `gitlab_search_projects`, `gitlab_get_project`, `gitlab_get_file`, `gitlab_list_branches`, `gitlab_get_branch`, `gitlab_find_page_code`, `gitlab_get_commits`
- GitLab Merge Requests: `gitlab_list_merge_requests`, `gitlab_get_merge_request`, `gitlab_create_merge_request`, `gitlab_update_merge_request`, `gitlab_merge_merge_request`, `gitlab_get_mr_changes`, `gitlab_get_mr_discussions`, `gitlab_create_mr_note`
- GitLab Issues: `gitlab_list_issues`, `gitlab_get_issue`, `gitlab_create_issue`, `gitlab_update_issue`, `gitlab_create_issue_note`, `gitlab_list_issue_notes`
- GitLab Pipelines/Jobs: `gitlab_list_pipelines`, `gitlab_get_pipeline`, `gitlab_retry_pipeline`, `gitlab_cancel_pipeline`, `gitlab_list_pipeline_jobs`, `gitlab_get_job_log`
- GitLab Labels: `gitlab_list_labels`, `gitlab_create_label`, `gitlab_update_label`, `gitlab_delete_label`

LangGraph built-in tools (used by `buglens` runtime):

- GitLab built-ins (gated for GitLab-like tasks)
- Frontend RUM built-ins (when Alibaba credentials are present): `arms_rum_list_apps`, `arms_rum_search_errors`, `arms_rum_get_error_context`, `arms_get_error_detail`
- External MCP tools from `BUGLENS_MCP_SERVERS` (merged with built-ins, external tool names override on conflict)

## Monitoring atomic capability library (RUM-focused)

`buglens.monitoring` provides adapter + service layers for model-side consumption:

- ARMS adapter (`ARMS/2019-08-08` OpenAPI): `get_rum_apps`
- RUM query adapter (OpenAPI-backed): `search_logs`, `get_log_context`, `get_log_histogram`, `list_projects`, `list_logstores`
- Unified service facade (`AtomicMonitoringService`) with unified envelope:
  - `{success, request_id, latency_ms, data, error, next_page_token, partial_success}`
  - unified time input/output convention: `epoch_ms`
  - unified error codes: `AUTH_FAILED | PERMISSION_DENIED | RATE_LIMITED | TIMEOUT | INVALID_PARAM | UPSTREAM_ERROR`

Minimal usage:

```python
from buglens.monitoring import ARMSClient, SLSClient, AtomicMonitoringService

sls = SLSClient(
    access_key_id="your-ak",
    access_key_secret="your-sk",
    security_token="optional-sts-token",
    region_id="cn-hangzhou",
)
arms = ARMSClient(
    access_key_id="your-ak",
    access_key_secret="your-sk",
    security_token="optional-sts-token",
    region_id="cn-hangzhou",
)
svc = AtomicMonitoringService(sls_client=sls, arms_client=arms)
result = svc.sls_search_logs(
    project="proj-demo",
    logstore="app-logstore",
    time_from_ms=1700000000000,
    time_to_ms=1700000900000,
)
```

Recommended architecture for the single external `buglens` skill:

- Keep Skill as orchestration/prompt layer (parse alert card, generate report text).
- Move executable capability to MCP tools (this repo now provides those tools).
- Result: less duplicate script management, better reuse, and stable typed interfaces.

## Environment configuration

Copy `.env.example` and set fields as needed:

- `BUGLENS_MODEL`
- `BUGLENS_RUNNER` (only `langgraph` is supported)
- `BUGLENS_LLM_PROVIDER` (default `litellm`)
- `BUGLENS_ENABLE_MCP_TOOLS` (default `true`; enable built-in GitLab + monitoring tools on `langgraph` runner)
- `BUGLENS_MCP_TOOL_CALL_MAX_STEPS` (default `6`; max auto tool-call rounds per invoke)
- `BUGLENS_SHOW_TOOL_CALL_TRACE` (default `false`; when stream output is enabled, print tool call args and tool outputs)
- `BUGLENS_SYSTEM_PROMPT`
- `BUGLENS_MAX_TURNS`
- `BUGLENS_TIMEOUT_SECONDS`
- `BUGLENS_FIRST_PACKET_TIMEOUT_SECONDS` (default `30`, fail fast if first SDK packet does not arrive)
- `BUGLENS_PERMISSION_MODE`
- `BUGLENS_MOCK_RESPONSE` (optional test-only shortcut)
- `BUGLENS_MCP_SERVERS` (optional JSON object for extra MCP servers; `langgraph` supports `mcpServers.*.url` only)
- `BUGLENS_ANTHROPIC_AUTH_TOKEN` (optional; fallback for API key)
- `BUGLENS_ANTHROPIC_API_KEY`
- `BUGLENS_ANTHROPIC_BASE_URL`
- `BUGLENS_ANTHROPIC_MODEL`
- `BUGLENS_ALIBABA_ACCESS_KEY_ID` (required for monitoring built-ins)
- `BUGLENS_ALIBABA_ACCESS_KEY_SECRET` (required for monitoring built-ins)
- `BUGLENS_ALIBABA_REGION_ID` (required for monitoring built-ins)
- `BUGLENS_ALIBABA_SECURITY_TOKEN` (optional STS token)
- `BUGLENS_ARMS_ENDPOINT` (optional, default `arms.aliyuncs.com`)
- `BUGLENS_SLS_ENDPOINT` (optional, default `${BUGLENS_ALIBABA_REGION_ID}.log.aliyuncs.com`)
- `BUGLENS_RUM_SLS_PROJECT` (required default project for `arms_rum_*` tools unless passed per call)
- `BUGLENS_RUM_SLS_LOGSTORE` (required default logstore for `arms_rum_*` tools unless passed per call)
- `BUGLENS_MONITORING_MAX_RETRIES` (default `2`)
- `BUGLENS_MONITORING_BASE_BACKOFF_SECONDS` (default `0.25`)
- `BUGLENS_MONITORING_MAX_BACKOFF_SECONDS` (default `5.0`)
- `BUGLENS_MONITORING_MAX_CONCURRENCY` (default `4`)

`buglens` will automatically load `.env` from the current working directory.

Also required by MCP tools:

- `GITLAB_URL`
- `GITLAB_TOKEN`
- `GITLAB_PROJECT_ID` (optional default; can pass `project_id` per MCP tool call)

To verify runtime config is applied (without printing secrets), use:

```bash
uv run buglens --log-level INFO invoke --task "ping" --stream
```

Example external MCP registration:

```bash
export BUGLENS_MCP_SERVERS='{"alibaba_cloud_observability":{"url":"http://localhost:8080"}}'
```

## Development

```bash
uv run ruff check .
uv run pytest
```

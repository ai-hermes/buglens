# buglens

`buglens` is a Python sub-agent runtime built with `uv`, `pydantic`, `langgraph`, and `claude-code-sdk`.
It runs as a STDIO JSON-RPC server so OpenClaw can spawn it as a child agent process.
It also provides an MCP server (`buglens-mcp`) for ARMS/GitLab diagnostic tools.

## Requirements

- Python `3.11+`
- `uv` installed
- LiteLLM/OpenAI-compatible endpoint credentials (default runner)
- Claude CLI/auth environment (only if using `BUGLENS_RUNNER=claude_sdk`)

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
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"config":{"model":"claude-sonnet-4-20250514"}}}
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

## MCP tools (recommended integration backbone)

Run MCP server:

```bash
uv run buglens-mcp
```

Exposed tools:

- `arms_get_error_detail`
- `arms_get_related_api`
- GitLab Project/Repo: `gitlab_list_projects`, `gitlab_search_projects`, `gitlab_get_project`, `gitlab_get_file`, `gitlab_list_branches`, `gitlab_get_branch`, `gitlab_find_page_code`, `gitlab_get_commits`
- GitLab Merge Requests: `gitlab_list_merge_requests`, `gitlab_get_merge_request`, `gitlab_create_merge_request`, `gitlab_update_merge_request`, `gitlab_merge_merge_request`, `gitlab_get_mr_changes`, `gitlab_get_mr_discussions`, `gitlab_create_mr_note`
- GitLab Issues: `gitlab_list_issues`, `gitlab_get_issue`, `gitlab_create_issue`, `gitlab_update_issue`, `gitlab_create_issue_note`, `gitlab_list_issue_notes`
- GitLab Pipelines/Jobs: `gitlab_list_pipelines`, `gitlab_get_pipeline`, `gitlab_retry_pipeline`, `gitlab_cancel_pipeline`, `gitlab_list_pipeline_jobs`, `gitlab_get_job_log`
- GitLab Labels: `gitlab_list_labels`, `gitlab_create_label`, `gitlab_update_label`, `gitlab_delete_label`

Recommended architecture for your two existing skills:

- Keep Skill as orchestration/prompt layer (parse alert card, generate report text).
- Move executable capability to MCP tools (this repo now provides those tools).
- Result: less duplicate script management, better reuse, and stable typed interfaces.

## Environment configuration

Copy `.env.example` and set fields as needed:

- `BUGLENS_MODEL`
- `BUGLENS_RUNNER` (default `langgraph`; options: `langgraph`, `claude_sdk`)
- `BUGLENS_LLM_PROVIDER` (default `litellm`)
- `BUGLENS_ENABLE_MCP_TOOLS` (default `true`; enable built-in ARMS/GitLab MCP tools on `langgraph` runner)
- `BUGLENS_MCP_TOOL_CALL_MAX_STEPS` (default `6`; max auto tool-call rounds per invoke)
- `BUGLENS_PASS_MODEL_TO_CLI` (default `false`; when `false`, do not pass CLI `--model`, rely on `ANTHROPIC_MODEL` env route)
- `BUGLENS_SYSTEM_PROMPT`
- `BUGLENS_MAX_TURNS`
- `BUGLENS_TIMEOUT_SECONDS`
- `BUGLENS_FIRST_PACKET_TIMEOUT_SECONDS` (default `30`, fail fast if first SDK packet does not arrive)
- `BUGLENS_PERMISSION_MODE`
- `BUGLENS_MOCK_RESPONSE` (optional test-only shortcut)
- `BUGLENS_ANTHROPIC_AUTH_TOKEN`
- `BUGLENS_ANTHROPIC_API_KEY` (optional; if absent, falls back to `BUGLENS_ANTHROPIC_AUTH_TOKEN`)
- `BUGLENS_ANTHROPIC_BASE_URL`
- `BUGLENS_ANTHROPIC_MODEL`

`buglens` will automatically load `.env` from the current working directory.

Also required by MCP tools:

- `ARMS_ACCESS_KEY_ID`
- `ARMS_ACCESS_KEY_SECRET`
- `ARMS_REGION_ID`
- `GITLAB_URL`
- `GITLAB_TOKEN`
- `GITLAB_PROJECT_ID` (optional default; can pass `project_id` per MCP tool call)

To verify runtime config is applied (without printing secrets), use:

```bash
uv run buglens --log-level INFO invoke --task "ping" --stream
```

## Development

```bash
uv run ruff check .
uv run pytest
```

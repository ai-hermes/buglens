# OpenClaw Skill Migration: Script -> MCP

## Decision

Use a hybrid model:

- **Skill**: orchestration only (intent parsing, diagnosis narrative, issue template generation).
- **MCP**: executable integrations.

This is better than pure Skill-script mode because tool interfaces become stable and reusable across agents.

## Mapping from `buglens` skill workflow

Monitoring phase:

- `arms_rum_search_errors`
- `arms_rum_get_error_context`
- `arms_get_error_detail`

GitLab phase:

- `gitlab_find_page_code`
- `gitlab_get_commits`
- `gitlab_create_issue`

`project_id` can be passed per tool call; `GITLAB_PROJECT_ID` is only a default fallback.

## Minimal SKILL.md adaptation pattern

Replace local shell command blocks with MCP tool instructions.
For ARMS diagnostics, call your external MCP server tools directly.

## Runtime

Start MCP server:

```bash
uv run buglens-mcp
```

Register the MCP server in OpenClaw, then keep your `buglens` skill as a thin workflow wrapper.

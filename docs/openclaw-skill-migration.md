# OpenClaw Skill Migration: Script -> MCP

## Decision

Use a hybrid model:

- **Skill**: orchestration only (intent parsing, diagnosis narrative, issue template generation).
- **MCP**: executable integrations.

This is better than pure Skill-script mode because tool interfaces become stable and reusable across agents.

## Mapping from existing skills

`gitlab-frontend`:

- `tools/find_page_code.py` -> `gitlab_find_page_code`
- `tools/get_commits.py` -> `gitlab_get_commits`
- `tools/create_issue.py` -> `gitlab_create_issue`

`project_id` can be passed per tool call; `GITLAB_PROJECT_ID` is only a default fallback.

## Minimal SKILL.md adaptation pattern

Replace local shell command blocks with MCP tool instructions.
For ARMS diagnostics, call your external MCP server tools directly.

## Runtime

Start MCP server:

```bash
uv run buglens-mcp
```

Register the MCP server in OpenClaw, then keep your two existing skills as thin workflow wrappers.

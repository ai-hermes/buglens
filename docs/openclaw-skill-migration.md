# OpenClaw Skill Migration: Script -> MCP

## Decision

Use a hybrid model:

- **Skill**: orchestration only (intent parsing, diagnosis narrative, issue template generation).
- **MCP**: all executable integrations (ARMS/GitLab API calls).

This is better than pure Skill-script mode because tool interfaces become stable and reusable across agents.

## Mapping from existing skills

`arms-rum-diagnosis`:

- `tools/get_error_detail.py` -> `arms_get_error_detail`
- `tools/get_related_api.py` -> `arms_get_related_api`

`gitlab-frontend`:

- `tools/find_page_code.py` -> `gitlab_find_page_code`
- `tools/get_commits.py` -> `gitlab_get_commits`
- `tools/create_issue.py` -> `gitlab_create_issue`

`project_id` can be passed per tool call; `GITLAB_PROJECT_ID` is only a default fallback.

## Minimal SKILL.md adaptation pattern

Replace shell command blocks like:

```bash
python {baseDir}/tools/get_error_detail.py --app "<app>" ...
```

with tool instructions like:

```md
Call MCP tool `arms_get_error_detail` with:
- app
- page
- error_message
- version
- event_url
```

Do this for all 5 tools above.

## Runtime

Start MCP server:

```bash
uv run buglens-mcp
```

Register the MCP server in OpenClaw, then keep your two existing skills as thin workflow wrappers.

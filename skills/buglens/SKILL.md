---
name: buglens
description: |
  Diagnose frontend production errors by orchestrating ARMS/RUM evidence, locating source ownership in GitLab, and drafting or creating actionable issues through MCP tools.
user-invocable: true
metadata:
  openclaw:
    requires:
      env:
        - GITLAB_URL
        - GITLAB_TOKEN
        - BUGLENS_ALIBABA_ACCESS_KEY_ID
        - BUGLENS_ALIBABA_ACCESS_KEY_SECRET
        - BUGLENS_ALIBABA_REGION_ID
---

# buglens Skill

Use this skill when users ask to investigate frontend online errors, map errors back to source code, or create a GitLab issue with owner context.

## Workflow

1. Parse or request key fields: `app`, `page`, `error_message`, `version`, `event_url`.
2. Call monitoring MCP tools to collect evidence:
   - `arms_rum_search_errors`
   - `arms_rum_get_error_context`
   - `arms_get_error_detail`
3. Extract downstream code inputs (`file_path`, `line`, optional `branch`, `project_id`).
4. Call GitLab MCP tools to confirm ownership and recent context:
   - `gitlab_find_page_code(file_path, line, branch?, context?, project_id?)`
   - `gitlab_get_commits(file_path, branch?, since?, limit?, project_id?)`
5. Draft a structured issue body (impact, repro hints, root-cause hypothesis, owner suggestion).
6. If user asks to create it, call:
   - `gitlab_create_issue(title, description, labels?, assignee_username?, milestone?, project_id?)`

## Output Contract

Always return:

- Error summary and confidence
- Source mapping result (`file_path`, `line`, commit hints)
- Impact/risk estimate
- Next action list
- If created: GitLab issue URL and ID

## Guardrails

- Keep the skill orchestration-only; do not replace MCP tool execution with ad-hoc shell scripts.
- If monitoring credentials are missing, clearly surface which env vars are required.
- If `project_id` is not provided and `GITLAB_PROJECT_ID` is absent, ask for explicit project scope before issue creation.

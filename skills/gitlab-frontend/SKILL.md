---
name: gitlab-frontend
description: |
  根据源码文件路径和行号定位 GitLab 代码、追踪责任提交并创建 Issue。执行能力来自 buglens MCP tools。
user-invocable: true
metadata: {"openclaw":{"requires":{"env":["GITLAB_URL","GITLAB_TOKEN"]}}}
---

# GitLab 前端定位与 Issue（MCP 版）

## 执行流程

1. 输入要求包含 `file_path` 与 `line`（可由上游 ARMS Skill 提供）。
2. 调用 MCP 工具 `gitlab_find_page_code` 拉取上下文代码。
3. 调用 MCP 工具 `gitlab_get_commits` 获取最近提交和建议 owner。
4. 基于错误摘要生成 issue body。
5. 调用 MCP 工具 `gitlab_create_issue` 创建 issue 并返回链接。

## MCP 工具调用约定

- `gitlab_find_page_code(file_path, line, branch, context, project_id?)`
- `gitlab_get_commits(file_path, branch, since, limit, project_id?)`
- `gitlab_create_issue(title, description, labels, assignee, milestone, project_id?)`

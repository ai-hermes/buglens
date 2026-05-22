---
name: arms-rum-diagnosis
description: |
  解析 ARMS 前端告警并输出错误归因摘要。执行能力来自 buglens MCP tools。
user-invocable: true
metadata: {"openclaw":{"requires":{"env":["ARMS_ACCESS_KEY_ID","ARMS_ACCESS_KEY_SECRET","ARMS_REGION_ID"]}}}
---

# ARMS 前端监控错误归因（MCP 版）

## 执行流程

1. 从用户消息提取 `app`、`page`、`error_message`、`version`、`event_url`。
2. 调用 MCP 工具 `arms_get_error_detail` 获取 SourceMap 定位结果。
3. 若返回 `trace_id`，调用 MCP 工具 `arms_get_related_api` 获取关联 API 上下文。
4. 输出结构化摘要：错误、源码位置、影响范围、根因假设、下游输入字段（`file_path` / `line`）。

## MCP 工具调用约定

- `arms_get_error_detail(app, page, error_message, version, event_url)`
- `arms_get_related_api(trace_id, app)`

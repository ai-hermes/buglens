---
name: arms-rum-diagnosis
description: |
  解析 ARMS 前端告警并输出错误归因摘要。执行能力来自外部 ARMS MCP server。
user-invocable: true
---

# ARMS 前端监控错误归因（MCP 版）

## 执行流程

1. 从用户消息提取 `app`、`page`、`error_message`、`version`、`event_url`。
2. 调用外部 ARMS MCP server 提供的错误详情工具获取 SourceMap 定位结果。
3. 若返回 `trace_id`，调用外部 ARMS MCP server 的关联 API 查询工具获取上下文。
4. 输出结构化摘要：错误、源码位置、影响范围、根因假设、下游输入字段（`file_path` / `line`）。

## MCP 工具调用约定

- 按外部 ARMS MCP server 实际暴露的工具名与参数调用。

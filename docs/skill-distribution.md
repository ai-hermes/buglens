# buglens Skill Distribution (Codex + OpenClaw)

This document describes how to package and distribute the `buglens` skill so both Codex and OpenClaw can recognize it.

## 1) Skill source layout

Canonical source in this repo:

- `skills/buglens/SKILL.md`
- `skills/buglens/agents/openai.yaml`

Packaged template used by CLI export:

- `src/buglens/skill_templates/buglens/...`

## 2) Export local distribution package

```bash
uv run buglens skills export --output ./dist/openclaw-skills
```

Expected output:

- `dist/openclaw-skills/manifest.json`
- `dist/openclaw-skills/buglens/SKILL.md`
- `dist/openclaw-skills/buglens/agents/openai.yaml`

Use `--overwrite` when re-exporting to an existing directory:

```bash
uv run buglens skills export --output ./dist/openclaw-skills --overwrite
```

## 3) OpenClaw local install

```bash
openclaw skills install ./dist/openclaw-skills/buglens
```

After installation, invoke skill intents such as:

- "用 buglens 分析这个前端报错并给出归因"
- "用 buglens 生成 GitLab issue 文案"

## 4) Codex recognition path

Codex recognition relies on `SKILL.md` metadata (`name`, `description`) and optional UI metadata in `agents/openai.yaml`.

Typical trigger examples:

- "Use buglens to diagnose this production frontend incident"
- "Run buglens workflow and prepare a GitLab issue"

## 5) MCP dependency checklist

### Required for GitLab MCP tools

- `GITLAB_URL`
- `GITLAB_TOKEN`
- `GITLAB_PROJECT_ID` (optional default)

### Required for ARMS/RUM monitoring tools

- `BUGLENS_ALIBABA_ACCESS_KEY_ID`
- `BUGLENS_ALIBABA_ACCESS_KEY_SECRET`
- `BUGLENS_ALIBABA_REGION_ID`
- `BUGLENS_RUM_SLS_PROJECT`
- `BUGLENS_RUM_SLS_LOGSTORE`

### Runtime

Start MCP server when needed:

```bash
uv run buglens-mcp
```

If tool calls fail, check env loading with:

```bash
uv run buglens --log-level INFO invoke --task "ping" --stream
```

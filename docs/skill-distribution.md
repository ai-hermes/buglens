# buglens Skill Distribution (Codex + OpenClaw)

This document describes how to package and distribute the `buglens` skill so both Codex and OpenClaw can recognize it.

## 1) Skill source layout

Canonical source in this repo:

- `skills/buglens/SKILL.md`
- `skills/buglens/agents/openai.yaml`

Packaged template used by CLI export:

- `src/buglens/skill_templates/buglens/...`

## 2) Export skill-only package (local quick mode)

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

This mode exports only the skill descriptor package and assumes runtime already exists.

## 3) Build full release bundle (recommended for third parties)

```bash
uv run buglens skills release --output ./dist/release-bundle
```

Bundle output:

- `dist/release-bundle/skill/buglens/...`
- `dist/release-bundle/runtime/buglens-*.whl`
- `dist/release-bundle/configs/openclaw-mcp.json`
- `dist/release-bundle/configs/codex-mcp.json`
- `dist/release-bundle/INSTALL.md`

If wheel was already built:

```bash
uv run buglens skills release --output ./dist/release-bundle --skip-build
```

## 4) OpenClaw local install

```bash
openclaw skills install ./dist/openclaw-skills/buglens
```

After installation, invoke skill intents such as:

- "用 buglens 分析这个前端报错并给出归因"
- "用 buglens 生成 GitLab issue 文案"

For full release bundle, install from:

```bash
openclaw skills install ./dist/release-bundle/skill/buglens
```

## 5) Codex recognition path

Codex recognition relies on `SKILL.md` metadata (`name`, `description`) and optional UI metadata in `agents/openai.yaml`.

Typical trigger examples:

- "Use buglens to diagnose this production frontend incident"
- "Run buglens workflow and prepare a GitLab issue"

## 6) MCP dependency checklist

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
uv run buglens-mcp --transport streamable-http --host 0.0.0.0 --port 8000
```

Default streamable endpoint:

```text
http://127.0.0.1:8000/mcp
```

If client runs from another machine and you see `Invalid Host header`, either:

```bash
uv run buglens-mcp --transport streamable-http --host 0.0.0.0 --port 8000 --allow-host 10.37.25.80:*
```

or (less strict, easier for LAN testing):

```bash
uv run buglens-mcp --transport streamable-http --host 0.0.0.0 --port 8000 --disable-dns-rebinding-protection
```

If tool calls fail, check env loading with:

```bash
uv run buglens --log-level INFO invoke --task "ping" --stream
```

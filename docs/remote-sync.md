# Remote Sync Scripts (`ssh devbox`)

Target remote path:

- `/home/dingwenjiang/workspace/buglens`

## 1) Full sync (recommended default)

```bash
./scripts/rsync-devbox.sh
```

Built-in excludes include non-essential local directories such as:

- `dist/`
- `venv/`
- `.venv/`
- `.pytest_cache/`
- `.ruff_cache/`

Options:

- `--dry-run`: preview only
- `--delete`: delete remote files that no longer exist locally
- `--remote-host <host>`: override host alias (default `devbox`)
- `--remote-dir <dir>`: override remote dir

## 2) Tracked-files-only sync (fast mode)

```bash
./scripts/rsync-devbox-tracked.sh
```

This syncs `git ls-files` plus `.env` / `.python-version` when present.

## 3) Run command remotely

```bash
./scripts/devbox-run.sh 'uv sync && uv run pytest -q'
```

## Typical workflow

```bash
./scripts/rsync-devbox.sh
./scripts/devbox-run.sh 'uv sync'
./scripts/devbox-run.sh 'uv run buglens-mcp --help'
```

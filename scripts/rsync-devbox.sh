#!/usr/bin/env bash
set -euo pipefail

# Sync current repo to remote devbox.
# Default remote: devbox:/home/dingwenjiang/workspace/buglens
#
# Usage examples:
#   ./scripts/rsync-devbox.sh
#   ./scripts/rsync-devbox.sh --delete
#   ./scripts/rsync-devbox.sh --dry-run
#   ./scripts/rsync-devbox.sh --remote-host devbox --remote-dir /home/dingwenjiang/workspace/buglens

REMOTE_HOST="devbox"
REMOTE_DIR="/home/dingwenjiang/workspace/buglens"
DELETE_FLAG=""
DRY_RUN_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-host)
      REMOTE_HOST="$2"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="$2"
      shift 2
      ;;
    --delete)
      DELETE_FLAG="--delete"
      shift
      ;;
    --dry-run)
      DRY_RUN_FLAG="--dry-run"
      shift
      ;;
    -h|--help)
      sed -n '1,22p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ensure remote target exists.
ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"

rsync -azP \
  $DRY_RUN_FLAG \
  $DELETE_FLAG \
  --filter=':- .gitignore' \
  --exclude '.git/' \
  --exclude 'dist/' \
  --exclude 'venv/' \
  --exclude '.venv/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.spec-workflow/' \
  --exclude '.tox/' \
  --exclude '.cache/' \
  --exclude '.DS_Store' \
  --exclude '*.log' \
  "$ROOT_DIR/" "$REMOTE_HOST:$REMOTE_DIR/"

echo "Synced $ROOT_DIR -> $REMOTE_HOST:$REMOTE_DIR"

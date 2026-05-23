#!/usr/bin/env bash
set -euo pipefail

# Sync only git-tracked files (+ selected dotfiles) to remote devbox.
# Faster for large repos with many generated artifacts.
#
# Usage examples:
#   ./scripts/rsync-devbox-tracked.sh
#   ./scripts/rsync-devbox-tracked.sh --dry-run

REMOTE_HOST="devbox"
REMOTE_DIR="/home/dingwenjiang/workspace/buglens"
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
    --dry-run)
      DRY_RUN_FLAG="--dry-run"
      shift
      ;;
    -h|--help)
      sed -n '1,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

(
  cd "$ROOT_DIR"
  git ls-files
  # Include common local config files when present.
  [[ -f .env ]] && echo ".env"
  [[ -f .python-version ]] && echo ".python-version"
) | sort -u > "$TMP_FILE"

ssh "$REMOTE_HOST" "mkdir -p '$REMOTE_DIR'"

rsync -azP \
  $DRY_RUN_FLAG \
  --files-from "$TMP_FILE" \
  "$ROOT_DIR/" "$REMOTE_HOST:$REMOTE_DIR/"

echo "Synced tracked files to $REMOTE_HOST:$REMOTE_DIR"

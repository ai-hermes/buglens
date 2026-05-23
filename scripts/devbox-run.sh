#!/usr/bin/env bash
set -euo pipefail

# Run a command in remote buglens workspace via ssh alias `devbox`.
#
# Usage examples:
#   ./scripts/devbox-run.sh 'pwd && ls -la'
#   ./scripts/devbox-run.sh 'uv sync && uv run pytest -q'

REMOTE_HOST="devbox"
REMOTE_DIR="/home/dingwenjiang/workspace/buglens"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 '<command>' [--remote-host HOST] [--remote-dir DIR]" >&2
  exit 1
fi

CMD="$1"
shift

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
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

ssh "$REMOTE_HOST" "cd '$REMOTE_DIR' && $CMD"

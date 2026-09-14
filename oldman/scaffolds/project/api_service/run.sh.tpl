#!/usr/bin/env sh

set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
OLDMAN_BIN="$PROJECT_DIR/.venv/bin/oldman"

if [ ! -x "$OLDMAN_BIN" ]; then
    echo "Oldman is not installed in $PROJECT_DIR/.venv; run 'uv sync' first." >&2
    exit 1
fi

cd "$PROJECT_DIR"
exec "$OLDMAN_BIN" "$@"

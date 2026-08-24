#!/usr/bin/env bash
# PreToolUse (Write|Edit|MultiEdit): защита путей.
# 1) Существующие файлы в migrations/versions/ не правятся — только новая ревизия.
# 2) Запись в .env запрещена (правь .env.example).
# exit 2 = блок.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)

FILE=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tool_input = data.get("tool_input") or {}
print(tool_input.get("file_path") or "")
' 2>/dev/null || true)

[ -n "${FILE:-}" ] || exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
REL="${FILE#"$PROJECT_DIR"/}"
BASE=$(basename "$FILE")

if [ "$BASE" = ".env" ]; then
  echo "protect_paths: запись в .env запрещена — секреты правит человек. Изменения шаблона — в .env.example." >&2
  exit 2
fi

case "$REL" in
  migrations/versions/*)
    if [ -f "$FILE" ] && [ "$BASE" != ".gitkeep" ]; then
      echo "protect_paths: правка существующей миграции '$REL' запрещена — создай новую ревизию: alembic revision --autogenerate -m \"...\"" >&2
      exit 2
    fi
    ;;
esac

exit 0

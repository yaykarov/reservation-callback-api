#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit): ruff format + ruff check --fix по изменённому .py,
# затем mypy по ВСЕМУ пакету app (mypy --strict на одном файле даёт ложные ошибки).
# Никогда не блокирует: всегда exit 0, вывод — в stderr для пользователя.
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
case "$FILE" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$FILE" ] || exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0

# Не трогаем файлы вне проекта
case "$FILE" in
  "$PROJECT_DIR"/*) ;;
  *) exit 0 ;;
esac

if command -v ruff >/dev/null 2>&1; then
  ruff format "$FILE" >&2 || true
  ruff check --fix "$FILE" >&2 || true
else
  echo "post_edit_check: ruff не установлен, форматирование пропущено" >&2
fi

# mypy — только если правка внутри app/ (иначе тесты/скрипты гоняют пакет зря)
case "$FILE" in
  "$PROJECT_DIR"/app/*)
    if command -v mypy >/dev/null 2>&1; then
      mypy app >&2 || true
    else
      echo "post_edit_check: mypy не установлен, проверка типов пропущена" >&2
    fi
    ;;
esac

exit 0

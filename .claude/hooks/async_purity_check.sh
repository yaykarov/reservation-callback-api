#!/usr/bin/env bash
# PostToolUse (Write|Edit|MultiEdit): запрещённые sync/legacy-паттерны в app/*.py.
# При находке — exit 2 и сообщение в stderr, чтобы Claude исправил сам.
# Файлы вне app/ не проверяются (никаких ложных срабатываний на тестах/скриптах).
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
REL="${FILE#"$PROJECT_DIR"/}"
case "$REL" in
  app/*) ;;
  *) exit 0 ;;
esac

FAIL=0

report() {
  # $1 — сообщение, $2 — grep -E паттерн
  echo "async_purity_check [$REL]: $1" >&2
  grep -nE "$2" "$FILE" | head -5 >&2
  FAIL=1
}

if grep -qE '^[[:space:]]*(import requests|from requests[[:space:].])' "$FILE"; then
  report "запрещён 'requests' — используй httpx.AsyncClient" '^[[:space:]]*(import requests|from requests[[:space:].])'
fi

if grep -qE '\btime\.sleep\(' "$FILE"; then
  report "time.sleep() блокирует event loop — используй await asyncio.sleep()" '\btime\.sleep\('
fi

if grep -qE '\bpsycopg2\b' "$FILE"; then
  report "psycopg2 запрещён — только asyncpg (postgresql+asyncpg://)" '\bpsycopg2\b'
fi

if grep -qE '\bsession\.query\(' "$FILE"; then
  report "session.query() — legacy 1.x, используй select() (SQLAlchemy 2.0 style)" '\bsession\.query\('
fi

case "$REL" in
  app/services/*)
    if grep -nE '^[[:space:]]*def [a-zA-Z_]' "$FILE" | grep -vE 'def __' >/dev/null; then
      echo "async_purity_check [$REL]: синхронный def в app/services — сервисный слой асинхронный (async def); dunder-методы исключение" >&2
      grep -nE '^[[:space:]]*def [a-zA-Z_]' "$FILE" | grep -vE 'def __' | head -5 >&2
      FAIL=1
    fi
    ;;
esac

if [ "$FAIL" -ne 0 ]; then
  echo "async_purity_check: исправь нарушения выше в $REL" >&2
  exit 2
fi

exit 0

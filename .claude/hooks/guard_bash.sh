#!/usr/bin/env bash
# PreToolUse (Bash): блокирует деструктивные/запрещённые команды. exit 2 = блок.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)

CMD=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
tool_input = data.get("tool_input") or {}
print(tool_input.get("command") or "")
' 2>/dev/null || true)

[ -n "${CMD:-}" ] || exit 0

deny() {
  echo "guard_bash: команда заблокирована — $1" >&2
  exit 2
}

# docker compose down -v / --volumes — снос тома с данными БД
if printf '%s' "$CMD" | grep -qE 'docker([[:space:]]+|-)compose[^|;&]*[[:space:]]down([[:space:]][^|;&]*)?[[:space:]](-[a-z]*v[a-z]*|--volumes)\b'; then
  deny "docker compose down -v удаляет том с данными PostgreSQL. Используй 'make down' (без -v)."
fi

# alembic downgrade
if printf '%s' "$CMD" | grep -qE '\balembic[[:space:]]+([^|;&]*[[:space:]])?downgrade\b'; then
  deny "alembic downgrade в этом проекте не используется — откат только новой корректирующей ревизией."
fi

# git push --force / -f (в т.ч. --force-with-lease)
if printf '%s' "$CMD" | grep -qE '\bgit[[:space:]]+push\b[^|;&]*[[:space:]](--force(-with-lease)?|-f)\b'; then
  deny "git push --force запрещён."
fi

# pip install в обход менеджера пакетов (uv pip install — разрешён)
if printf '%s' "$CMD" | grep -qE '(^|[[:space:];&|(])pip3?[[:space:]]+install\b' \
   && ! printf '%s' "$CMD" | grep -qE '\buv[[:space:]]+pip[[:space:]]+install\b'; then
  deny "голый pip install запрещён — используй 'uv add <pkg>' / 'uv sync' (или 'uv pip install' осознанно)."
fi

exit 0

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

# alembic downgrade: разрешён только при ALLOW_DOWNGRADE=1 И локальном хосте в DATABASE_URL
if printf '%s' "$CMD" | grep -qE '\balembic[[:space:]]+([^|;&]*[[:space:]])?downgrade\b'; then
  if ! printf '%s' "$CMD" | python3 -c '
import os
import re
import sys
from urllib.parse import urlsplit

cmd = sys.stdin.read()

def inline_env(name: str) -> str | None:
    # инлайн-присвоение VAR=value в тексте команды (в т.ч. в кавычках)
    m = re.search(rf"(?:^|[\s;&|(])({name})=(\"[^\"]*\"|\x27[^\x27]*\x27|\S+)", cmd)
    return m.group(2).strip("\"\x27") if m else None

allow = inline_env("ALLOW_DOWNGRADE") or os.environ.get("ALLOW_DOWNGRADE", "")
if allow != "1":
    print("ALLOW_DOWNGRADE=1 не выставлен", file=sys.stderr)
    sys.exit(1)

url = inline_env("DATABASE_URL") or os.environ.get("DATABASE_URL", "")
if not url:
    # fallback: .env в корне проекта
    env_path = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".env")
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip("\"\x27")
                    break
    except OSError:
        pass
if not url:
    print("DATABASE_URL не найден (ни в команде, ни в окружении, ни в .env)", file=sys.stderr)
    sys.exit(1)

try:
    host = urlsplit(url).hostname
except ValueError:
    host = None
if host not in {"localhost", "127.0.0.1", "::1"}:
    print(f"хост DATABASE_URL не локальный: {host!r}", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
'; then
    deny "downgrade заблокирован. Для локальной БД: ALLOW_DOWNGRADE=1 make migrate-down"
  fi
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

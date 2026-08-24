#!/usr/bin/env bash
# SessionStart: состояние docker compose + alembic current (timeout 5, тихий fallback) + git branch.
# UserPromptSubmit: ТОЛЬКО git branch — никаких обращений к БД на каждый промпт.
# Вывод в stdout попадает в контекст. Всегда exit 0.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)

EVENT=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
print(data.get("hook_event_name") or "")
' 2>/dev/null || true)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0

with_timeout() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
  else
    python3 -c '
import subprocess, sys
try:
    sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
except FileNotFoundError:
    sys.exit(127)
' "$secs" "$@"
  fi
}

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "не git-репозиторий")

if [ "$EVENT" = "SessionStart" ]; then
  echo "## Состояние проекта (session_context)"
  echo "git branch: $BRANCH"

  if command -v docker >/dev/null 2>&1; then
    COMPOSE_PS=$(with_timeout 5 docker compose ps --format '{{.Service}}: {{.Status}}' 2>/dev/null || true)
    if [ -n "${COMPOSE_PS:-}" ]; then
      echo "docker compose:"
      printf '%s\n' "$COMPOSE_PS"
    else
      echo "docker compose: сервисы не запущены (make up для старта)"
    fi
  else
    echo "docker compose: docker недоступен"
  fi

  if command -v alembic >/dev/null 2>&1; then
    ALEMBIC_CUR=$(with_timeout 5 alembic current 2>/dev/null || true)
    if [ -n "${ALEMBIC_CUR:-}" ]; then
      echo "alembic current: $ALEMBIC_CUR"
    else
      echo "alembic current: БД недоступна или миграции не накатаны (пропущено)"
    fi
  else
    echo "alembic current: alembic не установлен (пропущено)"
  fi
else
  # UserPromptSubmit и всё остальное — дёшево, без БД и docker
  echo "git branch: $BRANCH"
fi

exit 0

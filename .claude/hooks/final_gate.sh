#!/usr/bin/env bash
# Stop: финальный гейт — ruff check . && mypy app && pytest --cov (порог 85%).
# Провал любой проверки → exit 2 (задача не закрывается, Claude чинит).
# Защита от бесконечного цикла: stop_hook_active → exit 0.
# Отсутствие инструментов (не поставлено окружение) — предупреждение, не блок.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)

STOP_ACTIVE=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("false"); sys.exit(0)
print("true" if data.get("stop_hook_active") else "false")
' 2>/dev/null || echo "false")

if [ "$STOP_ACTIVE" = "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0
[ -d "$PROJECT_DIR/.venv/bin" ] && PATH="$PROJECT_DIR/.venv/bin:$PATH"

MISSING=""
for tool in ruff mypy pytest; do
  command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
  echo "final_gate: не установлены:$MISSING — гейт пропущен (поставь окружение: uv sync)" >&2
  exit 0
fi

# Порог покрытия: COV_MIN из окружения (дефолт 85); файл .coverage-grace в корне
# временно переопределяет его (строки с # — комментарии, первая прочая строка — число).
# Фаза 6: удалить .coverage-grace — 85% вернутся сами, скрипт править не нужно.
THRESHOLD="${COV_MIN:-85}"
if [ -f "$PROJECT_DIR/.coverage-grace" ]; then
  GRACE=$(grep -vE '^[[:space:]]*(#|$)' "$PROJECT_DIR/.coverage-grace" | head -1 | tr -d '[:space:]')
  if printf '%s' "$GRACE" | grep -qE '^[0-9]+$'; then
    THRESHOLD="$GRACE"
    echo "WARNING: покрытие временно ослаблено до ${THRESHOLD}% (.coverage-grace). Вернуть 85% в фазе 6." >&2
  else
    echo "final_gate: .coverage-grace нечитаем ('$GRACE') — используется порог ${THRESHOLD}%" >&2
  fi
fi

FAIL=0

run_check() {
  # $1 — имя, остальное — команда
  local name="$1"; shift
  local out rc
  out=$("$@" 2>&1)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "final_gate: FAILED [$name] (exit $rc):" >&2
    printf '%s\n' "$out" | tail -40 >&2
    FAIL=1
  else
    echo "final_gate: OK [$name]" >&2
  fi
}

run_check "ruff"   ruff check .
run_check "mypy"   mypy app
run_check "pytest+cov" pytest --cov=app --cov-fail-under="$THRESHOLD" -q

if [ "$FAIL" -ne 0 ]; then
  echo "final_gate: гейт не пройден — исправь ошибки выше, задача не закрыта" >&2
  exit 2
fi

exit 0

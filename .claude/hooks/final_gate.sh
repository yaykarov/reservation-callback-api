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

MISSING=""
for tool in ruff mypy pytest; do
  command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
  echo "final_gate: не установлены:$MISSING — гейт пропущен (поставь окружение: uv sync)" >&2
  exit 0
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
run_check "pytest+cov" pytest --cov=app --cov-fail-under=85 -q

if [ "$FAIL" -ne 0 ]; then
  echo "final_gate: гейт не пройден — исправь ошибки выше, задача не закрыта" >&2
  exit 2
fi

exit 0

#!/usr/bin/env bash
# SubagentStop: быстрый прогон pytest -q. НИКОГДА не блокирует (всегда exit 0):
# отсутствие/падение тестов — предупреждение в stderr. Жёсткий гейт — final_gate.sh.
set -uo pipefail

cat >/dev/null 2>&1 || true  # съесть stdin, содержимое не нужно

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0
[ -d "$PROJECT_DIR/.venv/bin" ] && PATH="$PROJECT_DIR/.venv/bin:$PATH"

if ! command -v pytest >/dev/null 2>&1; then
  echo "subagent_stop_test: pytest не установлен — прогон пропущен" >&2
  exit 0
fi

if ! find tests -name 'test_*.py' -o -name '*_test.py' 2>/dev/null | grep -q .; then
  echo "subagent_stop_test: тестов в tests/ пока нет — прогон пропущен" >&2
  exit 0
fi

OUTPUT=$(pytest -q 2>&1)
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "subagent_stop_test: ВНИМАНИЕ — pytest -q завершился с кодом $RC (не блокирует, но проверь):" >&2
  printf '%s\n' "$OUTPUT" | tail -30 >&2
fi

exit 0

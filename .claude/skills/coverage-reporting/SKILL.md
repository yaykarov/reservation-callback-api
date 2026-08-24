---
name: coverage-reporting
description: Coverage workflow - pytest-cov with branch coverage, 85% gate, reading term-missing and JSON reports, what may and may not be excluded. Apply when running coverage, the coverage gate fails, or deciding whether code needs pragma no cover.
---

# coverage-reporting

**Когда применять:** запуск покрытия, падение гейта 85%, споры про `# pragma: no cover`.

## Команды

```bash
pytest --cov=app --cov-report=term-missing --cov-fail-under=85   # make cov, гейт
pytest --cov=app --cov-report=html && open htmlcov/index.html    # разбор глазами
pytest --cov=app --cov-report=json:coverage.json                 # машинный разбор
```

Конфигурация уже в `pyproject.toml`: `branch = true`, `source = ["app"]`,
`fail_under = 85`, исключения — `if TYPE_CHECKING:`, `raise NotImplementedError`, `...`.

## Как читать term-missing с branch coverage

```
app/services/reservation.py   85   4   36   3   91%   72-75, 80->84
```

- `72-75` — непокрытые строки;
- `80->84` — покрытая строка 80, но НЕ пройденная ветка перехода на 84 (например,
  `if` всегда был истинным). Ветки `->exit` — ранние return'ы.
  Частичные ветки — главный источник пропущенных доменных сценариев (нехватка товара,
  невалидный переход, ретрай).

## Разбор JSON-отчёта

```python
import json

data = json.load(open("coverage.json"))
for path, f in sorted(data["files"].items(), key=lambda kv: kv[1]["summary"]["percent_covered"]):
    s = f["summary"]
    print(f"{s['percent_covered']:5.1f}%  {path}  missing={f['missing_lines']}"
          f"  partial_branches={f.get('missing_branches', [])}")
```

## Правила

- Гейт 85% — жёсткий (Stop-хук `final_gate.sh` его прогоняет); не опускать порог,
  а дописывать тесты.
- `# pragma: no cover` — только для реально недостижимого кода (защитные `assert`,
  platform-ветки), с обоснованием в ревью. Не для «лень писать тест».
- Не накручивать процент тестами без ассертов — покрытие метрика, а не цель;
  сценарии из CLAUDE.md (идемпотентность, гонки, переходы) важнее цифры.
- В приоритете покрытие веток `app/services/` и `app/repositories/` — там инварианты.

---
name: structured-logging
description: Structured JSON logging with structlog - request_id via contextvars middleware, one-line JSON events, sensitive-field masking, wiring stdlib/uvicorn loggers. Apply when writing app/core/logging.py, middleware, or adding log statements.
---

# structured-logging

**Когда применять:** `app/core/logging.py`, middleware request_id, любые новые лог-вызовы.

## Конфигурация structlog (app/core/logging.py)

```python
import logging

import structlog

SENSITIVE_KEYS = {"signature", "secret", "token", "password", "authorization"}


def _mask_sensitive(logger: object, method: str, event: dict[str, object]) -> dict[str, object]:
    for key in list(event):
        if key.lower() in SENSITIVE_KEYS:
            event[key] = "***"
    return event


def configure_logging(level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # сюда попадает request_id
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _mask_sensitive,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        cache_logger_on_first_use=True,
    )
    # uvicorn/sqlalchemy — в тот же stdout, уровень из конфига
    logging.basicConfig(level=level.upper(), format="%(message)s")
```

## Middleware request_id

```python
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        return response
```

## Как писать события

```python
log = structlog.get_logger(__name__)

log.info("callback_received", source=cmd.source, idempotency_key=cmd.key,
         product_id=str(cmd.product_id), quantity=cmd.quantity)
log.info("reservation_created", reservation_id=str(rid), status="PENDING")
log.warning("invalid_state_transition", current="CANCELLED", requested="CONFIRMED")
log.error("callback_failed", exc_info=True)
```

Правила:
- событие — фиксированный snake_case-литерал, переменные ТОЛЬКО полями
  (не `log.info(f"reserved {n}")`);
- обязательные доменные события: `callback_received`, `callback_processed`,
  `reservation_created/confirmed/cancelled/expired`,
  `reservation_rejected_insufficient_stock`, `invalid_state_transition`;
- секреты/подписи/токены в поля не класть (маскировщик — страховка, не разрешение);
- `print()` в приложении запрещён.

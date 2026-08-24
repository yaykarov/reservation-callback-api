---
name: problem-details
description: RFC 9457 Problem Details error responses - application/problem+json body shape, single exception handler mapping domain exceptions to status codes, normalizing FastAPI 422. Apply when writing error handling, exception handlers, or error response schemas.
---

# problem-details

**Когда применять:** обработка ошибок, exception handler'ы, схема тела ошибки.

## Формат (RFC 9457)

```json
{
  "type": "https://example.com/errors/invalid-state-transition",
  "title": "Invalid state transition",
  "status": 409,
  "detail": "Reservation 5f0c… is CANCELLED and cannot be confirmed",
  "instance": "/api/v1/callbacks/reservation",
  "request_id": "a1b2c3"
}
```

`Content-Type: application/problem+json`. Расширения (как `request_id`) — разрешены.

## Схема и хелпер

```python
# app/schemas/problem.py
class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
```

```python
# app/api/errors.py
STATUS_BY_EXCEPTION: dict[type[DomainError], tuple[int, str]] = {
    InvalidStateTransitionError: (409, "invalid-state-transition"),
    InsufficientStockError: (409, "insufficient-stock"),
    ReservationNotFoundError: (404, "reservation-not-found"),
}


def problem_response(request: Request, exc: DomainError) -> JSONResponse:
    status, slug = STATUS_BY_EXCEPTION.get(type(exc), (500, "internal"))
    problem = Problem(
        type=f"https://errors.reserve.local/{slug}",
        title=slug.replace("-", " ").capitalize(),
        status=status,
        detail=str(exc),
        instance=str(request.url.path),
        request_id=get_request_id(),
    )
    return JSONResponse(problem.model_dump(exclude_none=True), status_code=status,
                        media_type="application/problem+json")
```

## Нормализация встроенной 422 FastAPI

```python
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    problem = Problem(type="https://errors.reserve.local/validation", title="Validation error",
                      status=422, detail=str(exc.errors()[:5]), instance=str(request.url.path))
    return JSONResponse(problem.model_dump(exclude_none=True), status_code=422,
                        media_type="application/problem+json")
```

## Правила

- Один handler на `DomainError` — роутеры не ловят доменные исключения и не собирают
  тела ошибок руками.
- В `detail` нет стектрейсов, SQL, путей файлов, секретов; для 401 — без деталей
  («invalid signature», не что именно не сошлось).
- Непойманное исключение → 500 с generic Problem (handler на `Exception`), подробности
  только в лог.
- Каждый эндпоинт документирует свои ошибки в `responses={...}` моделью `Problem`.

---
name: fastapi-layout
description: Project layering for the FastAPI app - api/schemas/services/repositories/models/core boundaries, dependency injection chain, pydantic-settings config, domain exception handler. Apply when creating new modules, wiring DI, or unsure which layer code belongs to.
---

# fastapi-layout

**Когда применять:** новый модуль/эндпоинт/сервис; вопрос «в какой слой это положить»; DI.

## Слои и направление зависимостей

```
api ──> services ──> repositories ──> models
 │          │
 └──> schemas (вход/выход)      core <── все слои (config, db, exceptions, logging)
```

- `api`: роутеры, `Depends`, коды ответов. НЕ импортирует SQLAlchemy.
- `schemas`: pydantic v2. Только они пересекают границу HTTP.
- `services`: use-case'ы, стейт-машина, транзакции (`commit` здесь). НЕ импортирует FastAPI.
- `repositories`: запросы. Без бизнес-правил, без `commit` (только `flush`).
- `models`: ORM. Никогда не возвращаются из роутеров.

## DI-цепочка

```python
# app/api/deps.py
def get_reservation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReservationService:
    return ReservationService(session=session, repo=ReservationRepository())


# app/api/v1/callbacks.py
router = APIRouter(prefix="/api/v1", tags=["callbacks"])


@router.post("/callbacks/reservation", status_code=202, response_model=ReservationResponse)
async def reservation_callback(
    payload: ReservationCallbackIn,
    service: Annotated[ReservationService, Depends(get_reservation_service)],
) -> ReservationResponse:
    result = await service.handle_callback(payload.to_command())
    ...
```

Сервис принимает и возвращает доменные объекты/схемы, не Request/Response.

## Конфиг — только pydantic-settings

```python
# app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    callback_hmac_secret: str
    callback_timestamp_window_seconds: int = 300
    reservation_ttl_seconds: int = 900
    log_level: str = "INFO"


settings = Settings()
```

`os.getenv` по коду запрещён — всё через `settings`.

## Один exception handler для доменных исключений

```python
# app/api/errors.py — регистрируется в main.py
@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return problem_response(exc)  # RFC 9457, см. скилл problem-details
```

Роутеры не ловят доменные исключения и не собирают тела ошибок руками.

## app/main.py — только сборка

Создание приложения, `configure_logging()`, middleware (request_id), подключение
роутеров, регистрация exception handler'ов. Никакой логики.

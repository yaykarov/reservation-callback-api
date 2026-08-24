---
name: callback-signature
description: HMAC-SHA256 verification of incoming callbacks over the RAW request body - hmac.compare_digest, timestamp window against replay, FastAPI dependency that reads raw body without breaking pydantic validation. Apply when implementing or reviewing callback authentication.
---

# callback-signature

**Когда применять:** проверка подписи входящих callback'ов, защита от replay, 401-ветка.

## Схема подписи

Внешний сервис шлёт заголовки:
- `X-Timestamp` — unix-время отправки (входит в подписываемую строку!);
- `X-Signature` — `hex(HMAC_SHA256(secret, f"{timestamp}.{raw_body}"))`.

Подпись считается по **сырым байтам тела** — до и без парсинга JSON. Пересериализованный
JSON даёт другие байты (порядок ключей, пробелы) — подпись «поплывёт».
Timestamp в подписываемой строке обязателен: подпись только по телу можно replay'ить вечно.

## Проверка

```python
# app/core/security.py
import hashlib
import hmac
import time


def verify_callback_signature(
    raw_body: bytes, timestamp: str, signature: str, *, secret: str, window_seconds: int
) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - ts) > window_seconds:  # окно против replay
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)  # constant-time, НИКОГДА ==
```

## FastAPI: сырое тело в зависимости, pydantic не ломается

`await request.body()` в Starlette кэшируется — его можно читать в зависимости, и после
этого штатная валидация pydantic по телу работает как обычно:

```python
# app/api/deps.py
from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.config import settings
from app.core.security import verify_callback_signature


async def verify_signature(
    request: Request,
    x_signature: Annotated[str | None, Header()] = None,
    x_timestamp: Annotated[str | None, Header()] = None,
) -> None:
    raw = await request.body()  # сырые байты ДО парсинга; кэшируются Starlette
    if not (
        x_signature
        and x_timestamp
        and verify_callback_signature(
            raw, x_timestamp, x_signature,
            secret=settings.callback_hmac_secret,
            window_seconds=settings.callback_timestamp_window_seconds,
        )
    ):
        raise InvalidSignatureError()  # → 401 через общий handler, без деталей


# app/api/v1/callbacks.py
@router.post("/callbacks/reservation", status_code=202,
             dependencies=[Depends(verify_signature)])
async def reservation_callback(payload: ReservationCallbackIn, ...) -> ...:
    ...  # payload распарсен pydantic'ом из того же кэшированного тела
```

## Правила

- Отсутствие подписи и невалидная подпись отдают одинаковый 401 (RFC 9457, без деталей).
- Секрет — только из pydantic-settings; в логи не попадает (см. structured-logging).
- Окно timestamp — из конфига (`CALLBACK_TIMESTAMP_WINDOW_SECONDS`, дефолт 300 с);
  учитывай `abs()` — рассинхрон часов бывает в обе стороны.
- Replay внутри окна гасится идемпотентностью (`idempotency_key`) — обе защиты обязательны.
- В тестах подпись считай той же функцией от тех же сырых байт, что уйдут в
  `client.post(content=raw)`, — не через `json=` (httpx сериализует сам и байты другие).

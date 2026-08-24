"""Роутеры: callback-эндпоинты резервирования и health."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.schemas import (
    ErrorResponse,
    HealthResponse,
    ReservationCreateRequest,
    ReservationResponse,
)
from app.services.reservation import ReservationService

health_router = APIRouter()
router = APIRouter(prefix="/api/v1/reservations", tags=["reservations"])


def get_reservation_service() -> ReservationService:
    return ReservationService()


ServiceDep = Annotated[ReservationService, Depends(get_reservation_service)]


@health_router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.post(
    "",
    response_model=ReservationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_200_OK: {"model": ReservationResponse, "description": "Повтор idempotency_key"},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Нехватка остатка"},
    },
)
async def create_reservation(
    payload: ReservationCreateRequest, service: ServiceDep, response: Response
) -> ReservationResponse:
    result, replayed = await service.create(payload)
    if replayed:
        response.status_code = status.HTTP_200_OK
    return result


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
)
async def get_reservation(reservation_id: uuid.UUID, service: ServiceDep) -> ReservationResponse:
    return await service.get(reservation_id)


@router.post(
    "/{reservation_id}/confirm",
    response_model=ReservationResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def confirm_reservation(
    reservation_id: uuid.UUID, service: ServiceDep
) -> ReservationResponse:
    return await service.confirm(reservation_id)


@router.post(
    "/{reservation_id}/cancel",
    response_model=ReservationResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def cancel_reservation(reservation_id: uuid.UUID, service: ServiceDep) -> ReservationResponse:
    return await service.cancel(reservation_id)

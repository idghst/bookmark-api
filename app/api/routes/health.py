from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.integrations import database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def legacy_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


async def probe_database(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        async with database.connect(request, settings) as conn:
            await database.query(conn, "select id from bookmark.items limit 1")
    except ApiError as error:
        raise ApiError(
            503, "dependency_unavailable", "Database is unavailable"
        ) from error


@router.get("/ready")
async def readiness(_: Annotated[None, Depends(probe_database)]) -> dict[str, str]:
    return {"status": "ok"}

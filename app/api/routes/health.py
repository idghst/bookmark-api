from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.integrations.supabase import create_client, request

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def legacy_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


async def probe_database(
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    try:
        async with create_client(settings) as client:
            await request(client, "GET", "items", params={"select": "id", "limit": "1"})
    except ApiError as error:
        raise ApiError(
            503, "dependency_unavailable", "Database is unavailable"
        ) from error


@router.get("/ready")
async def readiness(_: Annotated[None, Depends(probe_database)]) -> dict[str, str]:
    return {"status": "ok"}

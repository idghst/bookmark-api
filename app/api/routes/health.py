from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.integrations.supabase import get_database_client, request

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def legacy_health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


async def probe_database(
    client: Annotated[httpx.AsyncClient, Depends(get_database_client)],
) -> None:
    try:
        await request(client, "GET", "items", params={"select": "id", "limit": "1"})
    except ApiError as error:
        raise ApiError(
            503, "dependency_unavailable", "Database is unavailable"
        ) from error


@router.get("/ready")
async def readiness(_: Annotated[None, Depends(probe_database)]) -> dict[str, str]:
    return {"status": "ok"}

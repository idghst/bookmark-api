from collections.abc import AsyncIterator
from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated, Any

import psycopg
from fastapi import Depends, Header
from psycopg.rows import dict_row

from app.core.config import Settings, get_settings
from app.core.errors import ApiError


@dataclass(frozen=True)
class ServiceUser:
    id: str
    email: None = None


@dataclass(frozen=True)
class AuthContext:
    user: ServiceUser
    connection: psycopg.AsyncConnection[dict[str, Any]]


async def connect(settings: Settings) -> psycopg.AsyncConnection[dict[str, Any]]:
    return await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL.get_secret_value(),
        row_factory=dict_row,
        connect_timeout=settings.DATABASE_TIMEOUT_SECONDS,
        options=f"-c statement_timeout={settings.DATABASE_TIMEOUT_SECONDS * 1000}",
    )


async def _get_service_user(
    connection: psycopg.AsyncConnection[dict[str, Any]], settings: Settings
) -> ServiceUser:
    if settings.BOOKMARK_USER_ID is not None:
        return ServiceUser(str(settings.BOOKMARK_USER_ID))
    cursor = await connection.execute(
        "SELECT user_id FROM bookmark.items UNION "
        "SELECT user_id FROM bookmark.folders UNION "
        "SELECT user_id FROM bookmark.sections UNION "
        "SELECT user_id FROM bookmark.folder_sections LIMIT 2"
    )
    rows = await cursor.fetchall()
    if len(rows) != 1 or rows[0]["user_id"] is None:
        raise ApiError(
            503, "service_identity_unavailable", "Service identity is unavailable"
        )
    return ServiceUser(str(rows[0]["user_id"]))


async def get_resource_auth_context(
    settings: Annotated[Settings, Depends(get_settings)],
    service_key: Annotated[str | None, Header(alias="X-Bookmark-Key")] = None,
) -> AsyncIterator[AuthContext]:
    if service_key is None:
        raise ApiError(401, "authentication_required", "API key is required")
    configured_key = settings.BOOKMARK_API_KEY
    if configured_key is None or not compare_digest(
        service_key.encode(), configured_key.get_secret_value().encode()
    ):
        raise ApiError(401, "invalid_api_key", "Invalid API key")
    try:
        async with await connect(settings) as connection:
            # The connection context commits only after the dependency succeeds.
            # Any route/validation/database exception rolls the entire request back.
            yield AuthContext(await _get_service_user(connection, settings), connection)
    except psycopg.Error as error:
        from app.services._db import database_error

        raise database_error(error) from error

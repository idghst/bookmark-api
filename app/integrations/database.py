"""Direct Postgres access; service methods always supply the resolved owner."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from math import ceil
from secrets import compare_digest
from typing import Annotated, Any, LiteralString

import psycopg
from fastapi import Depends, Header, Request
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings, get_settings
from app.core.errors import ApiError

type Connection = psycopg.AsyncConnection[Any]


@dataclass(frozen=True)
class ServiceUser:
    id: str
    email: None = None


@dataclass(frozen=True)
class AuthContext:
    user: ServiceUser
    conn: Connection


def connection_kwargs(settings: Settings) -> dict[str, Any]:
    timeout = settings.DATABASE_TIMEOUT_SECONDS
    return {
        "autocommit": True,
        "connect_timeout": max(2, ceil(timeout)),
        # UTC keeps the timestamp strings PostgREST returned (e.g. +00:00).
        "options": f"-c TimeZone=UTC -c statement_timeout={ceil(timeout * 1000)}",
    }


def create_pool(settings: Settings) -> AsyncConnectionPool[Connection]:
    return AsyncConnectionPool(
        settings.DATABASE_URL.get_secret_value(),
        kwargs=connection_kwargs(settings),
        min_size=1,
        max_size=5,
        timeout=settings.DATABASE_TIMEOUT_SECONDS,
        check=AsyncConnectionPool.check_connection,
        open=False,
    )


@asynccontextmanager
async def connect(request: Request, settings: Settings) -> AsyncIterator[Connection]:
    pool = getattr(request.app.state, "database_pool", None)
    try:
        if pool is not None:
            async with pool.connection() as conn:
                yield conn
        else:
            # ASGI callers that disable lifespan still get a closed connection.
            async with await psycopg.AsyncConnection.connect(
                settings.DATABASE_URL.get_secret_value(),
                **connection_kwargs(settings),
            ) as conn:
                yield conn
    except (psycopg.OperationalError, psycopg.InterfaceError) as error:
        raise ApiError(
            503, "database_unavailable", "Database is unavailable"
        ) from error


async def get_resource_auth_context(
    request: Request,
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
    async with connect(request, settings) as conn:
        yield AuthContext(ServiceUser(await service_user_id(conn, settings)), conn)


def database_error(error: psycopg.Error) -> ApiError:
    code = error.sqlstate
    if code == "42501":
        return ApiError(403, "database_access_denied", "Database access was denied")
    if code == "P0002":
        return ApiError(404, "resource_not_found", "Resource not found")
    if code in {"23503", "23514", "23505", "23502"}:
        return ApiError(
            409,
            "resource_conflict",
            "Resource conflicts with the current folder structure",
        )
    if code in {"22P02", "22004"}:
        return ApiError(422, "validation_error", "Request validation failed")
    if isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError)):
        return ApiError(503, "database_unavailable", "Database is unavailable")
    return ApiError(502, "database_request_failed", "Database request failed")


async def query(
    conn: Connection,
    statement: LiteralString | sql.Composed,
    params: Sequence[object] = (),
) -> list[Any]:
    """Run one statement and return the first column of every row."""
    try:
        cursor = await conn.execute(statement, params)
        return [row[0] for row in await cursor.fetchall()] if cursor.description else []
    except psycopg.Error as error:
        raise database_error(error) from error


OWNERS_SQL = """
select user_id::text from bookmark.items
union select user_id::text from bookmark.folders
union select user_id::text from bookmark.sections
union select user_id::text from bookmark.folder_sections
limit 2
"""


async def service_user_id(conn: Connection, settings: Settings) -> str:
    if settings.BOOKMARK_USER_ID is not None:
        return str(settings.BOOKMARK_USER_ID)
    owners = await query(conn, OWNERS_SQL)
    if len(owners) != 1 or not owners[0]:
        raise ApiError(
            503, "service_identity_unavailable", "Service identity is unavailable"
        )
    return str(owners[0])

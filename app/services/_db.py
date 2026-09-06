from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import sql

from app.core.errors import ApiError
from app.integrations.postgres import AuthContext
from app.schemas import PositionUpdate

TABLES = {
    "bookmarks": "items",
    "folders": "folders",
    "sections": "sections",
    "folder_sections": "folder_sections",
}
RESOURCE_NAMES = {
    "items": "Bookmark",
    "folders": "Folder",
    "sections": "Section",
    "folder_sections": "Folder section",
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def database_error(error: psycopg.Error) -> ApiError:
    if error.sqlstate == "42501":
        return ApiError(403, "database_access_denied", "Database access was denied")
    if error.sqlstate == "P0002":
        return ApiError(404, "resource_not_found", "Resource not found")
    if error.sqlstate in {"23503", "23514", "23505", "23502"}:
        return ApiError(
            409,
            "resource_conflict",
            "Resource conflicts with the current folder structure",
        )
    if error.sqlstate == "22P02":
        return ApiError(422, "validation_error", "Request validation failed")
    if isinstance(error, psycopg.OperationalError):
        return ApiError(503, "database_unavailable", "Database is unavailable")
    return ApiError(502, "database_request_failed", "Database request failed")


async def execute(
    auth: AuthContext,
    query: sql.SQL | sql.Composed | str,
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        cursor = await auth.connection.execute(query, params)
        rows = await cursor.fetchall()
    except psycopg.Error as error:
        raise database_error(error) from error
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ApiError(
            502, "database_response_invalid", "Database returned an invalid response"
        )
    return [
        {
            key: value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
            for key, value in row.items()
        }
        for row in rows
    ]


def ensure_row(rows: list[dict[str, Any]], resource_name: str) -> dict[str, Any]:
    if not rows:
        raise ApiError(404, "resource_not_found", f"{resource_name} not found")
    return rows[0]


def _where(
    auth: AuthContext, filters: dict[str, object]
) -> tuple[sql.Composed, list[Any]]:
    scoped = {**filters, "user_id": auth.user.id}
    return sql.SQL(" AND ").join(
        sql.SQL("{} IS NOT DISTINCT FROM %s").format(sql.Identifier(key))
        for key in scoped
    ), list(scoped.values())


async def select(
    auth: AuthContext, table: str, *, for_update: bool = False, **filters: object
) -> list[dict[str, Any]]:
    where, params = _where(auth, filters)
    return await execute(
        auth,
        sql.SQL("SELECT * FROM {} WHERE {} ORDER BY position, id{}").format(
            sql.Identifier("bookmark", table),
            where,
            sql.SQL(" FOR UPDATE" if for_update else ""),
        ),
        params,
    )


async def insert(
    auth: AuthContext, table: str, row: dict[str, Any]
) -> list[dict[str, Any]]:
    row = {**row, "user_id": auth.user.id}
    return await execute(
        auth,
        sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
            sql.Identifier("bookmark", table),
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join(sql.Placeholder() for _ in row),
        ),
        list(row.values()),
    )


async def update(
    auth: AuthContext, table: str, values: dict[str, Any], **filters: object
) -> list[dict[str, Any]]:
    where, params = _where(auth, filters)
    return await execute(
        auth,
        sql.SQL("UPDATE {} SET {} WHERE {} RETURNING *").format(
            sql.Identifier("bookmark", table),
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(key)) for key in values
            ),
            where,
        ),
        [*values.values(), *params],
    )


async def delete(
    auth: AuthContext, table: str, **filters: object
) -> list[dict[str, Any]]:
    where, params = _where(auth, filters)
    return await execute(
        auth,
        sql.SQL("DELETE FROM {} WHERE {} RETURNING *").format(
            sql.Identifier("bookmark", table), where
        ),
        params,
    )


async def next_position(auth: AuthContext, table: str, **filters: object) -> int:
    where, params = _where(auth, filters)
    rows = await execute(
        auth,
        sql.SQL(
            "SELECT COALESCE(MAX(position) + 1, 0) AS position FROM {} WHERE {}"
        ).format(sql.Identifier("bookmark", table), where),
        params,
    )
    return int(rows[0]["position"])


async def reorder(table: str, payload: list[PositionUpdate], auth: AuthContext) -> None:
    timestamp = now()
    for item in payload:
        ensure_row(
            await update(
                auth,
                table,
                {"position": item.position, "updated_at": timestamp},
                id=item.id,
            ),
            RESOURCE_NAMES[table],
        )

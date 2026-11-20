from datetime import UTC, datetime
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from app.core.errors import ApiError
from app.integrations import database
from app.integrations.database import AuthContext
from app.schemas import PositionUpdate

TABLES = {
    "bookmarks": "items",
    "folders": "folders",
    "sections": "sections",
    "folder_sections": "folder_sections",
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_row(rows: list[dict[str, Any]], resource_name: str) -> dict[str, Any]:
    if not rows:
        raise ApiError(404, "resource_not_found", f"{resource_name} not found")
    return rows[0]


def owner_filter(
    auth: AuthContext, filters: dict[str, object]
) -> tuple[sql.Composed, list[object]]:
    conditions: list[sql.Composed] = []
    params: list[object] = []
    for key, value in {**filters, "user_id": auth.user.id}.items():
        if value is None:
            conditions.append(sql.SQL("{} is null").format(sql.Identifier(key)))
        else:
            conditions.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            params.append(value)
    return sql.SQL(" and ").join(conditions), params


def table_name(table: str) -> sql.Identifier:
    return sql.Identifier("bookmark", table)


async def select(
    auth: AuthContext, table: str, **filters: object
) -> list[dict[str, Any]]:
    condition, params = owner_filter(auth, filters)
    # id is unique; an equality lookup needs at most one row.
    limit = sql.SQL(" limit 1" if filters.get("id") is not None else "")
    return await database.query(
        auth.conn,
        sql.SQL(
            "select to_jsonb(t) from {} as t where {} order by position, id{}"
        ).format(table_name(table), condition, limit),
        params,
    )


async def insert(
    auth: AuthContext, table: str, row: dict[str, Any]
) -> list[dict[str, Any]]:
    row = {**row, "user_id": auth.user.id}
    return await database.query(
        auth.conn,
        sql.SQL("insert into {} as t ({}) values ({}) returning to_jsonb(t)").format(
            table_name(table),
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join([sql.Placeholder()] * len(row)),
        ),
        list(row.values()),
    )


async def update(
    auth: AuthContext, table: str, values: dict[str, Any], **filters: object
) -> list[dict[str, Any]]:
    condition, params = owner_filter(auth, filters)
    return await database.query(
        auth.conn,
        sql.SQL("update {} as t set {} where {} returning to_jsonb(t)").format(
            table_name(table),
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(key)) for key in values
            ),
            condition,
        ),
        [*values.values(), *params],
    )


async def delete(
    auth: AuthContext, table: str, **filters: object
) -> list[dict[str, Any]]:
    condition, params = owner_filter(auth, filters)
    return await database.query(
        auth.conn,
        sql.SQL("delete from {} as t where {} returning to_jsonb(t)").format(
            table_name(table), condition
        ),
        params,
    )


async def next_position(auth: AuthContext, table: str, **filters: object) -> int:
    condition, params = owner_filter(auth, filters)
    rows = await database.query(
        auth.conn,
        sql.SQL(
            "select position from {} where {} order by position desc, id limit 1"
        ).format(table_name(table), condition),
        params,
    )
    return int(rows[0]) + 1 if rows else 0


async def reorder(table: str, payload: list[PositionUpdate], auth: AuthContext) -> None:
    await database.query(
        auth.conn,
        "select id from bookmark.reorder_resources("
        "p_table => %s, p_updates => %s, p_user_id => %s)",
        [table, Jsonb([item.model_dump() for item in payload]), auth.user.id],
    )

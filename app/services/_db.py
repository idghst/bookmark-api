from datetime import UTC, datetime
from typing import Any

from app.core.errors import ApiError
from app.integrations import supabase
from app.integrations.supabase import AuthContext
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


def http_filters(auth: AuthContext, filters: dict[str, object]) -> dict[str, str]:
    return {
        key: "is.null" if value is None else f"eq.{value}"
        for key, value in {**filters, "user_id": auth.user.id}.items()
    }


async def select(
    auth: AuthContext, table: str, **filters: object
) -> list[dict[str, Any]]:
    return await supabase.select(
        auth.client,
        table,
        {"select": "*", "order": "position,id", **http_filters(auth, filters)},
    )


async def insert(
    auth: AuthContext, table: str, row: dict[str, Any]
) -> list[dict[str, Any]]:
    return await supabase.request(
        auth.client, "POST", table, body={**row, "user_id": auth.user.id}
    )


async def update(
    auth: AuthContext, table: str, values: dict[str, Any], **filters: object
) -> list[dict[str, Any]]:
    return await supabase.request(
        auth.client, "PATCH", table, params=http_filters(auth, filters), body=values
    )


async def delete(
    auth: AuthContext, table: str, **filters: object
) -> list[dict[str, Any]]:
    return await supabase.request(
        auth.client, "DELETE", table, params=http_filters(auth, filters)
    )


async def next_position(auth: AuthContext, table: str, **filters: object) -> int:
    rows = await supabase.request(
        auth.client,
        "GET",
        table,
        params={
            **http_filters(auth, filters),
            "select": "position",
            "order": "position.desc,id",
            "limit": "1",
        },
    )
    return int(rows[0]["position"]) + 1 if rows else 0


async def reorder(table: str, payload: list[PositionUpdate], auth: AuthContext) -> None:
    await supabase.request(
        auth.client,
        "POST",
        "rpc/reorder_resources",
        body={
            "p_table": table,
            "p_user_id": auth.user.id,
            "p_updates": [item.model_dump() for item in payload],
        },
    )

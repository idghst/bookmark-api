from typing import Any
from uuid import uuid4

from app.integrations.supabase import AuthContext
from app.schemas import BookmarkCreate, BookmarkOut, BookmarkUpdate, PositionUpdate
from app.services._db import (
    TABLES,
    delete,
    ensure_row,
    insert,
    next_position,
    now,
    reorder,
    select,
    update,
)
from app.services.folder_sections import ensure_folder_section
from app.services.folders import (
    create_folder,
    delete_folder,
    ensure_folder,
    list_folders,
    reorder_folders,
    update_folder,
)
from app.services.sections import (
    create_section,
    delete_section,
    list_sections,
    reorder_sections,
    update_section,
)

__all__ = [
    "create_bookmark",
    "create_folder",
    "create_section",
    "delete_bookmark",
    "delete_folder",
    "delete_section",
    "list_bookmarks",
    "list_folders",
    "list_sections",
    "reorder_bookmarks",
    "reorder_folders",
    "reorder_sections",
    "update_bookmark",
    "update_folder",
    "update_section",
]


async def list_bookmarks(auth: AuthContext) -> list[BookmarkOut]:
    rows = await select(auth, TABLES["bookmarks"])
    return [BookmarkOut(**row) for row in rows]


async def create_bookmark(
    payload: BookmarkCreate,
    auth: AuthContext,
) -> BookmarkOut:
    if payload.folder_id is not None:
        await ensure_folder(payload.folder_id, auth)
    if payload.folder_section_id is not None:
        await ensure_folder_section(payload.folder_section_id, payload.folder_id, auth)
    timestamp = now()
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "title": payload.title,
        "url": payload.url,
        "description": payload.description,
        "is_favorite": payload.is_favorite,
        "color": payload.color,
        "folder_id": payload.folder_id,
        "folder_section_id": payload.folder_section_id,
        "position": await next_position(
            auth,
            TABLES["bookmarks"],
            folder_id=payload.folder_id,
            folder_section_id=payload.folder_section_id,
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
        "user_id": auth.user.id,
    }
    rows = await insert(auth, TABLES["bookmarks"], row)
    return BookmarkOut(**ensure_row(rows, "Bookmark"))


async def update_bookmark(
    bookmark_id: str,
    payload: BookmarkUpdate,
    auth: AuthContext,
) -> BookmarkOut:
    updates = payload.model_dump(by_alias=False, exclude_unset=True)
    moving_folder = "folder_id" in updates
    moving_section = "folder_section_id" in updates
    if moving_folder or moving_section:
        current = ensure_row(
            await select(auth, TABLES["bookmarks"], id=bookmark_id),
            "Bookmark",
        )
        folder_id = updates["folder_id"] if moving_folder else current.get("folder_id")
        folder_section_id = (
            updates["folder_section_id"]
            if moving_section
            else current.get("folder_section_id")
        )
        if moving_folder and not moving_section:
            folder_section_id = None
            updates["folder_section_id"] = None
        if isinstance(folder_id, str):
            await ensure_folder(folder_id, auth)
        if isinstance(folder_section_id, str):
            await ensure_folder_section(folder_section_id, folder_id, auth)
        if folder_id != current.get("folder_id") or folder_section_id != current.get(
            "folder_section_id"
        ):
            updates["position"] = await next_position(
                auth,
                TABLES["bookmarks"],
                folder_id=folder_id,
                folder_section_id=folder_section_id,
            )
    updates["updated_at"] = now()
    rows = await update(auth, TABLES["bookmarks"], updates, id=bookmark_id)
    return BookmarkOut(**ensure_row(rows, "Bookmark"))


async def delete_bookmark(bookmark_id: str, auth: AuthContext) -> None:
    rows = await delete(auth, TABLES["bookmarks"], id=bookmark_id)
    ensure_row(rows, "Bookmark")


async def reorder_bookmarks(
    payload: list[PositionUpdate],
    auth: AuthContext,
) -> None:
    await reorder(TABLES["bookmarks"], payload, auth)

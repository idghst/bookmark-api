from typing import Any
from uuid import uuid4

from app.core.errors import ApiError
from app.integrations.postgres import AuthContext
from app.schemas import (
    FolderSectionCreate,
    FolderSectionOut,
    FolderSectionUpdate,
    PositionUpdate,
)
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
from app.services.folders import ensure_folder


async def list_folder_sections(auth: AuthContext) -> list[FolderSectionOut]:
    rows = await select(auth, TABLES["folder_sections"])
    return [FolderSectionOut(**row) for row in rows]


async def ensure_folder_section(
    folder_section_id: str,
    folder_id: str | None,
    auth: AuthContext,
) -> dict[str, Any]:
    rows = await select(auth, TABLES["folder_sections"], id=folder_section_id)
    row = ensure_row(rows, "Folder section")
    if row.get("folder_id") != folder_id:
        raise ApiError(
            409,
            "resource_conflict",
            "Bookmark section must stay in the same folder",
        )
    return row


async def create_folder_section(
    payload: FolderSectionCreate,
    auth: AuthContext,
) -> FolderSectionOut:
    await ensure_folder(payload.folder_id, auth)
    timestamp = now()
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "name": payload.name,
        "color": payload.color,
        "folder_id": payload.folder_id,
        "position": await next_position(
            auth,
            TABLES["folder_sections"],
            folder_id=payload.folder_id,
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
        "user_id": auth.user.id,
    }
    rows = await insert(auth, TABLES["folder_sections"], row)
    return FolderSectionOut(**ensure_row(rows, "Folder section"))


async def update_folder_section(
    folder_section_id: str,
    payload: FolderSectionUpdate,
    auth: AuthContext,
) -> FolderSectionOut:
    updates = payload.model_dump(by_alias=False, exclude_unset=True)
    updates["updated_at"] = now()
    rows = await update(auth, TABLES["folder_sections"], updates, id=folder_section_id)
    return FolderSectionOut(**ensure_row(rows, "Folder section"))


async def delete_folder_section(folder_section_id: str, auth: AuthContext) -> None:
    rows = await delete(auth, TABLES["folder_sections"], id=folder_section_id)
    ensure_row(rows, "Folder section")


async def reorder_folder_sections(
    payload: list[PositionUpdate],
    auth: AuthContext,
) -> None:
    await reorder(TABLES["folder_sections"], payload, auth)

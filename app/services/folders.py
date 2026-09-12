from typing import Any
from uuid import uuid4

from app.core.errors import ApiError
from app.integrations import supabase
from app.integrations.supabase import AuthContext
from app.schemas import (
    FolderCreate,
    FolderOut,
    FolderUpdate,
    PositionUpdate,
)
from app.services._db import (
    TABLES,
    ensure_row,
    insert,
    next_position,
    now,
    reorder,
    select,
    update,
)


async def list_folders(auth: AuthContext) -> list[FolderOut]:
    rows = await select(auth, TABLES["folders"])
    folders = [FolderOut(**row) for row in rows]
    return sorted(
        folders,
        key=lambda folder: (
            folder.section_id is not None,
            folder.section_id or "",
            folder.position,
            folder.id,
        ),
    )


async def ensure_folder(folder_id: str, auth: AuthContext) -> None:
    rows = await select(auth, TABLES["folders"], id=folder_id)
    ensure_row(rows, "Folder")


async def ensure_section(section_id: str, auth: AuthContext) -> None:
    rows = await select(auth, TABLES["sections"], id=section_id)
    ensure_row(rows, "Section")


async def create_folder(
    payload: FolderCreate,
    auth: AuthContext,
) -> FolderOut:
    if payload.section_id is not None:
        await ensure_section(payload.section_id, auth)
    timestamp = now()
    row: dict[str, Any] = {
        "id": str(uuid4()),
        "name": payload.name,
        "color": payload.color,
        "section_id": payload.section_id,
        "position": await next_position(
            auth,
            TABLES["folders"],
            section_id=payload.section_id,
        ),
        "created_at": timestamp,
        "updated_at": timestamp,
        "user_id": auth.user.id,
    }
    rows = await insert(auth, TABLES["folders"], row)
    return FolderOut(**ensure_row(rows, "Folder"))


async def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    auth: AuthContext,
) -> FolderOut:
    updates = payload.model_dump(by_alias=False, exclude_unset=True)
    if "section_id" in updates:
        current = ensure_row(
            await select(auth, TABLES["folders"], id=folder_id),
            "Folder",
        )
        section_id = updates["section_id"]
        if isinstance(section_id, str):
            await ensure_section(section_id, auth)
        if section_id != current.get("section_id"):
            updates["position"] = await next_position(
                auth,
                TABLES["folders"],
                section_id=section_id,
            )
    updates["updated_at"] = now()
    rows = await update(auth, TABLES["folders"], updates, id=folder_id)
    return FolderOut(**ensure_row(rows, "Folder"))


async def delete_folder(
    folder_id: str,
    auth: AuthContext,
    destination_folder_id: str | None = None,
) -> None:
    if destination_folder_id == folder_id:
        raise ApiError(
            422,
            "folder_destination_invalid",
            "A folder cannot be its own deletion destination",
        )
    await supabase.request(
        auth.client,
        "POST",
        "rpc/delete_folder",
        body={
            "p_folder_id": folder_id,
            "p_destination_folder_id": destination_folder_id,
            "p_user_id": auth.user.id,
        },
    )


async def reorder_folders(
    payload: list[PositionUpdate],
    auth: AuthContext,
) -> None:
    await reorder(TABLES["folders"], payload, auth)

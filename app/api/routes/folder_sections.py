from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.integrations.postgres import AuthContext, get_resource_auth_context
from app.schemas import (
    FolderSectionCreate,
    FolderSectionOut,
    FolderSectionUpdate,
    PositionUpdate,
)
from app.services import folder_sections

router = APIRouter()
AuthDependency = Annotated[
    AuthContext, Depends(get_resource_auth_context, scope="function")
]


@router.get("/folder-sections", response_model=list[FolderSectionOut])
async def list_folder_sections(auth: AuthDependency) -> list[FolderSectionOut]:
    return await folder_sections.list_folder_sections(auth)


@router.post(
    "/folder-sections",
    response_model=FolderSectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder_section(
    payload: FolderSectionCreate,
    auth: AuthDependency,
) -> FolderSectionOut:
    return await folder_sections.create_folder_section(payload, auth)


@router.patch("/folder-sections/{folder_section_id}", response_model=FolderSectionOut)
async def update_folder_section(
    folder_section_id: str,
    payload: FolderSectionUpdate,
    auth: AuthDependency,
) -> FolderSectionOut:
    return await folder_sections.update_folder_section(folder_section_id, payload, auth)


@router.delete(
    "/folder-sections/{folder_section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_folder_section(
    folder_section_id: str,
    auth: AuthDependency,
) -> None:
    await folder_sections.delete_folder_section(folder_section_id, auth)


@router.post("/folder-sections/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_folder_sections(
    payload: list[PositionUpdate],
    auth: AuthDependency,
) -> None:
    await folder_sections.reorder_folder_sections(payload, auth)

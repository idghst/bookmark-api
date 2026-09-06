from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.integrations.postgres import AuthContext, get_resource_auth_context
from app.schemas import (
    FolderCreate,
    FolderOut,
    FolderUpdate,
    PositionUpdate,
)
from app.services import folders

router = APIRouter()
AuthDependency = Annotated[
    AuthContext, Depends(get_resource_auth_context, scope="function")
]


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(auth: AuthDependency) -> list[FolderOut]:
    return await folders.list_folders(auth)


@router.post(
    "/folders",
    response_model=FolderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    payload: FolderCreate,
    auth: AuthDependency,
) -> FolderOut:
    return await folders.create_folder(payload, auth)


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    auth: AuthDependency,
) -> FolderOut:
    return await folders.update_folder(folder_id, payload, auth)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    auth: AuthDependency,
    destination_folder_id: str | None = None,
) -> None:
    await folders.delete_folder(folder_id, auth, destination_folder_id)


@router.post("/folders/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_folders(
    payload: list[PositionUpdate],
    auth: AuthDependency,
) -> None:
    await folders.reorder_folders(payload, auth)

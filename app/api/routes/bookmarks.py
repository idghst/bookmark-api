from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.integrations.postgres import AuthContext, get_resource_auth_context
from app.schemas import BookmarkCreate, BookmarkOut, BookmarkUpdate, PositionUpdate
from app.services import bookmarks

router = APIRouter()
AuthDependency = Annotated[
    AuthContext, Depends(get_resource_auth_context, scope="function")
]


@router.get("/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks(auth: AuthDependency) -> list[BookmarkOut]:
    return await bookmarks.list_bookmarks(auth)


@router.post(
    "/bookmarks",
    response_model=BookmarkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_bookmark(
    payload: BookmarkCreate,
    auth: AuthDependency,
) -> BookmarkOut:
    return await bookmarks.create_bookmark(payload, auth)


@router.patch("/bookmarks/{bookmark_id}", response_model=BookmarkOut)
async def update_bookmark(
    bookmark_id: str,
    payload: BookmarkUpdate,
    auth: AuthDependency,
) -> BookmarkOut:
    return await bookmarks.update_bookmark(bookmark_id, payload, auth)


@router.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(bookmark_id: str, auth: AuthDependency) -> None:
    await bookmarks.delete_bookmark(bookmark_id, auth)


@router.post("/bookmarks/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_bookmarks(
    payload: list[PositionUpdate],
    auth: AuthDependency,
) -> None:
    await bookmarks.reorder_bookmarks(payload, auth)

from fastapi import APIRouter

from app.api.routes.bookmarks import AuthDependency
from app.api.routes.bookmarks import router as bookmarks_router
from app.api.routes.folder_sections import router as folder_sections_router
from app.api.routes.folders import router as folders_router
from app.api.routes.sections import router as sections_router
from app.schemas import SnapshotOut
from app.services import snapshot

router = APIRouter(prefix="/api", tags=["bookmarks"])
router.include_router(bookmarks_router)
router.include_router(folders_router)
router.include_router(folder_sections_router)
router.include_router(sections_router)


@router.get("/snapshot", response_model=SnapshotOut)
async def get_snapshot(auth: AuthDependency) -> SnapshotOut:
    return await snapshot.get_snapshot(auth)

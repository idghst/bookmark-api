import asyncio

from app.integrations.supabase import AuthContext
from app.schemas import SnapshotOut
from app.services.bookmarks import list_bookmarks
from app.services.folder_sections import list_folder_sections
from app.services.folders import list_folders
from app.services.sections import list_sections


async def get_snapshot(auth: AuthContext) -> SnapshotOut:
    # Wait for every read before propagating an error so outstanding tasks
    # cannot outlive the request or its fallback HTTP client.
    results = await asyncio.gather(
        list_bookmarks(auth),
        list_folders(auth),
        list_sections(auth),
        list_folder_sections(auth),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return SnapshotOut.model_validate(
        {
            "bookmarks": results[0],
            "folders": results[1],
            "sections": results[2],
            "folder_sections": results[3],
        }
    )

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.url_validation import require_http_url


class AuthMeOut(BaseModel):
    id: str
    email: str | None


class BookmarkOut(BaseModel):
    id: str
    title: str
    url: str
    description: str | None
    is_favorite: bool = Field(serialization_alias="isFavorite")
    color: str | None = None
    created_at: str = Field(serialization_alias="createdAt")
    updated_at: str = Field(serialization_alias="updatedAt")
    user_id: str = Field(serialization_alias="userId")
    folder_id: str | None = Field(default=None, serialization_alias="folderId")
    folder_section_id: str | None = Field(
        default=None, serialization_alias="folderSectionId"
    )
    position: int = 0

    model_config = ConfigDict(populate_by_name=True)


class BookmarkCreate(BaseModel):
    title: str
    url: str
    description: str | None = None
    is_favorite: bool = Field(default=False, alias="isFavorite")
    color: str | None = None
    folder_id: str | None = Field(default=None, alias="folderId")
    folder_section_id: str | None = Field(default=None, alias="folderSectionId")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("url")
    @classmethod
    def require_http_bookmark_url(cls, value: str) -> str:
        return require_http_url(value)


class BookmarkUpdate(BaseModel):
    title: str | None = None
    url: str | None = None
    description: str | None = None
    is_favorite: bool | None = Field(default=None, alias="isFavorite")
    color: str | None = None
    folder_id: str | None = Field(default=None, alias="folderId")
    folder_section_id: str | None = Field(default=None, alias="folderSectionId")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("url")
    @classmethod
    def require_http_bookmark_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_http_url(value)


class FolderOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    section_id: str | None = Field(default=None, serialization_alias="sectionId")
    position: int = 0
    user_id: str = Field(serialization_alias="userId")

    model_config = ConfigDict(populate_by_name=True)


class FolderCreate(BaseModel):
    name: str
    color: str | None = None
    section_id: str | None = Field(default=None, alias="sectionId")

    model_config = ConfigDict(populate_by_name=True)


class FolderUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    section_id: str | None = Field(default=None, alias="sectionId")

    model_config = ConfigDict(populate_by_name=True)


class SectionOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    position: int = 0
    user_id: str = Field(serialization_alias="userId")

    model_config = ConfigDict(populate_by_name=True)


class SectionCreate(BaseModel):
    name: str
    color: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class SectionUpdate(BaseModel):
    name: str | None = None
    color: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class FolderSectionOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    folder_id: str = Field(serialization_alias="folderId")
    position: int = 0
    user_id: str = Field(serialization_alias="userId")

    model_config = ConfigDict(populate_by_name=True)


class FolderSectionCreate(BaseModel):
    name: str
    color: str | None = None
    folder_id: str = Field(alias="folderId")

    model_config = ConfigDict(populate_by_name=True)


class FolderSectionUpdate(BaseModel):
    name: str | None = None
    color: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class SnapshotOut(BaseModel):
    bookmarks: list[BookmarkOut]
    folders: list[FolderOut]
    sections: list[SectionOut]
    folder_sections: list[FolderSectionOut] = Field(
        serialization_alias="folderSections"
    )

    model_config = ConfigDict(populate_by_name=True)


class PositionUpdate(BaseModel):
    id: str
    position: int


class HealthOut(BaseModel):
    status: str

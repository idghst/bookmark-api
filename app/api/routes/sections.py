from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.integrations.postgres import AuthContext, get_resource_auth_context
from app.schemas import PositionUpdate, SectionCreate, SectionOut, SectionUpdate
from app.services import sections

router = APIRouter()
AuthDependency = Annotated[
    AuthContext, Depends(get_resource_auth_context, scope="function")
]


@router.get("/sections", response_model=list[SectionOut])
async def list_sections(auth: AuthDependency) -> list[SectionOut]:
    return await sections.list_sections(auth)


@router.post(
    "/sections",
    response_model=SectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_section(
    payload: SectionCreate,
    auth: AuthDependency,
) -> SectionOut:
    return await sections.create_section(payload, auth)


@router.patch("/sections/{section_id}", response_model=SectionOut)
async def update_section(
    section_id: str,
    payload: SectionUpdate,
    auth: AuthDependency,
) -> SectionOut:
    return await sections.update_section(section_id, payload, auth)


@router.delete("/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(section_id: str, auth: AuthDependency) -> None:
    await sections.delete_section(section_id, auth)


@router.post("/sections/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_sections(
    payload: list[PositionUpdate],
    auth: AuthDependency,
) -> None:
    await sections.reorder_sections(payload, auth)

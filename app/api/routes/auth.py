from typing import Annotated

from fastapi import APIRouter, Depends

from app.integrations.postgres import AuthContext, get_resource_auth_context
from app.schemas import AuthMeOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=AuthMeOut)
async def me(
    context: Annotated[
        AuthContext, Depends(get_resource_auth_context, scope="function")
    ],
) -> AuthMeOut:
    return AuthMeOut(id=context.user.id, email=context.user.email)

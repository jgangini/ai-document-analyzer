from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.security import get_current_user
from apps.backend.app.core.tracing import trace
from apps.backend.app.services.auth_service import AuthService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    dependencies=[Depends(require_setup_completed)],
)

settings = None
db_manager = None


class LoginRequest(BaseModel):
    username: str
    password: str


def get_auth_service():
    return AuthService(db_manager, settings)


@router.post("/login")
@trace
async def login(request: LoginRequest):
    auth_service = get_auth_service()
    result = auth_service.login(request.username, request.password)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return result


@router.get("/me")
@trace
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    auth_service = get_auth_service()
    user_info = auth_service.get_current_user_info(current_user.get("user_id"))
    if not user_info:
        raise HTTPException(404, "User not found")
    return user_info


@router.post("/logout")
@trace
async def logout():
    return {"message": "Logout successful"}


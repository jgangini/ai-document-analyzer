from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.security import create_access_token, get_current_user
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
    if settings is not None and settings.setup_bypass_enabled:
        if request.username == settings.DEV_ADMIN_USERNAME and request.password == settings.DEV_ADMIN_PASSWORD:
            user = {
                "user_id": 1,
                "username": settings.DEV_ADMIN_USERNAME,
                "name": "Local",
                "last_name": "Admin",
                "email": "admin.local@example.com",
                "modules": [1, 2, 3, 4],
                "group_id": 0,
                "group_name": "Administrators",
            }
            token = create_access_token(
                {"sub": user["username"], "user_id": user["user_id"], "group_id": user["group_id"]},
                settings,
            )
            return {"access_token": token, "token_type": "bearer", "user": user}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
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

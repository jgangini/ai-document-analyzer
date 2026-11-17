import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.tracing import trace
from apps.backend.app.core.security import get_current_user
from apps.backend.app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/user",
    tags=["user"],
    dependencies=[Depends(require_setup_completed)],
)

settings = None
db_manager = None


def get_user_service() -> UserService:
    return UserService(db_manager, settings)


class UpdateProfileRequest(BaseModel):
    name: str
    last_name: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    name: str
    last_name: str
    group_id: int = 1


@router.get("/groups")
@trace
async def list_user_groups(current_user: dict = Depends(get_current_user)):
    del current_user
    if db_manager is None:
        raise HTTPException(500, "Database not initialized")
    try:
        groups = get_user_service().list_groups()
        return {"groups": groups}
    except Exception as e:
        raise HTTPException(500, f"Error listing user groups: {str(e)}")


@router.get("/users")
@trace
async def list_users(current_user: dict = Depends(get_current_user)):
    try:
        users = get_user_service().list_users(current_user.get("user_id"))
        return {"users": users}
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error listing users: {str(e)}")


@router.post("/create")
@trace
async def create_user(request: CreateUserRequest, current_user: dict = Depends(get_current_user)):
    try:
        get_user_service().create_user(
            current_user.get("user_id"),
            request.username,
            request.password,
            request.name,
            request.last_name,
            request.group_id,
        )
        return {"success": True, "message": "User created successfully"}
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        if "already exists" in str(e).lower():
            raise HTTPException(400, "User already exists")
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error creating user: {str(e)}")


@router.delete("/{user_id}")
@trace
async def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    try:
        get_user_service().delete_user(current_user.get("user_id"), user_id)
        return {"success": True, "message": "User deleted successfully"}
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        if "cannot delete" in str(e).lower():
            raise HTTPException(400, "Cannot delete the initial administrator user")
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error deleting user: {str(e)}")


@router.get("/me")
@trace
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    try:
        user_info = get_user_service().get_user_info(current_user.get("user_id"))
        if not user_info:
            raise HTTPException(404, "User not found")
        return user_info
    except HTTPException:
        raise
    except Exception as e:
        err_msg = str(e).upper() if e else ""
        if "ORA-00942" in err_msg or "TABLE OR VIEW DOES NOT EXIST" in err_msg:
            logger.warning("Database tables missing (setup not completed): %s", e)
            raise HTTPException(503, "Database setup not completed. Please complete the setup wizard.")
        logger.exception("Error fetching user info: %s", e)
        raise HTTPException(500, f"Error fetching user info: {str(e)}")


@router.put("/profile")
@trace
async def update_profile(request: UpdateProfileRequest, current_user: dict = Depends(get_current_user)):
    try:
        get_user_service().update_profile(
            current_user.get("user_id"),
            request.name,
            request.last_name,
        )
        return {"success": True, "message": "Profile updated successfully"}
    except Exception as e:
        raise HTTPException(500, f"Error updating profile: {str(e)}")


@router.post("/change-password")
@trace
async def change_password(request: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    try:
        get_user_service().change_password(
            current_user.get("user_id"),
            request.current_password,
            request.new_password,
        )
        return {"success": True, "message": "Password changed successfully"}
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(404, "User not found")
        if "incorrect" in str(e).lower():
            raise HTTPException(400, "Current password is incorrect")
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Error changing password: {str(e)}")


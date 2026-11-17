import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.security import get_current_user
from apps.backend.app.core.tracing import trace
from apps.backend.app.storage.download_service import FileDownloadService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/file",
    tags=["file"],
    dependencies=[Depends(require_setup_completed)],
)

db_manager = None


def get_file_service() -> FileDownloadService:
    return FileDownloadService(db_manager)


@router.get("/download/{file_id}")
@trace
async def get_download(file_id: int, current_user: dict = Depends(get_current_user)):
    try:
        filename, content, content_type = get_file_service().get_download(
            current_user.get("user_id"),
            file_id,
        )
        return StreamingResponse(
            io.BytesIO(content),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    except Exception as e:
        if getattr(e, "code", None) == "ObjectNotFound" or "ObjectNotFound" in str(e):
            raise HTTPException(404, "Original file not found in storage")
        logger.exception("Error downloading original file: %s", e)
        raise HTTPException(500, f"Error downloading file: {str(e)}")


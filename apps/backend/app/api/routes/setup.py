import logging
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from apps.backend.app.core.security import get_current_user
from apps.backend.app.core.tracing import trace
from apps.backend.app.services.bootstrap_service import SetupService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/setup", tags=["setup"])
settings = None
db_manager = None


class DBTestRequest(BaseModel):
    wallet_path: Optional[str] = ""
    wallet_password: Optional[str] = ""
    user: str
    password: str
    dsn: str


class DBRuntimeConfigRequest(BaseModel):
    wallet_path: str
    wallet_password: str
    user: str
    password: str
    dsn: str


class WalletDSNRequest(BaseModel):
    wallet_path: Optional[str] = ""


class OCIConfigRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    compartment_id: Optional[str] = ""
    user: Optional[str] = ""
    fingerprint: Optional[str] = ""
    tenancy: Optional[str] = ""
    region: Optional[str] = ""
    key_file: Optional[str] = ""
    namespace: Optional[str] = ""
    bucket_name: Optional[str] = "app_doc"
    bucket_input: Optional[str] = ""
    bucket_output: Optional[str] = ""
    classifier_model_id: Optional[str] = ""
    extract_actas_model_id: Optional[str] = ""
    extract_contratos_model_id: Optional[str] = ""
    extract_prospectos_model_id: Optional[str] = ""
    selected_project: Optional[str] = ""


class AdminPasswordRequest(BaseModel):
    password: str


class SetupRequest(BaseModel):
    admin_email: str
    admin_password: str
    wallet_path: str
    wallet_password: str
    user: str
    password: str
    dsn: str


class ObjectStorageTestRequest(BaseModel):
    namespace: str
    bucket_name: str


class GenerativeAIConfigRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    inference_url: Optional[str] = ""
    generative_model: Optional[str] = ""


def get_setup_service():
    return SetupService(db_manager)


@router.get("/check")
@trace
async def check_setup_status():
    try:
        if db_manager is None:
            return {"completed": False}
        setup_service = get_setup_service()
        completed = setup_service.check_setup_status()
        return {"completed": bool(completed)}
    except BaseException:
        return {"completed": False}


@router.post("/upload-wallet")
@trace
async def upload_wallet(file: UploadFile = File(...)):
    logger.debug("Upload wallet started: %s", file.filename)
    file_name = file.filename or ""
    if Path(file_name).suffix.lower() != ".zip":
        raise HTTPException(400, "File must be a ZIP archive")
    try:
        import time

        backend_root = Path(__file__).resolve().parents[3]
        wallet_dir = backend_root / "wallet"
        wallet_dir.mkdir(parents=True, exist_ok=True)
        zip_path = backend_root / "__uploaded_wallet__.zip"
        with open(zip_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(wallet_dir)
        for attempt in range(3):
            try:
                time.sleep(0.1)
                zip_path.unlink()
                break
            except (PermissionError, OSError):
                if attempt == 2:
                    logger.debug("Could not remove temporary ZIP, leaving at %s", zip_path)
        setup_service = get_setup_service()
        dsn_result = setup_service.list_wallet_dsns(str(wallet_dir.absolute()))
        return {
            "success": True,
            "message": "Wallet extracted successfully",
            "wallet_path": str(wallet_dir.absolute()),
            "dsns": dsn_result.get("dsns", []),
            "selected_dsn": dsn_result.get("selected_dsn", ""),
        }
    except zipfile.BadZipFile as e:
        raise HTTPException(500, f"ZIP file is corrupt: {str(e)}")
    except Exception as e:
        logger.exception("Wallet upload failed: %s", e)
        raise HTTPException(500, f"Error extracting wallet: {str(e)}")


@router.post("/test-db")
@trace
async def test_db_connection(request: DBTestRequest):
    wallet_path = (request.wallet_path or "").strip()
    if wallet_path == "__SERVER_DEFAULT_WALLET__":
        wallet_path = str(settings.wallet_dir) if settings is not None else ""
    if not wallet_path:
        raise HTTPException(400, "Wallet path is required")
    result = get_setup_service().test_db_connection(
        wallet_path,
        request.wallet_password or "",
        request.user,
        request.password,
        request.dsn,
    )
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/save-db-runtime")
@trace
async def save_db_runtime(request: DBRuntimeConfigRequest):
    wallet_path = (request.wallet_path or "").strip()
    if wallet_path == "__SERVER_DEFAULT_WALLET__":
        wallet_path = str(settings.wallet_dir) if settings is not None else ""
    if not all([
        wallet_path,
        (request.wallet_password or "").strip(),
        (request.user or "").strip(),
        (request.password or "").strip(),
        (request.dsn or "").strip(),
    ]):
        raise HTTPException(400, "Complete DB configuration is required")

    setup_service = get_setup_service()
    result = setup_service.test_db_connection(
        wallet_path,
        request.wallet_password,
        request.user,
        request.password,
        request.dsn,
    )
    if not result["success"]:
        raise HTTPException(400, result["message"])
    try:
        setup_service.save_runtime_db_config(
            wallet_path=wallet_path,
            wallet_password=request.wallet_password,
            user=request.user,
            password=request.password,
            dsn=request.dsn,
        )
    except Exception as exc:
        raise HTTPException(500, f"Could not persist runtime DB config: {exc}") from exc
    return {"success": True, "message": "Database configuration saved for runtime", "connected_user": result.get("connected_user")}


@router.post("/list-wallet-dsns")
@trace
async def list_wallet_dsns(request: WalletDSNRequest):
    wallet_path = (request.wallet_path or "").strip()
    if wallet_path == "__SERVER_DEFAULT_WALLET__":
        wallet_path = str(settings.wallet_dir) if settings is not None else ""
    if not wallet_path:
        raise HTTPException(400, "Wallet path is required")
    result = get_setup_service().list_wallet_dsns(wallet_path)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/installation")
@trace
async def execute_setup(request: SetupRequest):
    logger.debug("Setup started")
    try:
        wallet_path = (request.wallet_path or "").strip()
        if wallet_path == "__SERVER_DEFAULT_WALLET__":
            wallet_path = str(settings.wallet_dir) if settings is not None else ""
        if not all([
            wallet_path,
            (request.wallet_password or "").strip(),
            (request.user or "").strip(),
            (request.password or "").strip(),
            (request.dsn or "").strip(),
        ]):
            raise HTTPException(400, detail="Database configuration is required before installation.")

        setup_service = get_setup_service()
        result = setup_service.execute_setup_scripts(
            wallet_path=wallet_path,
            wallet_password=request.wallet_password,
            user=request.user,
            password=request.password,
            dsn=request.dsn,
        )
        if not result["success"]:
            raise HTTPException(500, detail=result)
        admin_created = setup_service.create_admin_user(
            request.admin_email,
            request.admin_password,
            wallet_path=wallet_path,
            wallet_password=request.wallet_password,
            user=request.user,
            db_password=request.password,
            dsn=request.dsn,
        )
        if not admin_created:
            raise HTTPException(500, detail="Error creating admin user")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Setup exception: %s", e)
        raise HTTPException(500, detail=str(e))


@router.post("/admin-password")
@trace
async def set_admin_password(request: AdminPasswordRequest):
    success = get_setup_service().update_admin_password(request.password)
    if not success:
        raise HTTPException(500, "Error updating password")
    return {"success": True, "message": "Password updated"}


@router.post("/upload-key")
@trace
async def upload_key_file(file: UploadFile = File(...)):
    if not file.filename.endswith(".pem"):
        raise HTTPException(400, "File must be .pem")
    try:
        backend_root = Path(__file__).resolve().parents[3]
        keys_dir = backend_root / "keys"
        keys_dir.mkdir(parents=True, exist_ok=True)
        key_path = keys_dir / file.filename
        with open(key_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return {"success": True, "message": "Key file uploaded", "key_path": str(key_path.absolute())}
    except Exception as e:
        raise HTTPException(500, f"Error uploading key: {str(e)}")


@router.post("/test-oci")
@trace
async def test_oci_connection(request: OCIConfigRequest):
    result = get_setup_service().test_oci_connection(request.model_dump())
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/save-oci-config")
@trace
async def save_oci_config(request: OCIConfigRequest):
    payload = request.model_dump()
    payload["bucket_name"] = (
        (request.bucket_name or "").strip()
        or (request.bucket_input or "").strip()
        or (request.bucket_output or "").strip()
    )
    success = get_setup_service().save_oci_config(payload)
    if not success:
        raise HTTPException(500, "Error saving configuration")
    return {"success": True, "message": "Configuration saved"}


@router.post("/test-object-storage")
@trace
async def test_object_storage(request: ObjectStorageTestRequest):
    result = get_setup_service().test_object_storage(request.namespace, request.bucket_name)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.get("/list-genai-models")
@trace
async def list_genai_models():
    result = get_setup_service().list_genai_models()
    if not result.get("success"):
        raise HTTPException(400, result.get("message", "Error listing GenAI models. Save API Key configuration first."))
    return result


@router.post("/test-generative-ai")
@trace
async def test_generative_ai(request: GenerativeAIConfigRequest):
    result = get_setup_service().test_generative_ai(
        request.inference_url or "",
        request.generative_model or "",
    )
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result


@router.post("/save-generative-ai-config")
@trace
async def save_generative_ai_config(request: GenerativeAIConfigRequest):
    success = get_setup_service().save_generative_ai_config(
        {
            "inference_url": request.inference_url or "",
            "generative_model": request.generative_model or "",
        }
    )
    if not success:
        raise HTTPException(500, "Error saving configuration")
    return {"success": True, "message": "Configuration saved"}


@router.post("/complete")
@trace
async def complete_setup():
    success = get_setup_service().complete_setup()
    if not success:
        raise HTTPException(500, "Error completing setup")
    try:
        logger.info("Setup complete - initializing database pool...")
        db_manager.init_pool()
        logger.info("Database pool initialized successfully")
    except Exception as e:
        logger.warning("Error initializing DB pool: %s", e)
    return {"success": True, "message": "Setup completed successfully"}

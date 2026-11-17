"""Prepare uploaded PDF and ZIP sources for editable ingestion plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from apps.backend.app.core.config import Settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.ingest.archive_service import ArchiveService
from apps.backend.app.ingest.document_metadata import extract_document_code_from_filename

SUPPORTED_LANGUAGES = {"es", "pt", "en"}
SUPPORTED_ACCESS_VALUES = {"private", "all"}


@dataclass(slots=True)
class PreparedUploadItem:
    source_path: str
    source_zip_path: str | None
    group_source_path: str
    group_name: str
    group_kind: str
    archive_slug: str
    file_name: str
    display_name: str
    document_code: str | None
    document_code_source: str
    document_language: str
    access: str
    order: int
    enabled: bool = True


@dataclass(slots=True)
class PreparedUploadGroup:
    group_source_path: str
    group_name: str
    group_kind: str
    archive_slug: str
    item_count: int
    items: list[PreparedUploadItem] = field(default_factory=list)


@dataclass(slots=True)
class PreparedUploadError:
    source_path: str
    source_name: str
    error: str


@dataclass(slots=True)
class PreparedUploadResult:
    groups: list[PreparedUploadGroup] = field(default_factory=list)
    errors: list[PreparedUploadError] = field(default_factory=list)


def _normalize_language(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    return "es"


def _normalize_access(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_ACCESS_VALUES:
        return normalized
    return "private"


def _is_within(base_dir: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base_dir.resolve())
        return True
    except ValueError:
        return False


class UploadPreparationService:
    def __init__(
        self,
        *,
        settings: Settings,
        archive_service: ArchiveService,
        db_manager: DatabaseManager | None = None,
    ) -> None:
        del db_manager
        self.settings = settings
        self.archive_service = archive_service

    def prepare_saved_files(
        self,
        *,
        saved_files: list[str],
        default_document_language: str | None,
        default_access: str | None,
    ) -> PreparedUploadResult:
        normalized_language = _normalize_language(default_document_language)
        normalized_access = _normalize_access(default_access)
        result = PreparedUploadResult()

        for raw_path in saved_files:
            source_path = Path(str(raw_path or "").strip())
            source_name = source_path.name or "upload.bin"
            try:
                if not source_path.exists():
                    raise FileNotFoundError("Uploaded source does not exist.")
                if not _is_within(self.settings.upload_path, source_path):
                    raise ValueError("Uploaded source path is outside the staging upload directory.")
                suffix = source_path.suffix.lower()
                if suffix == ".pdf":
                    result.groups.append(
                        self._prepare_pdf_group(
                            pdf_path=source_path,
                            default_document_language=normalized_language,
                            default_access=normalized_access,
                        )
                    )
                    continue
                if suffix == ".zip":
                    result.groups.append(
                        self._prepare_zip_group(
                            zip_path=source_path,
                            default_document_language=normalized_language,
                            default_access=normalized_access,
                        )
                    )
                    continue
                raise ValueError("Only PDF and ZIP files are supported.")
            except Exception as exc:
                result.errors.append(
                    PreparedUploadError(
                        source_path=str(source_path),
                        source_name=source_name,
                        error=str(exc),
                    )
                )

        return result

    def _prepare_pdf_group(
        self,
        *,
        pdf_path: Path,
        default_document_language: str,
        default_access: str,
    ) -> PreparedUploadGroup:
        document_code, document_code_source = extract_document_code_from_filename(pdf_path.name)
        item = PreparedUploadItem(
            source_path=str(pdf_path),
            source_zip_path=None,
            group_source_path=str(pdf_path),
            group_name=pdf_path.name,
            group_kind="pdf",
            archive_slug=pdf_path.stem,
            file_name=pdf_path.name,
            display_name=pdf_path.name,
            document_code=document_code,
            document_code_source=document_code_source,
            document_language=default_document_language,
            access=default_access,
            order=1,
        )
        return PreparedUploadGroup(
            group_source_path=str(pdf_path),
            group_name=pdf_path.name,
            group_kind="pdf",
            archive_slug=pdf_path.stem,
            item_count=1,
            items=[item],
        )

    def _prepare_zip_group(
        self,
        *,
        zip_path: Path,
        default_document_language: str,
        default_access: str,
    ) -> PreparedUploadGroup:
        pdf_contexts = self.archive_service.resolve_pdf_contexts([zip_path])
        if not pdf_contexts:
            raise ValueError("The ZIP file does not contain PDF files.")

        zip_document_code, zip_document_code_source = extract_document_code_from_filename(zip_path.name)
        extracted_root = None
        first_pdf_path = pdf_contexts[0].pdf_path
        if first_pdf_path.parent != first_pdf_path:
            extracted_root = first_pdf_path.parents[0]
            while extracted_root.parent != self.settings.extracted_path and extracted_root.parent != extracted_root:
                extracted_root = extracted_root.parent

        items: list[PreparedUploadItem] = []
        for index, pdf_context in enumerate(pdf_contexts, start=1):
            item_document_code, item_document_code_source = extract_document_code_from_filename(
                pdf_context.pdf_path.name
            )
            document_code = zip_document_code or item_document_code
            document_code_source = (
                zip_document_code_source if zip_document_code else item_document_code_source
            )
            display_name = pdf_context.pdf_path.name
            if extracted_root is not None:
                try:
                    display_name = pdf_context.pdf_path.relative_to(extracted_root).as_posix()
                except ValueError:
                    display_name = pdf_context.pdf_path.name
            items.append(
                PreparedUploadItem(
                    source_path=str(pdf_context.pdf_path),
                    source_zip_path=str(zip_path),
                    group_source_path=str(zip_path),
                    group_name=zip_path.name,
                    group_kind="zip",
                    archive_slug=zip_path.stem,
                    file_name=pdf_context.pdf_path.name,
                    display_name=display_name,
                    document_code=document_code,
                    document_code_source=document_code_source,
                    document_language=default_document_language,
                    access=default_access,
                    order=index,
                )
            )

        return PreparedUploadGroup(
            group_source_path=str(zip_path),
            group_name=zip_path.name,
            group_kind="zip",
            archive_slug=zip_path.stem,
            item_count=len(items),
            items=items,
        )

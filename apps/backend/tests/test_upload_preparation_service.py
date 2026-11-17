from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from apps.backend.app.core.config import Settings
from apps.backend.app.ingest.archive_service import ArchiveService
from apps.backend.app.ingest.upload_preparation_service import UploadPreparationService


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        UPLOAD_DIR=str(tmp_path / "uploads"),
        EXTRACTED_DIR=str(tmp_path / "extracted"),
    )


def test_prepare_saved_files_uses_zip_name_for_folio_without_retired_classification(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    settings.upload_path.mkdir(parents=True, exist_ok=True)

    zip_dir = settings.upload_path / "upload-a"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / "RM797_ID_1668.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("contracts/01-main.pdf", b"%PDF-1.4\n")
        archive.writestr("02-annex.pdf", b"%PDF-1.4\n")

    service = UploadPreparationService(
        settings=settings,
        archive_service=ArchiveService(settings),
    )
    result = service.prepare_saved_files(
        saved_files=[str(zip_path)],
        default_document_language="es",
        default_access="private",
    )

    assert result.errors == []
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.group_kind == "zip"
    assert group.group_name == "RM797_ID_1668.zip"
    assert group.item_count == 2
    assert [item.display_name for item in group.items] == ["contracts/01-main.pdf", "02-annex.pdf"]
    assert [item.order for item in group.items] == [1, 2]
    assert all(item.document_code == "RM797" for item in group.items)
    assert all(item.document_language == "es" for item in group.items)
    assert all(item.access == "private" for item in group.items)


def test_prepare_saved_files_keeps_pdf_defaults_without_retired_classification(tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    settings.upload_path.mkdir(parents=True, exist_ok=True)

    pdf_dir = settings.upload_path / "upload-b"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "RM800_Unknown_Document.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    service = UploadPreparationService(
        settings=settings,
        archive_service=ArchiveService(settings),
    )
    result = service.prepare_saved_files(
        saved_files=[str(pdf_path)],
        default_document_language="pt",
        default_access="all",
    )

    assert result.errors == []
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.group_kind == "pdf"
    assert group.item_count == 1
    item = group.items[0]
    assert item.display_name == "RM800_Unknown_Document.pdf"
    assert item.document_code == "RM800"
    assert item.document_language == "pt"
    assert item.access == "all"

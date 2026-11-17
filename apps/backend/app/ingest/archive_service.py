"""Discover PDF sources and extract ZIP archives safely."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from apps.backend.app.core.config import Settings
from apps.backend.app.core.hashing import sha256_file


@dataclass(slots=True)
class PDFSourceContext:
    pdf_path: Path
    archive_slug: str
    archive_id: str
    source_zip_path: Path | None


class ArchiveService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def discover_sources(
        self,
        source_path: Path | None = None,
        *,
        include_archives: bool = True,
    ) -> list[Path]:
        base_path = source_path or self.settings.docs_dir
        if not base_path.exists():
            return []
        if base_path.is_file():
            suffix = base_path.suffix.lower()
            if suffix == ".pdf":
                return [base_path]
            if include_archives and suffix == ".zip":
                return [base_path]
            return []
        patterns = ["*.pdf", "*.PDF"]
        if include_archives:
            patterns.extend(["*.zip", "*.ZIP"])
        discovered: list[Path] = []
        for pattern in patterns:
            discovered.extend(sorted(base_path.glob(pattern)))
        unique_paths = {path.resolve(): path for path in discovered}
        return list(unique_paths.values())

    def resolve_pdf_contexts(self, sources: list[Path]) -> list[PDFSourceContext]:
        resolved: list[PDFSourceContext] = []
        for source in sources:
            if source.suffix.lower() == ".zip":
                archive_id = sha256_file(source)
                archive_slug = source.stem
                for extracted_pdf in self.extract_zip(source, archive_id=archive_id):
                    resolved.append(
                        PDFSourceContext(
                            pdf_path=extracted_pdf,
                            archive_slug=archive_slug,
                            archive_id=archive_id,
                            source_zip_path=source,
                        )
                    )
                continue
            if source.suffix.lower() == ".pdf":
                resolved.append(
                    PDFSourceContext(
                        pdf_path=source,
                        archive_slug=source.stem,
                        archive_id=sha256_file(source),
                        source_zip_path=None,
                    )
                )
        return resolved

    def extract_zip(self, archive_path: Path, *, archive_id: str | None = None) -> list[Path]:
        resolved_archive_id = str(archive_id or sha256_file(archive_path)).strip()
        destination_suffix = resolved_archive_id[:12] if resolved_archive_id else "archive"
        destination = self.settings.extracted_path / f"{archive_path.stem}-{destination_suffix}"
        destination.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []
        with ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                target_path = (destination / member.filename).resolve()
                if destination.resolve() not in target_path.parents and target_path != destination.resolve():
                    raise ValueError(f"Unsafe archive member detected: {member.filename}")
                archive.extract(member, destination)
                extracted.append(destination / member.filename)
        return [path for path in extracted if path.suffix.lower() == ".pdf"]

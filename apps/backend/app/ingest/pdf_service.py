"""Servicios de procesamiento PDF estricto para flujo OCI."""

from __future__ import annotations

from pathlib import Path

import fitz
from pypdf import PdfReader

from apps.backend.app.core.config import Settings


class PDFService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_page_count(self, pdf_path: Path) -> int:
        try:
            reader = PdfReader(str(pdf_path))
            count = len(reader.pages)
            if count < 1:
                raise RuntimeError("PDF without pages.")
            return count
        except Exception as exc:
            raise RuntimeError(f"Could not read PDF page count: {pdf_path.name}") from exc

    def extract_native_text_pages(
        self,
        pdf_path: Path,
        *,
        max_pages: int = 2,
        max_chars_per_page: int = 3000,
    ) -> list[str]:
        safe_max_pages = max(1, int(max_pages))
        safe_max_chars = max(250, int(max_chars_per_page))
        try:
            document = fitz.open(pdf_path)
            extracted: list[str] = []
            for page_index in range(min(document.page_count, safe_max_pages)):
                page = document.load_page(page_index)
                text = " ".join(str(page.get_text("text") or "").split())
                if text:
                    extracted.append(text[:safe_max_chars])
            document.close()
            return extracted
        except Exception as exc:
            raise RuntimeError(f"Could not extract native PDF text: {pdf_path.name}") from exc

    def render_pages(self, pdf_path: Path, *, max_pages: int | None = None) -> list[dict]:
        output_dir = self.settings.page_image_path / pdf_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            document = fitz.open(pdf_path)
            rendered_pages: list[dict] = []
            total_pages = document.page_count if max_pages is None else min(document.page_count, max(1, int(max_pages)))
            for page_index in range(total_pages):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image_path = output_dir / f"page-{page_index + 1}.png"
                pixmap.save(image_path)
                rendered_pages.append(
                    {
                        "page_number": page_index + 1,
                        "image_path": image_path,
                        "width": int(pixmap.width),
                        "height": int(pixmap.height),
                        "native_text": " ".join(str(page.get_text("text") or "").split()),
                    }
                )
            document.close()
            if rendered_pages:
                return rendered_pages
            raise RuntimeError("PDF rendering returned zero pages.")
        except Exception as exc:
            raise RuntimeError(f"Could not render PDF pages: {pdf_path.name}") from exc

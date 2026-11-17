"""Document parsing via Docling with page-level OCR/layout artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from apps.backend.app.core.config import Settings
from apps.backend.app.ingest.ocr_types import PageOCRResult
from apps.backend.app.ingest.text_utils import compact_whitespace, normalize_text


@dataclass(slots=True)
class DoclingPageResult:
    page_number: int
    ocr_result: PageOCRResult
    visual_summary: str
    layout_json: str
    visual_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DoclingDocumentResult:
    pages: dict[int, DoclingPageResult]
    telemetry: dict[str, object] = field(default_factory=dict)


class DoclingDocumentService:
    _IMAGE_MARKER_RE = re.compile(r"<\s*!?-{2,}\s*images?\s*-{2,}\s*>", flags=re.IGNORECASE)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze_document(
        self,
        *,
        pdf_path: Path,
        document_language: str | None = None,
    ) -> DoclingDocumentResult:
        (
            DocumentConverter,
            PdfFormatOption,
            InputFormat,
            PdfPipelineOptions,
            RapidOcrOptions,
        ) = self._load_docling_runtime()

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.ocr_options = RapidOcrOptions(lang=self._resolve_languages(document_language))
        pipeline_options.do_table_structure = True
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True
        pipeline_options.generate_table_images = True
        pipeline_options.do_picture_classification = False
        pipeline_options.do_picture_description = False

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )
        try:
            conversion = converter.convert(pdf_path)
        except Exception as exc:
            raise RuntimeError(f"Docling could not parse '{pdf_path.name}'.") from exc

        document = conversion.document
        if not document.pages:
            raise RuntimeError(f"Docling returned zero pages for '{pdf_path.name}'.")

        page_buckets = {
            int(page_no): self._build_page_bucket(page=document.pages[page_no])
            for page_no in sorted(document.pages.keys())
        }
        for page_number, bucket in page_buckets.items():
            bucket["markdown_text"] = self._export_page_markdown(
                document=document,
                page_number=page_number,
            )

        for item, _level in document.iterate_items():
            page_numbers = self._extract_page_numbers(item)
            if not page_numbers:
                continue
            item_type = item.__class__.__name__
            if item_type == "TableItem":
                self._append_table_item(
                    document=document,
                    item=item,
                    page_numbers=page_numbers,
                    page_buckets=page_buckets,
                )
                continue
            if item_type == "PictureItem":
                self._append_picture_item(
                    item=item,
                    page_numbers=page_numbers,
                    page_buckets=page_buckets,
                )
                continue
            text_value = self._extract_item_text(document=document, item=item)
            if not text_value:
                continue
            for page_number in page_numbers:
                bucket = page_buckets.get(int(page_number))
                if bucket is None:
                    continue
                self._append_unique_text_fragment(bucket=bucket, text_value=text_value)
                bucket["detected_blocks"].append(
                    {
                        "type": item_type,
                        "text": text_value[:1200],
                        "page_number": int(page_number),
                        "bbox": self._serialize_bbox(self._resolve_primary_bbox(item)),
                    }
                )

        pages: dict[int, DoclingPageResult] = {}
        table_pages_count = 0
        picture_pages_count = 0
        text_pages_count = 0
        total_tables = 0
        total_pictures = 0

        total_pages = len(page_buckets)
        for page_number, bucket in page_buckets.items():
            page_result = self._build_page_result(
                page_number=page_number,
                bucket=bucket,
                total_pages=total_pages,
            )
            pages[page_number] = page_result
            if "contains_table" in page_result.visual_flags:
                table_pages_count += 1
            if "contains_picture" in page_result.visual_flags:
                picture_pages_count += 1
            if page_result.ocr_result.normalized_text:
                text_pages_count += 1
            total_tables += len(bucket["tables"])
            total_pictures += len(bucket["pictures"])

        return DoclingDocumentResult(
            pages=pages,
            telemetry={
                "docling_pages_count": len(pages),
                "docling_text_pages_count": text_pages_count,
                "docling_table_pages_count": table_pages_count,
                "docling_picture_pages_count": picture_pages_count,
                "docling_tables_count": total_tables,
                "docling_pictures_count": total_pictures,
            },
        )

    @staticmethod
    def _load_docling_runtime() -> tuple[Any, Any, Any, Any, Any]:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except Exception as exc:
            raise RuntimeError(
                "Docling dependencies are not installed. "
                "Run: pip install docling rapidocr_onnxruntime"
            ) from exc
        return (
            DocumentConverter,
            PdfFormatOption,
            InputFormat,
            PdfPipelineOptions,
            RapidOcrOptions,
        )

    @staticmethod
    def _resolve_languages(document_language: str | None) -> list[str]:
        raw_value = str(document_language or "").strip().lower()
        if not raw_value:
            return ["es"]
        tokens = [
            token.strip()
            for token in re.split(r"[,;/\s]+", raw_value)
            if token.strip()
        ]
        if not tokens:
            return ["es"]
        normalized: list[str] = []
        seen: set[str] = set()
        for token in tokens:
            resolved = token
            if token in {"spa", "es-419", "es-cl", "es-pe", "es-mx"} or token.startswith("es"):
                resolved = "es"
            elif token in {"eng", "en-us", "en-gb"} or token.startswith("en"):
                resolved = "en"
            if resolved in seen:
                continue
            seen.add(resolved)
            normalized.append(resolved)
        return normalized or ["es"]

    @staticmethod
    def _build_page_bucket(*, page: Any) -> dict[str, Any]:
        width = float(getattr(getattr(page, "size", None), "width", 0.0) or 0.0)
        height = float(getattr(getattr(page, "size", None), "height", 0.0) or 0.0)
        return {
            "page_width": width,
            "page_height": height,
            "text_fragments": [],
            "markdown_text": "",
            "seen_texts": set(),
            "detected_blocks": [],
            "tables": [],
            "pictures": [],
        }

    @staticmethod
    def _export_page_markdown(*, document: Any, page_number: int) -> str:
        export_to_markdown = getattr(document, "export_to_markdown", None)
        if not callable(export_to_markdown):
            raise RuntimeError("Docling document does not expose export_to_markdown().")
        try:
            return str(
                export_to_markdown(
                    page_no=int(page_number),
                    delim="\n\n",
                    compact_tables=False,
                    traverse_pictures=True,
                )
                or ""
            ).strip()
        except Exception as exc:
            raise RuntimeError(f"Docling could not export page {page_number} as Markdown.") from exc

    @staticmethod
    def _reconstruct_markdown_from_text(raw_text: str) -> str:
        """Keep OCR usable when Docling has text/provenance but exports empty page Markdown."""
        blocks = [
            compact_whitespace(block)
            for block in re.split(r"\n{2,}", str(raw_text or "").strip())
            if compact_whitespace(block)
        ]
        return "\n\n".join(blocks).strip()

    @classmethod
    def _meaningful_markdown_text(cls, markdown_text: str) -> str:
        return compact_whitespace(cls._IMAGE_MARKER_RE.sub(" ", str(markdown_text or "")))

    @classmethod
    def _should_reconstruct_markdown(cls, *, markdown_text: str, normalized_text: str) -> bool:
        text_length = len(compact_whitespace(normalized_text))
        if text_length == 0:
            return False
        markdown_length = len(cls._meaningful_markdown_text(markdown_text))
        if markdown_length == 0:
            return True
        if text_length < 120:
            return False
        if text_length >= 500 and markdown_length < 120:
            return True
        return markdown_length < max(80, int(text_length * 0.18))

    @staticmethod
    def _extract_page_numbers(item: Any) -> list[int]:
        ordered: list[int] = []
        seen: set[int] = set()
        for prov in list(getattr(item, "prov", None) or []):
            page_number = int(getattr(prov, "page_no", 0) or 0)
            if page_number <= 0 or page_number in seen:
                continue
            seen.add(page_number)
            ordered.append(page_number)
        return ordered

    @staticmethod
    def _resolve_primary_bbox(item: Any) -> Any | None:
        provenance = list(getattr(item, "prov", None) or [])
        if not provenance:
            return None
        return getattr(provenance[0], "bbox", None)

    @classmethod
    def _serialize_bbox(cls, bbox: Any | None) -> dict[str, object] | None:
        if bbox is None:
            return None
        try:
            width = float(getattr(bbox, "width", 0.0) or 0.0)
            height = float(getattr(bbox, "height", 0.0) or 0.0)
            return {
                "l": round(float(getattr(bbox, "l", 0.0) or 0.0), 3),
                "t": round(float(getattr(bbox, "t", 0.0) or 0.0), 3),
                "r": round(float(getattr(bbox, "r", 0.0) or 0.0), 3),
                "b": round(float(getattr(bbox, "b", 0.0) or 0.0), 3),
                "width": round(width, 3),
                "height": round(height, 3),
                "coord_origin": str(getattr(getattr(bbox, "coord_origin", None), "value", "") or ""),
            }
        except Exception:
            return None

    @classmethod
    def _append_unique_text_fragment(cls, *, bucket: dict[str, Any], text_value: str) -> None:
        normalized = compact_whitespace(text_value)
        if not normalized:
            return
        seen_texts = bucket["seen_texts"]
        if normalized in seen_texts:
            return
        seen_texts.add(normalized)
        bucket["text_fragments"].append(str(text_value).strip())

    @classmethod
    def _extract_item_text(cls, *, document: Any, item: Any) -> str:
        raw_text = getattr(item, "text", None)
        if raw_text is None:
            export_to_markdown = getattr(item, "export_to_markdown", None)
            if callable(export_to_markdown):
                try:
                    raw_text = export_to_markdown(doc=document)
                except Exception:
                    raw_text = ""
        return str(raw_text or "").strip()

    @classmethod
    def _append_table_item(
        cls,
        *,
        document: Any,
        item: Any,
        page_numbers: list[int],
        page_buckets: dict[int, dict[str, Any]],
    ) -> None:
        export_to_markdown = getattr(item, "export_to_markdown", None)
        markdown = ""
        if callable(export_to_markdown):
            try:
                markdown = str(export_to_markdown(doc=document) or "").strip()
            except Exception:
                markdown = ""
        table_payload = {
            "page_number": int(page_numbers[0]),
            "bbox": cls._serialize_bbox(cls._resolve_primary_bbox(item)),
            "markdown": markdown[:4000],
        }
        for page_number in page_numbers:
            bucket = page_buckets.get(int(page_number))
            if bucket is None:
                continue
            bucket["tables"].append(dict(table_payload, page_number=int(page_number)))
            bucket["detected_blocks"].append(
                {
                    "type": "table",
                    "page_number": int(page_number),
                    "bbox": table_payload["bbox"],
                    "preview": compact_whitespace(markdown)[:1200],
                }
            )
            if markdown:
                cls._append_unique_text_fragment(bucket=bucket, text_value=markdown)

    @classmethod
    def _append_picture_item(
        cls,
        *,
        item: Any,
        page_numbers: list[int],
        page_buckets: dict[int, dict[str, Any]],
    ) -> None:
        for page_number in page_numbers:
            bucket = page_buckets.get(int(page_number))
            if bucket is None:
                continue
            bbox = cls._resolve_primary_bbox(item)
            picture_payload = cls._build_picture_payload(
                bbox=bbox,
                page_number=int(page_number),
                page_width=float(bucket["page_width"] or 0.0),
                page_height=float(bucket["page_height"] or 0.0),
            )
            bucket["pictures"].append(picture_payload)
            bucket["detected_blocks"].append(
                {
                    "type": "picture",
                    "page_number": int(page_number),
                    "bbox": picture_payload.get("bbox"),
                    "kind_hint": picture_payload.get("kind_hint"),
                    "area_ratio": picture_payload.get("area_ratio"),
                }
            )

    @classmethod
    def _build_picture_payload(
        cls,
        *,
        bbox: Any | None,
        page_number: int,
        page_width: float,
        page_height: float,
    ) -> dict[str, object]:
        serialized_bbox = cls._serialize_bbox(bbox)
        bbox_width = float(getattr(bbox, "width", 0.0) or 0.0) if bbox is not None else 0.0
        bbox_height = float(getattr(bbox, "height", 0.0) or 0.0) if bbox is not None else 0.0
        page_area = max(1.0, float(page_width or 0.0) * float(page_height or 0.0))
        bbox_area = max(0.0, bbox_width * bbox_height)
        area_ratio = round(bbox_area / page_area, 4)
        aspect_ratio = round(bbox_width / max(1.0, bbox_height), 4) if bbox_height > 0 else 0.0
        kind_hint = "visual_region"
        if 1.8 <= aspect_ratio <= 8.0 and 0.0008 <= area_ratio <= 0.08:
            kind_hint = "signature_like"
        elif 0.75 <= aspect_ratio <= 1.45 and 0.0008 <= area_ratio <= 0.08:
            kind_hint = "stamp_like"
        return {
            "page_number": int(page_number),
            "bbox": serialized_bbox,
            "width": round(bbox_width, 3),
            "height": round(bbox_height, 3),
            "aspect_ratio": aspect_ratio,
            "area_ratio": area_ratio,
            "kind_hint": kind_hint,
        }

    @classmethod
    def _build_page_result(
        cls,
        *,
        page_number: int,
        bucket: dict[str, Any],
        total_pages: int,
    ) -> DoclingPageResult:
        text_fragments = list(bucket["text_fragments"])
        tables = list(bucket["tables"])
        pictures = list(bucket["pictures"])
        markdown_text = str(bucket["markdown_text"] or "").strip()
        raw_text = "\n\n".join(fragment for fragment in text_fragments if str(fragment).strip()).strip()
        normalized_text = compact_whitespace(raw_text)
        markdown_source = "docling_export"
        extra_visual_flags: list[str] = []
        if cls._should_reconstruct_markdown(
            markdown_text=markdown_text,
            normalized_text=normalized_text,
        ):
            markdown_text = cls._reconstruct_markdown_from_text(raw_text)
            markdown_source = "ocr_text_reconstruction"
            extra_visual_flags.append("markdown_reconstructed_from_ocr")
        visual_flags = cls._detect_visual_flags(
            page_number=page_number,
            total_pages=total_pages,
            normalized_text=normalized_text,
            tables=tables,
            pictures=pictures,
        )
        for flag in extra_visual_flags:
            if flag not in visual_flags:
                visual_flags.append(flag)
        visual_summary = cls._build_visual_summary(
            text_block_count=len(text_fragments),
            table_count=len(tables),
            picture_count=len(pictures),
            visual_flags=visual_flags,
        )
        ocr_confidence = cls._estimate_ocr_confidence(
            normalized_text=normalized_text,
            table_count=len(tables),
            picture_count=len(pictures),
        )
        layout_payload = {
            "parser": "docling",
            "ocr_engine": "rapidocr",
            "page_number": int(page_number),
            "text_block_count": len(text_fragments),
            "table_count": len(tables),
            "picture_count": len(pictures),
            "flags": list(visual_flags),
            "labels": cls._build_labels(visual_flags=visual_flags),
            "text_preview": normalized_text[:2000],
            "markdown_preview": markdown_text[:2000],
            "markdown_source": markdown_source,
            "tables": tables[:8],
            "pictures": pictures[:16],
            "detected_blocks": list(bucket["detected_blocks"])[:120],
        }
        return DoclingPageResult(
            page_number=int(page_number),
            ocr_result=PageOCRResult(
                raw_ocr_text=raw_text,
                normalized_text=normalized_text,
                markdown_text=markdown_text,
                detected_blocks_json=json.dumps(layout_payload["detected_blocks"], ensure_ascii=False),
                table_extraction_json=json.dumps(tables[:8], ensure_ascii=False),
                ocr_confidence=ocr_confidence,
                extraction_method="docling_rapidocr",
            ),
            visual_summary=visual_summary,
            layout_json=json.dumps(layout_payload, ensure_ascii=False),
            visual_flags=visual_flags,
        )

    @staticmethod
    def _build_labels(*, visual_flags: list[str]) -> list[str]:
        labels: list[str] = []
        mapping = {
            "contains_table": "table",
            "contains_picture": "picture",
            "possible_signature": "signature_like",
            "possible_stamp": "stamp_like",
            "low_ocr_confidence": "low_text_reliability",
        }
        for flag in visual_flags:
            label = mapping.get(str(flag))
            if label and label not in labels:
                labels.append(label)
        return labels

    @classmethod
    def _detect_visual_flags(
        cls,
        *,
        page_number: int,
        total_pages: int,
        normalized_text: str,
        tables: list[dict[str, object]],
        pictures: list[dict[str, object]],
    ) -> list[str]:
        flags: list[str] = []

        def _append(flag: str) -> None:
            if flag not in flags:
                flags.append(flag)

        if page_number == 1:
            _append("cover_page")
        if page_number == total_pages:
            _append("closing_page")
        if tables:
            _append("contains_table")
        if pictures:
            _append("contains_picture")

        digit_density = len(re.findall(r"\d", normalized_text)) / max(1, len(normalized_text))
        normalized_tokens = normalize_text(normalized_text)
        if not tables and (
            digit_density > 0.14
            or any(token in normalized_tokens for token in ("tabla", "table", "m2", "metros cuadrados"))
        ):
            _append("possible_table")

        if any(token in normalized_tokens for token in ("firma", "signed", "signature", "representante legal")):
            _append("possible_signature")
        if any(token in normalized_tokens for token in ("sello", "stamp", "timbr", "notario")):
            _append("possible_stamp")

        picture_hints = {str(item.get("kind_hint") or "") for item in pictures}
        if "signature_like" in picture_hints:
            _append("possible_signature")
        if "stamp_like" in picture_hints:
            _append("possible_stamp")

        text_length = len(normalized_text)
        if text_length < 30 and (tables or pictures):
            _append("low_ocr_confidence")
        elif text_length < 80 and pictures and digit_density < 0.02:
            _append("low_ocr_confidence")

        return flags

    @staticmethod
    def _build_visual_summary(
        *,
        text_block_count: int,
        table_count: int,
        picture_count: int,
        visual_flags: list[str],
    ) -> str:
        fragments = [f"Docling text blocks: {text_block_count}."]
        if table_count:
            fragments.append(f"Tables detected: {table_count}.")
        if picture_count:
            fragments.append(f"Visual regions detected: {picture_count}.")
        if "possible_signature" in visual_flags:
            fragments.append("Signature-like region detected.")
        if "possible_stamp" in visual_flags:
            fragments.append("Stamp-like region detected.")
        if "low_ocr_confidence" in visual_flags:
            fragments.append("Low OCR confidence for this page.")
        return compact_whitespace(" ".join(fragments))[:4000]

    @staticmethod
    def _estimate_ocr_confidence(
        *,
        normalized_text: str,
        table_count: int,
        picture_count: int,
    ) -> float:
        text_length = len(normalized_text)
        if text_length >= 600:
            return 0.97
        if text_length >= 250:
            return 0.93
        if text_length >= 120:
            return 0.88
        if text_length >= 40:
            return 0.78
        if table_count or picture_count:
            return 0.46
        return 0.0

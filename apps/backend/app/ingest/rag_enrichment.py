"""RAG enrichment helpers for page and document indexing."""

from __future__ import annotations

import base64
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from apps.backend.app.core.config import Settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.integrations.generative_ai import OCIGenerativeAIService
from apps.backend.app.services.runtime_config_service import ConfigService

FILE_ROLE_VALUES: tuple[str, ...] = (
    "primary",
    "amendment",
    "annex",
    "termination",
    "supporting",
    "other",
)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


def compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_rut(value: str) -> str:
    digits = re.sub(r"[^0-9kK]", "", value or "")
    if len(digits) < 2:
        return ""
    return f"{digits[:-1]}-{digits[-1].upper()}"


def extract_ruts(value: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in re.finditer(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b", value or ""):
        normalized = normalize_rut(match.group(0))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def parse_date_value(value: str | None) -> date | None:
    text = compact_whitespace(str(value or ""))
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    tokens = [fragment.strip() for fragment in normalize_text(text).split() if fragment.strip()]
    if len(tokens) == 4 and tokens[1] == "de" and tokens[3].isdigit():
        month = SPANISH_MONTHS.get(tokens[2])
        if month is not None:
            return date(int(tokens[3]), month, int(tokens[0]))
    if len(tokens) == 5 and tokens[1] == "de" and tokens[3] == "de" and tokens[4].isdigit():
        month = SPANISH_MONTHS.get(tokens[2])
        if month is not None:
            return date(int(tokens[4]), month, int(tokens[0]))
    return None


def _truncate_utf8_bytes(value: str, *, max_bytes: int) -> str:
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= int(max_bytes):
        return str(value or "")
    truncated = encoded[: int(max_bytes)]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


def build_file_group_key(
    *,
    primary_identifier: str | None,
    secondary_identifier: str | None,
    primary_subject: str | None,
    secondary_subject: str | None,
) -> str | None:
    safe_primary = compact_whitespace(str(primary_identifier or "")).upper()
    if safe_primary:
        return _truncate_utf8_bytes(f"primary:{safe_primary}", max_bytes=256)
    safe_secondary = compact_whitespace(str(secondary_identifier or "")).upper()
    safe_primary_subject = compact_whitespace(str(primary_subject or "")).upper()
    safe_secondary_subject = compact_whitespace(str(secondary_subject or "")).upper()
    if safe_secondary and safe_primary_subject and safe_secondary_subject:
        return _truncate_utf8_bytes(
            f"secondary:{safe_secondary}|"
            f"primary_subject:{safe_primary_subject}|"
            f"secondary_subject:{safe_secondary_subject}"
        , max_bytes=256)
    if safe_secondary and safe_primary_subject:
        return _truncate_utf8_bytes(
            f"secondary:{safe_secondary}|primary_subject:{safe_primary_subject}",
            max_bytes=256,
        )
    return None


class PageVisualSummaryOutput(BaseModel):
    visual_summary: str = Field(default="")
    labels: list[str] = Field(default_factory=list)
    contains_picture: bool = False
    contains_signature: bool = False
    contains_table: bool = False
    contains_stamp: bool = False
    contains_handwriting: bool = False


class StructuredEntityOutput(BaseModel):
    entity_role: str = Field(default="")
    entity_type: str = Field(default="organization")
    entity_name: str = Field(default="")
    person_name: str = Field(default="")
    identifier_value: str = Field(default="")
    has_visible_signature: bool = False


class StructuredAttributeOutput(BaseModel):
    attribute_key: str = Field(default="")
    text_value: str = Field(default="")
    number_value: float | None = None
    date_value: str = Field(default="")
    bool_value: bool | None = None


class StructuredLinkOutput(BaseModel):
    link_type: str = Field(default="")
    source_label: str = Field(default="")
    target_label: str = Field(default="")
    link_key: str = Field(default="")


class StructuredDocumentInsightOutput(BaseModel):
    group_type: str = Field(default="generic")
    file_role: str = Field(default="other")
    primary_identifier: str = Field(default="")
    secondary_identifier: str = Field(default="")
    primary_subject: str = Field(default="")
    secondary_subject: str = Field(default="")
    signed_at: str = Field(default="")
    effective_from: str = Field(default="")
    effective_to: str = Field(default="")
    summary: str = Field(default="")
    entities: list[StructuredEntityOutput] = Field(default_factory=list)
    attributes: list[StructuredAttributeOutput] = Field(default_factory=list)
    links: list[StructuredLinkOutput] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


@dataclass(slots=True)
class PageRAGEnrichment:
    visual_summary: str
    layout_json: str
    search_text: str
    visual_flags: list[str] = field(default_factory=list)
    text_quality: float = 0.0


@dataclass(slots=True)
class DocumentInsight:
    group_key: str | None
    group_type: str
    file_role: str
    primary_identifier: str | None
    secondary_identifier: str | None
    primary_subject: str | None
    secondary_subject: str | None
    signed_at: date | None
    effective_from: date | None
    effective_to: date | None
    summary_text: str
    confidence: float | None
    metadata_json: str
    entities: list[dict[str, Any]] = field(default_factory=list)
    attributes: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)


def build_page_search_text(
    *,
    file_name: str,
    document_code: str | None,
    document_type: str | None,
    page_number: int,
    ocr_text: str,
    visual_summary: str,
    visual_flags: list[str],
) -> str:
    parts = [
        f"file_name: {file_name}",
        f"document_code: {document_code or ''}",
        f"document_type: {document_type or ''}",
        f"page_number: {page_number}",
        f"ocr_text: {compact_whitespace(ocr_text)}",
        f"visual_summary: {compact_whitespace(visual_summary)}",
        f"visual_flags: {' '.join(visual_flags)}",
        f"ruts: {' '.join(extract_ruts(ocr_text))}",
    ]
    return " | ".join(part for part in parts if compact_whitespace(part))


def build_document_search_text(
    *,
    file_name: str,
    document_code: str | None,
    document_type: str | None,
    summary_text: str,
    excerpts: list[str],
    labels: list[str],
    primary_identifier: str | None,
    secondary_identifier: str | None,
) -> str:
    parts = [
        f"file_name: {file_name}",
        f"document_code: {document_code or ''}",
        f"document_type: {document_type or ''}",
        f"primary_identifier: {primary_identifier or ''}",
        f"secondary_identifier: {secondary_identifier or ''}",
        f"summary: {compact_whitespace(summary_text)}",
        f"labels: {' | '.join(compact_whitespace(label) for label in labels if compact_whitespace(label))}",
        f"excerpts: {' '.join(compact_whitespace(text) for text in excerpts if compact_whitespace(text))}",
    ]
    return " | ".join(part for part in parts if compact_whitespace(part))


def _infer_file_role(file_name: str, excerpts: str) -> str:
    normalized = normalize_text(f"{file_name}\n{excerpts}")
    if any(token in normalized for token in ("termination", "terminacion", "rescission", "termino anticipado")):
        return "termination"
    if any(token in normalized for token in ("amendment", "modificacion", "modificatorio", "modifica")):
        return "amendment"
    if any(token in normalized for token in ("annex", "anexo")):
        return "annex"
    if any(token in normalized for token in ("contract", "agreement", "lease", "contrato", "arrendamiento")):
        return "primary"
    return "other"


def _extract_primary_identifier(excerpts: str, default_value: str | None = None) -> str:
    patterns = (
        r"(?:id\s+de\s+contrato|contract\s+id|identifier|codigo|code|folio|expediente)\s*[:\-]?\s*([A-Z0-9./_-]{3,})",
        r"\bID\s*[:\-]?\s*([A-Z0-9./_-]{3,})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, excerpts, flags=re.IGNORECASE)
        if match:
            return compact_whitespace(match.group(1)).upper()[:128]
    return compact_whitespace(str(default_value or "")).upper()[:128]


def _extract_secondary_identifier(excerpts: str, default_value: str | None = None) -> str:
    patterns = (
        r"(?:sitio|site|ubicacion|location)\s*(?:id)?\s*[:\-]?\s*([A-Z0-9./_-]{2,})",
        r"\bRM\d{2,}\b",
    )
    for pattern in patterns:
        match = re.search(pattern, excerpts, flags=re.IGNORECASE)
        if match:
            matched_value = match.group(1) if match.lastindex else match.group(0)
            return compact_whitespace(matched_value).upper()[:128]
    return compact_whitespace(str(default_value or "")).upper()[:128]


def _extract_entity_name(excerpts: str, *, preferred_tokens: tuple[str, ...]) -> str:
    text = compact_whitespace(excerpts)
    for token in preferred_tokens:
        match = re.search(
            rf"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-z0-9&.,\-\s]{{3,120}}{re.escape(token)}[A-ZÁÉÍÓÚÑa-z0-9&.,\-\s]{{0,40}})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return compact_whitespace(match.group(1))[:512]
    return ""


def _extract_signed_at(excerpts: str) -> date | None:
    patterns = (
        r"(?:suscrito|firmado|otorgado|signed).{0,40}?(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+(?:de\s+)?\d{4})",
        r"(?:fecha\s+de\s+firma|signature\s+date).{0,20}?(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, excerpts, flags=re.IGNORECASE)
        if match:
            return parse_date_value(match.group(1))
    return None


def _extract_effective_to(excerpts: str) -> date | None:
    patterns = (
        r"(?:vigencia|plazo|validity|term).{0,60}?(?:hasta|al|until)\s+(\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+(?:de\s+)?\d{4})",
        r"(?:vigencia|plazo|validity|term).{0,60}?(?:hasta|al|until)\s+(\d{1,2}[/-]\d{1,2}[/-]\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, excerpts, flags=re.IGNORECASE)
        if match:
            return parse_date_value(match.group(1))
    return None


def _extract_notice_period_days(excerpts: str) -> int | None:
    match = re.search(
        r"(?:aviso|carta|notificacion|notification).{0,80}?(\d{1,3})\s+dias",
        normalize_text(excerpts),
    )
    return int(match.group(1)) if match else None


def _extract_area_value(excerpts: str) -> float | None:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*m(?:etros?)?\s*(?:2|cuadrados)", normalize_text(excerpts))
    if not match:
        return None
    return float(match.group(1).replace(".", "").replace(",", "."))


def _extract_clause_snippet(excerpts: str, clause_term: str, *, max_chars: int = 280) -> str:
    match = re.search(rf"(.{{0,80}}{clause_term}.{{0,180}})", excerpts or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return compact_whitespace(match.group(1))[:max_chars]


def _infer_payment_method(excerpts: str) -> str:
    normalized = normalize_text(excerpts)
    if "transferencia" in normalized:
        return "transfer"
    if "deposito" in normalized or "deposit" in normalized:
        return "deposit"
    if "vale vista" in normalized:
        return "cashier_check"
    if "cheque" in normalized or "check" in normalized:
        return "check"
    if "efectivo" in normalized or "cash" in normalized:
        return "cash"
    return ""


class PageVisualEnricher:
    def __init__(self, *, settings: Settings, db_manager: DatabaseManager | None = None) -> None:
        self.settings = settings
        self.config_service = ConfigService(db_manager) if db_manager is not None else None
        self.provider = OCIGenerativeAIService(settings=settings, config_service=self.config_service)

    def _visual_enrichment_enabled(self) -> bool:
        if self.config_service is None:
            return False
        try:
            value = str(
                self.config_service.get_value("rag.ingest.visual_enrichment_enabled", "false")
            ).strip().lower()
        except Exception:
            return False
        return value in {"1", "true", "yes", "on"}

    def enrich_page(
        self,
        *,
        image_path: Path,
        file_name: str,
        document_code: str | None,
        document_type: str | None,
        page_number: int,
        total_pages: int,
        ocr_text: str,
        ocr_confidence: float,
        base_visual_summary: str = "",
        base_layout_payload: dict[str, Any] | None = None,
        base_visual_flags: list[str] | None = None,
    ) -> PageRAGEnrichment:
        flags = self._detect_visual_flags(
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            page_number=page_number,
            total_pages=total_pages,
            base_flags=base_visual_flags,
        )
        visual_summary = compact_whitespace(str(base_visual_summary or ""))[:4000]
        layout_payload: dict[str, Any] = dict(base_layout_payload or {})
        existing_labels = [
            compact_whitespace(str(item))
            for item in list(layout_payload.get("labels") or [])
            if compact_whitespace(str(item))
        ]
        layout_payload["labels"] = list(dict.fromkeys(existing_labels))
        for token in (
            "contains_picture",
            "contains_signature",
            "contains_table",
            "contains_stamp",
            "contains_handwriting",
        ):
            if bool(layout_payload.get(token)) and token not in flags:
                flags.append(token)
        if self._visual_enrichment_enabled() and self._should_call_vision(flags=flags):
            if not self.provider.is_available():
                raise RuntimeError(
                    f"Visual enrichment requested for page {page_number}, but the OCI generative provider is not available."
                )
            parsed = self.provider.invoke_multimodal_structured(
                schema_model=PageVisualSummaryOutput,
                prompt=(
                    "Write a short page summary optimized for retrieval.\n"
                    "Describe visible layout, tables, signatures, stamps, headers, and spatial clues.\n"
                    "Do not copy the OCR text.\n\n"
                    f"File name: {file_name}\n"
                    f"Document code: {document_code or 'N/A'}\n"
                    f"Document type: {document_type or 'N/A'}\n"
                    f"Page: {page_number}/{total_pages}\n"
                    f"OCR excerpt: {compact_whitespace(ocr_text)[:1200] or 'No reliable OCR text.'}\n"
                ),
                image_data_uri=self._build_image_data_uri(image_path),
            )
            provider_visual_summary = compact_whitespace(str(parsed.get("visual_summary") or ""))[:4000]
            if provider_visual_summary:
                visual_summary = compact_whitespace(
                    " ".join(fragment for fragment in (visual_summary, provider_visual_summary) if fragment)
                )[:4000]
            layout_payload["labels"] = list(
                dict.fromkeys(
                    list(layout_payload.get("labels") or [])
                    + [
                        compact_whitespace(str(item))
                        for item in list(parsed.get("labels") or [])
                        if compact_whitespace(str(item))
                    ]
                )
            )
            for token in (
                "contains_picture",
                "contains_signature",
                "contains_table",
                "contains_stamp",
                "contains_handwriting",
            ):
                layout_payload[token] = bool(layout_payload.get(token) or parsed.get(token) or False)
            for token, enabled in (
                ("contains_picture", layout_payload["contains_picture"]),
                ("contains_signature", layout_payload["contains_signature"]),
                ("contains_table", layout_payload["contains_table"]),
                ("contains_stamp", layout_payload["contains_stamp"]),
                ("contains_handwriting", layout_payload["contains_handwriting"]),
            ):
                if enabled and token not in flags:
                    flags.append(token)
        elif not layout_payload:
            layout_payload = {"labels": list(flags)}
        text_quality = self._estimate_text_quality(ocr_text=ocr_text, ocr_confidence=ocr_confidence)
        return PageRAGEnrichment(
            visual_summary=visual_summary,
            layout_json=json.dumps(layout_payload, ensure_ascii=False),
            search_text=build_page_search_text(
                file_name=file_name,
                document_code=document_code,
                document_type=document_type,
                page_number=page_number,
                ocr_text=ocr_text,
                visual_summary=visual_summary,
                visual_flags=flags,
            ),
            visual_flags=flags,
            text_quality=text_quality,
        )

    @staticmethod
    def _should_call_vision(*, flags: list[str]) -> bool:
        interesting = {
            "low_ocr_confidence",
            "contains_picture",
            "possible_table",
            "possible_signature",
            "possible_stamp",
            "contains_signature",
            "contains_table",
            "contains_stamp",
            "contains_handwriting",
        }
        return any(flag in interesting for flag in flags)

    @staticmethod
    def _detect_visual_flags(
        *,
        ocr_text: str,
        ocr_confidence: float,
        page_number: int,
        total_pages: int,
        base_flags: list[str] | None = None,
    ) -> list[str]:
        flags: list[str] = []

        def _append(flag: str) -> None:
            if flag not in flags:
                flags.append(flag)

        for flag in list(base_flags or []):
            normalized_flag = compact_whitespace(str(flag))
            if normalized_flag:
                _append(normalized_flag)

        normalized = normalize_text(ocr_text)
        if ocr_confidence < 0.78:
            _append("low_ocr_confidence")
        if page_number == 1:
            _append("cover_page")
        if page_number == total_pages:
            _append("closing_page")
        digit_density = len(re.findall(r"\d", ocr_text or "")) / max(1, len(ocr_text or ""))
        if digit_density > 0.18 or any(token in normalized for token in ("tabla", "table", "m2", "metros cuadrados")):
            _append("possible_table")
        if any(token in normalized for token in ("firma", "signature", "representante legal", "signed")):
            _append("possible_signature")
        if any(token in normalized for token in ("sello", "stamp")):
            _append("possible_stamp")
        return flags

    @staticmethod
    def _estimate_text_quality(*, ocr_text: str, ocr_confidence: float) -> float:
        length_factor = min(1.0, len(compact_whitespace(ocr_text)) / 1200.0)
        return round(max(0.0, min(1.0, (ocr_confidence * 0.7) + (length_factor * 0.3))), 4)

    @staticmethod
    def _build_image_data_uri(image_path: Path) -> str:
        payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{payload}"


class DocumentFactExtractor:
    def __init__(self, *, settings: Settings, db_manager: DatabaseManager | None = None) -> None:
        self.settings = settings
        self.config_service = ConfigService(db_manager) if db_manager is not None else None
        self.provider = OCIGenerativeAIService(settings=settings, config_service=self.config_service)

    def _structured_facts_enabled(self) -> bool:
        if self.config_service is None:
            return False
        try:
            value = str(
                self.config_service.get_value("rag.ingest.structured_facts_enabled", "false")
            ).strip().lower()
        except Exception:
            return False
        return value in {"1", "true", "yes", "on"}

    def extract(
        self,
        *,
        file_name: str,
        document_code: str | None,
        document_type: str | None,
        page_rows: list[dict[str, Any]],
    ) -> DocumentInsight:
        excerpts = self._build_excerpts(page_rows)
        heuristic = self._extract_heuristically(
            file_name=file_name,
            document_code=document_code,
            document_type=document_type,
            excerpts=excerpts,
            page_rows=page_rows,
        )
        if not self._structured_facts_enabled() or not self.provider.is_available():
            return heuristic
        prompt = (
            "Extract a generic document profile using only the supplied evidence.\n"
            "Do not invent values. Leave fields empty when evidence is insufficient.\n"
            "Use stable generic keys for attributes and descriptive entity roles.\n\n"
            f"File name: {file_name}\n"
            f"Document code: {document_code or 'N/A'}\n"
            f"Document type: {document_type or 'N/A'}\n\n"
            f"Evidence:\n{excerpts}\n"
        )
        try:
            parsed = self.provider.invoke_structured(
                schema_model=StructuredDocumentInsightOutput,
                prompt=prompt,
            )
            return self._merge_structured_over_heuristic(heuristic=heuristic, parsed=parsed)
        except Exception:
            return heuristic

    @staticmethod
    def _build_excerpts(page_rows: list[dict[str, Any]]) -> str:
        sorted_rows = sorted(page_rows, key=lambda item: int(item.get("file_pages_number") or 0))
        selected = sorted_rows[:3]
        if len(sorted_rows) > 3:
            selected.extend(sorted_rows[-2:])
        lines: list[str] = []
        for row in selected:
            page_number = int(row.get("file_pages_number") or 0)
            ocr_text = compact_whitespace(str(row.get("file_pages_ocr_text") or ""))[:1800]
            visual_summary = compact_whitespace(str(row.get("file_pages_visual_summary") or ""))[:400]
            lines.append(f"[Page {page_number}] OCR={ocr_text}")
            if visual_summary:
                lines.append(f"[Page {page_number}] VISUAL={visual_summary}")
        return "\n".join(lines).strip()

    @staticmethod
    def _attribute_row(
        attribute_key: str,
        *,
        text_value: str = "",
        number_value: float | None = None,
        date_value: date | None = None,
        bool_value: bool | None = None,
        confidence: float = 0.5,
        source_type: str = "ocr",
    ) -> dict[str, Any]:
        return {
            "page_id": None,
            "attribute_key": attribute_key,
            "attribute_value_text": compact_whitespace(text_value)[:4000],
            "attribute_value_number": number_value,
            "attribute_value_date": date_value,
            "attribute_value_bool": 1 if bool_value is True else (0 if bool_value is False else None),
            "source_type": source_type,
            "metadata_json": json.dumps({"source": source_type}, ensure_ascii=False),
            "confidence": confidence,
        }

    def _extract_heuristically(
        self,
        *,
        file_name: str,
        document_code: str | None,
        document_type: str | None,
        excerpts: str,
        page_rows: list[dict[str, Any]],
    ) -> DocumentInsight:
        primary_identifier = _extract_primary_identifier(excerpts, default_value=document_code) or None
        secondary_identifier = _extract_secondary_identifier(excerpts, default_value=document_code) or None
        primary_subject = _extract_entity_name(
            excerpts,
            preferred_tokens=("entel", "telecomunicaciones", "empresa", "sociedad", "s.a.", "sa", "transam"),
        ) or None
        secondary_subject = _extract_entity_name(
            excerpts,
            preferred_tokens=("limitada", "ltda", "spa", "propietario", "arrendador", "s.a.", "sa"),
        ) or None
        signed_at = _extract_signed_at(excerpts)
        effective_to = _extract_effective_to(excerpts)
        effective_from = signed_at
        group_type = compact_whitespace(str(document_type or "generic")).lower() or "generic"
        file_role = _infer_file_role(file_name, excerpts)

        entities: list[dict[str, Any]] = []
        if primary_subject:
            entities.append(
                {
                    "page_id": None,
                    "entity_role": "primary_subject",
                    "entity_type": "organization",
                    "entity_name": primary_subject,
                    "person_name": "",
                    "identifier_value": "",
                    "has_visible_signature": 0,
                    "bbox_json": "{}",
                    "metadata_json": json.dumps({"source": "heuristic"}, ensure_ascii=False),
                    "confidence": 0.65,
                }
            )
        ruts = extract_ruts(excerpts)
        if secondary_subject or ruts:
            entities.append(
                {
                    "page_id": None,
                    "entity_role": "secondary_subject",
                    "entity_type": "organization",
                    "entity_name": secondary_subject or "",
                    "person_name": "",
                    "identifier_value": ruts[0] if ruts else "",
                    "has_visible_signature": 0,
                    "bbox_json": "{}",
                    "metadata_json": json.dumps({"source": "heuristic"}, ensure_ascii=False),
                    "confidence": 0.55,
                }
            )
        signature_pages = [
            row
            for row in page_rows
            if "possible_signature" in str(row.get("file_pages_visual_flags") or "")
        ]
        if primary_subject:
            entities.append(
                {
                    "page_id": int(signature_pages[-1].get("file_pages_id") or 0) if signature_pages else None,
                    "entity_role": "signatory",
                    "entity_type": "person",
                    "entity_name": primary_subject,
                    "person_name": "",
                    "identifier_value": "",
                    "has_visible_signature": 1 if signature_pages else 0,
                    "bbox_json": "{}",
                    "metadata_json": json.dumps({"source": "heuristic"}, ensure_ascii=False),
                    "confidence": 0.45,
                }
            )

        attributes: list[dict[str, Any]] = []
        payment_method = _infer_payment_method(excerpts)
        late_penalty = _extract_clause_snippet(excerpts, "mora|atraso|penal")
        assignment = _extract_clause_snippet(excerpts, "cesion|cesión|assignment")
        access_modification = _extract_clause_snippet(excerpts, "acceso al terreno|acceso|access")
        automatic_renewal = "renovacion automatica" in normalize_text(excerpts) or "automatic renewal" in normalize_text(excerpts)
        early_termination = "termino anticipado" in normalize_text(excerpts) and "propietar" in normalize_text(excerpts)
        notice_days = _extract_notice_period_days(excerpts)
        area_value = _extract_area_value(excerpts)
        if payment_method:
            attributes.append(self._attribute_row("payment_method", text_value=payment_method, confidence=0.70))
        if late_penalty:
            attributes.append(self._attribute_row("late_payment_penalty", text_value=late_penalty, confidence=0.55))
        if automatic_renewal:
            attributes.append(self._attribute_row("automatic_renewal", text_value="automatic renewal detected", bool_value=True, confidence=0.60))
        if notice_days is not None:
            attributes.append(self._attribute_row("notice_period_days", text_value=f"{notice_days} days", number_value=float(notice_days), confidence=0.60))
        if early_termination:
            attributes.append(self._attribute_row("early_termination_by_subject", text_value="owner early termination detected", bool_value=True, confidence=0.55))
        if assignment:
            attributes.append(self._attribute_row("assignment_to_third_parties", text_value=assignment, confidence=0.55))
        if area_value is not None:
            attributes.append(self._attribute_row("leased_area_m2", text_value=f"{area_value}", number_value=float(area_value), confidence=0.60))
        if access_modification:
            attributes.append(self._attribute_row("access_modification", text_value=access_modification, confidence=0.50))
        if effective_from:
            attributes.append(self._attribute_row("effective_from", text_value=effective_from.isoformat(), date_value=effective_from, confidence=0.65))
        if effective_to:
            attributes.append(self._attribute_row("effective_to", text_value=effective_to.isoformat(), date_value=effective_to, confidence=0.65))

        links: list[dict[str, Any]] = []
        if secondary_identifier and primary_identifier:
            links.append(
                {
                    "page_id": None,
                    "link_type": "identifier_pair",
                    "source_label": secondary_identifier,
                    "target_label": primary_identifier,
                    "link_key": "secondary_to_primary",
                    "metadata_json": json.dumps({"source": "heuristic"}, ensure_ascii=False),
                    "confidence": 0.60,
                }
            )

        summary_text = compact_whitespace(
            " | ".join(
                [
                    f"group_type={group_type}",
                    f"file_role={file_role}",
                    f"primary_identifier={primary_identifier or ''}",
                    f"secondary_identifier={secondary_identifier or ''}",
                    f"primary_subject={primary_subject or ''}",
                    f"secondary_subject={secondary_subject or ''}",
                    f"signed_at={signed_at.isoformat() if signed_at else ''}",
                    f"effective_to={effective_to.isoformat() if effective_to else ''}",
                ]
            )
        )[:4000]
        return DocumentInsight(
            group_key=build_file_group_key(
                primary_identifier=primary_identifier,
                secondary_identifier=secondary_identifier,
                primary_subject=primary_subject,
                secondary_subject=secondary_subject,
            ),
            group_type=group_type,
            file_role=file_role,
            primary_identifier=primary_identifier,
            secondary_identifier=secondary_identifier,
            primary_subject=primary_subject,
            secondary_subject=secondary_subject,
            signed_at=signed_at,
            effective_from=effective_from,
            effective_to=effective_to,
            summary_text=summary_text,
            confidence=0.60,
            metadata_json=json.dumps(
                {
                    "document_code": document_code,
                    "document_type": document_type,
                    "extraction_mode": "heuristic",
                },
                ensure_ascii=False,
            ),
            entities=entities,
            attributes=attributes,
            links=links,
        )

    def _merge_structured_over_heuristic(
        self,
        *,
        heuristic: DocumentInsight,
        parsed: dict[str, Any],
    ) -> DocumentInsight:
        primary_identifier = compact_whitespace(str(parsed.get("primary_identifier") or "")) or heuristic.primary_identifier
        secondary_identifier = compact_whitespace(str(parsed.get("secondary_identifier") or "")) or heuristic.secondary_identifier
        primary_subject = compact_whitespace(str(parsed.get("primary_subject") or "")) or heuristic.primary_subject
        secondary_subject = compact_whitespace(str(parsed.get("secondary_subject") or "")) or heuristic.secondary_subject
        signed_at = parse_date_value(str(parsed.get("signed_at") or "")) or heuristic.signed_at
        effective_from = parse_date_value(str(parsed.get("effective_from") or "")) or heuristic.effective_from
        effective_to = parse_date_value(str(parsed.get("effective_to") or "")) or heuristic.effective_to
        group_type = compact_whitespace(str(parsed.get("group_type") or "")) or heuristic.group_type or "generic"
        file_role = compact_whitespace(str(parsed.get("file_role") or "")) or heuristic.file_role
        if file_role not in FILE_ROLE_VALUES:
            file_role = heuristic.file_role

        entities = heuristic.entities
        if parsed.get("entities"):
            entities = [
                {
                    "page_id": None,
                    "entity_role": compact_whitespace(str(item.get("entity_role") or ""))[:64],
                    "entity_type": compact_whitespace(str(item.get("entity_type") or ""))[:64] or "organization",
                    "entity_name": compact_whitespace(str(item.get("entity_name") or ""))[:512],
                    "person_name": compact_whitespace(str(item.get("person_name") or ""))[:512],
                    "identifier_value": compact_whitespace(str(item.get("identifier_value") or ""))[:128],
                    "has_visible_signature": 1 if bool(item.get("has_visible_signature") or False) else 0,
                    "bbox_json": "{}",
                    "metadata_json": json.dumps({"source": "oci_structured"}, ensure_ascii=False),
                    "confidence": float(parsed.get("confidence") or 0.70),
                }
                for item in list(parsed.get("entities") or [])
                if compact_whitespace(str(item.get("entity_role") or ""))
            ]
        attributes = heuristic.attributes
        if parsed.get("attributes"):
            attributes = [
                self._attribute_row(
                    compact_whitespace(str(item.get("attribute_key") or ""))[:128],
                    text_value=compact_whitespace(str(item.get("text_value") or ""))[:4000],
                    number_value=float(item["number_value"]) if item.get("number_value") is not None else None,
                    date_value=parse_date_value(str(item.get("date_value") or "")),
                    bool_value=item.get("bool_value"),
                    confidence=float(parsed.get("confidence") or 0.70),
                    source_type="oci_structured",
                )
                for item in list(parsed.get("attributes") or [])
                if compact_whitespace(str(item.get("attribute_key") or ""))
            ]
        links = heuristic.links
        if parsed.get("links"):
            links = [
                {
                    "page_id": None,
                    "link_type": compact_whitespace(str(item.get("link_type") or ""))[:64],
                    "source_label": compact_whitespace(str(item.get("source_label") or ""))[:512],
                    "target_label": compact_whitespace(str(item.get("target_label") or ""))[:512],
                    "link_key": compact_whitespace(str(item.get("link_key") or ""))[:128],
                    "metadata_json": json.dumps({"source": "oci_structured"}, ensure_ascii=False),
                    "confidence": float(parsed.get("confidence") or 0.70),
                }
                for item in list(parsed.get("links") or [])
                if compact_whitespace(str(item.get("link_type") or ""))
            ]
        return DocumentInsight(
            group_key=build_file_group_key(
                primary_identifier=primary_identifier,
                secondary_identifier=secondary_identifier,
                primary_subject=primary_subject,
                secondary_subject=secondary_subject,
            ) or heuristic.group_key,
            group_type=group_type,
            file_role=file_role,
            primary_identifier=primary_identifier or None,
            secondary_identifier=secondary_identifier or None,
            primary_subject=primary_subject or None,
            secondary_subject=secondary_subject or None,
            signed_at=signed_at,
            effective_from=effective_from,
            effective_to=effective_to,
            summary_text=(compact_whitespace(str(parsed.get("summary") or "")) or heuristic.summary_text)[:4000],
            confidence=float(parsed.get("confidence") or heuristic.confidence or 0.60),
            metadata_json=json.dumps(
                {"document_type": group_type, "extraction_mode": "oci_structured"},
                ensure_ascii=False,
            ),
            entities=entities,
            attributes=attributes,
            links=links,
        )

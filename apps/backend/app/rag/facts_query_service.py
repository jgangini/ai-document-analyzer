"""Structured fact resolution for routing and deterministic answers."""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
import json
import re
import unicodedata

from apps.backend.app.ingest.rag_enrichment import parse_date_value
from apps.backend.app.repositories.document_facts_repository import DocumentFactsRepository
from apps.backend.app.repositories.repository_utils import code_to_status
from apps.backend.app.rag.display_text import repair_document_file_name
from apps.backend.app.rag.scope_resolver import ScopeResolutionError, extract_candidate_archive_slugs_from_question
from apps.backend.app.services.metadata_upload_service import canonicalize_file_key

_METADATA_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
_METADATA_STOPWORDS = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "lo",
    "los",
    "metadata",
    "para",
    "por",
    "que",
    "se",
    "su",
    "the",
    "un",
    "una",
    "uno",
    "y",
}
_METADATA_ANSWERABILITY_IGNORE_TOKENS = {
    "actual",
    "archivo",
    "archivos",
    "asociado",
    "asociados",
    "campo",
    "campos",
    "comparacion",
    "comparar",
    "compara",
    "consulta",
    "cual",
    "cuales",
    "cuando",
    "cuanto",
    "cuantos",
    "cuanta",
    "cuantas",
    "del",
    "detalle",
    "diferencia",
    "diferencias",
    "dime",
    "donde",
    "el",
    "en",
    "es",
    "existe",
    "existen",
    "file",
    "files",
    "filtra",
    "folio",
    "folios",
    "hay",
    "id",
    "indica",
    "la",
    "las",
    "lista",
    "listame",
    "lo",
    "los",
    "metadata",
    "metadatos",
    "muestra",
    "muestrame",
    "pdf",
    "pdfs",
    "por",
    "para",
    "que",
    "quien",
    "quienes",
    "confirma",
    "confirmar",
    "reportada",
    "reportadas",
    "reportado",
    "reportados",
    "revisa",
    "segun",
    "se",
    "si",
    "son",
    "su",
    "tiene",
    "tienen",
    "usa",
    "usando",
    "valida",
    "validacion",
    "validar",
    "valor",
    "valores",
    "versus",
    "y",
}
_METADATA_OPEN_ANSWER_TOKENS = {
    "analisis",
    "analiza",
    "analizar",
    "causa",
    "causas",
    "conclusion",
    "conclusiones",
    "contexto",
    "desarrolla",
    "diagnostica",
    "diagnostico",
    "explica",
    "explicar",
    "fundamenta",
    "fundamento",
    "impacto",
    "impactos",
    "interpreta",
    "interpretacion",
    "justifica",
    "justificacion",
    "motivo",
    "motivos",
    "profundiza",
    "razon",
    "razones",
    "recomienda",
    "recomendacion",
    "relaciona",
    "relacion",
    "riesgo",
    "riesgos",
    "sintesis",
    "sintetiza",
}
_BOOLEAN_TRUE = {"1", "si", "s\u00ed", "true", "yes"}
_BOOLEAN_FALSE = {"0", "false", "no"}
_METADATA_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "nombre de propietario principal": (
        "propietario principal",
        "dueno principal",
        "arrendador principal",
        "nombre del propietario",
        "quien es el propietario",
    ),
    "rut propietario principal": (
        "rut del propietario principal",
        "rut propietario principal",
        "rut del propietario",
        "rut propietario",
    ),
    "nombre beneficiario": (
        "beneficiario actual",
        "beneficiario",
        "arrendatario actual",
        "quien recibe la renta",
        "recibe la renta",
        "quien recibe el pago",
    ),
    "rut beneficiario del contrato": (
        "rut del beneficiario",
        "rut beneficiario",
        "rut de quien recibe la renta",
        "rut de quien recibe el pago",
    ),
    "id": (
        "id de contrato",
        "id contrato",
        "numero de contrato",
    ),
    "codigo de sitio": (
        "codigo de sitio",
        "sitio",
        "codigo sitio",
    ),
    "figura legal": (
        "sociedad entel",
        "entel pcs",
        "entel s.a",
        "sociedad firmante",
        "figura legal",
    ),
    "estado contrato": (
        "estado del contrato",
        "contrato vigente",
        "sigue vigente",
        "sigue activo",
        "contrato activo",
        "vigencia del contrato",
    ),
    "forma de pago": (
        "medio de pago",
        "modo de pago",
    ),
    "pago anticipado": (
        "pago adelantado",
        "prepago",
    ),
    "periodo de pago": (
        "periodicidad de pago",
        "cada cuanto se paga",
    ),
    "renta o precio vigente": (
        "renta vigente",
        "precio vigente",
        "valor vigente",
        "renta",
    ),
    "metros cuadrados arrendados": (
        "superficie arrendada",
        "m2 arrendados",
        "metros arrendados",
    ),
    "clausula de acceso sitio": (
        "acceso al sitio",
        "clausula de acceso",
        "acceso al terreno",
    ),
    "cesion a terceros": (
        "cesion a terceros",
        "cede a terceros",
        "ceder a terceros",
        "libre cesion",
    ),
    "fecha de firma primer contrato": (
        "primer contrato",
        "fecha del primer contrato",
    ),
    "fecha firma ultimo contrato": (
        "ultimo contrato",
        "fecha del ultimo contrato",
        "ultima firma",
    ),
    "fecha de termino del contrato": (
        "fecha de termino",
        "termino del contrato",
        "vencimiento del contrato",
        "fecha de vencimiento",
    ),
    "fecha de aviso de termino del contrato": (
        "aviso de termino",
        "carta de termino",
        "aviso previo de termino",
    ),
}


@dataclass(slots=True)
class FactResolution:
    narrowed_file_ids: list[int]
    fact_context_text: str
    answer_override: str | None = None
    facts_used_count: int = 0
    file_group_ids: list[int] = field(default_factory=list)
    confidence_notes: list[str] = field(default_factory=list)
    metadata_phase_used: bool = False
    resolved_archive_slugs: list[str] = field(default_factory=list)
    resolved_metadata_fields: list[str] = field(default_factory=list)
    metadata_only_reason: str = ""
    document_phase_required: bool = False
    answerability_route: str = ""


@dataclass(slots=True)
class ArchiveMetadataEntry:
    file_id: int
    archive_slug: str
    fields: dict[str, object]


@dataclass(slots=True)
class MetadataFilterMatch:
    field_header: str
    field_base: str
    match_value: str
    score: int


@dataclass(slots=True)
class MetadataSchemaField:
    header: str
    base: str
    tokens: tuple[str, ...]
    display_values: tuple[str, ...]


class QuestionFactResolver:
    def __init__(
        self,
        repository: DocumentFactsRepository,
        *,
        file_repository=None,
    ) -> None:
        self.repository = repository
        self.file_repository = file_repository

    def resolve(
        self,
        *,
        question_class: str,
        question: str,
        user_id: int,
        file_ids: list[int],
        metadata_mode: str = "auto",
        archive_slugs: list[str] | None = None,
        metadata_fields: list[str] | None = None,
        reference_date: date | None = None,
    ) -> FactResolution:
        safe_archive_slugs = [
            canonicalize_file_key(str(value or "").strip())
            for value in list(archive_slugs or [])
            if canonicalize_file_key(str(value or "").strip())
        ]
        safe_metadata_mode = (
            "metadata_first"
            if str(metadata_mode or "").strip().lower() == "metadata_first"
            else "auto"
        )
        metadata_rows = self._load_archive_metadata_rows(
            user_id=user_id,
            file_ids=file_ids,
        )
        metadata_rows = self._filter_metadata_rows_for_explicit_archive_scope(
            question=question,
            metadata_rows=metadata_rows,
            archive_slugs=safe_archive_slugs,
        )
        metadata_requested = bool(safe_metadata_mode == "metadata_first" or list(metadata_fields or []))
        if metadata_requested and not metadata_rows:
            raise ScopeResolutionError(
                "No metadata is available for the current scope.",
                status_code=404,
            )
        resolved_metadata_fields = self._resolve_structured_metadata_fields(
            metadata_rows=metadata_rows,
            metadata_fields=metadata_fields,
        )
        inferred_metadata_fields = (
            list(resolved_metadata_fields)
            if resolved_metadata_fields
            else (
                self._extract_requested_metadata_fields(question=question, metadata_rows=metadata_rows)
                if metadata_rows
                else []
            )
        )
        metadata_file_ids = [row.file_id for row in metadata_rows if int(row.file_id) > 0]
        effective_metadata_file_ids = metadata_file_ids or list(file_ids or [])

        if question_class == "inventory" or self._question_requests_document_inventory_listing(question):
            return self._resolve_inventory(
                question=question,
                user_id=user_id,
                file_ids=file_ids,
            )
        if metadata_rows and (
            question_class == "metadata_comparison"
            or metadata_requested
            or bool(inferred_metadata_fields)
        ):
            return self._resolve_metadata_comparison(
                question_class=question_class,
                question=question,
                user_id=user_id,
                file_ids=list(file_ids or effective_metadata_file_ids),
                archive_slugs=safe_archive_slugs,
                metadata_rows=metadata_rows,
                requested_fields=inferred_metadata_fields,
                explicit_metadata_fields=bool(resolved_metadata_fields),
                metadata_mode=safe_metadata_mode,
                reference_date=reference_date or self._parse_reference_date(question) or datetime.utcnow().date(),
            )
        if question_class == "analytics":
            return self._resolve_analytics(
                question=question,
                user_id=user_id,
                file_ids=effective_metadata_file_ids,
                reference_date=reference_date or datetime.utcnow().date(),
            )
        if question_class == "temporal":
            return self._resolve_temporal(
                question=question,
                user_id=user_id,
                file_ids=effective_metadata_file_ids,
                reference_date=reference_date or self._parse_reference_date(question) or datetime.utcnow().date(),
            )
        if question_class in {"versioned", "exhaustive_synthesis"}:
            group_ids = self.repository.list_group_ids_for_file_ids(
                user_id=int(user_id),
                file_ids=file_ids,
                include_shared=True,
            )
            narrowed_file_ids = self.repository.list_file_ids_for_group_ids(
                user_id=int(user_id),
                group_ids=group_ids,
                current_only=(question_class == "versioned"),
                include_shared=True,
            )
            requested_file_ids: list[int] = []
            requested_seen: set[int] = set()
            for raw_file_id in list(file_ids or []):
                file_id = int(raw_file_id)
                if file_id <= 0 or file_id in requested_seen:
                    continue
                requested_seen.add(file_id)
                requested_file_ids.append(file_id)
            if requested_file_ids:
                allowed_file_ids = set(requested_file_ids)
                bounded_file_ids = [
                    int(file_id)
                    for file_id in list(narrowed_file_ids or [])
                    if int(file_id) in allowed_file_ids
                ]
                narrowed_file_ids = bounded_file_ids or requested_file_ids
            resolution = FactResolution(
                narrowed_file_ids=narrowed_file_ids,
                fact_context_text=(
                    f"Resolved file groups: {', '.join(str(item) for item in group_ids)}. "
                    f"Narrowed files: {', '.join(str(item) for item in narrowed_file_ids[:40])}."
                    if narrowed_file_ids
                    else ""
                ),
                facts_used_count=len(narrowed_file_ids),
                file_group_ids=group_ids,
                confidence_notes=(
                    ["Facts resolver narrowed the scope using file grouping."]
                    if narrowed_file_ids
                    else []
                ),
            )
            return self._append_archive_metadata_context(
                resolution=resolution,
                user_id=user_id,
                file_ids=narrowed_file_ids or file_ids,
            )
        resolution = FactResolution(narrowed_file_ids=[], fact_context_text="", facts_used_count=0)
        return self._append_archive_metadata_context(
            resolution=resolution,
            user_id=user_id,
            file_ids=file_ids,
        )

    def _resolve_inventory(
        self,
        *,
        question: str,
        user_id: int,
        file_ids: list[int],
    ) -> FactResolution:
        if self.file_repository is None:
            return FactResolution(
                narrowed_file_ids=[],
                fact_context_text="",
                answer_override="No se pudo resolver el inventario documental porque el repositorio de archivos no esta disponible.",
                facts_used_count=0,
                confidence_notes=["Inventory resolver could not access the file repository."],
            )

        list_files_for_user = getattr(self.file_repository, "list_files_for_user", None)
        if not callable(list_files_for_user):
            return FactResolution(
                narrowed_file_ids=[],
                fact_context_text="",
                answer_override="No se pudo resolver el inventario documental porque el repositorio no expone list_files_for_user.",
                facts_used_count=0,
                confidence_notes=["Inventory resolver requires list_files_for_user support."],
            )

        try:
            rows = list(list_files_for_user(user_id=int(user_id), include_shared=True))
        except Exception:
            return FactResolution(
                narrowed_file_ids=[],
                fact_context_text="",
                answer_override="No se pudo consultar el inventario documental del usuario.",
                facts_used_count=0,
                confidence_notes=["Inventory resolver failed while loading the file list."],
            )

        scoped_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        if scoped_file_ids:
            allowed = set(scoped_file_ids)
            rows = [dict(row) for row in rows if int(row.get("file_id") or 0) in allowed]
        else:
            rows = [dict(row) for row in rows]

        rows.sort(
            key=lambda row: (
                str(row.get("archive_slug") or "").lower(),
                str(row.get("file_input_file_name") or "").lower(),
                int(row.get("file_id") or 0),
            )
        )

        if not rows:
            return FactResolution(
                narrowed_file_ids=scoped_file_ids,
                fact_context_text="No se encontraron documentos en el scope solicitado.",
                answer_override="No se encontraron documentos en el scope solicitado.",
                facts_used_count=0,
                confidence_notes=["Inventory resolver returned an empty document list."],
            )

        lines: list[str] = []
        resolved_file_ids: list[int] = []
        for index, row in enumerate(rows, start=1):
            file_id = int(row.get("file_id") or 0)
            if file_id > 0:
                resolved_file_ids.append(file_id)
            archive_slug = str(row.get("archive_slug") or "").strip()
            file_name = repair_document_file_name(row.get("file_input_file_name") or "") or f"file-{file_id}"
            file_code = str(row.get("file_code") or "").strip()
            raw_status = row.get("file_state")
            if isinstance(raw_status, str) and raw_status.strip():
                status = raw_status.strip().lower()
            else:
                status = code_to_status(raw_status)
            page_count = int(row.get("file_page_count") or 0)
            lines.append(
                self._build_inventory_markdown_row(
                    index=index,
                    archive_slug=archive_slug or file_name,
                    file_name=file_name,
                    file_code=file_code,
                    status=status,
                    page_count=page_count,
                )
            )

        archive_slugs = sorted(
            {
                str(row.get("archive_slug") or "").strip()
                for row in rows
                if str(row.get("archive_slug") or "").strip()
            },
            key=str.lower,
        )
        heading = f"Documentos disponibles ({len(lines)}):"
        if self._question_requests_document_inventory_listing(question) and len(archive_slugs) == 1:
            heading = f"Documentos asociados a {archive_slugs[0]} ({len(lines)}):"
        answer_override = self._build_inventory_markdown_answer(lines, heading=heading)
        if self._inventory_request_requires_document_reasoning(question):
            return FactResolution(
                narrowed_file_ids=resolved_file_ids or scoped_file_ids,
                fact_context_text=answer_override,
                facts_used_count=len(lines),
                confidence_notes=[
                    "Inventory rows were resolved first, but the question still requires documentary reasoning."
                ],
                document_phase_required=True,
            )
        return FactResolution(
            narrowed_file_ids=resolved_file_ids or scoped_file_ids,
            fact_context_text=answer_override,
            answer_override=answer_override,
            facts_used_count=len(lines),
            confidence_notes=["Inventory answer resolved directly from the files repository."],
        )

    @staticmethod
    def _escape_markdown_table_cell(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return "-"
        return text.replace("|", "\\|").replace("\n", "<br />")

    @classmethod
    def _build_inventory_markdown_row(
        cls,
        *,
        index: int,
        archive_slug: str,
        file_name: str,
        file_code: str,
        status: str,
        page_count: int,
    ) -> str:
        rendered_values = [
            str(index),
            cls._escape_markdown_table_cell(archive_slug),
            cls._escape_markdown_table_cell(file_name),
            cls._escape_markdown_table_cell(file_code),
            cls._escape_markdown_table_cell(status),
            cls._escape_markdown_table_cell(page_count),
        ]
        return "| " + " | ".join(rendered_values) + " |"

    @classmethod
    def _build_inventory_markdown_answer(cls, rows: list[str], *, heading: str | None = None) -> str:
        table_lines = [
            "| # | Archivo | Documento | Codigo | Estado | Paginas |",
            "| --- | --- | --- | --- | --- | --- |",
            *rows,
        ]
        rendered_heading = str(heading or "").strip() or f"Documentos disponibles ({len(rows)}):"
        return rendered_heading + "\n\n" + "\n".join(table_lines)

    def _resolve_analytics(
        self,
        *,
        question: str,
        user_id: int,
        file_ids: list[int],
        reference_date: date,
    ) -> FactResolution:
        normalized = self._normalize_text(question)
        metadata_rows = self._load_archive_metadata_rows(
            user_id=user_id,
            file_ids=file_ids,
        )
        resolved_metadata_file_ids = [row.file_id for row in metadata_rows if row.file_id > 0]

        if metadata_rows and self._question_targets_sites_with_multiple_contract_ids(question):
            answer, facts_used_count = self._build_multi_contract_site_answer(metadata_rows=metadata_rows)
            return FactResolution(
                narrowed_file_ids=resolved_metadata_file_ids,
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=facts_used_count,
                confidence_notes=["Analytics answered directly from canonical CSV metadata rows."],
                metadata_phase_used=True,
                resolved_archive_slugs=[row.archive_slug for row in metadata_rows if str(row.archive_slug).strip()],
                metadata_only_reason="metadata_analytics",
            )

        if metadata_rows and self._question_targets_contract_state_counts(question):
            answer, facts_used_count = self._build_contract_state_counts_answer(metadata_rows=metadata_rows)
            return FactResolution(
                narrowed_file_ids=resolved_metadata_file_ids,
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=facts_used_count,
                confidence_notes=["Contract state counts were resolved directly from canonical CSV metadata rows."],
                metadata_phase_used=True,
                resolved_archive_slugs=[row.archive_slug for row in metadata_rows if str(row.archive_slug).strip()],
                metadata_only_reason="metadata_analytics",
            )

        if self._question_targets_top_document_versions(question):
            answer, facts_used_count = self._build_top_document_versions_answer(
                user_id=user_id,
                file_ids=file_ids,
            )
            if answer:
                return FactResolution(
                    narrowed_file_ids=list(file_ids or []),
                    fact_context_text=answer,
                    answer_override=answer,
                    facts_used_count=facts_used_count,
                    confidence_notes=["Document version counts were resolved directly from the processed file inventory."],
                )

        if metadata_rows and self._question_targets_entel_figure_count(question):
            answer, facts_used_count = self._build_entel_figure_count_answer(
                question=question,
                metadata_rows=metadata_rows,
            )
            if answer:
                return FactResolution(
                    narrowed_file_ids=resolved_metadata_file_ids,
                    fact_context_text=answer,
                    answer_override=answer,
                    facts_used_count=facts_used_count,
                    confidence_notes=["Figura Legal counts were resolved directly from canonical CSV metadata rows."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=[row.archive_slug for row in metadata_rows if str(row.archive_slug).strip()],
                    metadata_only_reason="metadata_analytics",
                )

        generic_metadata_answer = self._resolve_generic_metadata_analytics(
            question=question,
            metadata_rows=metadata_rows,
        )
        if generic_metadata_answer is not None:
            answer, facts_used_count, narrowed_file_ids = generic_metadata_answer
            return FactResolution(
                narrowed_file_ids=narrowed_file_ids,
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=facts_used_count,
                confidence_notes=["Metadata analytics were resolved directly from canonical CSV rows."],
                metadata_phase_used=True,
                resolved_archive_slugs=[row.archive_slug for row in metadata_rows if str(row.archive_slug).strip()],
                metadata_only_reason="metadata_analytics",
            )

        if any(token in normalized for token in ("empresa nacional de telecomunicaciones", "entel")):
            current_only = "vigent" in normalized
            count = self.repository.count_groups_by_subject_name(
                user_id=int(user_id),
                subject_name="Empresa Nacional de Telecomunicaciones",
                file_ids=file_ids or None,
                current_only=current_only,
                include_shared=True,
            )
            answer = (
                f"Se identificaron {count} contratos {'vigentes ' if current_only else ''}"
                "asociados a Empresa Nacional de Telecomunicaciones SA."
            )
            return self._append_archive_metadata_context(
                resolution=FactResolution(
                narrowed_file_ids=[],
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=count,
                confidence_notes=["Analytics answered from structured document facts."],
                ),
                user_id=user_id,
                file_ids=file_ids,
            )
        if "transam" in normalized:
            count = self.repository.count_groups_by_subject_name(
                user_id=int(user_id),
                subject_name="TRANSAM",
                file_ids=file_ids or None,
                current_only=False,
                include_shared=True,
            )
            answer = f"Se identificaron {count} contratos asociados a TRANSAM."
            return self._append_archive_metadata_context(
                resolution=FactResolution(
                narrowed_file_ids=[],
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=count,
                confidence_notes=["Analytics answered from structured document facts."],
                ),
                user_id=user_id,
                file_ids=file_ids,
            )
        if "vencid" in normalized:
            count = self.repository.count_expired_groups(
                user_id=int(user_id),
                as_of_date=reference_date,
                file_ids=file_ids or None,
                include_shared=True,
            )
            answer = f"Se identificaron {count} contratos vencidos al {reference_date.isoformat()}."
            return self._append_archive_metadata_context(
                resolution=FactResolution(
                narrowed_file_ids=[],
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=count,
                confidence_notes=["Expiration count resolved from current structured profiles."],
                ),
                user_id=user_id,
                file_ids=file_ids,
            )
        if "sitios" in normalized and "id de contrato" in normalized:
            rows = self.repository.list_secondary_identifiers_with_multiple_primary_identifiers(
                user_id=int(user_id),
                file_ids=file_ids or None,
                include_shared=True,
            )
            answer = "No se identificaron sitios con mas de un ID de contrato."
            if rows:
                fragments = [
                    (
                        f"{row.get('secondary_identifier')}: "
                        f"{row.get('primary_identifier_count')} IDs "
                        f"({row.get('primary_identifiers')})"
                    )
                    for row in rows[:10]
                ]
                answer = "Sitios con multiples IDs de contrato: " + "; ".join(fragments) + "."
            return self._append_archive_metadata_context(
                resolution=FactResolution(
                narrowed_file_ids=[],
                fact_context_text=answer,
                answer_override=answer,
                facts_used_count=len(rows),
                confidence_notes=["Identifier multiplicity resolved from structured profiles."],
                ),
                user_id=user_id,
                file_ids=file_ids,
            )
        return self._append_archive_metadata_context(
            resolution=FactResolution(narrowed_file_ids=[], fact_context_text="", facts_used_count=0),
            user_id=user_id,
            file_ids=file_ids,
        )

    def _resolve_metadata_comparison(
        self,
        *,
        question_class: str,
        question: str,
        user_id: int,
        file_ids: list[int],
        archive_slugs: list[str] | None = None,
        metadata_rows: list[ArchiveMetadataEntry] | None = None,
        requested_fields: list[str] | None = None,
        explicit_metadata_fields: bool = False,
        metadata_mode: str = "auto",
        reference_date: date | None = None,
    ) -> FactResolution:
        safe_archive_slugs = [
            canonicalize_file_key(str(value or "").strip())
            for value in list(archive_slugs or [])
            if canonicalize_file_key(str(value or "").strip())
        ]
        metadata_rows = list(metadata_rows or self._load_archive_metadata_rows(
            user_id=user_id,
            file_ids=file_ids,
        ))
        metadata_rows = self._filter_metadata_rows_for_explicit_archive_scope(
            question=question,
            metadata_rows=metadata_rows,
            archive_slugs=safe_archive_slugs,
        )
        if not metadata_rows:
            raise ScopeResolutionError(
                "No metadata is available for the current scope.",
                status_code=404,
            )
        resolved_archive_slugs = [row.archive_slug for row in metadata_rows if str(row.archive_slug).strip()]
        safe_requested_fields = list(requested_fields or [])
        document_centric_question = question_class in {"exhaustive_synthesis", "versioned", "visual_consistency"}
        pattern_summary_requested = self._question_requests_pattern_summary(question)
        prefer_field_resolution = (
            bool(explicit_metadata_fields)
            and not self._question_requests_quantified_aggregate(question)
            and not pattern_summary_requested
        )

        if (
            not prefer_field_resolution
            and not document_centric_question
            and (
                self._question_targets_sites_with_multiple_contract_ids(question)
                or self._question_targets_contract_state_counts(question)
                or self._question_targets_entel_figure_count(question)
            )
        ):
            return self._resolve_analytics(
                question=question,
                user_id=user_id,
                file_ids=file_ids,
                reference_date=reference_date or datetime.utcnow().date(),
            )

        if (
            self._question_requests_aggregate(question)
            and not prefer_field_resolution
            and not document_centric_question
        ):
            generic_metadata_answer = self._resolve_generic_metadata_analytics(
                question=question,
                metadata_rows=metadata_rows,
            )
            if generic_metadata_answer is not None:
                answer_override, facts_used_count, narrowed_file_ids = generic_metadata_answer
                return FactResolution(
                    narrowed_file_ids=narrowed_file_ids,
                    fact_context_text=answer_override,
                    answer_override=answer_override,
                    facts_used_count=facts_used_count,
                    confidence_notes=["Aggregate metadata answers were resolved before document retrieval."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=safe_requested_fields,
                    metadata_only_reason="metadata_analytics",
                )

        requested_fields = safe_requested_fields or self._extract_requested_metadata_fields(
            question=question,
            metadata_rows=metadata_rows,
        )
        compare_requested = self._question_requests_comparison(question)
        metadata_forced = str(metadata_mode or "").strip().lower() == "metadata_first"
        document_content_requested = self._question_requests_document_content(question)
        document_evidence_requested = (
            self._question_requests_document_evidence(question)
            or document_content_requested
        )
        append_inventory_to_answer = bool(
            safe_archive_slugs and self._question_requests_document_inventory(question)
        )
        interpretive_followup_requested = self._question_requests_interpretive_followup(question)
        resolved_file_ids = [row.file_id for row in metadata_rows if row.file_id > 0]
        document_scope_file_ids = self._expand_document_evidence_file_ids(
            user_id=user_id,
            candidate_file_ids=file_ids,
            metadata_rows=metadata_rows,
        )

        if document_content_requested:
            context_lines = (
                self._build_metadata_field_context_lines(
                    metadata_rows=metadata_rows,
                    requested_fields=requested_fields,
                )
                if requested_fields
                else []
            )
            fact_context = (
                "Resolved metadata facts:\n" + "\n".join(context_lines)
                if context_lines
                else ""
            )
            return self._append_archive_metadata_context(
                resolution=FactResolution(
                    narrowed_file_ids=document_scope_file_ids or resolved_file_ids,
                    fact_context_text=fact_context,
                    facts_used_count=max(1, len(metadata_rows) * max(1, len(requested_fields))),
                    confidence_notes=[
                        "Metadata resolved the scope first, but the question asks for OCR/document content."
                    ],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=requested_fields,
                    document_phase_required=True,
                    answerability_route="metadata_plus_documents",
                ),
                user_id=user_id,
                file_ids=document_scope_file_ids or resolved_file_ids or file_ids,
            )

        if (
            self._question_targets_docling_quality_review(question)
            or self._question_targets_metadata_document_quality_review(question)
            or self._question_targets_metadata_document_differences(question)
        ):
            quality_answer = self._build_docling_quality_review_answer(
                user_id=user_id,
                file_ids=document_scope_file_ids or resolved_file_ids or file_ids,
                metadata_rows=metadata_rows,
                requested_fields=safe_requested_fields,
            )
            if quality_answer is not None:
                answer_override, facts_used_count, narrowed_file_ids = quality_answer
                return FactResolution(
                    narrowed_file_ids=narrowed_file_ids or document_scope_file_ids or resolved_file_ids,
                    fact_context_text=answer_override,
                    answer_override=answer_override,
                    facts_used_count=facts_used_count,
                    confidence_notes=["Docling OCR quality gates were evaluated before trusting metadata fields."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=safe_requested_fields,
                    metadata_only_reason="docling_quality_review",
                )

        if safe_requested_fields and pattern_summary_requested and not document_centric_question:
            pattern_answer = self._build_metadata_pattern_summary_answer(
                metadata_rows=metadata_rows,
                requested_fields=safe_requested_fields,
            )
            if pattern_answer is not None:
                answer_override, facts_used_count, narrowed_file_ids = pattern_answer
                return FactResolution(
                    narrowed_file_ids=narrowed_file_ids,
                    fact_context_text=answer_override,
                    answer_override=answer_override,
                    facts_used_count=facts_used_count,
                    confidence_notes=["Metadata pattern summary was resolved from dynamic CSV fields."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=safe_requested_fields,
                    metadata_only_reason="metadata_pattern_summary",
                )

        if self._question_targets_metadata_document_differences(question):
            difference_answer = self._build_metadata_document_difference_answer(
                user_id=user_id,
                question=question,
                file_ids=document_scope_file_ids or resolved_file_ids or file_ids,
                metadata_rows=metadata_rows,
            )
            if difference_answer is not None:
                answer_override, facts_used_count = difference_answer
                return FactResolution(
                    narrowed_file_ids=document_scope_file_ids or resolved_file_ids,
                    fact_context_text=answer_override,
                    answer_override=answer_override,
                    facts_used_count=facts_used_count,
                    confidence_notes=[
                        "Metadata and structured document facts were compared directly before vector retrieval."
                    ],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=requested_fields,
                    metadata_only_reason="metadata_document_difference",
                )

        if requested_fields:
            derived_answer = self._build_metadata_derived_answer(
                question=question,
                metadata_rows=metadata_rows,
                requested_fields=requested_fields,
                compare_requested=compare_requested,
                reference_date=reference_date or datetime.utcnow().date(),
            )
            if derived_answer is not None:
                answer_override, facts_used_count = derived_answer
                if append_inventory_to_answer:
                    answer_override = self._append_document_inventory_to_answer(
                        answer=answer_override,
                        user_id=user_id,
                        file_ids=document_scope_file_ids or resolved_file_ids,
                    )
                return FactResolution(
                    narrowed_file_ids=resolved_file_ids,
                    fact_context_text=answer_override,
                    answer_override=answer_override,
                    facts_used_count=facts_used_count,
                    confidence_notes=["Metadata-derived answer resolved from canonical CSV rows."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=requested_fields,
                    metadata_only_reason="metadata_fields_derived",
                )
            answer_override = self._build_metadata_answer(
                question=question,
                metadata_rows=metadata_rows,
                requested_fields=requested_fields,
                compare_requested=compare_requested,
            )
            if answer_override:
                if append_inventory_to_answer:
                    answer_override = self._append_document_inventory_to_answer(
                        answer=answer_override,
                        user_id=user_id,
                        file_ids=document_scope_file_ids or resolved_file_ids,
                    )
                context_lines = self._build_metadata_field_context_lines(
                    metadata_rows=metadata_rows,
                    requested_fields=requested_fields,
                )
                fact_context = (
                    "Resolved metadata facts:\n" + "\n".join(context_lines)
                    if context_lines
                    else ""
                )
                should_require_document_followup = bool(
                    document_evidence_requested
                    or (
                        compare_requested
                        and (
                            interpretive_followup_requested
                            or self._requested_metadata_has_gaps(
                                metadata_rows=metadata_rows,
                                requested_fields=requested_fields,
                            )
                        )
                    )
                )
                metadata_sufficient, answerability_reason = self._metadata_is_sufficient_for_answer(
                    question=question,
                    metadata_rows=metadata_rows,
                    requested_fields=requested_fields,
                    explicit_metadata_fields=explicit_metadata_fields,
                    metadata_forced=metadata_forced,
                    document_evidence_requested=document_evidence_requested,
                    document_centric_question=document_centric_question,
                )
                should_require_document_followup = should_require_document_followup or not metadata_sufficient
                if should_require_document_followup:
                    if document_evidence_requested:
                        note = (
                            "Metadata rows matched the requested fields, but the question still requires documentary evidence."
                        )
                    elif interpretive_followup_requested:
                        note = (
                            "Metadata rows matched, but the comparative question requires documentary grounding before drawing conclusions."
                        )
                    else:
                        note = (
                            "Metadata rows matched partially, but missing values require documentary evidence before concluding the comparison."
                            if metadata_sufficient
                            else f"Metadata rows matched requested fields, but {answerability_reason}."
                        )
                    return self._append_archive_metadata_context(
                        resolution=FactResolution(
                            narrowed_file_ids=document_scope_file_ids or resolved_file_ids,
                            fact_context_text=fact_context,
                            facts_used_count=max(1, len(metadata_rows) * len(requested_fields)),
                            confidence_notes=[note],
                            metadata_phase_used=True,
                            resolved_archive_slugs=resolved_archive_slugs,
                            resolved_metadata_fields=requested_fields,
                            document_phase_required=True,
                            answerability_route="metadata_plus_documents",
                        ),
                        user_id=user_id,
                        file_ids=document_scope_file_ids or resolved_file_ids or file_ids,
                    )
                return FactResolution(
                    narrowed_file_ids=resolved_file_ids,
                    fact_context_text=fact_context,
                    answer_override=answer_override,
                    facts_used_count=max(1, len(metadata_rows) * len(requested_fields)),
                    confidence_notes=["Metadata-first answer resolved from canonical CSV rows."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=requested_fields,
                    metadata_only_reason="metadata_fields_sufficient",
                    answerability_route="structured_only",
                )

        if compare_requested and len(metadata_rows) >= 2:
            diff_context_lines = self._build_metadata_difference_context_lines(metadata_rows=metadata_rows)
            if diff_context_lines:
                if document_evidence_requested:
                    return FactResolution(
                        narrowed_file_ids=document_scope_file_ids or resolved_file_ids,
                        fact_context_text="Resolved metadata differences:\n" + "\n".join(diff_context_lines),
                        facts_used_count=len(diff_context_lines),
                        confidence_notes=[
                            "Metadata differences were resolved, but the question still requires evidence from the documents."
                        ],
                        metadata_phase_used=True,
                        resolved_archive_slugs=resolved_archive_slugs,
                        resolved_metadata_fields=requested_fields,
                        document_phase_required=True,
                        answerability_route="metadata_plus_documents",
                    )
                return FactResolution(
                    narrowed_file_ids=resolved_file_ids,
                    fact_context_text="Resolved metadata differences:\n" + "\n".join(diff_context_lines),
                    answer_override=(
                        "Principales diferencias de metadata: "
                        + "; ".join(diff_context_lines[:6])
                        + "." 
                    ),
                    facts_used_count=len(diff_context_lines),
                    confidence_notes=["Metadata comparison resolved directly from canonical CSV rows."],
                    metadata_phase_used=True,
                    resolved_archive_slugs=resolved_archive_slugs,
                    resolved_metadata_fields=requested_fields,
                    metadata_only_reason="metadata_comparison_sufficient",
                    answerability_route="structured_only",
                )

        return self._append_archive_metadata_context(
            resolution=FactResolution(
                narrowed_file_ids=document_scope_file_ids or resolved_file_ids,
                fact_context_text="",
                facts_used_count=len(metadata_rows),
                confidence_notes=[
                    "Metadata rows were available but the question still needs broader retrieval."
                    if not metadata_forced
                    else "Metadata phase ran first, but the question still requires documentary evidence."
                ],
                metadata_phase_used=True,
                resolved_archive_slugs=resolved_archive_slugs,
                resolved_metadata_fields=requested_fields,
                document_phase_required=True,
                answerability_route="metadata_plus_documents",
            ),
            user_id=user_id,
            file_ids=document_scope_file_ids or resolved_file_ids or file_ids,
        )

    def _resolve_temporal(
        self,
        *,
        question: str,
        user_id: int,
        file_ids: list[int],
        reference_date: date,
    ) -> FactResolution:
        current_rows = self.repository.list_current_profiles(
            user_id=int(user_id),
            file_ids=file_ids or None,
            as_of_date=None,
            include_shared=True,
        )
        if not current_rows:
            return FactResolution(narrowed_file_ids=[], fact_context_text="", facts_used_count=0)
        current = current_rows[0]
        effective_to = current.get("effective_to")
        if hasattr(effective_to, "date"):
            effective_to = effective_to.date()
        if isinstance(effective_to, datetime):
            effective_to = effective_to.date()
        if not isinstance(effective_to, date):
            return self._append_archive_metadata_context(
                resolution=FactResolution(
                narrowed_file_ids=[int(current.get("file_id") or 0)],
                fact_context_text="A current profile was found, but there is no effective_to value in the facts layer.",
                facts_used_count=1,
                ),
                user_id=user_id,
                file_ids=[int(current.get("file_id") or 0)],
            )
        delta_days = (effective_to - reference_date).days
        answer = (
            f"Al {reference_date.isoformat()}, al contrato vigente le quedan {delta_days} dias de vigencia."
            if delta_days >= 0
            else f"Al {reference_date.isoformat()}, el contrato vigente aparece vencido hace {abs(delta_days)} dias."
        )
        return self._append_archive_metadata_context(
            resolution=FactResolution(
            narrowed_file_ids=[int(current.get("file_id") or 0)],
            fact_context_text=answer,
            answer_override=answer if "vigencia" in question.lower() else None,
            facts_used_count=1,
            file_group_ids=[int(current.get("file_group_id") or 0)] if int(current.get("file_group_id") or 0) > 0 else [],
            confidence_notes=["Temporal answer resolved from structured current profiles."],
            ),
            user_id=user_id,
            file_ids=[int(current.get("file_id") or 0)],
        )

    def _append_archive_metadata_context(
        self,
        *,
        resolution: FactResolution,
        user_id: int,
        file_ids: list[int],
    ) -> FactResolution:
        metadata_rows = self._load_archive_metadata_rows(
            user_id=user_id,
            file_ids=file_ids,
        )
        metadata_context = self._build_archive_metadata_context(
            user_id=user_id,
            file_ids=file_ids,
        )
        inventory_context = self._build_file_inventory_context(
            user_id=user_id,
            file_ids=file_ids,
        )
        structured_context = "\n".join(
            part for part in (metadata_context, inventory_context) if str(part).strip()
        ).strip()
        if not structured_context:
            return resolution
        merged_context = "\n".join(
            part for part in (resolution.fact_context_text, structured_context) if str(part).strip()
        ).strip()
        notes = list(resolution.confidence_notes)
        notes.append("Archive metadata enriched the structured context for retrieval.")
        return FactResolution(
            narrowed_file_ids=list(resolution.narrowed_file_ids),
            fact_context_text=merged_context,
            answer_override=resolution.answer_override,
            facts_used_count=resolution.facts_used_count,
            file_group_ids=list(resolution.file_group_ids),
            confidence_notes=notes,
            metadata_phase_used=True,
            resolved_archive_slugs=(
                list(resolution.resolved_archive_slugs)
                or [row.archive_slug for row in metadata_rows if str(row.archive_slug).strip()]
            ),
            resolved_metadata_fields=list(resolution.resolved_metadata_fields),
            metadata_only_reason=str(resolution.metadata_only_reason or ""),
            document_phase_required=bool(resolution.document_phase_required),
            answerability_route=str(resolution.answerability_route or ""),
        )

    def _build_archive_metadata_context(self, *, user_id: int, file_ids: list[int]) -> str:
        if self.file_repository is None:
            return ""
        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        if not safe_file_ids:
            return ""
        try:
            rows = self.file_repository.get_archive_metadata_for_file_ids(
                user_id=int(user_id),
                file_ids=safe_file_ids,
                include_shared=True,
            )
        except Exception:
            return ""
        fragments: list[str] = []
        for row in rows[:8]:
            raw_metadata = row.get("metadata_json")
            if hasattr(raw_metadata, "read"):
                raw_metadata = raw_metadata.read()
            try:
                metadata_payload = json.loads(str(raw_metadata or "{}"))
            except Exception:
                continue
            fields = metadata_payload.get("fields")
            if not isinstance(fields, dict) or not fields:
                continue
            archive_slug = str(row.get("archive_slug") or metadata_payload.get("file") or "").strip()
            items = self._prioritize_metadata_context_items(fields)
            if not items:
                continue
            fragments.append(f"{archive_slug}: {'; '.join(items[:48])}")
        if not fragments:
            return ""
        return "Archive metadata context:\n" + "\n".join(fragments)

    def _build_file_inventory_context(self, *, user_id: int, file_ids: list[int]) -> str:
        rows = self._list_user_files(user_id=user_id, file_ids=file_ids)
        if not rows:
            return ""
        lines: list[str] = []
        for row in sorted(
            rows,
            key=lambda item: (
                str(item.get("archive_slug") or "").lower(),
                str(item.get("file_input_file_name") or "").lower(),
                int(item.get("file_id") or 0),
            ),
        )[:120]:
            file_id = int(row.get("file_id") or 0)
            if file_id <= 0:
                continue
            raw_status = row.get("file_state")
            status = str(raw_status or "").strip().lower() if isinstance(raw_status, str) else code_to_status(raw_status)
            lines.append(
                "- "
                f"file_id={file_id} "
                f"archive={str(row.get('archive_slug') or '').strip() or '-'} "
                f"file={repair_document_file_name(row.get('file_input_file_name') or f'file-{file_id}')} "
                f"status={status or 'unknown'} "
                f"pages={int(row.get('file_page_count') or 0)}"
            )
        if not lines:
            return ""
        return "Document inventory context:\n" + "\n".join(lines)

    def _append_document_inventory_to_answer(self, *, answer: str, user_id: int, file_ids: list[int]) -> str:
        text = str(answer or "").strip()
        if not text or "documentos asociados:" in self._normalize_text(text):
            return text
        rows = self._list_user_files(user_id=user_id, file_ids=file_ids)
        if not rows:
            return text
        names: list[str] = []
        seen: set[str] = set()
        for row in sorted(
            rows,
            key=lambda item: (
                str(item.get("archive_slug") or "").lower(),
                str(item.get("file_input_file_name") or "").lower(),
                int(item.get("file_id") or 0),
            ),
        ):
            name = repair_document_file_name(row.get("file_input_file_name") or "")
            if not name:
                continue
            key = self._normalize_text(name)
            if not key or key in seen:
                continue
            seen.add(key)
            names.append(name)
        if not names:
            return text
        return text.rstrip(".") + ". Documentos asociados: " + "; ".join(names[:20]) + "."

    def _list_user_files(self, *, user_id: int, file_ids: list[int]) -> list[dict[str, object]]:
        if self.file_repository is None:
            return []
        list_files_for_user = getattr(self.file_repository, "list_files_for_user", None)
        if not callable(list_files_for_user):
            return []
        try:
            rows = [dict(row) for row in list(list_files_for_user(user_id=int(user_id), include_shared=True))]
        except Exception:
            return []
        safe_file_ids = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
        if safe_file_ids:
            rows = [row for row in rows if int(row.get("file_id") or 0) in safe_file_ids]
        return rows

    def _list_page_quality_rows(self, *, user_id: int, file_ids: list[int]) -> list[dict[str, object]]:
        if self.file_repository is None:
            return []
        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        if not safe_file_ids:
            return []
        list_page_quality = getattr(self.file_repository, "list_page_quality_for_file_ids", None)
        if not callable(list_page_quality):
            return []
        try:
            return [
                dict(row)
                for row in list(
                    list_page_quality(
                        user_id=int(user_id),
                        file_ids=safe_file_ids,
                        include_shared=True,
                    )
                )
            ]
        except Exception:
            return []

    @classmethod
    def _question_targets_docling_quality_review(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "revision humana",
                "requiere revision",
                "priorizarse para revision",
                "ocr",
                "cifrado",
                "cifrados",
                "no validable",
                "inconsistencia",
                "inconsistencias",
                "ambiguedad",
                "ambigüedad",
                "contradiccion",
                "contradicción",
                "ausencia",
                "calidad",
            )
        )

    @classmethod
    def _question_requests_document_content(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        source_requested = any(
            token in normalized
            for token in (
                "segun el ocr",
                "segun ocr",
                "ocr del documento",
                "ocr del contrato",
                "texto ocr",
                "texto extraido",
                "texto del documento",
                "texto contractual",
                "contenido del documento",
                "contenido contractual",
                "segun el documento",
                "segun los documentos",
                "segun el contrato",
                "segun el pdf",
                "segun los pdfs",
                "documento",
                "documentos",
                "pdf",
                "pdfs",
            )
        )
        if not source_requested:
            return False
        return any(
            token in normalized
            for token in (
                "resume",
                "resumen",
                "de que trata",
                "menciona",
                "identifica",
                "extrae",
                "partes",
                "partes principales",
                "partes involucradas",
                "arrendador",
                "arrendatario",
                "firmantes",
                "representantes",
                "direccion",
                "sitio",
                "renta",
                "precio",
                "canon",
                "vigencia",
                "objeto del contrato",
            )
        )

    @classmethod
    def _question_targets_metadata_document_quality_review(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        metadata_requested = any(token in normalized for token in ("metadata", "metadatos"))
        document_requested = "document" in normalized
        validation_requested = any(
            token in normalized
            for token in (
                "coincid",
                "consisten",
                "validable",
                "validar",
                "valida",
                "coheren",
            )
        )
        return bool(metadata_requested and document_requested and validation_requested)

    @classmethod
    def _question_requests_pattern_summary(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "patron",
                "patrones",
                "tendencia",
                "tendencias",
                "distribucion",
                "distribución",
                "resumen por",
                "agrupa",
                "agrupacion",
                "agrupación",
            )
        )

    @classmethod
    def _pluralize_metadata_value_for_count(cls, value: str, count: int) -> str:
        text = str(value or "").strip()
        if int(count or 0) == 1 or not text:
            return text
        lower = text.lower()
        if lower.endswith("s"):
            return text
        if lower.endswith(("a", "e", "i", "o", "u")):
            return text + "s"
        return text + "es"

    @classmethod
    def _build_metadata_pattern_summary_answer(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> tuple[str, int, list[int]] | None:
        if not metadata_rows or not requested_fields:
            return None
        fragments: list[str] = []
        for requested_field in requested_fields:
            counter: Counter[str] = Counter()
            resolved_header = ""
            for row in metadata_rows:
                header, raw_value = cls._find_metadata_field(row, requested_field)
                if header:
                    resolved_header = resolved_header or header
                rendered = cls._format_metadata_value(raw_value)
                if cls._is_unspecified_metadata_value(rendered):
                    continue
                counter[rendered] += 1
            if not counter:
                continue
            top_values = counter.most_common(4)
            rendered_values = [
                f"{cls._pluralize_metadata_value_for_count(value, count)}: {count} expedientes"
                for value, count in top_values
            ]
            fragments.append(f"{resolved_header or requested_field}: " + ", ".join(rendered_values))
        if not fragments:
            return None
        narrowed_file_ids: list[int] = []
        seen: set[int] = set()
        for row in metadata_rows:
            file_id = int(row.file_id)
            if file_id <= 0 or file_id in seen:
                continue
            seen.add(file_id)
            narrowed_file_ids.append(file_id)
        answer = (
            f"Patrones relevantes en la metadata ({len(metadata_rows)} expedientes): "
            + " | ".join(fragments)
            + "."
        )
        return answer, len(metadata_rows), narrowed_file_ids

    @classmethod
    def _normalize_sequence_field(cls, value: object) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [item.strip() for item in re.split(r"[,;|]\s*", text) if item.strip()]

    @classmethod
    def _quality_row_is_encrypted_or_unreadable(cls, row: dict[str, object]) -> bool:
        flags = " ".join(cls._normalize_sequence_field(row.get("visual_flags"))).lower()
        methods = " ".join(cls._normalize_sequence_field(row.get("ocr_methods"))).lower()
        status = str(row.get("status") or "").strip().lower()
        encrypted_pages = int(row.get("encrypted_or_unreadable_pages_count") or 0)
        indexed_pages = int(row.get("indexed_pages_count") or 0)
        file_page_count = int(row.get("file_page_count") or row.get("page_count") or 0)
        encrypted_terms = ("encrypted", "cifrado", "password", "locked", "unreadable", "no_extraible")
        if encrypted_pages > 0 or any(term in flags or term in methods for term in encrypted_terms):
            return True
        return bool(status == "failed" and file_page_count > 0 and indexed_pages == 0)

    @classmethod
    def _quality_row_has_low_ocr(cls, row: dict[str, object]) -> bool:
        flags = " ".join(cls._normalize_sequence_field(row.get("visual_flags"))).lower()
        low_pages = int(row.get("low_ocr_pages_count") or 0)
        blank_pages = int(row.get("blank_pages_count") or 0)
        avg_confidence = float(row.get("avg_ocr_confidence") or 0.0)
        avg_text_quality = float(row.get("avg_text_quality") or 0.0)
        return bool(
            low_pages > 0
            or blank_pages > 0
            or "low_ocr_confidence" in flags
            or (0.0 < avg_confidence < 0.78)
            or (0.0 < avg_text_quality < 0.55)
        )

    @classmethod
    def _build_metadata_quality_fragments(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> list[str]:
        if not metadata_rows or not requested_fields:
            return []
        fragments: list[str] = []
        for row in metadata_rows:
            row_parts: list[str] = []
            for field_name in requested_fields:
                header, raw_value = cls._find_metadata_field(row, field_name)
                if not header:
                    row_parts.append(f"{field_name}=sin metadata")
                    continue
                rendered = cls._format_metadata_value(raw_value)
                row_parts.append(f"{header}={rendered}")
            if row_parts:
                fragments.append(f"{row.archive_slug}: " + "; ".join(row_parts))
        return fragments

    def _build_docling_quality_review_answer(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> tuple[str, int, list[int]] | None:
        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        if not safe_file_ids:
            safe_file_ids = [int(row.file_id) for row in metadata_rows if int(row.file_id) > 0]
        quality_rows = self._list_page_quality_rows(user_id=user_id, file_ids=safe_file_ids)
        if not quality_rows:
            return None

        encrypted_rows: list[dict[str, object]] = []
        issue_lines: list[str] = []
        narrowed_file_ids: list[int] = []
        encrypted_by_archive: Counter[str] = Counter()
        total_by_archive: Counter[str] = Counter()
        for row in quality_rows:
            file_id = int(row.get("file_id") or 0)
            if file_id > 0 and file_id not in narrowed_file_ids:
                narrowed_file_ids.append(file_id)
            file_name = repair_document_file_name(
                row.get("file_name") or row.get("file_input_file_name") or f"file-{file_id}"
            )
            archive_slug = str(row.get("archive_slug") or "").strip()
            if archive_slug:
                total_by_archive[archive_slug] += 1
            page_count = int(row.get("file_page_count") or row.get("page_count") or 0)
            indexed_pages = int(row.get("indexed_pages_count") or 0)
            encrypted = self._quality_row_is_encrypted_or_unreadable(row)
            low_ocr = self._quality_row_has_low_ocr(row)
            if encrypted:
                encrypted_rows.append(row)
                if archive_slug:
                    encrypted_by_archive[archive_slug] += 1
            if not encrypted and not low_ocr:
                continue
            issue_parts: list[str] = []
            if encrypted:
                page_hint = max(1, page_count or indexed_pages or 0)
                issue_parts.append(f"PDF cifrado/no extraible ({page_hint} paginas registradas)")
            if low_ocr:
                avg_confidence = float(row.get("avg_ocr_confidence") or 0.0)
                if avg_confidence > 0:
                    issue_parts.append(f"OCR Docling bajo ({avg_confidence:.2f})")
                else:
                    issue_parts.append("OCR Docling bajo o texto insuficiente")
            if issue_parts:
                prefix = f"{archive_slug}: " if archive_slug else ""
                issue_lines.append(f"{prefix}{file_name} -> " + "; ".join(issue_parts))

        if not issue_lines:
            return None

        metadata_fragments = self._build_metadata_quality_fragments(
            metadata_rows=metadata_rows,
            requested_fields=requested_fields,
        )
        encrypted_count = len(encrypted_rows)
        archive_fragments = [
            (
                f"{archive_slug}: {count} de {max(1, int(total_by_archive.get(archive_slug) or count))} PDF cifrado"
                if int(total_by_archive.get(archive_slug) or 0) == count
                else f"{archive_slug}: {count} PDF cifrados"
            )
            for archive_slug, count in sorted(encrypted_by_archive.items())
            if count > 0
        ]
        headline = (
            f"requiere revision humana: {encrypted_count} PDF cifrados o no extraibles; "
            "consistencia no validable aun con la metadata hasta revisar OCR/layout Docling."
            if encrypted_count
            else "requiere revision humana: se detectaron senales de OCR/layout Docling insuficientes."
        )
        answer_parts = [headline]
        if archive_fragments:
            answer_parts.append("Resumen por expediente: " + "; ".join(archive_fragments))
        answer_parts.append("Prioridad documental: " + " | ".join(issue_lines))
        if metadata_fragments:
            answer_parts.append(
                "Metadata asociada: "
                + " | ".join(metadata_fragments[:8])
                + ". Si la metadata indica REVISADO OK, queda contradicha por las senales de calidad documental."
            )
        answer = " ".join(part.strip() for part in answer_parts if part.strip())
        return answer, max(1, len(issue_lines) + len(metadata_fragments)), narrowed_file_ids or safe_file_ids

    @classmethod
    def _question_targets_sites_with_multiple_contract_ids(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return "sitio" in normalized and "id de contrato" in normalized

    @classmethod
    def _question_targets_contract_state_counts(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if "entel" in normalized or "figura legal" in normalized or "sociedad" in normalized:
            return False
        return (
            any(token in normalized for token in ("cuantos", "cuantas", "cuenta", "cantidad"))
            and "contrato" in normalized
            and any(token in normalized for token in ("vigent", "vencid", "terminad"))
        )

    @classmethod
    def _question_targets_top_document_versions(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if "versiones documentales" in normalized or "pdfs asociados" in normalized:
            return True
        return (
            "version" in normalized
            and "contrato" in normalized
            and any(token in normalized for token in ("mas", "mayor a menor", "ordena", "ordenalos"))
        )

    @classmethod
    def _question_targets_entel_figure_count(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return "entel" in normalized and any(
            token in normalized
            for token in ("figura legal", "sociedad", "firmados por", "contratos vigentes")
        )

    @classmethod
    def _question_requests_aggregate(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        plural_scope_requested = any(
            token in normalized
            for token in ("contratos", "sitios", "archivos", "documentos", "folios")
        )
        listing_signal = any(
            token in normalized
            for token in ("indica", "indicar", "dime", "muestra", "mostrar", "muestrame", "lista", "listar")
        )
        if plural_scope_requested and listing_signal and not cls._question_requests_comparison(question):
            return True
        if any(
            token in normalized
            for token in (
                "cuantos",
                "cuantas",
                "cantidad",
                "cuenta de",
                "que sitios",
                "cuales sitios",
                "que contratos",
                "cuales contratos",
                "que comunas",
                "cuales comunas",
                "que regiones",
                "cuales regiones",
                "lista sitios",
                "lista contratos",
                "lista comunas",
                "lista regiones",
                "listame los sitios",
                "listame los contratos",
                "muestrame los sitios",
                "muestrame los contratos",
            )
        ):
            return True
        metadata_prompt = any(token in normalized for token in ("metadata", "metadatos"))
        if not metadata_prompt:
            return False
        if re.search(r"\bque\b.+\b(?:hay|existen|tienen?)\b", normalized):
            return True
        return any(
            token in normalized
            for token in (
                "cuales",
                "lista",
                "listame",
                "muestrame",
                "ordena",
                "top",
                "mayor a menor",
                "mas de un",
                "mas de una",
                "multiples",
                "repetid",
                "duplicad",
            )
        )

    @classmethod
    def _question_requests_value_listing(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if any(token in normalized for token in ("cuantos", "cuantas", "cantidad", "cuenta de")):
            return False
        if re.search(r"\b(?:lista|listar|listame|muestra|mostrar|muestrame)\b", normalized):
            return True
        plural_scope_requested = any(
            token in normalized
            for token in ("contratos", "sitios", "archivos", "documentos", "folios")
        )
        listing_signal = any(
            token in normalized
            for token in ("indica", "indicar", "dime", "muestra", "mostrar", "muestrame", "lista", "listar")
        )
        if plural_scope_requested and listing_signal and not cls._question_requests_comparison(question):
            return True
        if any(
            token in normalized
            for token in (
                "que sitios",
                "cuales sitios",
                "que contratos",
                "cuales contratos",
                "que comunas",
                "cuales comunas",
                "que regiones",
                "cuales regiones",
                "lista sitios",
                "lista contratos",
                "lista comunas",
                "lista regiones",
                "listame los sitios",
                "listame los contratos",
                "muestrame los sitios",
                "muestrame los contratos",
            )
        ):
            return True
        metadata_prompt = any(token in normalized for token in ("metadata", "metadatos"))
        if not metadata_prompt:
            return False
        if re.search(r"\bque\b.+\b(?:hay|existen|tienen?)\b", normalized):
            return True
        return any(
            token in normalized
            for token in ("cuales", "lista", "listame", "muestrame", "ordena", "top")
        )

    @classmethod
    def _question_requests_quantified_aggregate(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "cuantos",
                "cuantas",
                "cantidad",
                "cuenta de",
                "top",
                "ranking",
                "mayor a menor",
                "mas de un",
                "mas de una",
                "multiples",
                "repetid",
                "duplicad",
                "ordena",
                "ordenalos",
            )
        )

    @classmethod
    def _inventory_request_requires_document_reasoning(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return bool(
            cls._question_requests_document_evidence(question)
            or any(
                token in normalized
                for token in (
                    "modific",
                    "documento base",
                    "contrato base",
                    "de donde fue extraido",
                    "dato clave",
                    "datos clave",
                    "instrumento vigente",
                    "gobierna",
                    "rige",
                    "quien firma",
                    "quienes firman",
                    "representante",
                    "representantes",
                )
            )
        )

    @classmethod
    def _question_requests_document_inventory(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if not normalized:
            return False
        if cls._inventory_request_requires_document_reasoning(question):
            return True
        if any(
            token in normalized
            for token in (
                "inventario documental",
                "inventario de documentos",
                "documentos asociados",
                "archivos asociados",
                "pdfs asociados",
                "documentos vinculados",
                "archivos vinculados",
                "documentos del expediente",
                "archivos del expediente",
                "integran el expediente",
                "documentos integran",
                "archivos integran",
                "lista de documentos",
                "listado de documentos",
                "listar documentos",
                "lista documentos",
                "listame los documentos",
                "muestrame los documentos",
                "cuales documentos",
                "que documentos",
            )
        ):
            return True
        return bool(
            re.search(r"\b(?:que|cuales)\s+(?:documentos|archivos|pdfs?)\b", normalized)
            or re.search(
                r"\b(?:documentos|archivos|pdfs?)\b.*\b(?:asociad|vinculad|integran|pertenecen|incluye|contiene)\b",
                normalized,
            )
        )

    @classmethod
    def _question_requests_document_inventory_listing(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if not normalized or cls._inventory_request_requires_document_reasoning(question):
            return False
        if any(
            token in normalized
            for token in (
                "inventario documental",
                "inventario de documentos",
                "inventario de archivos",
                "documentos asociados",
                "archivos asociados",
                "pdfs asociados",
                "documentos vinculados",
                "archivos vinculados",
                "documentos relacionados",
                "archivos relacionados",
                "lista de documentos",
                "listado de documentos",
                "listar documentos",
                "lista documentos",
                "listame los documentos",
                "muestrame los documentos",
                "cuales son los documentos",
                "cuales documentos",
                "que documentos",
            )
        ):
            return True
        return bool(
            re.search(r"\b(?:que|cuales)\s+(?:son\s+)?(?:sus\s+)?(?:documentos|archivos|pdfs?)\b", normalized)
            and re.search(r"\b(?:asociad|vinculad|relacionad|disponibles|cargad|procesad)\b", normalized)
        )

    @classmethod
    def _find_preferred_metadata_header(
        cls,
        metadata_rows: list[ArchiveMetadataEntry],
        *field_bases: str,
    ) -> str | None:
        allowed_bases = {
            cls._normalize_metadata_field_base(field_base)
            for field_base in field_bases
            if cls._normalize_metadata_field_base(field_base)
        }
        if not allowed_bases:
            return None
        for header in cls._preferred_metadata_headers(metadata_rows=metadata_rows):
            if cls._normalize_metadata_field_base(header) in allowed_bases:
                return str(header)
        return None

    @classmethod
    def _question_mentions_metadata_field(
        cls,
        *,
        question: str,
        field: MetadataSchemaField,
    ) -> bool:
        normalized_question = cls._normalize_text(question)
        if not field.base:
            return False
        question_tokens = cls._expanded_token_set(question)
        score, _ = cls._score_schema_field_match(
            normalized_question=normalized_question,
            question_tokens=question_tokens,
            field=field,
        )
        return score >= 150

    @classmethod
    def _iter_distinct_field_values(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        field_header: str,
    ) -> list[str]:
        values: list[str] = []
        seen_values: set[str] = set()
        for row in metadata_rows:
            raw_value = row.fields.get(field_header)
            rendered = cls._format_metadata_value(raw_value)
            normalized_rendered = cls._normalize_text(rendered)
            if cls._is_unspecified_metadata_value(rendered) or normalized_rendered in seen_values:
                continue
            seen_values.add(normalized_rendered)
            values.append(rendered)
        return values

    @classmethod
    def _score_metadata_value_match(
        cls,
        *,
        normalized_question: str,
        question_tokens: set[str],
        field_base: str,
        candidate_value: str,
        header_referenced: bool,
    ) -> int:
        normalized_value = cls._normalize_text(candidate_value)
        if not normalized_value or normalized_value in {"-", "(blank)"}:
            return 0
        if field_base == "estado contrato":
            if "vigent" in normalized_question and "vigent" in normalized_value:
                return 320 + len(normalized_value)
            if "vencid" in normalized_question and "vencid" in normalized_value:
                return 320 + len(normalized_value)
            if "terminad" in normalized_question and "terminad" in normalized_value:
                return 320 + len(normalized_value)
        if normalized_value in {"si", "no"} and not header_referenced:
            return 0
        if len(normalized_value) >= 5 and re.search(rf"\b{re.escape(normalized_value)}\b", normalized_question):
            return 300 + len(normalized_value)
        value_tokens = [
            token
            for token in cls._tokenize(normalized_value)
            if token not in _METADATA_STOPWORDS and len(token) > 1
        ]
        if not value_tokens:
            return 0
        overlap_count = sum(1 for token in value_tokens if token in question_tokens)
        if overlap_count == len(value_tokens):
            return (240 if header_referenced else 180) + overlap_count * 10 + len(normalized_value)
        if header_referenced and len(value_tokens) >= 2 and overlap_count >= max(2, len(value_tokens) - 1):
            return 150 + overlap_count * 10 + len(normalized_value)
        if len(value_tokens) >= 3 and overlap_count >= max(2, len(value_tokens) - 1):
            return 110 + overlap_count * 10 + len(normalized_value)
        return 0

    @classmethod
    def _extract_metadata_filter_matches(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> list[MetadataFilterMatch]:
        normalized_question = cls._normalize_text(question)
        question_tokens = cls._expanded_token_set(question)
        matches: list[MetadataFilterMatch] = []
        seen_bases: set[str] = set()
        always_allowed_bases = {"estado contrato", "figura legal", "codigo de sitio", "id"}
        for field in cls._build_metadata_schema(metadata_rows=metadata_rows):
            if not field.base or field.base == "file" or field.base in seen_bases:
                continue
            header_referenced = cls._question_mentions_metadata_field(question=question, field=field)
            best_value = ""
            best_score = 0
            for candidate_value in field.display_values or cls._iter_distinct_field_values(
                metadata_rows=metadata_rows,
                field_header=field.header,
            ):
                score = cls._score_metadata_value_match(
                    normalized_question=normalized_question,
                    question_tokens=question_tokens,
                    field_base=field.base,
                    candidate_value=candidate_value,
                    header_referenced=header_referenced,
                )
                if score <= best_score:
                    continue
                best_score = score
                best_value = candidate_value
            if not best_value:
                continue
            minimum_score = 300
            if header_referenced:
                minimum_score = 140
            elif field.base in always_allowed_bases:
                minimum_score = 220
            if best_score < minimum_score:
                continue
            seen_bases.add(field.base)
            matches.append(
                MetadataFilterMatch(
                    field_header=str(field.header),
                    field_base=field.base,
                    match_value=best_value,
                    score=best_score,
                )
            )
        matches.sort(key=lambda item: (-int(item.score), item.field_base))
        return matches[:3]

    @classmethod
    def _row_matches_metadata_filters(
        cls,
        *,
        row: ArchiveMetadataEntry,
        filters: list[MetadataFilterMatch],
    ) -> bool:
        for filter_match in filters:
            _, actual_value = cls._find_metadata_field(row, filter_match.field_base)
            if not cls._metadata_value_matches(
                actual_value=actual_value,
                expected_value=filter_match.match_value,
            ):
                return False
        return True

    @classmethod
    def _describe_metadata_filters(cls, filters: list[MetadataFilterMatch]) -> str:
        if not filters:
            return ""
        return " y ".join(
            f"{item.field_header}={item.match_value}"
            for item in filters
            if str(item.field_header or "").strip() and str(item.match_value or "").strip()
        )

    @classmethod
    def _resolve_metadata_analytics_target(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> tuple[str | None, str, bool]:
        normalized = cls._normalize_text(question)
        if any(
            token in normalized
            for token in (
                "id de sitio",
                "ids de sitio",
                "codigo de sitio",
                "que sitios",
                "cuales sitios",
                "sitios hay",
            )
        ) or ("sitio" in normalized and "contrato" not in normalized):
            header = cls._find_preferred_metadata_header(metadata_rows, "codigo de sitio")
            if header:
                return header, "sitios", True
        if any(token in normalized for token in ("id de contrato", "ids de contrato")):
            header = cls._find_preferred_metadata_header(metadata_rows, "id")
            if header:
                return header, "ids de contrato", True
        if any(token in normalized for token in ("que comunas", "cuales comunas", "cuantas comunas")):
            header = cls._find_preferred_metadata_header(metadata_rows, "comuna")
            if header:
                return header, "comunas", True
        if any(token in normalized for token in ("que regiones", "cuales regiones", "cuantas regiones")):
            header = cls._find_preferred_metadata_header(metadata_rows, "region")
            if header:
                return header, "regiones", True
        if "beneficiario" in normalized and "rut" not in normalized:
            header = cls._find_preferred_metadata_header(metadata_rows, "nombre beneficiario")
            if header:
                return header, "beneficiarios", True
        if "propietario" in normalized and "rut" not in normalized:
            header = cls._find_preferred_metadata_header(metadata_rows, "nombre de propietario principal")
            if header:
                return header, "propietarios", True
        if any(token in normalized for token in ("sociedad", "sociedades", "figura legal")):
            header = cls._find_preferred_metadata_header(metadata_rows, "figura legal")
            if header:
                return header, "sociedades", True
        schema_candidates = cls._rank_schema_fields_for_text(
            text=question,
            metadata_rows=metadata_rows,
            min_score=140,
        )
        if not schema_candidates:
            return None, "contratos", False
        contract_like_request = any(
            token in normalized
            for token in ("contrat", "archivo", "archivos", "file", "files", "folio", "folios", "documento")
        )
        explicit_candidates = [
            field
            for _, _, field in schema_candidates
            if cls._field_is_explicit_analytics_target(
                normalized_question=normalized,
                field=field,
            )
        ]
        if explicit_candidates:
            field = explicit_candidates[0]
            return field.header, field.header, True
        if not contract_like_request:
            field = schema_candidates[0][2]
            return field.header, field.header, True
        return None, "contratos", False

    @classmethod
    def _resolve_generic_metadata_analytics(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> tuple[str, int, list[int]] | None:
        if not metadata_rows or not cls._question_requests_aggregate(question):
            return None

        filter_matches = cls._extract_metadata_filter_matches(
            question=question,
            metadata_rows=metadata_rows,
        )
        filtered_rows = [
            row
            for row in metadata_rows
            if cls._row_matches_metadata_filters(row=row, filters=filter_matches)
        ] if filter_matches else list(metadata_rows)
        narrowed_file_ids: list[int] = []
        seen_file_ids: set[int] = set()
        for row in filtered_rows:
            file_id = int(row.file_id)
            if file_id <= 0 or file_id in seen_file_ids:
                continue
            seen_file_ids.add(file_id)
            narrowed_file_ids.append(file_id)
        filter_description = cls._describe_metadata_filters(filter_matches)
        if not filtered_rows:
            answer = "No se encontraron filas de metadata"
            if filter_description:
                answer += f" con {filter_description}"
            return answer + ".", 0, []

        duplicate_answer = cls._resolve_duplicate_metadata_analytics(
            question=question,
            metadata_rows=filtered_rows,
            filter_description=filter_description,
        )
        if duplicate_answer is not None:
            return duplicate_answer

        target_header, target_label, distinct_target = cls._resolve_metadata_analytics_target(
            question=question,
            metadata_rows=filtered_rows,
        )
        list_requested = cls._question_requests_value_listing(question)

        if target_header is not None:
            distinct_values = cls._iter_distinct_field_values(
                metadata_rows=filtered_rows,
                field_header=target_header,
            )
            if not distinct_values:
                return None
            if target_label == target_header:
                answer = f"Segun la metadata cargada, hay {len(distinct_values)} valores distintos de {target_label}"
            else:
                answer = f"Segun la metadata cargada, hay {len(distinct_values)} {target_label}"
                if distinct_target:
                    answer += " distintos"
            if filter_description:
                answer += f" con {filter_description}"
            if len(filtered_rows) != len(distinct_values):
                answer += f" ({len(filtered_rows)} archivos/filas coincidentes)"
            if list_requested or len(distinct_values) <= 12:
                suffix = ", ".join(distinct_values[:12])
                if len(distinct_values) > 12:
                    suffix += ", ..."
                answer += f": {suffix}"
            return answer + ".", len(filtered_rows), narrowed_file_ids

        archive_values = [
            str(row.archive_slug or "").strip()
            for row in filtered_rows
            if str(row.archive_slug or "").strip()
        ]
        answer = f"Segun la metadata cargada, hay {len(filtered_rows)} contratos"
        if filter_description:
            answer += f" con {filter_description}"
        if archive_values and (list_requested or len(filtered_rows) <= 12):
            suffix = ", ".join(archive_values[:12])
            if len(archive_values) > 12:
                suffix += ", ..."
            answer += f": {suffix}"
        return answer + ".", len(filtered_rows), narrowed_file_ids

    @classmethod
    def _find_metadata_field(
        cls,
        row: ArchiveMetadataEntry,
        *field_bases: str,
    ) -> tuple[str | None, object | None]:
        allowed_bases = {
            cls._normalize_metadata_field_base(field_base)
            for field_base in field_bases
            if cls._normalize_metadata_field_base(field_base)
        }
        if not allowed_bases:
            return None, None
        for header, value in dict(row.fields or {}).items():
            if cls._normalize_metadata_field_base(header) in allowed_bases:
                return str(header), value
        best_header: str | None = None
        best_value: object | None = None
        best_score = 0

        def _compact_key(value: str) -> str:
            return re.sub(r"[^a-z0-9]", "", cls._normalize_metadata_field_base(value))

        def _ngram_overlap_score(left: str, right: str) -> int:
            if not left or not right:
                return 0
            if len(left) < 3 or len(right) < 3:
                return 1 if left in right or right in left else 0
            left_ngrams = {left[index : index + 3] for index in range(len(left) - 2)}
            right_ngrams = {right[index : index + 3] for index in range(len(right) - 2)}
            return len(left_ngrams & right_ngrams)

        allowed_tokens_by_base = {
            allowed_base: (
                cls._expanded_token_set(allowed_base),
                _compact_key(allowed_base),
            )
            for allowed_base in allowed_bases
        }
        for header, value in dict(row.fields or {}).items():
            header_base = cls._normalize_metadata_field_base(header)
            header_tokens = cls._expanded_token_set(header_base)
            compact_header = _compact_key(header_base)
            if not header_tokens:
                continue
            for allowed_base, (allowed_tokens, compact_allowed) in allowed_tokens_by_base.items():
                if not allowed_tokens:
                    continue
                overlap = len(header_tokens & allowed_tokens)
                minimum_overlap = max(2, min(len(header_tokens), len(allowed_tokens)) - 1)
                ngram_score = _ngram_overlap_score(compact_header, compact_allowed)
                if overlap < minimum_overlap and ngram_score < 4:
                    continue
                score = overlap * 100 + ngram_score
                if score <= best_score:
                    continue
                best_score = score
                best_header = str(header)
                best_value = value
        if best_header is not None:
            return best_header, best_value
        return None, None

    @classmethod
    def _metadata_text_value(cls, row: ArchiveMetadataEntry, *field_bases: str) -> str:
        _, value = cls._find_metadata_field(row, *field_bases)
        return cls._format_metadata_value(value)

    @classmethod
    def _normalize_contract_state(cls, value: object | None) -> str:
        normalized = cls._normalize_text(value)
        if "vigent" in normalized:
            return "vigente"
        if "vencid" in normalized:
            return "vencido"
        if "terminad" in normalized:
            return "terminado"
        return ""

    @classmethod
    def _build_multi_contract_site_answer(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> tuple[str, int]:
        site_to_contract_ids: dict[str, set[str]] = defaultdict(set)
        for row in metadata_rows:
            site_code = cls._metadata_text_value(row, "codigo de sitio")
            contract_id = cls._metadata_text_value(row, "id")
            if not site_code or not contract_id:
                continue
            site_to_contract_ids[site_code].add(contract_id)
        repeated_sites = [
            (site_code, sorted(contract_ids, key=lambda item: cls._normalize_text(item)))
            for site_code, contract_ids in site_to_contract_ids.items()
            if len(contract_ids) > 1
        ]
        repeated_sites.sort(key=lambda item: (-len(item[1]), cls._normalize_text(item[0])))
        if not repeated_sites:
            return "No se identificaron sitios con más de un ID de contrato en la metadata cargada.", 0
        fragments = [
            f"{site_code}: {', '.join(contract_ids)}"
            for site_code, contract_ids in repeated_sites[:12]
        ]
        facts_used_count = sum(len(contract_ids) for _, contract_ids in repeated_sites)
        return (
            f"Se identificaron {len(repeated_sites)} sitios con más de un ID de contrato: "
            + "; ".join(fragments)
            + ".",
            facts_used_count,
        )

    @classmethod
    def _build_contract_state_counts_answer(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> tuple[str, int]:
        state_counter: Counter[str] = Counter()
        blank_count = 0
        for row in metadata_rows:
            state = cls._normalize_contract_state(cls._metadata_text_value(row, "estado contrato"))
            if state:
                state_counter[state] += 1
            else:
                blank_count += 1
        answer = (
            "Según la metadata cargada: "
            f"vigentes={int(state_counter.get('vigente', 0))}, "
            f"vencidos={int(state_counter.get('vencido', 0))}, "
            f"terminados={int(state_counter.get('terminado', 0))}"
        )
        if blank_count > 0:
            answer += f", sin estado={blank_count}"
        return answer + ".", len(metadata_rows)

    def _build_top_document_versions_answer(
        self,
        *,
        user_id: int,
        file_ids: list[int],
    ) -> tuple[str | None, int]:
        rows = self._list_user_files(user_id=user_id, file_ids=file_ids)
        if not rows:
            return None, 0
        archive_counter: Counter[str] = Counter()
        file_names_by_archive: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            archive_slug = str(row.get("archive_slug") or "").strip()
            if archive_slug:
                archive_counter[archive_slug] += 1
                file_name = str(row.get("file_input_file_name") or "").strip()
                if file_name:
                    file_names_by_archive[archive_slug].append(file_name)
        if not archive_counter:
            return None, 0
        ranked = sorted(
            archive_counter.items(),
            key=lambda item: (-int(item[1]), self._normalize_text(item[0])),
        )
        if len(ranked) == 1:
            archive_slug, count = ranked[0]
            file_names = sorted(
                {
                    file_name
                    for file_name in file_names_by_archive.get(archive_slug, [])
                    if str(file_name).strip()
                },
                key=self._normalize_text,
            )
            if file_names:
                answer = (
                    f"{archive_slug} tiene {count} documentos/versiones: "
                    + "; ".join(file_names[:20])
                    + "."
                )
                return answer, int(count)
        fragments = [f"{archive_slug} ({count} PDFs)" for archive_slug, count in ranked[:8]]
        answer = "Contratos con más versiones documentales: " + "; ".join(fragments) + "."
        return answer, sum(int(count) for _, count in ranked)

    @classmethod
    def _build_entel_figure_count_answer(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> tuple[str | None, int]:
        normalized_question = cls._normalize_text(question)
        current_only = "vigent" in normalized_question
        explicit_targets = (
            ("entel pcs", "ENTEL PCS"),
            ("entel s.a", "ENTEL S.A."),
            ("entel sa", "ENTEL S.A."),
            ("transam", "TRANSAM"),
        )
        requested_label = ""
        for raw_token, display_label in explicit_targets:
            if raw_token in normalized_question:
                requested_label = display_label
                break

        counts: Counter[str] = Counter()
        for row in metadata_rows:
            state = cls._normalize_contract_state(cls._metadata_text_value(row, "estado contrato"))
            if current_only and state != "vigente":
                continue
            figure_label = cls._metadata_text_value(row, "figura legal")
            if not figure_label:
                continue
            normalized_figure = cls._normalize_text(figure_label)
            if requested_label:
                if cls._normalize_text(requested_label) != normalized_figure:
                    continue
                counts[requested_label] += 1
                continue
            if "entel" in normalized_figure:
                counts[figure_label] += 1

        if not counts:
            return None, 0

        if requested_label:
            count = int(counts.get(requested_label, 0))
            scope_text = "vigentes " if current_only else ""
            return (
                f"Se identificaron {count} contratos {scope_text}firmados por {requested_label} según la metadata cargada.",
                count,
            )

        ranked = sorted(counts.items(), key=lambda item: (-int(item[1]), cls._normalize_text(item[0])))
        scope_text = "vigentes " if current_only else ""
        fragments = [f"{label}: {count}" for label, count in ranked]
        return (
            f"Distribución de contratos {scope_text}por sociedad Entel según la metadata: "
            + "; ".join(fragments)
            + ".",
            sum(int(count) for _, count in ranked),
        )

    @classmethod
    def _question_targets_metadata_document_differences(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return (
            any(token in normalized for token in ("metadata", "metadatos"))
            and "document" in normalized
            and any(token in normalized for token in ("diferencia", "contradic", "vacio", "vacios", "coheren"))
        )

    @classmethod
    def _is_unspecified_metadata_value(cls, value: object | None) -> bool:
        normalized = cls._normalize_text(value)
        return (
            not normalized
            or normalized in {"-", "(blank)"}
            or "no se indica" in normalized
            or "no especifica" in normalized
            or "sin informacion" in normalized
            or "sin metadata" in normalized
        )

    @classmethod
    def _names_loosely_match(cls, left: object | None, right: object | None) -> bool:
        left_normalized = cls._normalize_text(left)
        right_normalized = cls._normalize_text(right)
        if not left_normalized or not right_normalized:
            return True
        if left_normalized in right_normalized or right_normalized in left_normalized:
            return True
        left_tokens = {
            token
            for token in cls._tokenize(left_normalized)
            if token not in _METADATA_STOPWORDS and len(token) > 2
        }
        right_tokens = {
            token
            for token in cls._tokenize(right_normalized)
            if token not in _METADATA_STOPWORDS and len(token) > 2
        }
        if not left_tokens or not right_tokens:
            return True
        overlap = left_tokens & right_tokens
        return len(overlap) >= max(2, min(len(left_tokens), len(right_tokens)) - 1)

    @classmethod
    def _derive_profile_state(cls, profile: dict[str, object], *, reference_date: date) -> str:
        effective_to = profile.get("effective_to")
        if hasattr(effective_to, "date"):
            effective_to = effective_to.date()
        if isinstance(effective_to, datetime):
            effective_to = effective_to.date()
        if not isinstance(effective_to, date):
            return ""
        return "vencido" if effective_to < reference_date else "vigente"

    def _build_metadata_document_difference_answer(
        self,
        *,
        user_id: int,
        question: str,
        file_ids: list[int],
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> tuple[str, int] | None:
        del question
        if not metadata_rows:
            return None

        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        archive_slug_map = {
            int(row.file_id): str(row.archive_slug)
            for row in metadata_rows
            if int(row.file_id) > 0 and str(row.archive_slug or "").strip()
        }
        get_archive_slug_map = getattr(self.file_repository, "get_archive_slug_map_for_file_ids", None)
        if callable(get_archive_slug_map) and safe_file_ids:
            try:
                archive_slug_map.update(
                    {
                        int(file_id): str(archive_slug or "")
                        for file_id, archive_slug in dict(
                            get_archive_slug_map(
                                user_id=int(user_id),
                                file_ids=safe_file_ids,
                                include_shared=True,
                            )
                        ).items()
                        if int(file_id) > 0 and str(archive_slug or "").strip()
                    }
                )
            except Exception:
                pass

        list_current_profiles = getattr(self.repository, "list_current_profiles", None)
        current_profiles_by_archive: dict[str, list[dict[str, object]]] = defaultdict(list)
        if callable(list_current_profiles) and safe_file_ids:
            try:
                profile_rows = list_current_profiles(
                    user_id=int(user_id),
                    file_ids=safe_file_ids,
                    as_of_date=None,
                    include_shared=True,
                )
            except Exception:
                profile_rows = []
            for profile_row in list(profile_rows or []):
                file_id = int(profile_row.get("file_id") or 0)
                archive_slug = str(archive_slug_map.get(file_id) or "").strip()
                if not archive_slug:
                    continue
                archive_key = canonicalize_file_key(archive_slug).lower()
                current_profiles_by_archive[archive_key].append(dict(profile_row))

        priority_fields = (
            ("estado contrato", "Estado Contrato"),
            ("cesion a terceros", "Cesión a Terceros"),
            ("clausula de acceso sitio", "Cláusula de Acceso Sitio"),
            ("renta o precio vigente", "Renta o Precio Vigente"),
            ("nombre de propietario principal", "Nombre de Propietario Principal"),
            ("nombre beneficiario", "Nombre Beneficiario"),
        )
        difference_rows: list[tuple[str, list[str]]] = []
        reference_date = datetime.utcnow().date()
        for row in metadata_rows:
            archive_slug = str(row.archive_slug or "").strip()
            archive_key = canonicalize_file_key(archive_slug).lower()
            issues: list[str] = []

            for field_base, label in priority_fields:
                value = self._metadata_text_value(row, field_base)
                if self._is_unspecified_metadata_value(value):
                    issues.append(f"{label} sin metadata clara")

            current_profile = next(iter(current_profiles_by_archive.get(archive_key) or []), None)
            if current_profile is not None:
                metadata_state = self._normalize_contract_state(self._metadata_text_value(row, "estado contrato"))
                profile_state = self._derive_profile_state(current_profile, reference_date=reference_date)
                if metadata_state and profile_state and metadata_state != profile_state:
                    issues.append(
                        f"Estado metadata={metadata_state} vs documento={profile_state}"
                    )

                metadata_contract_id = self._metadata_text_value(row, "id")
                profile_contract_id = str(current_profile.get("primary_identifier") or "").strip()
                if (
                    metadata_contract_id
                    and profile_contract_id
                    and self._normalize_text(metadata_contract_id) not in self._normalize_text(profile_contract_id)
                ):
                    issues.append(
                        f"ID metadata={metadata_contract_id} vs documento={profile_contract_id}"
                    )

                metadata_site_code = self._metadata_text_value(row, "codigo de sitio")
                profile_site_code = str(current_profile.get("secondary_identifier") or "").strip()
                if (
                    metadata_site_code
                    and profile_site_code
                    and self._normalize_text(metadata_site_code) not in self._normalize_text(profile_site_code)
                ):
                    issues.append(
                        f"Sitio metadata={metadata_site_code} vs documento={profile_site_code}"
                    )

                metadata_owner = self._metadata_text_value(row, "nombre de propietario principal")
                profile_owner = str(current_profile.get("primary_subject") or "").strip()
                if metadata_owner and profile_owner and not self._names_loosely_match(metadata_owner, profile_owner):
                    issues.append("Propietario difiere entre metadata y facts documentales")

                metadata_beneficiary = self._metadata_text_value(row, "nombre beneficiario")
                profile_beneficiary = str(current_profile.get("secondary_subject") or "").strip()
                if (
                    metadata_beneficiary
                    and profile_beneficiary
                    and not self._names_loosely_match(metadata_beneficiary, profile_beneficiary)
                ):
                    issues.append("Beneficiario difiere entre metadata y facts documentales")

            if issues:
                deduped_issues: list[str] = []
                seen_issues: set[str] = set()
                for issue in issues:
                    normalized_issue = self._normalize_text(issue)
                    if not normalized_issue or normalized_issue in seen_issues:
                        continue
                    seen_issues.add(normalized_issue)
                    deduped_issues.append(issue)
                difference_rows.append((archive_slug, deduped_issues[:4]))

        if not difference_rows:
            return (
                "No se detectaron diferencias estructuradas obvias entre la metadata cargada y los facts documentales actuales; "
                "las diferencias finas de cláusulas aún requieren revisión documental dirigida.",
                max(1, len(metadata_rows)),
            )

        difference_rows.sort(key=lambda item: (-len(item[1]), self._normalize_text(item[0])))
        fragments = [f"{archive_slug}: {'; '.join(issues)}" for archive_slug, issues in difference_rows[:8]]
        answer = (
            f"Se detectaron diferencias, vacíos o contradicciones relevantes en {len(difference_rows)} contratos: "
            + " | ".join(fragments)
            + "."
        )
        return answer, sum(len(issues) for _, issues in difference_rows)

    @staticmethod
    def _parse_reference_date(question: str) -> date | None:
        match = re.search(r"si hoy es\s+(.+)$", question or "", flags=re.IGNORECASE)
        if not match:
            return None
        return parse_date_value(match.group(1).strip())

    def _load_archive_metadata_rows(
        self,
        *,
        user_id: int,
        file_ids: list[int],
    ) -> list[ArchiveMetadataEntry]:
        if self.file_repository is None:
            return []
        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        get_archive_metadata_for_file_ids = getattr(self.file_repository, "get_archive_metadata_for_file_ids", None)
        list_archive_metadata_for_user = getattr(self.file_repository, "list_archive_metadata_for_user", None)
        if safe_file_ids and not callable(get_archive_metadata_for_file_ids):
            return []
        if not safe_file_ids and not callable(list_archive_metadata_for_user):
            return []
        if not safe_file_ids:
            try:
                rows = list_archive_metadata_for_user(user_id=int(user_id), include_shared=True)
            except Exception:
                return []
        else:
            try:
                rows = get_archive_metadata_for_file_ids(
                    user_id=int(user_id),
                    file_ids=safe_file_ids,
                    include_shared=True,
                )
            except Exception:
                return []
        parsed_by_archive: dict[str, ArchiveMetadataEntry] = {}
        for row in rows:
            raw_metadata = row.get("metadata_json")
            if hasattr(raw_metadata, "read"):
                raw_metadata = raw_metadata.read()
            try:
                metadata_payload = json.loads(str(raw_metadata or "{}"))
            except Exception:
                continue
            raw_fields = metadata_payload.get("fields")
            if not isinstance(raw_fields, dict):
                continue
            fields: dict[str, object] = {}
            for raw_key, raw_value in raw_fields.items():
                key = str(raw_key or "").strip()
                if not key or key.lower() == "file":
                    continue
                fields[key] = raw_value
            if not fields:
                continue
            archive_slug = str(row.get("archive_slug") or metadata_payload.get("file") or "").strip()
            if not archive_slug:
                continue
            archive_key = archive_slug.lower()
            current_file_id = int(row.get("file_id") or 0)
            existing = parsed_by_archive.get(archive_key)
            if existing is not None:
                if existing.file_id <= 0 and current_file_id > 0:
                    parsed_by_archive[archive_key] = ArchiveMetadataEntry(
                        file_id=current_file_id,
                        archive_slug=existing.archive_slug,
                        fields=existing.fields,
                    )
                continue
            parsed_by_archive[archive_key] = ArchiveMetadataEntry(
                file_id=current_file_id,
                archive_slug=archive_slug,
                fields=fields,
            )
        return list(parsed_by_archive.values())

    @classmethod
    def _filter_metadata_rows_for_explicit_archive_scope(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
        archive_slugs: list[str] | None = None,
    ) -> list[ArchiveMetadataEntry]:
        explicit_archive_slugs = [
            canonicalize_file_key(str(value or "").strip())
            for value in list(archive_slugs or [])
            if canonicalize_file_key(str(value or "").strip())
        ] or extract_candidate_archive_slugs_from_question(question)
        if not explicit_archive_slugs or not metadata_rows:
            return metadata_rows
        allowed_archive_keys = {
            canonicalize_file_key(archive_slug).lower()
            for archive_slug in explicit_archive_slugs
            if canonicalize_file_key(archive_slug)
        }
        if not allowed_archive_keys:
            return metadata_rows
        filtered_rows = [
            row
            for row in metadata_rows
            if canonicalize_file_key(row.archive_slug).lower() in allowed_archive_keys
        ]
        return filtered_rows

    def _expand_document_evidence_file_ids(
        self,
        *,
        user_id: int,
        candidate_file_ids: list[int],
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> list[int]:
        resolved_file_ids = [row.file_id for row in metadata_rows if row.file_id > 0]
        safe_candidate_file_ids = [int(file_id) for file_id in list(candidate_file_ids or []) if int(file_id) > 0]
        if not safe_candidate_file_ids or not metadata_rows or self.file_repository is None:
            return resolved_file_ids
        get_archive_slug_map = getattr(self.file_repository, "get_archive_slug_map_for_file_ids", None)
        if not callable(get_archive_slug_map):
            return resolved_file_ids
        allowed_archive_keys = {
            canonicalize_file_key(row.archive_slug).lower()
            for row in metadata_rows
            if canonicalize_file_key(row.archive_slug)
        }
        if not allowed_archive_keys:
            return resolved_file_ids
        try:
            archive_slug_map = get_archive_slug_map(
                user_id=int(user_id),
                file_ids=safe_candidate_file_ids,
                include_shared=True,
            )
        except Exception:
            return resolved_file_ids
        filtered_file_ids = [
            int(file_id)
            for file_id in safe_candidate_file_ids
            if canonicalize_file_key(str(archive_slug_map.get(int(file_id)) or "")).lower() in allowed_archive_keys
        ]
        return filtered_file_ids or resolved_file_ids

    @staticmethod
    def _normalize_text(value: object | None) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.lower().strip()

    @classmethod
    def _tokenize(cls, value: object | None) -> list[str]:
        return _METADATA_TOKEN_PATTERN.findall(cls._normalize_text(value))

    @classmethod
    def _normalize_metadata_field_base(cls, header: str) -> str:
        normalized = cls._normalize_text(header)
        normalized = re.sub(r"(?:[\s._-]*\d+)+$", "", normalized).strip()
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    @classmethod
    def _token_variants(cls, token: str) -> set[str]:
        normalized = str(token or "").strip().lower()
        if not normalized:
            return set()
        variants = {normalized}
        if len(normalized) > 4 and normalized.endswith("es"):
            variants.add(normalized[:-2])
        if len(normalized) > 3 and normalized.endswith("s"):
            variants.add(normalized[:-1])
        return {item for item in variants if item}

    @classmethod
    def _expanded_token_set(cls, value: object | None) -> set[str]:
        expanded: set[str] = set()
        for token in cls._tokenize(value):
            if token in _METADATA_STOPWORDS:
                continue
            expanded.update(cls._token_variants(token))
        return expanded

    @classmethod
    def _build_metadata_schema(cls, *, metadata_rows: list[ArchiveMetadataEntry]) -> list[MetadataSchemaField]:
        preferred_by_base: dict[str, str] = {}
        field_order: list[str] = []
        value_counts_by_base: dict[str, Counter[str]] = {}
        display_by_base: dict[str, dict[str, str]] = {}
        for row in metadata_rows:
            for header in row.fields.keys():
                base = cls._normalize_metadata_field_base(header)
                if not base or base == "file":
                    continue
                if base not in field_order:
                    field_order.append(base)
                value_counts_by_base.setdefault(base, Counter())
                display_by_base.setdefault(base, {})
                current = preferred_by_base.get(base)
                if current is None:
                    preferred_by_base[base] = str(header)
                else:
                    current_is_exact = cls._normalize_text(current) == base
                    header_is_exact = cls._normalize_text(header) == base
                    if header_is_exact and not current_is_exact:
                        preferred_by_base[base] = str(header)
                raw_value = row.fields.get(header)
                if raw_value is None:
                    continue
                display_value = cls._format_metadata_value(raw_value)
                normalized_value = cls._normalize_text(display_value)
                if not normalized_value:
                    continue
                value_counts_by_base[base][normalized_value] += 1
                display_by_base[base].setdefault(normalized_value, display_value)

        schema: list[MetadataSchemaField] = []
        seen_headers: set[str] = set()
        seen_bases: set[str] = set()
        for row in metadata_rows:
            for header in row.fields.keys():
                base = cls._normalize_metadata_field_base(header)
                preferred = preferred_by_base.get(base or "")
                if not base or not preferred or preferred in seen_headers or base in seen_bases:
                    continue
                seen_headers.add(preferred)
                seen_bases.add(base)
                counts = value_counts_by_base.get(base) or Counter()
                displays = display_by_base.get(base) or {}
                ordered_values = tuple(
                    displays[normalized_value]
                    for normalized_value, _ in counts.most_common(60)
                    if normalized_value in displays
                )
                schema.append(
                    MetadataSchemaField(
                        header=str(preferred),
                        base=base,
                        tokens=tuple(sorted(cls._expanded_token_set(base))),
                        display_values=ordered_values,
                    )
                )
        remaining_bases = [base for base in field_order if base not in seen_bases]
        for base in remaining_bases:
            preferred = preferred_by_base.get(base)
            if not preferred:
                continue
            counts = value_counts_by_base.get(base) or Counter()
            displays = display_by_base.get(base) or {}
            ordered_values = tuple(
                displays[normalized_value]
                for normalized_value, _ in counts.most_common(60)
                if normalized_value in displays
            )
            schema.append(
                MetadataSchemaField(
                    header=str(preferred),
                    base=base,
                    tokens=tuple(sorted(cls._expanded_token_set(base))),
                    display_values=ordered_values,
                )
            )
        return schema

    @classmethod
    def _preferred_metadata_headers(cls, *, metadata_rows: list[ArchiveMetadataEntry]) -> list[str]:
        return [field.header for field in cls._build_metadata_schema(metadata_rows=metadata_rows)]

    @classmethod
    def _score_metadata_alias_match(
        cls,
        *,
        normalized_question: str,
        question_tokens: set[str],
        field_base: str,
    ) -> tuple[int, int]:
        aliases = _METADATA_FIELD_ALIASES.get(field_base, ())
        best_score = 0
        best_index = -1
        for alias in aliases:
            normalized_alias = cls._normalize_text(alias)
            if not normalized_alias:
                continue
            alias_match = re.search(rf"\b{re.escape(normalized_alias)}\b", normalized_question)
            if alias_match is not None:
                score = 260 + len(cls._tokenize(normalized_alias)) * 10 + len(normalized_alias)
                if score > best_score:
                    best_score = score
                    best_index = alias_match.start()
                continue
            alias_tokens = [
                token
                for token in cls._tokenize(normalized_alias)
                if token not in _METADATA_STOPWORDS
            ]
            if not alias_tokens:
                continue
            overlap = [token for token in alias_tokens if token in question_tokens]
            if overlap and len(overlap) == len(alias_tokens):
                score = 180 + len(alias_tokens) * 10
                if score > best_score:
                    best_score = score
                    best_index = 15_000
        return best_score, best_index

    @classmethod
    def _score_schema_field_match(
        cls,
        *,
        normalized_question: str,
        question_tokens: set[str],
        field: MetadataSchemaField,
    ) -> tuple[int, int]:
        if not field.base:
            return 0, -1
        phrase_match = re.search(rf"\b{re.escape(field.base)}\b", normalized_question)
        if phrase_match is not None:
            return 320 + len(field.tokens) * 10 + len(field.base), phrase_match.start()
        field_tokens = set(field.tokens)
        if field_tokens:
            overlap = [token for token in field_tokens if token in question_tokens]
            if overlap and len(overlap) == len(field_tokens):
                return 230 + len(field_tokens) * 10 + len(field.base), 10_000
            if len(overlap) >= max(1, len(field_tokens) - 1) and (len(overlap) * 2) >= len(field_tokens):
                return 150 + len(overlap) * 10 + len(field.base), 20_000
        return cls._score_metadata_alias_match(
            normalized_question=normalized_question,
            question_tokens=question_tokens,
            field_base=field.base,
        )

    @classmethod
    def _iter_metadata_field_phrases(cls, field: MetadataSchemaField) -> tuple[str, ...]:
        phrases = [field.base]
        phrases.extend(
            cls._normalize_text(alias)
            for alias in _METADATA_FIELD_ALIASES.get(field.base, ())
        )
        return tuple(dict.fromkeys(phrase for phrase in phrases if phrase))

    @classmethod
    def _rank_schema_fields_for_text(
        cls,
        *,
        text: str,
        metadata_rows: list[ArchiveMetadataEntry],
        exclude_bases: set[str] | None = None,
        min_score: int = 1,
    ) -> list[tuple[int, int, MetadataSchemaField]]:
        normalized_text = cls._normalize_text(text)
        question_tokens = cls._expanded_token_set(text)
        normalized_exclusions = {
            cls._normalize_metadata_field_base(base)
            for base in list(exclude_bases or set())
            if cls._normalize_metadata_field_base(base)
        }
        candidates: list[tuple[int, int, MetadataSchemaField]] = []
        for field in cls._build_metadata_schema(metadata_rows=metadata_rows):
            if field.base in normalized_exclusions:
                continue
            score, phrase_index = cls._score_schema_field_match(
                normalized_question=normalized_text,
                question_tokens=question_tokens,
                field=field,
            )
            if score < min_score:
                continue
            candidates.append(
                (
                    score,
                    phrase_index if phrase_index >= 0 else 50_000,
                    field,
                )
            )
        candidates.sort(key=lambda item: (-item[0], item[1], item[2].header.lower()))
        return candidates

    @classmethod
    def _metadata_answerability_tokens(
        cls,
        *,
        question: str,
    ) -> set[str]:
        tokens: set[str] = set()
        for token in cls._expanded_token_set(question):
            if not token:
                continue
            if token in _METADATA_STOPWORDS or token in _METADATA_ANSWERABILITY_IGNORE_TOKENS:
                continue
            if any(ch.isdigit() for ch in token):
                continue
            if len(token) <= 1:
                continue
            tokens.add(token)
        return tokens

    @classmethod
    def _metadata_field_answer_tokens(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> set[str]:
        requested_bases = {
            cls._normalize_metadata_field_base(field)
            for field in list(requested_fields or [])
            if cls._normalize_metadata_field_base(field)
        }
        if not requested_bases:
            return set()
        answer_tokens: set[str] = set()
        for field in cls._build_metadata_schema(metadata_rows=metadata_rows):
            if field.base not in requested_bases:
                continue
            answer_tokens.update(cls._expanded_token_set(field.header))
            answer_tokens.update(cls._expanded_token_set(field.base))
            for alias in _METADATA_FIELD_ALIASES.get(field.base, ()):
                answer_tokens.update(cls._expanded_token_set(alias))
            for display_value in field.display_values:
                answer_tokens.update(cls._expanded_token_set(display_value))
        return {
            token
            for token in answer_tokens
            if token and token not in _METADATA_STOPWORDS and not any(ch.isdigit() for ch in token)
        }

    @classmethod
    def _metadata_fields_cover_question(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> tuple[bool, list[str]]:
        question_tokens = cls._metadata_answerability_tokens(question=question)
        if not question_tokens:
            return True, []
        answer_tokens = cls._metadata_field_answer_tokens(
            metadata_rows=metadata_rows,
            requested_fields=requested_fields,
        )
        if not answer_tokens:
            return False, sorted(question_tokens)
        missing = sorted(token for token in question_tokens if token not in answer_tokens)
        return not missing, missing

    @classmethod
    def _metadata_question_requests_open_answer(cls, question: str) -> bool:
        question_tokens = cls._metadata_answerability_tokens(question=question)
        return any(token in question_tokens for token in _METADATA_OPEN_ANSWER_TOKENS)

    @classmethod
    def _metadata_is_sufficient_for_answer(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
        explicit_metadata_fields: bool,
        metadata_forced: bool,
        document_evidence_requested: bool,
        document_centric_question: bool,
    ) -> tuple[bool, str]:
        if document_evidence_requested or document_centric_question:
            return False, "document evidence was requested"
        if explicit_metadata_fields or metadata_forced:
            return True, "explicit metadata field request"
        if cls._metadata_question_requests_open_answer(question):
            return False, "the question asks for an explanatory answer"
        covered, missing_tokens = cls._metadata_fields_cover_question(
            question=question,
            metadata_rows=metadata_rows,
            requested_fields=requested_fields,
        )
        if covered:
            return True, "requested metadata fields cover the question"
        preview = ", ".join(missing_tokens[:6])
        return False, "metadata fields do not cover the whole question" + (f" ({preview})" if preview else "")

    @classmethod
    def _field_is_explicit_analytics_target(
        cls,
        *,
        normalized_question: str,
        field: MetadataSchemaField,
    ) -> bool:
        bridge_blockers = ("contrat", "archivo", "archivos", "folio", "folios", "document", "file")
        for phrase in cls._iter_metadata_field_phrases(field):
            target_match = re.search(
                rf"\b(?:que|cuales|cuantos|cuantas|lista(?:me)?|muestrame|muestra|top|ranking)\b"
                rf"(?P<bridge>(?:\s+\w+){{0,5}})\s+{re.escape(phrase)}\b",
                normalized_question,
            )
            if target_match is not None:
                bridge = str(target_match.group("bridge") or "")
                if not any(token in bridge for token in bridge_blockers):
                    return True
            if re.search(
                rf"\b{re.escape(phrase)}\b\s+(?:hay|existen|distint\w*|diferent\w*|repetid\w*|duplicad\w*)",
                normalized_question,
            ):
                return True
        return False

    @classmethod
    def _question_requests_duplicate_analytics(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in ("mas de un", "mas de una", "multiples", "repetid", "duplicad")
        )

    @classmethod
    def _resolve_duplicate_metadata_analytics(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
        filter_description: str = "",
    ) -> tuple[str, int, list[int]] | None:
        if not metadata_rows or not cls._question_requests_duplicate_analytics(question):
            return None

        normalized_question = cls._normalize_text(question)
        split_match = re.search(
            r"\b(?:mas de un(?:a)?|multiples|repetid\w*|duplicad\w*)\b",
            normalized_question,
        )
        before_text = question
        after_text = question
        if split_match is not None:
            before_text = question[: split_match.start()]
            after_text = question[split_match.end() :]

        group_candidates = cls._rank_schema_fields_for_text(
            text=before_text or question,
            metadata_rows=metadata_rows,
            min_score=140,
        )
        group_field = group_candidates[0][2] if group_candidates else None
        compared_candidates = cls._rank_schema_fields_for_text(
            text=after_text or question,
            metadata_rows=metadata_rows,
            exclude_bases={group_field.base} if group_field is not None else None,
            min_score=140,
        )
        compared_field = compared_candidates[0][2] if compared_candidates else None

        if group_field is None or compared_field is None or group_field.base == compared_field.base:
            overall_candidates = cls._rank_schema_fields_for_text(
                text=question,
                metadata_rows=metadata_rows,
                min_score=140,
            )
            distinct_fields: list[MetadataSchemaField] = []
            seen_bases: set[str] = set()
            for _, _, field in overall_candidates:
                if field.base in seen_bases:
                    continue
                seen_bases.add(field.base)
                distinct_fields.append(field)
                if len(distinct_fields) == 2:
                    break
            if len(distinct_fields) < 2:
                return None
            group_field = distinct_fields[0]
            compared_field = distinct_fields[1]

        grouped_values: dict[str, set[str]] = defaultdict(set)
        grouped_file_ids: dict[str, list[int]] = defaultdict(list)
        for row in metadata_rows:
            group_raw = row.fields.get(group_field.header)
            compared_raw = row.fields.get(compared_field.header)
            group_value = cls._format_metadata_value(group_raw)
            compared_value = cls._format_metadata_value(compared_raw)
            if cls._is_unspecified_metadata_value(group_value) or cls._is_unspecified_metadata_value(compared_value):
                continue
            grouped_values[group_value].add(compared_value)
            if int(row.file_id) > 0:
                grouped_file_ids[group_value].append(int(row.file_id))

        repeated_groups = [
            (
                group_value,
                sorted(values, key=cls._normalize_text),
            )
            for group_value, values in grouped_values.items()
            if len(values) > 1
        ]
        repeated_groups.sort(key=lambda item: (-len(item[1]), cls._normalize_text(item[0])))
        if not repeated_groups:
            answer = (
                f"No se encontraron valores de {group_field.header} con mas de un valor distinto en "
                f"{compared_field.header}"
            )
            if filter_description:
                answer += f" con {filter_description}"
            return answer + ".", 0, []

        narrowed_file_ids: list[int] = []
        seen_file_ids: set[int] = set()
        for group_value, _ in repeated_groups:
            for file_id in grouped_file_ids.get(group_value, []):
                if file_id <= 0 or file_id in seen_file_ids:
                    continue
                seen_file_ids.add(file_id)
                narrowed_file_ids.append(file_id)

        fragments = [
            f"{group_value}: {', '.join(values[:10])}"
            for group_value, values in repeated_groups[:12]
        ]
        answer = (
            f"Segun la metadata cargada, se identificaron {len(repeated_groups)} valores de "
            f"{group_field.header} con mas de un valor distinto en {compared_field.header}"
        )
        if filter_description:
            answer += f" con {filter_description}"
        answer += ": " + "; ".join(fragments) + "."
        facts_used_count = sum(len(values) for _, values in repeated_groups)
        return answer, facts_used_count, narrowed_file_ids

    @classmethod
    def _extract_requested_metadata_fields(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> list[str]:
        candidates = cls._rank_schema_fields_for_text(
            text=question,
            metadata_rows=metadata_rows,
            min_score=140,
        )
        if not candidates:
            return []
        return [field.header for _, _, field in candidates[:4]]

    @classmethod
    def _resolve_structured_metadata_fields(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        metadata_fields: list[str] | None,
    ) -> list[str]:
        safe_requested = [str(field or "").strip() for field in list(metadata_fields or []) if str(field or "").strip()]
        if not safe_requested:
            return []
        if not metadata_rows:
            raise ScopeResolutionError(
                "No metadata is available for the current scope.",
                status_code=404,
            )
        available_fields = cls._build_metadata_schema(metadata_rows=metadata_rows)
        normalized_map: dict[str, str] = {}
        for field in available_fields:
            normalized_map[cls._normalize_text(field.header)] = field.header
            normalized_map[field.base] = field.header
        resolved: list[str] = []
        seen: set[str] = set()
        missing: list[str] = []
        for requested in safe_requested:
            matched = normalized_map.get(cls._normalize_text(requested))
            if not matched:
                missing.append(requested)
                continue
            lowered = matched.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            resolved.append(matched)
        if missing:
            raise ScopeResolutionError(
                "Unknown metadata field(s) for the current scope: " + ", ".join(missing) + ".",
                status_code=404,
            )
        return resolved

    @staticmethod
    def _question_requests_comparison(question: str) -> bool:
        normalized = QuestionFactResolver._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "compara",
                "comparar",
                "comparacion",
                "comparacion",
                "diferencia",
                "diferencias",
                "versus",
            )
        )

    @staticmethod
    def _question_requests_document_evidence(question: str) -> bool:
        normalized = QuestionFactResolver._normalize_text(question)
        return bool(
            ".pdf" in normalized
            or any(
                token in normalized
                for token in (
                    "documentos contractuales",
                    "documentos vigentes",
                    "dicen los documentos",
                    "lo que dicen los documentos",
                    "evidencia",
                    "texto contractual",
                    "texto del contrato",
                    "que dice",
                    "que indica",
                    "ultima modific",
                    "ultima version",
                    "ultimo contrato vigente",
                    "modific",
                    "modificaci",
                    "version",
                    "linea de tiempo",
                    "linea del tiempo",
                    "documento base",
                    "contrato base",
                    "clausula",
                    "contradic",
                    "pagina",
                    "paginas",
                    "usando metadata y documentos",
                )
            )
        )

    @classmethod
    def _question_requests_interpretive_followup(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "parece",
                "parecen",
                "vigent",
                "vigencia",
                "coheren",
                "coherencia",
                "diferencias claras",
                "si ambos",
                "si los dos",
            )
        )

    @staticmethod
    def _requested_metadata_has_gaps(
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> bool:
        safe_fields = [str(field).strip() for field in list(requested_fields or []) if str(field).strip()]
        if not safe_fields:
            return False
        for row in metadata_rows:
            fields = dict(row.fields or {})
            for field in safe_fields:
                value = fields.get(field)
                if value is None:
                    return True
                if isinstance(value, str) and not value.strip():
                    return True
        return False

    @classmethod
    def _extract_expected_value(cls, *, question: str, field_header: str) -> str | None:
        normalized_question = cls._normalize_text(question)
        field_base = cls._normalize_metadata_field_base(field_header)
        if not field_base:
            return None
        match = re.search(
            rf"{re.escape(field_base)}\s+(?:es|sea|igual a|equivale a|corresponde a)\s+([^?.,;]+)",
            normalized_question,
            flags=re.IGNORECASE,
        )
        if not match:
            match = re.search(
                rf"{re.escape(field_base)}(?:\s+(?!y\b|e\b|o\b)\w+){{0,4}}\s+"
                rf"(?:es|sea|igual a|equivale a|corresponde a)\s+([^?.,;]+)",
                normalized_question,
                flags=re.IGNORECASE,
            )
        if not match:
            return None
        extracted = match.group(1).strip()
        extracted = re.split(r"\b(?:ademas|adicionalmente|luego|pero|y)\b", extracted, maxsplit=1)[0].strip()
        return extracted or None

    @classmethod
    def _metadata_value_matches(cls, *, actual_value: object, expected_value: str | None) -> bool:
        if expected_value is None:
            return False
        actual_normalized = cls._normalize_text(actual_value)
        expected_normalized = cls._normalize_text(expected_value)
        if not actual_normalized or not expected_normalized:
            return False
        if actual_normalized == expected_normalized:
            return True
        if isinstance(actual_value, bool):
            if actual_value and expected_normalized in _BOOLEAN_TRUE:
                return True
            if not actual_value and expected_normalized in _BOOLEAN_FALSE:
                return True
        actual_tokens = {
            token
            for token in cls._tokenize(actual_normalized)
            if token not in _METADATA_STOPWORDS
        }
        expected_tokens = {
            token
            for token in cls._tokenize(expected_normalized)
            if token not in _METADATA_STOPWORDS
        }
        return bool(expected_tokens) and expected_tokens.issubset(actual_tokens)

    @staticmethod
    def _format_metadata_value(value: object) -> str:
        if value is True:
            return "SI"
        if value is False:
            return "NO"
        return str(value or "").strip()

    @classmethod
    def _rank_metadata_field_for_context(cls, field_name: str) -> int:
        normalized = cls._normalize_text(field_name)
        if not normalized:
            return 0
        score = 0
        priority_groups = (
            (90, ("estado", "actividad", "revision", "validacion", "calidad")),
            (85, ("renta", "precio", "monto", "canon", "valor", "moneda", "uf", "iva")),
            (80, ("fecha", "termino", "inicio", "vigencia", "duracion", "plazo", "prorroga", "aviso")),
            (70, ("beneficiario", "propietario", "arrendador", "arrendatario", "representante", "rut")),
            (60, ("tipo de contrato", "figura legal", "codigo de sitio", "id")),
            (45, ("notaria", "repertorio", "comuna", "region", "direccion")),
        )
        for weight, terms in priority_groups:
            if any(term in normalized for term in terms):
                score = max(score, weight)
        return score

    @classmethod
    def _prioritize_metadata_context_items(cls, fields: dict[str, object]) -> list[str]:
        ranked_items: list[tuple[int, int, str, str]] = []
        for index, (raw_key, raw_value) in enumerate(fields.items()):
            key = str(raw_key or "").strip()
            if not key or raw_value is None:
                continue
            value = cls._format_metadata_value(raw_value)
            if not value:
                continue
            ranked_items.append((cls._rank_metadata_field_for_context(key), index, key, value))
        if not ranked_items:
            return []
        selected: list[tuple[int, int, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for collection in (
            sorted(ranked_items, key=lambda item: (-item[0], item[1]))[:40],
            ranked_items[:16],
        ):
            for score, index, key, value in collection:
                dedupe_key = (cls._normalize_text(key), cls._normalize_text(value))
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                selected.append((score, index, key, value))
        selected.sort(key=lambda item: (-item[0], item[1]))
        return [f"{key}={value}" for _, _, key, value in selected]

    @classmethod
    def _build_metadata_field_context_lines(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
    ) -> list[str]:
        lines: list[str] = []
        for row in metadata_rows:
            field_parts = []
            for header in requested_fields:
                if header not in row.fields or row.fields.get(header) is None:
                    continue
                field_parts.append(f"{header}={cls._format_metadata_value(row.fields[header])}")
            if field_parts:
                lines.append(f"{row.archive_slug}: {'; '.join(field_parts)}")
        return lines

    @classmethod
    def _build_metadata_difference_context_lines(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> list[str]:
        if len(metadata_rows) < 2:
            return []
        lines: list[str] = []
        for header in cls._preferred_metadata_headers(metadata_rows=metadata_rows):
            values_by_archive: list[tuple[str, str]] = []
            seen_normalized_values: set[str] = set()
            for row in metadata_rows:
                if header not in row.fields or row.fields.get(header) is None:
                    continue
                display_value = cls._format_metadata_value(row.fields[header])
                normalized_value = cls._normalize_text(display_value)
                if not normalized_value:
                    continue
                values_by_archive.append((row.archive_slug, display_value))
                seen_normalized_values.add(normalized_value)
            if len(values_by_archive) < 2 or len(seen_normalized_values) <= 1:
                continue
            rendered = "; ".join(f"{archive_slug}: {value}" for archive_slug, value in values_by_archive)
            lines.append(f"{header}: {rendered}")
        return lines[:8]

    @classmethod
    def _question_requests_monthly_equivalent(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "canon mensual",
                "mensual equivalente",
                "equivalente mensual",
                "por mes",
            )
        )

    @classmethod
    def _question_requests_total_initial_term(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return bool(
            any(token in normalized for token in ("total estimado", "total de pagos", "total por canon"))
            and any(token in normalized for token in ("vigencia inicial", "durante la vigencia inicial", "canon"))
        )

    @classmethod
    def _question_requests_remaining_term(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "cuanto tiempo resta",
                "tiempo resta",
                "resta para el vencimiento",
                "vencimiento o renovacion",
                "hitos deben vigilarse",
            )
        )

    @classmethod
    def _question_requests_contract_term_summary(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return "plazo contractual" in normalized or ("plazo" in normalized and "fecha de termino" in normalized)

    @classmethod
    def _question_requests_next_renewal_window(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "siguiente vencimiento",
                "ventana de salida",
                "si existe prorroga automatica",
            )
        )

    @classmethod
    def _question_requests_rent_change_summary(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "como cambian la renta",
                "cambian la renta",
                "renta, plazo y estado",
            )
        )

    @classmethod
    def _parse_numeric_metadata_value(cls, value: object | None) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        cleaned = re.sub(r"[^0-9,.\-]", "", str(value or "").strip())
        if not cleaned or cleaned in {"-", ".", ","}:
            return None
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif cleaned.count(",") == 1 and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    @classmethod
    def _parse_payment_period_months(cls, value: object | None) -> int | None:
        normalized = cls._normalize_text(value)
        if not normalized:
            return None
        if "mensual" in normalized:
            return 1
        if "bimestral" in normalized:
            return 2
        if "trimestral" in normalized:
            return 3
        if "semestral" in normalized:
            return 6
        if "anual" in normalized:
            return 12
        cadence_match = re.search(r"cada\s+(\d+)\s+(ano|anos|mes|meses)", normalized)
        if cadence_match is not None:
            quantity = int(cadence_match.group(1) or 0)
            unit = str(cadence_match.group(2) or "")
            if quantity <= 0:
                return None
            return quantity * 12 if "ano" in unit else quantity
        return None

    @classmethod
    def _parse_duration_months_and_days(cls, value: object | None) -> tuple[int, int] | None:
        normalized = cls._normalize_text(value).replace(" ", "")
        if not normalized:
            return None
        encoded_match = re.search(r"(\d+)a-(\d+)m-(\d+)d", normalized)
        if encoded_match is not None:
            years = int(encoded_match.group(1) or 0)
            months = int(encoded_match.group(2) or 0)
            days = int(encoded_match.group(3) or 0)
            return years * 12 + months, days
        return None

    @staticmethod
    def _months_between_dates(start_value: date, end_value: date) -> tuple[int, int]:
        months = (end_value.year - start_value.year) * 12 + (end_value.month - start_value.month)
        days = end_value.day - start_value.day
        if days < 0:
            months -= 1
            days += 30
        return max(0, months), max(0, days)

    @staticmethod
    def _humanize_duration(months: int, days: int = 0) -> str:
        years, remaining_months = divmod(max(0, int(months)), 12)
        parts: list[str] = []
        if years:
            parts.append(f"{years} año" + ("s" if years != 1 else ""))
        if remaining_months:
            parts.append(f"{remaining_months} mes" + ("es" if remaining_months != 1 else ""))
        if days:
            parts.append(f"{days} dia" + ("s" if days != 1 else ""))
        if not parts:
            return "0 meses"
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " y " + parts[-1]

    @classmethod
    def _humanize_duration_value(cls, value: object | None) -> str:
        parsed = cls._parse_duration_months_and_days(value)
        if parsed is None:
            return str(value or "").strip()
        months, days = parsed
        return cls._humanize_duration(months, days)

    @staticmethod
    def _format_decimal_for_answer(value: float, *, decimals: int = 2) -> str:
        rounded = round(float(value), int(decimals))
        if abs(rounded - round(rounded)) < 1e-9:
            return str(int(round(rounded)))
        rendered = f"{rounded:.{int(decimals)}f}".rstrip("0").rstrip(".")
        return rendered.replace(".", ",")

    @classmethod
    def _format_amount_with_currency(cls, amount: float, currency: str) -> str:
        base = cls._format_decimal_for_answer(amount)
        currency_text = str(currency or "").strip()
        return f"{base} {currency_text}".strip()

    @classmethod
    def _build_payment_frequency_phrase(
        cls,
        *,
        amount: float,
        currency: str,
        period_text: str,
    ) -> str:
        normalized_period = cls._normalize_text(period_text)
        amount_text = cls._format_amount_with_currency(amount, currency)
        if normalized_period.startswith("cada "):
            return f"{amount_text} {str(period_text or '').strip().lower()}".strip()
        if "mensual" in normalized_period:
            return f"{amount_text} mensuales"
        if "anual" in normalized_period:
            return f"{amount_text} anuales"
        if "semestral" in normalized_period:
            return f"{amount_text} semestrales"
        return f"{amount_text} por periodo ({str(period_text or '').strip()})".strip()

    @staticmethod
    def _add_months(base_date: date, months: int) -> date:
        total_months = (base_date.year * 12 + (base_date.month - 1)) + int(months)
        year = total_months // 12
        month = (total_months % 12) + 1
        day = min(base_date.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @classmethod
    def _parse_metadata_date_field(
        cls,
        row: ArchiveMetadataEntry,
        *field_bases: str,
    ) -> date | None:
        _, raw_value = cls._find_metadata_field(row, *field_bases)
        if raw_value is None:
            return None
        return parse_date_value(cls._format_metadata_value(raw_value))

    @classmethod
    def _build_monthly_equivalent_answer(
        cls,
        *,
        row: ArchiveMetadataEntry,
    ) -> str | None:
        amount = cls._parse_numeric_metadata_value(cls._metadata_text_value(row, "renta o precio vigente"))
        period_text = cls._metadata_text_value(row, "periodo de pago")
        currency = cls._metadata_text_value(row, "tipo de moneda")
        period_months = cls._parse_payment_period_months(period_text)
        if amount is None or not period_text or period_months is None or period_months <= 0:
            return None
        monthly_amount = amount / float(period_months)
        payment_phrase = cls._build_payment_frequency_phrase(
            amount=amount,
            currency=currency,
            period_text=period_text,
        )
        monthly_text = cls._format_amount_with_currency(monthly_amount, currency)
        return (
            f"Segun la metadata de {row.archive_slug}, el canon vigente es {payment_phrase}, "
            f"equivalente a {monthly_text} por mes."
        )

    @classmethod
    def _build_total_initial_term_answer(
        cls,
        *,
        row: ArchiveMetadataEntry,
    ) -> str | None:
        amount = cls._parse_numeric_metadata_value(cls._metadata_text_value(row, "renta o precio vigente"))
        period_text = cls._metadata_text_value(row, "periodo de pago")
        currency = cls._metadata_text_value(row, "tipo de moneda")
        period_months = cls._parse_payment_period_months(period_text)
        duration_value = cls._metadata_text_value(row, "duracion inicial del contrato")
        duration_parts = cls._parse_duration_months_and_days(duration_value)
        if duration_parts is None:
            start_date = cls._parse_metadata_date_field(row, "fecha de inicio de vigencia del contrato")
            end_date = cls._parse_metadata_date_field(row, "fecha de termino del contrato")
            if start_date is not None and end_date is not None and end_date >= start_date:
                duration_parts = cls._months_between_dates(start_date, end_date)
        if amount is None or not period_text or period_months is None or duration_parts is None:
            return None
        duration_months, duration_days = duration_parts
        if duration_months <= 0:
            return None
        estimated_periods = duration_months / float(period_months)
        total_amount = amount * estimated_periods
        payment_phrase = cls._build_payment_frequency_phrase(
            amount=amount,
            currency=currency,
            period_text=period_text,
        )
        duration_text = cls._humanize_duration(duration_months, duration_days)
        total_text = cls._format_amount_with_currency(total_amount, currency)
        return (
            f"Segun la metadata de {row.archive_slug}, durante la vigencia inicial ({duration_text}) "
            f"el canon corresponde a {payment_phrase}, para un total estimado de {total_text}."
        )

    @classmethod
    def _build_contract_term_summary_answer(
        cls,
        *,
        row: ArchiveMetadataEntry,
    ) -> str | None:
        duration_value = cls._metadata_text_value(row, "duracion inicial del contrato")
        duration_parts = cls._parse_duration_months_and_days(duration_value)
        if duration_parts is None:
            start_date = cls._parse_metadata_date_field(row, "fecha de inicio de vigencia del contrato")
            end_date = cls._parse_metadata_date_field(row, "fecha de termino del contrato")
            if start_date is not None and end_date is not None and end_date >= start_date:
                duration_parts = cls._months_between_dates(start_date, end_date)
        start_date = cls._parse_metadata_date_field(row, "fecha de inicio de vigencia del contrato")
        end_date = cls._parse_metadata_date_field(row, "fecha de termino del contrato")
        renewal_flag = cls._metadata_text_value(row, "prorroga automatica")
        renewal_period = cls._metadata_text_value(row, "periodo prorroga automatica")
        if duration_parts is None and end_date is None:
            return None
        fragments: list[str] = []
        if start_date is not None:
            fragments.append(f"parte el {start_date.strftime('%d/%m/%Y')}")
        if duration_parts is not None:
            duration_months, duration_days = duration_parts
            fragments.append(f"el plazo contractual vigente es {cls._humanize_duration(duration_months, duration_days)}")
        if end_date is not None:
            fragments.append(f"la fecha de termino es {end_date.strftime('%d/%m/%Y')}")
        if renewal_flag:
            fragments.append(f"Prórroga Automática: {cls._format_metadata_value(renewal_flag)}")
        if renewal_period and cls._normalize_text(renewal_flag) in _BOOLEAN_TRUE:
            fragments.append(
                "Periodo Prórroga Automática: " + cls._humanize_duration_value(renewal_period)
            )
        if not fragments:
            return None
        return f"Segun la metadata de {row.archive_slug}, " + "; ".join(fragments) + "."

    @classmethod
    def _build_remaining_term_answer(
        cls,
        *,
        row: ArchiveMetadataEntry,
        reference_date: date,
    ) -> str | None:
        end_date = cls._parse_metadata_date_field(row, "fecha de termino del contrato")
        if end_date is None:
            return None
        notice_date = cls._parse_metadata_date_field(row, "fecha de aviso de termino del contrato")
        renewal_flag = cls._metadata_text_value(row, "prorroga automatica")
        renewal_period = cls._metadata_text_value(row, "periodo prorroga automatica")
        delta_days = (end_date - reference_date).days
        fragments: list[str] = []
        if delta_days >= 0:
            fragments.append(
                f"al {reference_date.strftime('%d/%m/%Y')} restan {delta_days} dias para el vencimiento ({end_date.strftime('%d/%m/%Y')})"
            )
        else:
            fragments.append(
                f"al {reference_date.strftime('%d/%m/%Y')} el contrato aparece vencido hace {abs(delta_days)} dias ({end_date.strftime('%d/%m/%Y')})"
            )
        if notice_date is not None:
            notice_text = notice_date.strftime("%d/%m/%Y")
            if notice_date >= reference_date:
                fragments.append(f"la fecha de aviso es {notice_text}")
            else:
                fragments.append(f"la fecha de aviso fue {notice_text}")
        if renewal_flag:
            fragments.append(f"Prórroga Automática: {cls._format_metadata_value(renewal_flag)}")
        if renewal_period and cls._normalize_text(renewal_flag) in _BOOLEAN_TRUE:
            fragments.append(
                "Periodo Prórroga Automática: " + cls._humanize_duration_value(renewal_period)
            )
        return f"Segun la metadata de {row.archive_slug}, " + "; ".join(fragments) + "."

    @classmethod
    def _build_next_renewal_window_answer(
        cls,
        *,
        row: ArchiveMetadataEntry,
    ) -> str | None:
        end_date = cls._parse_metadata_date_field(row, "fecha de termino del contrato")
        notice_date = cls._parse_metadata_date_field(row, "fecha de aviso de termino del contrato")
        renewal_flag = cls._metadata_text_value(row, "prorroga automatica")
        renewal_period = cls._metadata_text_value(row, "periodo prorroga automatica")
        if end_date is None:
            return None
        renewal_months = cls._parse_payment_period_months(renewal_period)
        if renewal_months is None:
            parsed_duration = cls._parse_duration_months_and_days(renewal_period)
            if parsed_duration is not None:
                renewal_months = parsed_duration[0]
        if cls._normalize_text(renewal_flag) in _BOOLEAN_TRUE and renewal_months is not None and renewal_months > 0:
            next_end_date = cls._add_months(end_date, renewal_months)
            fragments = [
                f"el vencimiento actual es {end_date.strftime('%d/%m/%Y')}",
                f"el siguiente vencimiento seria {next_end_date.strftime('%d/%m/%Y')}",
                f"Prórroga Automática: {cls._format_metadata_value(renewal_flag)}",
                "Periodo Prórroga Automática: " + cls._humanize_duration_value(renewal_period),
            ]
            if notice_date is not None:
                fragments.append(f"si no se da aviso antes del {notice_date.strftime('%d/%m/%Y')}")
                next_notice_date = cls._add_months(notice_date, renewal_months)
                fragments.append(
                    f"la siguiente ventana de salida seria {next_notice_date.strftime('%d/%m/%Y')}"
                )
            return f"Segun la metadata de {row.archive_slug}, " + "; ".join(fragments) + "."
        fragments = [
            f"no existe prorroga automatica para {row.archive_slug}",
            f"el vencimiento actual es {end_date.strftime('%d/%m/%Y')}",
        ]
        if notice_date is not None:
            fragments.append(f"la ventana de salida vigente se notifica el {notice_date.strftime('%d/%m/%Y')}")
        return "Segun la metadata, " + "; ".join(fragments) + "."

    @classmethod
    def _build_multi_row_rent_change_answer(
        cls,
        *,
        metadata_rows: list[ArchiveMetadataEntry],
    ) -> str | None:
        if len(metadata_rows) < 2:
            return None
        fragments: list[str] = []
        for row in metadata_rows:
            field_parts: list[str] = []
            site_code = cls._metadata_text_value(row, "codigo de sitio")
            if site_code:
                field_parts.append(f"Codigo de Sitio: {site_code}")
            contract_state = cls._metadata_text_value(row, "estado contrato")
            if contract_state:
                field_parts.append(f"Estado Contrato: {contract_state}")
            amount = cls._parse_numeric_metadata_value(cls._metadata_text_value(row, "renta o precio vigente"))
            currency = cls._metadata_text_value(row, "tipo de moneda")
            period_text = cls._metadata_text_value(row, "periodo de pago")
            if amount is not None and period_text:
                field_parts.append(
                    "Canon: "
                    + cls._build_payment_frequency_phrase(
                        amount=amount,
                        currency=currency,
                        period_text=period_text,
                    )
                )
            term_date = cls._parse_metadata_date_field(row, "fecha de termino del contrato")
            if term_date is not None:
                field_parts.append(f"Fecha de Término del Contrato: {term_date.strftime('%d/%m/%Y')}")
            if field_parts:
                fragments.append(f"{row.archive_slug} -> " + "; ".join(field_parts))
        if not fragments:
            return None
        return "Cambios de renta y plazo segun metadata: " + " | ".join(fragments) + "."

    @classmethod
    def _build_metadata_derived_answer(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
        compare_requested: bool,
        reference_date: date,
    ) -> tuple[str, int] | None:
        del requested_fields
        if len(metadata_rows) >= 2 and cls._question_requests_rent_change_summary(question):
            answer = cls._build_multi_row_rent_change_answer(metadata_rows=metadata_rows)
            if answer:
                return answer, len(metadata_rows) * 4
        if len(metadata_rows) != 1:
            return None
        row = metadata_rows[0]
        if cls._question_requests_monthly_equivalent(question):
            answer = cls._build_monthly_equivalent_answer(row=row)
            if answer:
                return answer, 3
        if cls._question_requests_total_initial_term(question):
            answer = cls._build_total_initial_term_answer(row=row)
            if answer:
                return answer, 5
        if cls._question_requests_contract_term_summary(question):
            answer = cls._build_contract_term_summary_answer(row=row)
            if answer:
                return answer, 5
        if cls._question_requests_remaining_term(question):
            answer = cls._build_remaining_term_answer(
                row=row,
                reference_date=reference_date,
            )
            if answer:
                return answer, 4
        if cls._question_requests_next_renewal_window(question):
            answer = cls._build_next_renewal_window_answer(row=row)
            if answer:
                return answer, 4
        return None

    @classmethod
    def _build_metadata_answer(
        cls,
        *,
        question: str,
        metadata_rows: list[ArchiveMetadataEntry],
        requested_fields: list[str],
        compare_requested: bool,
    ) -> str | None:
        if not metadata_rows or not requested_fields:
            return None
        if len(metadata_rows) == 1:
            row = metadata_rows[0]
            rendered_fields: list[tuple[str, str]] = []
            validation_rows: list[tuple[str, str, str]] = []
            for header in requested_fields:
                if header not in row.fields or row.fields.get(header) is None:
                    continue
                actual_value = row.fields[header]
                display_value = cls._format_metadata_value(actual_value)
                expected_value = cls._extract_expected_value(question=question, field_header=header)
                if expected_value:
                    if cls._metadata_value_matches(actual_value=actual_value, expected_value=expected_value):
                        validation_rows.append((header, display_value, "coincide"))
                    else:
                        validation_rows.append((header, display_value, f"esperado: {expected_value}"))
                    continue
                rendered_fields.append((header, display_value))
            if len(validation_rows) == 1 and not rendered_fields:
                header, display_value, validation_status = validation_rows[0]
                if validation_status == "coincide":
                    return f"Si, en la metadata de {row.archive_slug} {header} es {display_value}."
                expected_marker = "esperado: "
                if validation_status.startswith(expected_marker):
                    expected_value = validation_status.removeprefix(expected_marker)
                    return (
                        f"No. En la metadata de {row.archive_slug} {header} es {display_value.strip()}, "
                        f"no {expected_value}."
                    )
            if validation_rows:
                table_lines = [
                    "| Campo | Valor | Validacion |",
                    "| --- | --- | --- |",
                    *[
                        (
                            f"| {cls._escape_markdown_table_cell(header)} | "
                            f"{cls._escape_markdown_table_cell(display_value)} | "
                            f"{cls._escape_markdown_table_cell(status)} |"
                        )
                        for header, display_value, status in validation_rows
                    ],
                    *[
                        (
                            f"| {cls._escape_markdown_table_cell(header)} | "
                            f"{cls._escape_markdown_table_cell(display_value)} | - |"
                        )
                        for header, display_value in rendered_fields
                    ],
                ]
                return f"Validacion de metadata para {row.archive_slug}:\n\n" + "\n".join(table_lines)
            if rendered_fields:
                table_lines = [
                    "| Campo | Valor |",
                    "| --- | --- |",
                    *[
                        (
                            f"| {cls._escape_markdown_table_cell(header)} | "
                            f"{cls._escape_markdown_table_cell(display_value)} |"
                        )
                        for header, display_value in rendered_fields
                    ],
                ]
                return f"En la metadata de {row.archive_slug}:\n\n" + "\n".join(table_lines)
            return None

        if len(requested_fields) == 1:
            header = requested_fields[0]
            fragments = []
            table_rows: list[tuple[str, str]] = []
            distinct_values: set[str] = set()
            missing_archives: list[str] = []
            for row in metadata_rows:
                if header not in row.fields or row.fields.get(header) is None:
                    missing_archives.append(row.archive_slug)
                    continue
                display_value = cls._format_metadata_value(row.fields[header])
                fragments.append(f"{row.archive_slug}: {display_value}")
                table_rows.append((str(row.archive_slug or "").strip(), display_value))
                distinct_values.add(cls._normalize_text(display_value))
            if not fragments:
                return None
            table_lines = [
                f"| Archivo | {cls._escape_markdown_table_cell(header)} |",
                "| --- | --- |",
                *[
                    (
                        f"| {cls._escape_markdown_table_cell(archive_slug)} | "
                        f"{cls._escape_markdown_table_cell(display_value)} |"
                    )
                    for archive_slug, display_value in table_rows
                ],
            ]
            answer = f"{header} por archivo:\n\n" + "\n".join(table_lines)
            if compare_requested:
                if missing_archives:
                    answer += "\n\nFalta metadata para: " + ", ".join(missing_archives) + "."
                else:
                    answer += (
                        "\n\nLos valores coinciden."
                        if len(distinct_values) == 1
                        else "\n\nLos valores difieren entre documentos."
                    )
            return answer

        table_rows: list[list[str]] = []
        for row in metadata_rows:
            values: list[str] = []
            has_value = False
            for header in requested_fields:
                if header not in row.fields or row.fields.get(header) is None:
                    values.append("sin metadata" if compare_requested else "")
                    continue
                values.append(cls._format_metadata_value(row.fields[header]))
                has_value = True
            if has_value or (compare_requested and values):
                table_rows.append([str(row.archive_slug or "").strip(), *values])
        if not table_rows:
            return None
        prefix = "Comparacion de metadata" if compare_requested else "Metadata resuelta"
        headers = ["Archivo", *requested_fields]
        table_lines = [
            "| " + " | ".join(cls._escape_markdown_table_cell(header) for header in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for row_values in table_rows:
            padded_values = row_values + [""] * max(0, len(headers) - len(row_values))
            table_lines.append(
                "| " + " | ".join(cls._escape_markdown_table_cell(value) for value in padded_values[: len(headers)]) + " |"
            )
        return prefix + ":\n\n" + "\n".join(table_lines)

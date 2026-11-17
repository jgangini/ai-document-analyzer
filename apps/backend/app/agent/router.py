"""Runtime LLM para routing y rama casual del agente."""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Literal

from pydantic import BaseModel, Field

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.agent.contracts import LLMResult, serialize_evidence
from apps.backend.app.integrations.generative_ai import OCIGenerativeAIService
from apps.backend.app.rag.display_text import repair_document_file_name


class IntentRouteOutput(BaseModel):
    route: Literal["search", "document"]


class SearchReplyOutput(BaseModel):
    reply: str = Field(min_length=1)


class SynthesisOutput(BaseModel):
    answer_text: str
    executive_summary: str
    key_points: list[str]
    obligations: list[str]
    citation_source_numbers: list[int]


class CollaborationOutput(BaseModel):
    confidence_note: str = Field(min_length=1)


class GraphIntentRouter:
    SEARCH_ROUTE = "search"
    DOCUMENT_ROUTE = "document"
    CASUAL_TERMS = (
        "hola", "hello", "hi", "hey", "buenas", "buen dia", "buenos dias",
        "buenas tardes", "buenas noches", "que tal", "como estas", "como andas", "saludos",
    )
    DOCUMENT_HINT_TERMS = (
        "document", "archivo", "pagina", "contrato", "monto", "fecha", "resumen",
        "clausula", "obligacion", "hipoteca", "inscripcion", "ocr", "evidencia",
        "decreto", "resolucion", "factura", "certificado", "anexo", "formulario",
    )

    def __init__(self, provider: OCIGenerativeAIService) -> None:
        self.provider = provider

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()

    @staticmethod
    def _contains_document_code(question: str) -> bool:
        return bool(re.search(r"\b[A-Z]{2,24}[A-Z0-9_-]*\d[A-Z0-9_-]*\b", str(question or "").upper()))

    def _heuristic_route(self, *, question: str, file_ids: list[int]) -> str | None:
        if file_ids:
            return self.DOCUMENT_ROUTE
        normalized = self._normalize(question)
        if not normalized:
            return self.DOCUMENT_ROUTE
        if self._contains_document_code(question):
            return self.DOCUMENT_ROUTE
        if re.search(r"(?:cuenta|contar|count)\s+(?:hasta|to)\s+\d{1,2}", normalized):
            return self.SEARCH_ROUTE
        has_casual = any(term in normalized for term in self.CASUAL_TERMS)
        has_document_hint = any(term in normalized for term in self.DOCUMENT_HINT_TERMS)
        if has_document_hint:
            return self.DOCUMENT_ROUTE
        if has_casual and len(normalized.split()) <= 12:
            return self.SEARCH_ROUTE
        return None

    @staticmethod
    def _format_chat_history(chat_history: list[dict[str, str]] | None, *, limit: int = 8) -> str:
        if not chat_history:
            return "No previous messages."
        relevant = chat_history[-limit:]
        lines: list[str] = []
        for item in relevant:
            role = str(item.get("role", "user")).strip().lower() or "user"
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "No previous messages."

    def classify(
        self,
        *,
        question: str,
        file_ids: list[int],
        chat_history: list[dict[str, str]] | None = None,
    ) -> str:
        heuristic_route = self._heuristic_route(question=question, file_ids=file_ids)
        if heuristic_route in {self.SEARCH_ROUTE, self.DOCUMENT_ROUTE}:
            return heuristic_route
        if not self.provider.is_available():
            return self.DOCUMENT_ROUTE
        history_block = self._format_chat_history(chat_history)
        prompt = (
            "Clasifica la entrada del usuario en una sola ruta.\n\n"
            f"Recent conversation:\n{history_block}\n\n"
            f"Question:\n{question}\n\n"
            f"Selected file ids count: {len(file_ids)}\n\n"
            "Rutas validas:\n"
            "- search: saludos, small-talk o micro-tareas simples y seguras.\n"
            "- document: preguntas documentales, OCR, paginas, clausulas, fechas, montos.\n"
            "Responde solo con route."
        )
        parsed = self.provider.invoke_structured(schema_model=IntentRouteOutput, prompt=prompt)
        route = str(parsed.get("route", "")).strip().lower()
        if route in {self.SEARCH_ROUTE, self.DOCUMENT_ROUTE}:
            return route
        raise RuntimeError("OCI routing model returned an invalid route.")


class GraphSearchResponder:
    def __init__(
        self,
        provider: OCIGenerativeAIService,
        assistant_name_provider: Callable[[], str] | None = None,
    ) -> None:
        self.provider = provider
        self.assistant_name_provider = assistant_name_provider

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()

    @classmethod
    def _is_greeting(cls, question: str) -> bool:
        normalized_question = cls._normalize(question)
        greeting_terms = (
            "hola",
            "hello",
            "hi",
            "hey",
            "buenas",
            "buen dia",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "saludos",
        )
        return any(term in normalized_question for term in greeting_terms)

    @classmethod
    def _contains_forbidden_vendor_mentions(cls, text: str) -> bool:
        normalized = cls._normalize(text)
        forbidden_terms = (
            "google",
            "gemini",
            "openai",
            "anthropic",
            "claude",
            "oci",
            "oracle cloud",
            "llm",
            "modelo",
            "model",
        )
        return any(term in normalized for term in forbidden_terms)

    @staticmethod
    def _format_chat_history(chat_history: list[dict[str, str]] | None, *, limit: int = 8) -> str:
        if not chat_history:
            return "No previous messages."
        relevant = chat_history[-limit:]
        lines: list[str] = []
        for item in relevant:
            role = str(item.get("role", "user")).strip().lower() or "user"
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{role}: {content}")
        return "\n".join(lines) if lines else "No previous messages."

    def _assistant_already_greeted(self, chat_history: list[dict[str, str]] | None) -> bool:
        if not chat_history:
            return False
        recent_assistant_messages = [
            self._normalize(str(item.get("content", "")))
            for item in chat_history[-12:]
            if str(item.get("role", "")).strip().lower() == "assistant"
        ]
        if not recent_assistant_messages:
            return False
        greeting_markers = (
            "hola",
            "hello",
            "hi",
            "hey",
            "buenas",
            "buen dia",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "encantado de ayudarte",
            "en que puedo ayudarte",
        )
        return any(any(marker in msg for marker in greeting_markers) for msg in recent_assistant_messages)

    def _resolve_assistant_name(self) -> str:
        default_name = "Nadia Assist"
        if self.assistant_name_provider is None:
            return default_name
        try:
            resolved = str(self.assistant_name_provider() or "").strip()
            return resolved or default_name
        except Exception:
            return default_name

    def respond(self, *, question: str, chat_history: list[dict[str, str]] | None = None) -> LLMResult:
        assistant_name = self._resolve_assistant_name()
        is_greeting = self._is_greeting(question)
        if is_greeting and self._assistant_already_greeted(chat_history):
            answer_text = (
                f"Hola de nuevo. Soy {assistant_name}, tu asistente de analisis documental. "
                "Puedo ayudarte a buscar, resumir y extraer informacion de tus documentos."
            )
            return LLMResult(
                answer_text=answer_text,
                executive_summary=answer_text,
                key_points=[],
                obligations=[],
                citation_source_numbers=[],
                model_used="langgraph-search-agent-memory",
            )
        if not self.provider.is_available():
            raise RuntimeError("OCI conversational model is not available.")
        history_block = self._format_chat_history(chat_history)
        prompt = (
            f'Assistant name: "{assistant_name}".\n'
            "You are the search/casual branch of a document-analysis assistant.\n"
            "Always answer in the same language as the user message.\n\n"
            f"Recent conversation:\n{history_block}\n\n"
            f"User message:\n{question}\n\n"
            "Rules:\n"
            "- Keep it concise: maximum 2 short sentences.\n"
            "- Friendly and natural tone; if it is a greeting, greet first.\n"
            f'- If this is a greeting, explicitly present yourself as "{assistant_name}" and explain your function as a document-analysis assistant.\n'
            "- If the assistant already greeted in the recent conversation, avoid greeting again.\n"
            "- For complex/off-topic requests, politely decline and redirect to document analysis.\n"
            "- Do not invent capabilities outside document QA.\n"
            "- Never mention model vendors, providers, cloud brands, or implementation technology (e.g., Google, Gemini, OpenAI, OCI, Oracle Cloud), unless the user explicitly asks for technical details.\n"
            "Return only 'reply'."
        )
        parsed = self.provider.invoke_structured(schema_model=SearchReplyOutput, prompt=prompt)
        answer_text = str(parsed.get("reply", "")).strip()
        if not answer_text:
            raise RuntimeError("OCI conversational model returned an empty reply.")
        if is_greeting and (
            self._contains_forbidden_vendor_mentions(answer_text)
            or self._normalize(assistant_name) not in self._normalize(answer_text)
        ):
            answer_text = (
                f"Hola, soy {assistant_name}, tu asistente de analisis documental. "
                "Puedo ayudarte a buscar, resumir y extraer informacion de tus documentos."
            )
        return LLMResult(
            answer_text=answer_text,
            executive_summary=answer_text,
            key_points=[],
            obligations=[],
            citation_source_numbers=[],
            model_used="langgraph-search-agent",
        )


class GraphSynthesis:
    MAX_EVIDENCE_CHARS = 32000
    MAX_SUMMARY_CHARS_PER_SOURCE = 1600
    MARKDOWN_TABLE_PATTERN = re.compile(
        r"(^|\n)\s*\|.+\|\s*\n\s*\|(?:\s*:?-{3,}:?\s*\|)+",
        flags=re.MULTILINE,
    )

    def __init__(self, provider: OCIGenerativeAIService) -> None:
        self.provider = provider

    @classmethod
    def _build_bounded_evidence_text(cls, evidence: list[EvidenceItem]) -> str:
        if not evidence:
            return "No evidence provided."
        lines: list[str] = []
        used = 0
        for index, item in enumerate(evidence, start=1):
            summary_text = str(item.summary_text or "").replace("\n", " ").strip()
            if len(summary_text) > cls.MAX_SUMMARY_CHARS_PER_SOURCE:
                summary_text = summary_text[: cls.MAX_SUMMARY_CHARS_PER_SOURCE].rstrip() + "..."
            archive_part = f" archive={item.archive_slug}" if str(item.archive_slug or "").strip() else ""
            line = (
                f"[Source {index}]{archive_part} file={item.file_name} page={item.page_number} "
                f"score={item.score:.4f} summary={summary_text}"
            )
            projected = used + len(line) + 1
            if lines and projected > cls.MAX_EVIDENCE_CHARS:
                break
            lines.append(line)
            used = projected
        return "\n".join(lines) if lines else "No evidence provided."

    @staticmethod
    def _extract_section(raw_text: str, section_name: str, next_sections: list[str]) -> str:
        if not raw_text:
            return ""
        escaped_section = re.escape(section_name)
        next_pattern = "|".join(re.escape(item) for item in next_sections)
        pattern = (
            rf"(?:^|\n)\s*{escaped_section}\s*:\s*(.*?)(?=\n\s*(?:{next_pattern})\s*:|\Z)"
            if next_pattern
            else rf"(?:^|\n)\s*{escaped_section}\s*:\s*(.*)$"
        )
        match = re.search(pattern, raw_text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return match.group(1).strip()

    @classmethod
    def _extract_answer_section_or_raw(cls, raw_text: str) -> str:
        answer_text = cls._extract_section(
            raw_text,
            "ANSWER",
            ["EXECUTIVE_SUMMARY", "KEY_POINTS", "OBLIGATIONS", "CITATIONS"],
        )
        if answer_text:
            return answer_text
        text = str(raw_text or "").strip()
        if not text:
            return ""
        first_internal_section = re.search(
            r"\n\s*(?:EXECUTIVE_SUMMARY|KEY_POINTS|OBLIGATIONS|CITATIONS)\s*:",
            text,
            flags=re.IGNORECASE,
        )
        if first_internal_section:
            return text[: first_internal_section.start()].strip()
        return text

    @classmethod
    def _contains_markdown_table(cls, text: str) -> bool:
        return bool(cls.MARKDOWN_TABLE_PATTERN.search(str(text or "")))

    @classmethod
    def _question_requests_tabular_answer(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if not normalized:
            return False
        explicit_table_terms = (
            "tabla",
            "tablas",
            "table",
            "tables",
            "cuadro",
            "cuadros",
        )
        key_value_terms = (
            "clave valor",
            "clave-valor",
            "key value",
            "key-value",
            "lista valor",
            "listado valor",
        )
        field_terms = (
            "campos clave",
            "campos relevantes",
            "campos que consideres",
            "todos los campos",
            "valores importantes",
            "referencias por pagina",
            "referencias de pagina",
        )
        return any(term in normalized for term in explicit_table_terms + key_value_terms + field_terms)

    @classmethod
    def _build_tabular_repair_prompt(
        cls,
        *,
        question: str,
        question_class: str,
        strategy: str,
        evidence_text: str,
        visual_section: str,
        facts_section: str,
        previous_answer: str,
    ) -> str:
        return (
            "La respuesta anterior no cumplio el formato solicitado: faltaba una tabla Markdown valida.\n"
            "Reescribe la respuesta usando SOLO la evidencia provista. No inventes datos.\n"
            "Responde en el mismo idioma de la pregunta.\n\n"
            f"Question:\n{question}\n\n"
            f"Question class:\n{question_class}\n\n"
            f"Strategy:\n{strategy}\n\n"
            f"Evidence:\n{evidence_text}{visual_section}{facts_section}\n\n"
            f"Previous non-compliant answer:\n{previous_answer}\n\n"
            "Contrato obligatorio de salida (texto plano, SIN JSON):\n"
            "ANSWER:\n"
            "| Campo | Valor | Fuente | Nota |\n"
            "| --- | --- | --- | --- |\n"
            "| <campo encontrado> | <valor exacto o resumen fiel> | <archivo - pagina N o Source N> | <observacion breve o -> |\n"
            "EXECUTIVE_SUMMARY: <resumen breve>\n"
            "KEY_POINTS:\n"
            "- <punto>\n"
            "OBLIGATIONS:\n"
            "- <obligacion>\n"
            "CITATIONS: <numeros de fuentes separados por coma, ejemplo 1,2>\n\n"
            "Reglas estrictas:\n"
            "- ANSWER debe contener una tabla Markdown GFM valida con encabezado, separador y al menos una fila.\n"
            "- No reemplaces la tabla por parrafos ni bullets.\n"
            "- Si un campo pedido no aparece en la evidencia, agrega una fila con valor 'No encontrado en la evidencia OCR provista'.\n"
            "- La columna Fuente debe apuntar a pagina o Source cuando la evidencia lo permita.\n"
            "- No incluyas secciones Sources/Fuentes dentro de ANSWER; las citas numericas van solo en CITATIONS.\n"
        )

    @staticmethod
    def _extract_bullets(section_text: str) -> list[str]:
        if not section_text:
            return []
        bullets: list[str] = []
        for raw_line in section_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            normalized = re.sub(r"^[-*•\d\.\)\(]+\s*", "", line).strip()
            if normalized:
                bullets.append(normalized)
        if bullets:
            return bullets
        compact = section_text.strip()
        return [compact] if compact else []

    @staticmethod
    def _extract_citation_numbers(raw_text: str, *, evidence_count: int) -> list[int]:
        if evidence_count <= 0:
            return []
        citations_section = GraphSynthesis._extract_section(
            raw_text,
            "CITATIONS",
            [],
        )
        numbers: list[int] = []
        if citations_section:
            numbers = [
                int(match)
                for match in re.findall(r"\b(\d{1,2})\b", citations_section)
                if 1 <= int(match) <= evidence_count
            ]
        if not numbers:
            referenced = re.findall(
                r"(?:\[\s*source\s*(\d{1,2})\s*\]|(?:source|fuente)\s*#?\s*(\d{1,2}))",
                raw_text,
                flags=re.IGNORECASE,
            )
            for first, second in referenced:
                token = first or second
                if not token:
                    continue
                parsed = int(token)
                if 1 <= parsed <= evidence_count:
                    numbers.append(parsed)
        if numbers:
            return sorted(set(numbers))
        return []

    @staticmethod
    def _sanitize_answer_text(answer_text: str) -> str:
        text = str(answer_text or "").strip()
        if not text:
            return ""
        cleaned_lines: list[str] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue
            if re.match(r"^\**\s*(sources?|fuentes?|citations?)\s*:?", stripped, flags=re.IGNORECASE):
                continue
            if re.match(r"^[-*]\s*\**\s*(source|fuente)\b", stripped, flags=re.IGNORECASE):
                continue
            cleaned_lines.append(raw_line)
        cleaned = "\n".join(cleaned_lines).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned or text

    @staticmethod
    def _truncate_text(value: str, *, max_chars: int) -> str:
        text = str(value or "").replace("\n", " ").strip()
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    @classmethod
    def _clean_ocr_excerpt(cls, value: object, *, max_chars: int = 360) -> str:
        text = str(value or "").replace("\n", " ").strip()
        if not text:
            return ""
        normalized_probe = cls._normalize_text(text)
        if "docling text blocks" in normalized_probe or "visual regions detected" in normalized_probe:
            return "Sin texto OCR suficiente; Docling detecto contenido visual que requiere revision humana si es critico."
        text = re.sub(r"\\+", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"([,;:!?])(?=[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ])", r"\1 ", text)
        text = re.sub(r"(?<!\b[A-ZÁÉÍÓÚÜÑ])\.(?=[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ])", ". ", text)
        text = re.sub(r"([a-záéíóúüñ])([A-ZÁÉÍÓÚÜÑ])", r"\1 \2", text)
        text = re.sub(r"\s+", " ", text).strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if sentences:
            if max_chars <= 500 and len(sentences[0]) >= 40:
                return cls._truncate_text(sentences[0], max_chars=max_chars)
            selected: list[str] = []
            length = 0
            for sentence in sentences[:3]:
                if length and length + 1 + len(sentence) > max_chars:
                    break
                selected.append(sentence)
                length += len(sentence) + (1 if length else 0)
                if length >= max_chars * 0.55:
                    break
            if selected:
                return cls._truncate_text(" ".join(selected), max_chars=max_chars)
        return cls._truncate_text(text, max_chars=max_chars)

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()

    @classmethod
    def _question_requests_people_details(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "persona",
                "personas",
                "representante",
                "representantes",
                "facultad",
                "facultades",
                "firmar",
                "firma",
                "comparec",
                "consentir",
            )
        )

    @classmethod
    def _question_requests_document_inventory_answer(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if not normalized:
            return False
        if any(
            token in normalized
            for token in (
                "inventario documental",
                "inventario de documentos",
                "inventario de archivos",
                "document inventory",
                "lista de documentos",
                "listado de documentos",
                "lista los documentos",
                "listar documentos",
                "listame los documentos",
                "muestrame los documentos",
                "documentos del expediente",
                "archivos del expediente",
                "integran el expediente",
                "documentos integran",
                "archivos integran",
                "que documentos tengo",
                "que archivos tengo",
                "cuales son los documentos",
                "cuales son los archivos",
            )
        ):
            return True
        return bool(
            re.search(
                r"\b(?:que|cuales|lista|listar|listame|muestra|mostrar|muestrame|inventario|catalogo)\b"
                r".{0,60}\b(?:documentos|archivos|pdfs?)\b",
                normalized,
            )
            and re.search(
                r"\b(?:asociad|vinculad|relacionad|integran|pertenecen|incluye|contiene|disponibles|cargad)\b",
                normalized,
            )
        )

    @classmethod
    def _question_requests_provenance_map(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if not normalized:
            return False
        return bool(
            any(
                token in normalized
                for token in (
                    "de donde fue extraido",
                    "de donde se extrajo",
                    "donde fue extraido",
                    "donde se extrajo",
                    "origen de cada dato",
                    "fuente de cada dato",
                    "trazabilidad de cada dato",
                    "provenance",
                    "data lineage",
                )
            )
            or (
                "cada dato" in normalized
                and any(token in normalized for token in ("fuente", "origen", "extraido", "extrajo"))
            )
        )

    @classmethod
    def _question_requests_document_level_synthesis(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        if not normalized:
            return False
        if any(
            token in normalized
            for token in (
                "por documento",
                "por archivo",
                "por pdf",
                "documento por documento",
                "archivo por archivo",
                "cada documento",
                "cada archivo",
                "cada pdf",
                "todos los documentos",
                "todos los archivos",
                "documentos seleccionados",
                "archivos seleccionados",
                "expediente completo",
                "cobertura documental",
                "resumen por documento",
                "summarize each document",
                "document by document",
            )
        ):
            return True
        return bool(
            "expediente" in normalized
            and "cada" in normalized
            and any(token in normalized for token in ("instrumento", "variable", "gobierna", "rige", "sustenta"))
        )

    @classmethod
    def _should_use_per_document_inventory_answer(cls, *, question: str, question_class: str) -> bool:
        normalized_class = str(question_class or "").strip().lower()
        return bool(
            normalized_class == "inventory"
            or cls._question_requests_document_inventory_answer(question)
            or cls._question_requests_modification_map(question)
            or cls._question_requests_people_details(question)
            or cls._question_requests_provenance_map(question)
            or (
                normalized_class == "exhaustive_synthesis"
                and cls._question_requests_document_level_synthesis(question)
            )
        )

    @classmethod
    def _question_excerpt_focus_terms(cls, question: str) -> tuple[str, ...]:
        if not cls._question_requests_people_details(question):
            return ()
        return (
            "comparecen",
            "comparece",
            "representada",
            "representado",
            "representacion",
            "facultad",
            "facultades",
            "firma",
            "firmar",
            "p.p",
            "por don",
            "por dona",
            "mandato",
        )

    @classmethod
    def _rank_metadata_field_for_summary(cls, field_name: str) -> int:
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
    def _parse_metadata_context_line(cls, line: str) -> tuple[str, list[tuple[str, str]]] | None:
        archive_slug, separator, payload = str(line or "").partition(":")
        if not separator or "=" not in payload:
            return None
        archive_slug = archive_slug.strip()
        fields: list[tuple[str, str]] = []
        for raw_part in payload.split(";"):
            key, field_separator, value = raw_part.partition("=")
            if not field_separator:
                continue
            key = key.strip()
            value = value.strip()
            if not key or not value:
                continue
            fields.append((key, value))
        if not archive_slug or not fields:
            return None
        return archive_slug, fields

    @classmethod
    def _build_prioritized_metadata_summary(cls, lines: list[str]) -> str:
        grouped: dict[str, list[tuple[str, str, int]]] = {}
        unparsed: list[str] = []
        seen_fields: set[tuple[str, str, str]] = set()
        sequence = 0
        for line in lines:
            parsed = cls._parse_metadata_context_line(line)
            if parsed is None:
                unparsed.append(line)
                continue
            archive_slug, fields = parsed
            grouped.setdefault(archive_slug, [])
            for key, value in fields:
                field_key = (archive_slug.casefold(), cls._normalize_text(key), cls._normalize_text(value))
                if field_key in seen_fields:
                    continue
                seen_fields.add(field_key)
                grouped[archive_slug].append((key, value, sequence))
                sequence += 1
        if not grouped:
            return cls._truncate_text(" | ".join(unparsed[:6]), max_chars=2400)

        fragments: list[str] = []
        for archive_slug, fields in grouped.items():
            ranked = sorted(
                fields,
                key=lambda item: (-cls._rank_metadata_field_for_summary(item[0]), item[2]),
            )
            important = [item for item in ranked if cls._rank_metadata_field_for_summary(item[0]) > 0]
            baseline = sorted(fields[:8], key=lambda item: item[2])
            selected: list[tuple[str, str, int]] = []
            seen_selected: set[tuple[str, str]] = set()
            for collection in (important[:24], baseline):
                for key, value, index in collection:
                    selected_key = (cls._normalize_text(key), cls._normalize_text(value))
                    if selected_key in seen_selected:
                        continue
                    seen_selected.add(selected_key)
                    selected.append((key, value, index))
            selected.sort(
                key=lambda item: (
                    -cls._rank_metadata_field_for_summary(item[0]),
                    item[2],
                )
            )
            rendered = "; ".join(f"{key}={value}" for key, value, _ in selected[:32])
            if rendered:
                fragments.append(f"{archive_slug}: {rendered}")
        if unparsed:
            fragments.extend(unparsed[:2])
        return cls._truncate_text(" | ".join(fragments), max_chars=3600)

    @classmethod
    def _build_question_focused_excerpt(
        cls,
        *,
        source_texts: list[str],
        question: str,
        max_chars: int,
    ) -> str:
        focus_terms = tuple(cls._normalize_text(term) for term in cls._question_excerpt_focus_terms(question))
        if not focus_terms:
            return ""
        windows: list[str] = []
        seen_windows: set[str] = set()
        for raw_text in source_texts:
            text = str(raw_text or "").replace("\n", " ").strip()
            if not text:
                continue
            normalized = cls._normalize_text(text)
            positions: list[int] = []
            for term in focus_terms:
                if not term:
                    continue
                start_at = 0
                while True:
                    position = normalized.find(term, start_at)
                    if position < 0:
                        break
                    positions.append(position)
                    start_at = position + max(1, len(term))
            for position in sorted(set(positions))[:3]:
                start = max(0, position - 280)
                end = min(len(text), position + int(max_chars))
                window = text[start:end].strip()
                if start > 0:
                    window = "..." + window
                if end < len(text):
                    window = window.rstrip() + "..."
                key = cls._normalize_text(window[:240])
                if window and key not in seen_windows:
                    seen_windows.add(key)
                    windows.append(window)
            if len(windows) >= 4:
                break
        if not windows:
            return ""
        return cls._truncate_text(" ".join(windows), max_chars=max_chars)

    @classmethod
    def _build_per_document_items(
        cls,
        evidence: list[EvidenceItem],
        *,
        question: str = "",
    ) -> list[dict[str, object]]:
        grouped: dict[int, list[EvidenceItem]] = {}
        for item in evidence:
            grouped.setdefault(int(item.file_id), []).append(item)
        items: list[dict[str, object]] = []
        people_detail_requested = cls._question_requests_people_details(question)
        for file_id, file_evidence in grouped.items():
            sorted_items = sorted(file_evidence, key=lambda row: float(row.score), reverse=True)
            primary = sorted_items[0]
            source_texts = [
                str(item.summary_text or "")
                for item in sorted_items[: (4 if people_detail_requested else 2)]
                if str(item.summary_text or "").strip()
            ]
            focused_excerpt = cls._build_question_focused_excerpt(
                source_texts=source_texts,
                question=question,
                max_chars=5200 if people_detail_requested else 2600,
            )
            merged_text = focused_excerpt or " ".join(
                cls._truncate_text(item.summary_text or "", max_chars=900)
                for item in sorted_items[:2]
                if str(item.summary_text or "").strip()
            ).strip()
            items.append(
                {
                    "file_id": file_id,
                    "file_name": repair_document_file_name(primary.file_name or f"document-{file_id}"),
                    "source_number": int(primary.source_number),
                    "best_score": float(primary.score),
                    "summary_excerpt": merged_text or "Sin texto OCR utilizable en evidencia.",
                    "has_evidence": True,
                }
            )
        items.sort(key=lambda item: str(item.get("file_name") or ""))
        return items

    @classmethod
    def _infer_document_role(cls, file_name: str) -> str:
        normalized = cls._normalize_text(repair_document_file_name(file_name))
        role_terms = [
            ("modificacion" in normalized and "cesion" in normalized, "modificacion y cesion"),
            ("modificacion" in normalized or "anexo" in normalized or "rectificacion" in normalized, "modificacion/anexo"),
            ("transaccion" in normalized, "transaccion"),
            ("alzamiento" in normalized, "alzamiento"),
            ("notificacion" in normalized and "cesion" in normalized, "notificacion de cesion"),
            ("cesion" in normalized, "cesion"),
            ("finiquito" in normalized or "resciliacion" in normalized, "termino/finiquito"),
            ("contrato" in normalized or normalized.endswith(".pdf"), "contrato/documento base"),
        ]
        for matches, label in role_terms:
            if matches:
                return label
        return "documento del expediente"

    @staticmethod
    def _normalize_inventory_file_name(file_name: str) -> str:
        text = unicodedata.normalize("NFKD", str(file_name or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
        return re.sub(r"[^a-z0-9]+", "", text)

    @staticmethod
    def _parse_positive_int(value: object) -> int:
        match = re.search(r"\d+", str(value or ""))
        return int(match.group(0)) if match else 0

    @classmethod
    def _extract_document_inventory_items(cls, fact_context: str) -> list[dict[str, object]]:
        text = str(fact_context or "")
        if not text.strip():
            return []
        items: list[dict[str, object]] = []
        seen_keys: set[tuple[int, str]] = set()

        def _append(item: dict[str, object]) -> None:
            file_id = int(item.get("file_id") or 0)
            file_name = repair_document_file_name(item.get("file_name") or "")
            normalized_name = cls._normalize_inventory_file_name(file_name)
            if not normalized_name:
                return
            key = (file_id, normalized_name)
            if key in seen_keys:
                return
            seen_keys.add(key)
            item["role"] = item.get("role") or cls._infer_document_role(file_name)
            item["has_evidence"] = False
            items.append(item)

        bullet_pattern = re.compile(
            r"file_id=(?P<file_id>\d+)\s+archive=(?P<archive>\S+)\s+"
            r"file=(?P<file_name>.+?)\s+status=(?P<status>\S+)\s+pages=(?P<pages>\d+)",
            flags=re.IGNORECASE,
        )
        for match in bullet_pattern.finditer(text):
            _append(
                {
                    "file_id": int(match.group("file_id")),
                    "archive_slug": match.group("archive"),
                    "file_name": repair_document_file_name(match.group("file_name")),
                    "status": match.group("status"),
                    "page_count": int(match.group("pages")),
                }
            )

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|") or "---" in line or "Documento" in line and "Archivo" in line:
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 6 or not cells[0].isdigit():
                continue
            _append(
                {
                    "file_id": 0,
                    "archive_slug": cells[1],
                    "file_name": repair_document_file_name(cells[2]),
                    "status": cells[4],
                    "page_count": cls._parse_positive_int(cells[5]),
                }
            )
        return items

    @classmethod
    def _merge_inventory_and_evidence_items(
        cls,
        *,
        inventory_items: list[dict[str, object]],
        evidence_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        if not inventory_items:
            return [
                {
                    **item,
                    "role": item.get("role") or cls._infer_document_role(str(item.get("file_name") or "")),
                    "has_evidence": True,
                }
                for item in evidence_items
            ]

        evidence_by_id = {
            int(item.get("file_id") or 0): item
            for item in evidence_items
            if int(item.get("file_id") or 0) > 0
        }
        evidence_by_name = {
            cls._normalize_inventory_file_name(str(item.get("file_name") or "")): item
            for item in evidence_items
            if cls._normalize_inventory_file_name(str(item.get("file_name") or ""))
        }
        used_evidence_ids: set[int] = set()
        merged: list[dict[str, object]] = []
        for inventory_item in inventory_items:
            file_id = int(inventory_item.get("file_id") or 0)
            normalized_name = cls._normalize_inventory_file_name(str(inventory_item.get("file_name") or ""))
            evidence_item = evidence_by_id.get(file_id) if file_id > 0 else None
            if evidence_item is None:
                evidence_item = evidence_by_name.get(normalized_name)
            if evidence_item is not None:
                used_evidence_ids.add(int(evidence_item.get("file_id") or 0))
                merged.append(
                    {
                        **inventory_item,
                        **evidence_item,
                        "archive_slug": inventory_item.get("archive_slug") or evidence_item.get("archive_slug") or "",
                        "status": inventory_item.get("status") or "",
                        "page_count": inventory_item.get("page_count") or 0,
                        "role": inventory_item.get("role")
                        or cls._infer_document_role(str(evidence_item.get("file_name") or "")),
                        "has_evidence": True,
                    }
                )
            else:
                merged.append(dict(inventory_item))

        for evidence_item in evidence_items:
            evidence_file_id = int(evidence_item.get("file_id") or 0)
            if evidence_file_id > 0 and evidence_file_id in used_evidence_ids:
                continue
            normalized_name = cls._normalize_inventory_file_name(str(evidence_item.get("file_name") or ""))
            if any(cls._normalize_inventory_file_name(str(item.get("file_name") or "")) == normalized_name for item in merged):
                continue
            merged.append(
                {
                    **evidence_item,
                    "role": evidence_item.get("role")
                    or cls._infer_document_role(str(evidence_item.get("file_name") or "")),
                    "has_evidence": True,
                }
            )
        return merged

    @classmethod
    def _extract_fact_context_summary(cls, fact_context: str) -> str:
        lines: list[str] = []
        capture_metadata = False
        for raw_line in str(fact_context or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(("Archive metadata context:", "Resolved metadata facts:", "Resolved metadata differences:")):
                capture_metadata = True
                continue
            if line.startswith("Document inventory context:"):
                break
            if capture_metadata and re.match(r"^[A-Za-z].+ context:", line):
                break
            if capture_metadata:
                lines.append(line)
        if not lines:
            return ""
        return "Metadata estructurada: " + cls._build_prioritized_metadata_summary(lines)

    @classmethod
    def _metadata_summary_bullets(cls, fact_context: str, *, max_fields_per_archive: int = 8) -> list[str]:
        summary = cls._extract_fact_context_summary(fact_context)
        prefix = "Metadata estructurada:"
        if not summary.startswith(prefix):
            return []
        payload = summary[len(prefix):].strip()
        bullets: list[str] = []
        for archive_fragment in payload.split(" | "):
            archive_slug, separator, fields_payload = archive_fragment.partition(":")
            archive_slug = archive_slug.strip()
            if not separator or not archive_slug:
                continue
            fields: list[str] = []
            for raw_field in fields_payload.split(";"):
                key, field_separator, value = raw_field.partition("=")
                key = key.strip()
                value = value.strip()
                if not field_separator or not key or not value:
                    continue
                fields.append(f"{key}={value}")
            if fields:
                rendered = "; ".join(fields[:max_fields_per_archive])
                bullets.append(f"- **{archive_slug}:** {rendered}.")
        return bullets

    @classmethod
    def _question_requests_modification_map(cls, question: str) -> bool:
        normalized = cls._normalize_text(question)
        return any(
            token in normalized
            for token in (
                "modific",
                "contrato base",
                "documento base",
                "version",
                "anexo",
                "complement",
            )
        )

    @classmethod
    def _role_modifies_or_complements_base(cls, role: str, file_name: str) -> bool:
        normalized = cls._normalize_text(f"{role} {file_name}")
        return any(
            token in normalized
            for token in (
                "modificacion",
                "anexo",
                "rectificacion",
                "cesion",
                "adenda",
                "addendum",
            )
        )

    @classmethod
    def _role_is_probable_base(cls, role: str, file_name: str) -> bool:
        normalized = cls._normalize_text(f"{role} {file_name}")
        return "base" in normalized or (
            "contrato" in normalized and not cls._role_modifies_or_complements_base(role, file_name)
        )

    @staticmethod
    def _markdown_safe_inline(value: object) -> str:
        return str(value or "").replace("\n", " ").strip()

    def _synthesize_per_document_map_reduce(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        strategy: str,
        selected_docs_count: int,
        fact_context: str = "",
    ) -> LLMResult:
        del strategy
        inventory_items = self._extract_document_inventory_items(fact_context)
        doc_items = self._merge_inventory_and_evidence_items(
            inventory_items=inventory_items,
            evidence_items=self._build_per_document_items(evidence, question=question),
        )
        if not doc_items:
            return LLMResult(
                answer_text="No se obtuvo evidencia suficiente para resumir los documentos seleccionados.",
                executive_summary="No se obtuvo evidencia suficiente.",
                key_points=[],
                obligations=[],
                citation_source_numbers=[],
                model_used="langgraph-per-document-summary",
            )

        lines: list[str] = []
        key_points: list[str] = []
        citation_numbers: list[int] = []
        for index, item in enumerate(doc_items, start=1):
            file_name = repair_document_file_name(item.get("file_name") or f"document-{index}")
            has_evidence = bool(item.get("has_evidence"))
            if has_evidence:
                excerpt_limit = 5200 if self._question_requests_people_details(question) else 360
                excerpt = self._clean_ocr_excerpt(item.get("summary_excerpt") or "", max_chars=excerpt_limit)
            else:
                status = str(item.get("status") or "estado desconocido").strip()
                page_count = int(item.get("page_count") or 0)
                page_fragment = f"; {page_count} paginas registradas" if page_count > 0 else ""
                excerpt = (
                    "sin evidencia OCR suficiente recuperada"
                    f" ({status}{page_fragment})."
                )
            role = str(item.get("role") or self._infer_document_role(file_name)).strip()
            source_number = int(item.get("source_number") or 0)
            role_label = f" ({role})" if role else ""
            safe_file_name = self._markdown_safe_inline(file_name)
            safe_excerpt = self._markdown_safe_inline(excerpt)
            lines.append(f"{index}. **{safe_file_name}**{role_label}.")
            lines.append(f"   - Lectura OCR: {safe_excerpt}")
            key_points.append(f"{file_name}: {excerpt}")
            if source_number > 0:
                citation_numbers.append(source_number)

        covered = sum(1 for item in doc_items if bool(item.get("has_evidence")))
        requested = max(len(doc_items), int(selected_docs_count or len(doc_items)))
        clean_question = question.strip().rstrip(".?!")
        if inventory_items:
            coverage_note = (
                f"Inventario documental completo: {len(doc_items)} documentos seleccionados; "
                f"{covered} con evidencia OCR recuperada para responder: {clean_question}"
            )
        else:
            coverage_note = (
                f"Resumen por documento basado en {covered} documentos con evidencia recuperada "
                f"para responder: {clean_question}"
            )
        answer_lines: list[str] = [
            "## Resumen",
            f"- **Cobertura:** {coverage_note}.",
            f"- **Evidencia:** {covered}/{requested} documentos tienen OCR recuperado para esta respuesta.",
        ]
        metadata_bullets = self._metadata_summary_bullets(fact_context)
        if metadata_bullets:
            answer_lines.extend(
                ["", "## Metadata clave", "Metadata estructurada priorizada desde el CSV:", *metadata_bullets]
            )

        answer_lines.extend(["", "## Documentos del expediente", *lines])

        if self._question_requests_modification_map(question):
            modifier_items: list[str] = []
            base_items: list[str] = []
            related_items: list[str] = []
            for item in doc_items:
                file_name = repair_document_file_name(item.get("file_name") or "")
                role = str(item.get("role") or self._infer_document_role(file_name)).strip()
                rendered = f"- **{self._markdown_safe_inline(file_name)}**: {role}."
                if self._role_modifies_or_complements_base(role, file_name):
                    modifier_items.append(rendered)
                elif self._role_is_probable_base(role, file_name):
                    base_items.append(rendered)
                else:
                    related_items.append(rendered)
            answer_lines.extend(["", "## Documentos que modifican o complementan el contrato base"])
            if base_items:
                answer_lines.extend(["", "### Base probable"])
                answer_lines.extend(base_items)
            if modifier_items:
                answer_lines.extend(["", "### Modifican o complementan"])
                answer_lines.extend(modifier_items)
            if related_items:
                answer_lines.extend(["", "### Otros documentos relacionados"])
                answer_lines.extend(related_items)
            if not modifier_items:
                answer_lines.append("- No se identifico un modificatorio claro solo por rol/nombre y OCR recuperado.")

        if covered < requested:
            answer_lines.extend(
                [
                    "",
                    "## Calidad OCR",
                    f"- Hay {requested - covered} documento(s) sin evidencia OCR suficiente en esta recuperacion.",
                ]
            )
        answer_text = "\n".join(answer_lines).strip()
        executive_summary = (
            f"Resumen por documento completado con evidencia {covered}/{requested} "
            f"({(covered / requested) * 100:.1f}%)."
        )
        return LLMResult(
            answer_text=answer_text,
            executive_summary=executive_summary,
            key_points=key_points,
            obligations=[],
            citation_source_numbers=sorted(set(citation_numbers)),
            model_used="langgraph-per-document-summary",
        )

    def synthesize(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        strategy: str,
        visual_context: str = "",
        summary_mode: str = "default",
        selected_docs_count: int = 0,
        fact_context: str = "",
        question_class: str = "extractive",
    ) -> LLMResult:
        use_per_document_inventory_answer = (
            str(summary_mode).strip().lower() == "per_document"
            and self._should_use_per_document_inventory_answer(
                question=question,
                question_class=question_class,
            )
        )
        if use_per_document_inventory_answer:
            return self._synthesize_per_document_map_reduce(
                question=question,
                evidence=evidence,
                strategy=strategy,
                selected_docs_count=selected_docs_count,
                fact_context=fact_context,
            )
        if not self.provider.is_available():
            raise RuntimeError("OCI synthesis model is not available.")
        evidence_text = self._build_bounded_evidence_text(evidence)
        visual_section = f"\n\nVisual context:\n{visual_context}\n" if visual_context.strip() else ""
        facts_section = (
            f"\n\nMetadata findings and structured facts:\n{fact_context}\n"
            if fact_context.strip()
            else ""
        )
        prompt = (
            "Responde usando SOLO la evidencia provista. Si falta evidencia suficiente, dilo.\n"
            "Responde en el mismo idioma de la pregunta.\n\n"
            f"Question:\n{question}\n\n"
            f"Question class:\n{question_class}\n\n"
            f"Strategy:\n{strategy}\n\n"
            f"Evidence:\n{evidence_text}{visual_section}{facts_section}\n\n"
            "Formato requerido (texto plano, SIN JSON):\n"
            "ANSWER: <respuesta final>\n"
            "EXECUTIVE_SUMMARY: <resumen breve>\n"
            "KEY_POINTS:\n"
            "- <punto>\n"
            "OBLIGATIONS:\n"
            "- <obligacion>\n"
            "CITATIONS: <numeros de fuentes separados por coma, ejemplo 1,2>\n"
            "Reglas adicionales:\n"
            "- Si hay metadata findings y evidencia documental, combina ambas capas de forma explicita en ANSWER.\n"
            "- En respuestas mixtas, abre con la metadata solo como contexto y fundamenta la conclusion con evidencia documental.\n"
            "- Si hay multiples archivos o grupos relacionados, organiza la respuesta por archivo/grupo antes de la conclusion compuesta.\n"
            "- No trates metadata findings como citas documentales; las citas deben venir de Evidence/CITATIONS.\n"
            "- Cierra respuestas mixtas con una frase breve que deje claro que se puede profundizar en un archivo, campo o hallazgo.\n"
            "- No incluyas secciones de cobertura, inventario documental, metadata clave o lectura OCR salvo que la pregunta las pida expresamente.\n"
            "- Si la pregunta pide una lista clave-valor, campos o valores importantes, usa una tabla Markdown con columnas Campo, Valor, Fuente y Nota.\n"
            "- No escribas 'revisado ok' como conclusion de cobertura; si ese texto viene de metadata, identificalo como valor de metadata.\n"
            "- Si no existe evidencia suficiente para un campo, escribe 'No encontrado en la evidencia OCR provista' en vez de dejarlo vacio.\n"
            "- No incluyas listas de fuentes ni secciones 'Fuente/Sources' dentro de ANSWER.\n"
            "- Las referencias de fuentes deben ir solo en CITATIONS.\n"
        )
        raw_text = self.provider.invoke_text(prompt=prompt)
        answer_text = self._sanitize_answer_text(self._extract_answer_section_or_raw(raw_text))
        if self._question_requests_tabular_answer(question) and not self._contains_markdown_table(answer_text):
            repair_prompt = self._build_tabular_repair_prompt(
                question=question,
                question_class=question_class,
                strategy=strategy,
                evidence_text=evidence_text,
                visual_section=visual_section,
                facts_section=facts_section,
                previous_answer=answer_text,
            )
            repaired_raw_text = self.provider.invoke_text(prompt=repair_prompt)
            repaired_answer_text = self._sanitize_answer_text(
                self._extract_answer_section_or_raw(repaired_raw_text)
            )
            if self._contains_markdown_table(repaired_answer_text):
                raw_text = repaired_raw_text
                answer_text = repaired_answer_text
        executive_summary = self._extract_section(
            raw_text,
            "EXECUTIVE_SUMMARY",
            ["KEY_POINTS", "OBLIGATIONS", "CITATIONS"],
        )
        if not executive_summary:
            executive_summary = answer_text[:280].strip()
        key_points = self._extract_bullets(
            self._extract_section(
                raw_text,
                "KEY_POINTS",
                ["OBLIGATIONS", "CITATIONS"],
            )
        )
        obligations = self._extract_bullets(
            self._extract_section(
                raw_text,
                "OBLIGATIONS",
                ["CITATIONS"],
            )
        )
        citation_numbers = self._extract_citation_numbers(raw_text, evidence_count=len(evidence))
        resolved = self.provider.resolve_config()
        return LLMResult(
            answer_text=answer_text.strip(),
            executive_summary=executive_summary.strip(),
            key_points=[str(item).strip() for item in key_points if str(item).strip()],
            obligations=[str(item).strip() for item in obligations if str(item).strip()],
            citation_source_numbers=sorted(set(citation_numbers)),
            model_used=f"langgraph-oci-synthesis:{resolved.model_id}",
        )


class GraphCollaboration:
    def __init__(self, provider: OCIGenerativeAIService) -> None:
        self.provider = provider

    def confidence_notes(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        strategy: str,
    ) -> list[str]:
        if not self.provider.is_available():
            return []
        evidence_text = serialize_evidence(evidence) or "No evidence provided."
        prompt = (
            "Evalua en una frase la suficiencia de evidencia para responder la pregunta.\n\n"
            f"Question:\n{question}\n\n"
            f"Strategy:\n{strategy}\n\n"
            f"Evidence:\n{evidence_text}\n"
        )
        try:
            parsed = self.provider.invoke_structured(schema_model=CollaborationOutput, prompt=prompt)
            note = str(parsed.get("confidence_note", "")).strip()
            return [f"LangGraph review: {note[:300]}"] if note else []
        except Exception:
            return []

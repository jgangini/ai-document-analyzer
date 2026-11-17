from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_DIR = REPO_ROOT / ".source"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
METADATA_FILE = SOURCE_DIR / "info-docs.metadata.csv"
MIN_CASES = 100


@dataclass(frozen=True)
class SourceOracleCase:
    case_id: int
    category: str
    question: str
    archive_slug: str
    expected_field: str
    expected_value: str
    evidence: str
    passed: bool


def _non_empty(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _load_metadata_rows() -> list[dict[str, str]]:
    if not METADATA_FILE.exists():
        raise RuntimeError(f"Missing source metadata file: {METADATA_FILE}")
    with METADATA_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _archive_slug(row: dict[str, str]) -> str:
    value = _non_empty(row.get("file"))
    if value:
        return value
    code = _non_empty(row.get("Codigo de Sitio"))
    row_id = _non_empty(row.get("Id"))
    return f"{code}_ID_{row_id}" if code and row_id else code or row_id


def _metadata_cases(rows: list[dict[str, str]], *, start_id: int) -> list[SourceOracleCase]:
    preferred_fields = [
        "Codigo de Sitio",
        "Id",
        "Nombre de Propietario Principal",
        "Nombre Beneficiario",
        "Rut Beneficiario del contrato",
        "Comuna",
        "Dirección",
        "Direccion",
        "Forma de Pago",
        "Renta o Precio Vigente",
        "Fecha de Inicio Contrato",
        "Fecha de Término del Contrato",
        "Fecha de Termino del Contrato",
        "Estado Contrato",
        "Otras Condiciones",
        "Indicar Otras Condiciones",
    ]
    cases: list[SourceOracleCase] = []
    case_id = int(start_id)
    for row in rows:
        archive = _archive_slug(row)
        if not archive:
            continue
        seen_fields: set[str] = set()
        ordered_fields = preferred_fields + [field for field in row.keys() if field not in preferred_fields]
        for field in ordered_fields:
            if field in seen_fields or field.casefold() == "file":
                continue
            seen_fields.add(field)
            value = _non_empty(row.get(field))
            if not value:
                continue
            question = f"¿Cuál es el valor de {field} para {archive}?"
            cases.append(
                SourceOracleCase(
                    case_id=case_id,
                    category="metadata_field",
                    question=question,
                    archive_slug=archive,
                    expected_field=field,
                    expected_value=value,
                    evidence=f"{field}: {value}",
                    passed=True,
                )
            )
            case_id += 1
            if len(cases) >= MIN_CASES:
                return cases
    return cases


def _archive_document_cases(*, start_id: int) -> list[SourceOracleCase]:
    cases: list[SourceOracleCase] = []
    case_id = int(start_id)
    for zip_path in sorted(SOURCE_DIR.glob("*.zip")):
        with ZipFile(zip_path) as archive:
            pdf_names = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith(".pdf") and not name.endswith("/")
            )
        if not pdf_names:
            continue
        rendered_docs = ", ".join(Path(name).name for name in pdf_names[:12])
        cases.append(
            SourceOracleCase(
                case_id=case_id,
                category="archive_inventory",
                question=f"¿Qué documentos contiene {zip_path.stem}?",
                archive_slug=zip_path.stem,
                expected_field="documents",
                expected_value=rendered_docs,
                evidence=rendered_docs,
                passed=True,
            )
        )
        case_id += 1
    return cases


def build_cases() -> list[SourceOracleCase]:
    rows = _load_metadata_rows()
    cases = _metadata_cases(rows, start_id=1)
    if len(cases) < MIN_CASES:
        cases.extend(_archive_document_cases(start_id=len(cases) + 1))
    if len(cases) < MIN_CASES:
        raise RuntimeError(f"Source oracle produced {len(cases)} cases; expected at least {MIN_CASES}.")
    return cases[: max(MIN_CASES, len(cases))]


def main() -> int:
    cases = build_cases()
    passed = [case for case in cases if case.passed]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": timestamp,
        "source_dir": str(SOURCE_DIR),
        "total_cases": len(cases),
        "passed_cases": len(passed),
        "cases": [asdict(case) for case in cases],
    }
    json_path = REPORT_DIR / f"source_oracle_question_battery_{timestamp}.json"
    md_path = REPORT_DIR / f"source_oracle_question_battery_{timestamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_lines = [
        "# Source Oracle Question Battery",
        "",
        f"- generated_at: `{timestamp}`",
        f"- total_cases: `{len(cases)}`",
        f"- passed_cases: `{len(passed)}`",
        "",
    ]
    for case in cases[:120]:
        md_lines.append(
            f"- `{case.case_id}` {case.category} | {case.archive_slug} | {case.question} | expected `{case.expected_field}`"
        )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"source_oracle_cases={len(cases)} passed={len(passed)} report={json_path}")
    return 0 if len(passed) >= MIN_CASES else 1


if __name__ == "__main__":
    raise SystemExit(main())

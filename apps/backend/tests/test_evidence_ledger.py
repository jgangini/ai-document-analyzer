from __future__ import annotations

import pytest

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.evidence.ledger import (
    EvidenceVerificationError,
    build_evidence_id,
    sha256_text,
    DocumentUnit,
)
from apps.backend.app.evidence.service import evidence_unit_from_page_item, source_labels_from_evidence


def _evidence_item(source_number: int = 1) -> EvidenceItem:
    return EvidenceItem(
        source_number=source_number,
        file_id=10,
        file_name="ley_906_2004.pdf",
        archive_slug="ley_906_2004",
        file_code="LEY906",
        page_id=301,
        page_number=12,
        score=0.98,
        summary_text="ARTICULO 301. Flagrancia.",
        image_path_local="",
    )


def test_document_unit_hash_and_evidence_id_are_stable() -> None:
    unit = DocumentUnit.from_text(
        source_id="ley_906_2004",
        unit_id="article:301",
        text="ARTICULO 301. Flagrancia.",
        citation_label="Ley 906 de 2004, art. 301",
    )

    assert unit.unit_text_sha256 == sha256_text("ARTICULO 301. Flagrancia.")
    assert unit.evidence_id == build_evidence_id(
        source_id="ley_906_2004",
        unit_id="article:301",
        unit_text_sha256=unit.unit_text_sha256,
    )
    assert unit.hash_verified is True


def test_document_unit_rejects_hash_mismatch() -> None:
    unit = DocumentUnit.from_text(
        source_id="source",
        unit_id="unit",
        text="texto original",
        citation_label="Fuente",
    )

    with pytest.raises(EvidenceVerificationError):
        unit.verify_against("texto alterado")


def test_page_evidence_gets_deterministic_hash_id_source_label() -> None:
    item = _evidence_item()

    unit = evidence_unit_from_page_item(item)
    labels = source_labels_from_evidence(evidence=[item], citation_source_numbers=[1])

    assert unit.source_id == "file:10"
    assert unit.unit_id == "page:301:source:1"
    assert unit.hash_verified is False
    assert labels == [f"ley_906_2004.pdf - page 12 [{unit.evidence_id}]"]


def test_source_labels_filter_to_cited_sources() -> None:
    labels = source_labels_from_evidence(
        evidence=[_evidence_item(1), _evidence_item(2)],
        citation_source_numbers=[2],
    )

    assert len(labels) == 1
    assert "source:2" not in labels[0]

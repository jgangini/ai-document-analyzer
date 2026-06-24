"""Evidence helpers used by chat/API presentation paths."""

from __future__ import annotations

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.evidence.ledger import DocumentUnit


def evidence_unit_from_page_item(item: EvidenceItem) -> DocumentUnit:
    """Create a deterministic, hashable unit from an already retrieved page."""

    source_id = f"file:{int(item.file_id)}"
    unit_id = f"page:{int(item.page_id)}:source:{int(item.source_number)}"
    label = f"{item.file_name} - page {int(item.page_number)}"
    return DocumentUnit.from_text(
        source_id=source_id,
        unit_id=unit_id,
        text=str(item.summary_text or ""),
        citation_label=label,
        hash_verified=False,
        metadata={
            "archive_slug": item.archive_slug,
            "file_code": item.file_code,
            "page_number": int(item.page_number),
            "source_number": int(item.source_number),
        },
    )


def source_labels_from_evidence(
    *,
    evidence: list[EvidenceItem],
    citation_source_numbers: list[int] | None = None,
) -> list[str]:
    citation_set = {
        int(value)
        for value in list(citation_source_numbers or [])
        if int(value) > 0
    }
    selected = [
        item
        for item in list(evidence or [])
        if not citation_set or int(item.source_number) in citation_set
    ]
    if not selected and citation_set:
        selected = list(evidence or [])

    labels: list[str] = []
    seen: set[str] = set()
    for item in selected:
        unit = evidence_unit_from_page_item(item)
        label = f"{unit.citation_label} [{unit.evidence_id}]"
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels

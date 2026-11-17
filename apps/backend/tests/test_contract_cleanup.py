from __future__ import annotations

from apps.backend.app.api.contracts.files import FileSummary
from apps.backend.app.api.contracts.questions import EvidenceItem


def test_file_summary_contract_omits_retired_file_type_fields() -> None:
    assert "file_type_key" not in FileSummary.model_fields
    assert "file_type_source" not in FileSummary.model_fields
    assert "file_type_suggested_key" not in FileSummary.model_fields
    assert "file_type_suggested_confidence" not in FileSummary.model_fields
    assert "file_type_suggested_source" not in FileSummary.model_fields


def test_evidence_item_contract_omits_retired_file_type_field() -> None:
    assert "file_type_key" not in EvidenceItem.model_fields

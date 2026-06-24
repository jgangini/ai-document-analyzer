"""Hash-verified document evidence primitives.

The ledger is domain agnostic: legal documents are only one profile on top of
source/unit/hash/evidence identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any


class EvidenceVerificationError(ValueError):
    """Raised when recomposed source text does not match the stored unit hash."""


def sha256_text(text: str) -> str:
    return sha256(str(text or "").encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_evidence_id(*, source_id: str, unit_id: str, unit_text_sha256: str) -> str:
    material = f"{source_id}\n{unit_id}\n{unit_text_sha256}"
    return f"ev_{sha256_text(material)[:20]}"


@dataclass(frozen=True, slots=True)
class DocumentUnit:
    source_id: str
    unit_id: str
    text: str
    citation_label: str
    char_start: int = 0
    char_end: int = 0
    source_sha256: str = ""
    unit_text_sha256: str = ""
    evidence_id: str = ""
    hash_verified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        *,
        source_id: str,
        unit_id: str,
        text: str,
        citation_label: str,
        char_start: int = 0,
        char_end: int | None = None,
        source_sha256: str = "",
        hash_verified: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> "DocumentUnit":
        safe_text = str(text or "")
        unit_hash = sha256_text(safe_text)
        safe_char_end = len(safe_text) if char_end is None else int(char_end)
        return cls(
            source_id=str(source_id),
            unit_id=str(unit_id),
            text=safe_text,
            citation_label=str(citation_label or unit_id),
            char_start=max(0, int(char_start)),
            char_end=max(0, safe_char_end),
            source_sha256=str(source_sha256 or ""),
            unit_text_sha256=unit_hash,
            evidence_id=build_evidence_id(
                source_id=str(source_id),
                unit_id=str(unit_id),
                unit_text_sha256=unit_hash,
            ),
            hash_verified=bool(hash_verified),
            metadata=dict(metadata or {}),
        )

    def verify_against(self, recomposed_text: str) -> "DocumentUnit":
        actual_hash = sha256_text(recomposed_text)
        if actual_hash != self.unit_text_sha256:
            raise EvidenceVerificationError(
                "Evidence unit hash mismatch: "
                f"{self.source_id}/{self.unit_id} expected {self.unit_text_sha256}, got {actual_hash}."
            )
        return DocumentUnit(
            source_id=self.source_id,
            unit_id=self.unit_id,
            text=str(recomposed_text or ""),
            citation_label=self.citation_label,
            char_start=self.char_start,
            char_end=self.char_end,
            source_sha256=self.source_sha256,
            unit_text_sha256=self.unit_text_sha256,
            evidence_id=self.evidence_id
            or build_evidence_id(
                source_id=self.source_id,
                unit_id=self.unit_id,
                unit_text_sha256=self.unit_text_sha256,
            ),
            hash_verified=True,
            metadata=dict(self.metadata or {}),
        )

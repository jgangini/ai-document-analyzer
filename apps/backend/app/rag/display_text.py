from __future__ import annotations

import re


_FILENAME_REPAIRS: tuple[tuple[str, str], ...] = (
    ("Aclaracin", "Aclaracion"),
    ("Cesin", "Cesion"),
    ("Comunicacin", "Comunicacion"),
    ("Constitucin", "Constitucion"),
    ("Gestin", "Gestion"),
    ("Inscripcin", "Inscripcion"),
    ("Insripcin", "Inscripcion"),
    ("Modificacin", "Modificacion"),
    ("Notificacin", "Notificacion"),
    ("Rectificacin", "Rectificacion"),
    ("Resciliacin", "Resciliacion"),
    ("Revocacin", "Revocacion"),
    ("Transaccin", "Transaccion"),
)


def repair_document_file_name(value: object) -> str:
    """Repair common mojibake-like Spanish filename losses without changing IDs."""
    text = str(value or "").strip()
    if not text:
        return ""
    for wrong, right in _FILENAME_REPAIRS:
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    return text

from __future__ import annotations

from pathlib import Path

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_extract_document_code_from_filename() -> None:
    code, source = extract_document_code_from_filename("RM797_-_Decreto_MOP_Exento_N667.pdf")
    assert code == "RM797"
    assert source == "filename_rule"

def test_extract_document_code_from_filename_with_underscore_prefix() -> None:
    code, source = extract_document_code_from_filename("RM797_Contrato.pdf")
    assert code == "RM797"
    assert source == "filename_rule"

def test_extract_document_code_from_filename_with_dash_prefix() -> None:
    code, source = extract_document_code_from_filename("RM797-Contrato_2.pdf")
    assert code == "RM797"
    assert source == "filename_rule"

def test_extract_document_code_from_filename_without_separator() -> None:
    code, source = extract_document_code_from_filename("Decreto_MOP_Exento_N667.pdf")
    assert code is None
    assert source == "none"

def test_build_file_group_key_prefers_primary_identifier() -> None:
    value = build_file_group_key(
        primary_identifier="RM797-5515",
        secondary_identifier="RM797",
        primary_subject="Entel",
        secondary_subject="Transam",
    )
    assert value == "primary:RM797-5515"

def test_build_file_group_key_uses_secondary_identifier_and_subjects() -> None:
    value = build_file_group_key(
        primary_identifier=None,
        secondary_identifier="RM797",
        primary_subject="Entel",
        secondary_subject="Transam",
    )
    assert value == "secondary:RM797|primary_subject:ENTEL|secondary_subject:TRANSAM"

def test_build_file_group_key_truncates_on_utf8_byte_boundary() -> None:
    value = build_file_group_key(
        primary_identifier=None,
        secondary_identifier="ESTBI044",
        primary_subject="Ñ" * 200,
        secondary_subject="Á" * 200,
    )
    assert value is not None
    assert len(value.encode("utf-8")) <= 256

def test_extract_secondary_identifier_matches_rm_token_without_capture_group() -> None:
    assert _extract_secondary_identifier("Contrato sitio RM797 firmado por las partes.") == "RM797"

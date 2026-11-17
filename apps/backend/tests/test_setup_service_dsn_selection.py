from __future__ import annotations

from apps.backend.app.services.bootstrap_service import SetupService


def test_select_preferred_wallet_dsn_prefers_medium_for_rag_workload() -> None:
    aliases = [
        "ora26ai_high",
        "ora26ai_medium",
        "ora26ai_low",
        "ora26ai_tp",
        "ora26ai_tpurgent",
    ]

    assert SetupService._select_preferred_wallet_dsn(aliases) == "ora26ai_medium"


def test_select_preferred_wallet_dsn_falls_back_in_expected_order() -> None:
    aliases = [
        "ora26ai_low",
        "ora26ai_tp",
        "ora26ai_tpurgent",
    ]

    assert SetupService._select_preferred_wallet_dsn(aliases) == "ora26ai_tp"

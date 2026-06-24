from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bot_server import (
    INTERACTION_RESPONSE_TYPE_PONG,
    INTERACTION_TYPE_PING,
    handle_interaction_payload,
    parse_stockwatch_options,
    verify_discord_signature,
)


def test_ping_returns_pong() -> None:
    response = handle_interaction_payload({"type": INTERACTION_TYPE_PING})

    assert response == {"type": INTERACTION_RESPONSE_TYPE_PONG}


def test_parse_stockwatch_options() -> None:
    options = parse_stockwatch_options(
        [
            {"name": "ticker", "value": "9503.T"},
            {"name": "status", "value": "DANGER"},
            {"name": "dry_run", "value": True},
            {"name": "ignored", "value": "x"},
        ]
    )

    assert options == {"ticker": "9503.T", "status": "DANGER", "dry_run": True}


def test_signature_verification_rejects_missing_values() -> None:
    assert verify_discord_signature(b"{}", None, "123", "abc") is False
    assert verify_discord_signature(b"{}", "abc", None, "abc") is False
    assert verify_discord_signature(b"{}", "abc", "123", None) is False

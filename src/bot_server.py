from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app_service import PROJECT_ROOT, run_stock_watch, save_stock_watch_state, summarize_for_interaction
from discord_client import post_or_print


logger = logging.getLogger(__name__)

INTERACTION_TYPE_PING = 1
INTERACTION_TYPE_APPLICATION_COMMAND = 2
INTERACTION_RESPONSE_TYPE_PONG = 1
INTERACTION_RESPONSE_TYPE_CHANNEL_MESSAGE = 4
EPHEMERAL_FLAG = 64

try:
    from fastapi import FastAPI, Header, HTTPException, Request
except ImportError:  # Allows pure helper tests without web dependencies installed.
    FastAPI = None  # type: ignore[assignment]
    Header = None  # type: ignore[assignment]
    HTTPException = Exception  # type: ignore[assignment]
    Request = Any  # type: ignore[assignment]


if FastAPI is not None:
    app = FastAPI(title="Stock Bottom Watch Discord Interactions")
else:
    app = None


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


if app is not None:
    _load_dotenv()

    @app.post("/interactions")
    async def interactions(
        request: Request,
        x_signature_ed25519: str | None = Header(default=None),
        x_signature_timestamp: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = await request.body()
        public_key = os.getenv("DISCORD_PUBLIC_KEY")
        if not verify_discord_signature(
            body=body,
            signature=x_signature_ed25519,
            timestamp=x_signature_timestamp,
            public_key=public_key,
        ):
            raise HTTPException(status_code=401, detail="invalid request signature")

        payload = json.loads(body.decode("utf-8"))
        return handle_interaction_payload(payload)


def handle_interaction_payload(payload: dict[str, Any]) -> dict[str, Any]:
    interaction_type = payload.get("type")
    if interaction_type == INTERACTION_TYPE_PING:
        return {"type": INTERACTION_RESPONSE_TYPE_PONG}

    if interaction_type != INTERACTION_TYPE_APPLICATION_COMMAND:
        return _message_response("未対応のInteractionです。")

    data = payload.get("data") or {}
    command_name = data.get("name")
    if command_name != "stockwatch":
        return _message_response("未対応のコマンドです。")

    options = parse_stockwatch_options(data.get("options") or [])
    return handle_stockwatch_command(options)


def handle_stockwatch_command(options: dict[str, Any]) -> dict[str, Any]:
    dry_run = bool(options.get("dry_run", False))
    try:
        result = run_stock_watch(
            config_path=PROJECT_ROOT / "config.yaml",
            watchlist_path=PROJECT_ROOT / "watchlist.csv",
            state_path=PROJECT_ROOT / "data" / "state.json",
            ticker=options.get("ticker"),
            status=options.get("status"),
            write_history_cache=not dry_run,
        )
    except Exception as exc:
        logger.exception("stockwatch command failed")
        return _message_response(f"Stock Bottom Watch の実行に失敗しました: {exc}")

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    detail_posted = False

    if len(result.report) > 1900 and webhook_url and not dry_run:
        try:
            post_or_print(result.report, webhook_url)
            detail_posted = True
        except Exception as exc:
            logger.exception("failed to post detailed stockwatch report to webhook")
            return _message_response(f"詳細レポートのWebhook投稿に失敗しました: {exc}")

    if not dry_run:
        save_stock_watch_state(result, PROJECT_ROOT / "data" / "state.json")

    content = summarize_for_interaction(result.report, detail_posted=detail_posted, limit=1900)
    return _message_response(content)


def parse_stockwatch_options(raw_options: list[dict[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for option in raw_options:
        name = option.get("name")
        if name in {"ticker", "status", "dry_run"}:
            parsed[name] = option.get("value")
    return parsed


def verify_discord_signature(
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    public_key: str | None,
) -> bool:
    if not signature or not timestamp or not public_key:
        return False

    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey
    except ImportError as exc:
        raise RuntimeError("pynacl is required for Discord signature verification") from exc

    try:
        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(timestamp.encode("utf-8") + body, bytes.fromhex(signature))
    except (BadSignatureError, ValueError):
        return False
    return True


def _message_response(content: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "content": content,
        "allowed_mentions": {"parse": []},
    }
    if _use_ephemeral_response():
        data["flags"] = EPHEMERAL_FLAG
    return {"type": INTERACTION_RESPONSE_TYPE_CHANNEL_MESSAGE, "data": data}


def _use_ephemeral_response() -> bool:
    return os.getenv("DISCORD_INTERACTION_EPHEMERAL", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }

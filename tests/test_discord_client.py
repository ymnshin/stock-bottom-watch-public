from __future__ import annotations

import sys
import types
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from discord_client import DiscordPostError, _chunk_message, post_or_print


def test_chunk_message_keeps_chunks_within_discord_safe_limit() -> None:
    message = "\n".join([f"line-{index}-" + ("x" * 80) for index in range(80)])

    chunks = list(_chunk_message(message))

    assert len(chunks) > 1
    assert all(len(chunk) <= 1900 for chunk in chunks)


def test_chunk_message_splits_single_long_line() -> None:
    message = "x" * 4100

    chunks = list(_chunk_message(message))

    assert [len(chunk) for chunk in chunks] == [1900, 1900, 300]


def test_post_or_print_uses_webhook_when_url_is_set() -> None:
    calls = []

    class Response:
        status_code = 204
        text = ""

    def post(url: str, json: dict[str, str], timeout: int) -> Response:
        calls.append((url, json, timeout))
        return Response()

    sys.modules["requests"] = types.SimpleNamespace(post=post)
    output = StringIO()
    try:
        with redirect_stdout(output):
            post_or_print("hello", "https://discord.example/webhook")
    finally:
        sys.modules.pop("requests", None)

    assert calls == [("https://discord.example/webhook", {"content": "hello"}, 20)]
    assert "INFO: Discord notification sent" in output.getvalue()


def test_post_or_print_failure_includes_status_code_and_response_text() -> None:
    class Response:
        status_code = 400
        text = "bad request body"

    def post(url: str, json: dict[str, str], timeout: int) -> Response:
        return Response()

    sys.modules["requests"] = types.SimpleNamespace(post=post)
    try:
        try:
            post_or_print("hello", "https://discord.example/webhook")
        except DiscordPostError as exc:
            message = str(exc)
        else:
            raise AssertionError("DiscordPostError was not raised")
    finally:
        sys.modules.pop("requests", None)

    assert "status_code=400" in message
    assert "response_text=bad request body" in message

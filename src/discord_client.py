from __future__ import annotations

import logging
import sys
from collections.abc import Iterable


logger = logging.getLogger(__name__)


class DiscordPostError(RuntimeError):
    """Raised when Discord rejects a webhook request."""


def post_or_print(report: str, webhook_url: str | None) -> None:
    if not webhook_url:
        print(report)
        return

    import requests

    sent_count = 0
    for chunk in _chunk_message(report):
        response = requests.post(webhook_url, json={"content": chunk}, timeout=20)
        if response.status_code >= 400:
            message = response.text[:500]
            logger.error(
                "Discord webhook failed: status_code=%s, response_text=%s",
                response.status_code,
                message,
            )
            raise DiscordPostError(
                f"Discord webhook failed: status_code={response.status_code}, response_text={message}"
            )
        sent_count += 1

    logger.info("Discord notification sent")
    print(f"INFO: Discord notification sent chunks={sent_count}")


def _chunk_message(message: str, limit: int = 1900) -> Iterable[str]:
    if len(message) <= limit:
        yield message
        return

    current: list[str] = []
    current_length = 0
    for line in message.splitlines():
        line_length = len(line) + 1
        if current and current_length + line_length > limit:
            yield "\n".join(current)
            current = []
            current_length = 0

        if line_length > limit:
            yield from _split_long_line(line, limit)
            continue

        current.append(line)
        current_length += line_length

    if current:
        yield "\n".join(current)


def _split_long_line(line: str, limit: int) -> Iterable[str]:
    start = 0
    while start < len(line):
        yield line[start : start + limit]
        start += limit


def print_error(message: str) -> None:
    print(message, file=sys.stderr)

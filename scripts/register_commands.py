from __future__ import annotations

import os
import sys

import requests


DISCORD_API_BASE = "https://discord.com/api/v10"


def main() -> int:
    _load_dotenv()
    application_id = _require_env("DISCORD_APPLICATION_ID")
    bot_token = _require_env("DISCORD_BOT_TOKEN")
    guild_id = _require_env("DISCORD_GUILD_ID")

    url = f"{DISCORD_API_BASE}/applications/{application_id}/guilds/{guild_id}/commands"
    payload = {
        "name": "stockwatch",
        "description": "Stock Bottom Watch のレポートを表示します",
        "type": 1,
        "options": [
            {
                "name": "ticker",
                "description": "例: 9503.T",
                "type": 3,
                "required": False,
            },
            {
                "name": "status",
                "description": "表示するステータス",
                "type": 3,
                "required": False,
                "choices": [
                    {"name": "DANGER", "value": "DANGER"},
                    {"name": "WAIT", "value": "WAIT"},
                    {"name": "BUY_CANDIDATE", "value": "BUY_CANDIDATE"},
                    {"name": "MOMENTUM", "value": "MOMENTUM"},
                    {"name": "OVERHEATED", "value": "OVERHEATED"},
                ],
            },
            {
                "name": "dry_run",
                "description": "state.json を更新せずに確認します",
                "type": 5,
                "required": False,
            },
        ],
    }
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if response.status_code >= 400:
        print(
            f"Failed to register command: status={response.status_code}, body={response.text}",
            file=sys.stderr,
        )
        return 1

    print("Registered /stockwatch as a guild command.")
    print(response.text)
    return 0


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())

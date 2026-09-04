"""Runtime configuration loaded from environment variables (and .env if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional at runtime
    pass


DEFAULT_MODEL = "claude-opus-4-8"
# 2022-06-28 is the stable Notion API version; newer versions split databases
# into "data sources" and would change every payload shape below.
NOTION_API_VERSION = "2022-06-28"


def _int_env(name: str, default: int) -> int:
    """Parse an int env var, falling back to the default on missing/garbage
    values so a typo can't crash every entry point at import time."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY")
    )
    notion_token: str | None = field(
        default_factory=lambda: os.environ.get("NOTION_TOKEN")
    )
    telegram_bot_token: str | None = field(
        default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN")
    )
    model: str = field(
        default_factory=lambda: os.environ.get("NOTION_AI_MODEL", DEFAULT_MODEL)
    )
    notion_version: str = field(
        default_factory=lambda: os.environ.get("NOTION_VERSION", NOTION_API_VERSION)
    )
    max_agent_turns: int = field(
        default_factory=lambda: max(1, _int_env("NOTION_AI_MAX_TURNS", 30))
    )
    screenshot_dir: str = field(
        default_factory=lambda: os.environ.get(
            "NOTION_AI_SCREENSHOT_DIR", os.path.join(os.getcwd(), "form_screenshots")
        )
    )

    def require_notion(self) -> str:
        if not self.notion_token:
            raise RuntimeError(
                "NOTION_TOKEN is not set. Create an internal integration at "
                "https://www.notion.so/my-integrations, copy the secret, and share "
                "your pages/databases with it."
            )
        return self.notion_token

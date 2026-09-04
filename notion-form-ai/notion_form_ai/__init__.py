"""Notion Form AI — an agent that fills Notion databases, page templates,
Notion forms, and external web forms from natural-language requests."""

from .agent import NotionFormAgent
from .config import Settings

__all__ = ["NotionFormAgent", "Settings"]
__version__ = "0.1.0"

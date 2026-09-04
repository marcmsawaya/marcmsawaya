"""Tool definitions the agent exposes to Claude, plus the dispatcher that
executes them against Notion / the browser."""

from __future__ import annotations

import json
from typing import Any

from .config import Settings
from .notion_api import NotionAPIError, NotionClient

TOOLS: list[dict] = [
    {
        "name": "search_notion",
        "description": (
            "Search the Notion workspace for pages and databases by name/content. "
            "Use this first whenever you need to find the database, template page, "
            "or profile page a request refers to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search text"},
                "object_type": {
                    "type": "string",
                    "enum": ["page", "database", "all"],
                    "description": "Restrict results to pages or databases",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_database_schema",
        "description": (
            "Get a database's fields: each field's name, type, whether it is writable, "
            "and the valid options for select/multi_select/status fields. Always call "
            "this before creating or updating an entry so values match the schema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"database_id": {"type": "string"}},
            "required": ["database_id"],
        },
    },
    {
        "name": "query_database",
        "description": (
            "List a few recent entries of a database (titles + ids). Useful to see "
            "how existing entries look or to find an entry to update."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string"},
                "page_size": {"type": "integer", "description": "Max entries, default 5"},
            },
            "required": ["database_id"],
        },
    },
    {
        "name": "create_database_entry",
        "description": (
            "Create a fully filled-in entry (row/page) in a Notion database. "
            "'values' maps field names to plain values — strings for text/select/"
            "status/url/email/phone, numbers, booleans for checkboxes, ISO dates "
            "(YYYY-MM-DD) or {start,end} objects for dates, arrays or comma-separated "
            "strings for multi_select. This also submits Notion Forms responses when "
            "the form's backing database is shared with the integration. Optional "
            "'content' adds body text below the entry's fields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string"},
                "values": {
                    "type": "object",
                    "description": "Map of field name -> value",
                    "additionalProperties": True,
                },
                "content": {
                    "type": "string",
                    "description": "Optional page body ('# ' headings, '- ' bullets, paragraphs)",
                },
            },
            "required": ["database_id", "values"],
        },
    },
    {
        "name": "update_database_entry",
        "description": "Update fields of an existing database entry (page).",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "values": {"type": "object", "additionalProperties": True},
            },
            "required": ["page_id", "values"],
        },
    },
    {
        "name": "get_page_content",
        "description": (
            "Read a Notion page's text content. Use it to inspect a template page's "
            "{{placeholders}} or to read stored profile info (addresses, links, etc.) "
            "needed to fill external forms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"page_id": {"type": "string"}},
            "required": ["page_id"],
        },
    },
    {
        "name": "create_page_from_template",
        "description": (
            "Duplicate a Notion template page and fill its {{placeholder}} markers. "
            "'replacements' maps placeholder names (without braces) to text. The new "
            "page is created under 'parent_id' — a page, or a database (in which case "
            "'values' can also fill the entry's fields). Read the template with "
            "get_page_content first to discover its placeholders."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "template_page_id": {"type": "string"},
                "parent_id": {"type": "string"},
                "parent_type": {"type": "string", "enum": ["page", "database"]},
                "title": {"type": "string", "description": "Title for the new page"},
                "replacements": {"type": "object", "additionalProperties": True},
                "values": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Database field values when parent_type is 'database'",
                },
            },
            "required": ["template_page_id", "parent_id", "parent_type", "title"],
        },
    },
    {
        "name": "read_web_form",
        "description": (
            "Open any web form URL (Google Forms, Notion Forms links, applications, "
            "sign-ups) in a headless browser and list its fields: index, label, type, "
            "options, required. Always call this before fill_web_form."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "fill_web_form",
        "description": (
            "Fill fields on a web form. Each field entry has a 'value' plus one "
            "locator: 'index' (from read_web_form), 'name', or 'label'. Leave "
            "submit=false to only fill and screenshot. IMPORTANT: only pass "
            "submit=true after the user has explicitly confirmed submission in this "
            "conversation — never submit on your own judgment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": {"type": "integer"},
                            "name": {"type": "string"},
                            "label": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["value"],
                    },
                },
                "submit": {"type": "boolean", "description": "Default false"},
            },
            "required": ["url", "fields"],
        },
    },
]


class ToolContext:
    """Holds the live clients tools execute against."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._notion: NotionClient | None = None

    @property
    def notion(self) -> NotionClient:
        if self._notion is None:
            self._notion = NotionClient(
                self.settings.require_notion(), self.settings.notion_version
            )
        return self._notion

    def close(self) -> None:
        if self._notion is not None:
            self._notion.close()
            self._notion = None


def execute_tool(ctx: ToolContext, name: str, tool_input: dict[str, Any]) -> tuple[str, bool]:
    """Run one tool call. Returns (result_text, is_error)."""
    try:
        result = _dispatch(ctx, name, tool_input)
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        return result, False
    except (NotionAPIError, ValueError, KeyError, TypeError) as exc:
        return f"Error: {exc}", True
    except Exception as exc:  # browser and unexpected failures
        return f"Error ({type(exc).__name__}): {exc}", True


def _dispatch(ctx: ToolContext, name: str, args: dict[str, Any]) -> Any:
    if name == "search_notion":
        object_type = args.get("object_type")
        if object_type == "all":
            object_type = None
        return ctx.notion.search(args["query"], object_type)

    if name == "get_database_schema":
        return ctx.notion.get_database_schema(args["database_id"])

    if name == "query_database":
        return ctx.notion.query_database(args["database_id"], int(args.get("page_size") or 5))

    if name == "create_database_entry":
        return ctx.notion.create_database_entry(
            args["database_id"], dict(args.get("values") or {}), args.get("content")
        )

    if name == "update_database_entry":
        return ctx.notion.update_database_entry(args["page_id"], dict(args.get("values") or {}))

    if name == "get_page_content":
        text = ctx.notion.page_text(args["page_id"])
        return text or "(page has no readable text content)"

    if name == "create_page_from_template":
        return ctx.notion.create_page_from_template(
            template_page_id=args["template_page_id"],
            parent_id=args["parent_id"],
            parent_type=args["parent_type"],
            title=args["title"],
            replacements=dict(args.get("replacements") or {}),
            values=dict(args.get("values") or {}),
        )

    if name == "read_web_form":
        from . import browser

        return browser.read_form(args["url"])

    if name == "fill_web_form":
        from . import browser

        return browser.fill_form(
            url=args["url"],
            fields=list(args.get("fields") or []),
            submit=bool(args.get("submit", False)),
            screenshot_dir=ctx.settings.screenshot_dir,
        )

    raise ValueError(f"unknown tool '{name}'")

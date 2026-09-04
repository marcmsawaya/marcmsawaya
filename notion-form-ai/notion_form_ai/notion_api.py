"""Thin, schema-aware wrapper around the Notion REST API.

Everything the agent does in Notion goes through this module: searching,
reading database schemas, building typed property payloads from plain values,
creating/updating pages, and instantiating page templates with
``{{placeholder}}`` replacement.
"""

from __future__ import annotations

import re
import time
from typing import Any

import httpx

NOTION_BASE_URL = "https://api.notion.com/v1"

# Notion caps a single rich-text content string at 2000 chars and a single
# create/append request at 100 child blocks.
_MAX_RICH_TEXT = 2000
_MAX_CHILDREN_PER_REQUEST = 100

# Property types the API accepts when creating/updating a page.
WRITABLE_TYPES = {
    "title",
    "rich_text",
    "number",
    "select",
    "multi_select",
    "status",
    "date",
    "checkbox",
    "url",
    "email",
    "phone_number",
    "people",
    "relation",
    "files",
}

# Block types we know how to copy when instantiating a template.
_TEXT_BLOCK_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
}
_COPYABLE_TYPES = _TEXT_BLOCK_TYPES | {"code", "divider"}

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class NotionAPIError(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, notion_version: str = "2022-06-28"):
        self._http = httpx.Client(
            base_url=NOTION_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------------ HTTP

    def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        for attempt in range(4):
            resp = self._http.request(method, path, json=json)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(float(resp.headers.get("Retry-After", "1")))
                continue
            if resp.status_code >= 400:
                try:
                    detail = resp.json().get("message", resp.text)
                except ValueError:
                    detail = resp.text
                raise NotionAPIError(f"Notion API {resp.status_code}: {detail}")
            return resp.json()
        raise NotionAPIError("Notion API: retries exhausted")

    # ---------------------------------------------------------------- Search

    def search(self, query: str, object_type: str | None = None, limit: int = 10) -> list[dict]:
        """Search the workspace. object_type: 'page', 'database', or None for both."""
        payload: dict[str, Any] = {"query": query, "page_size": min(limit, 100)}
        if object_type in ("page", "database"):
            payload["filter"] = {"property": "object", "value": object_type}
        data = self._request("POST", "/search", payload)
        return [self._summarize_object(obj) for obj in data.get("results", [])]

    @staticmethod
    def _plain_text(rich_text: list[dict]) -> str:
        return "".join(rt.get("plain_text", "") for rt in rich_text or [])

    def _summarize_object(self, obj: dict) -> dict:
        kind = obj.get("object")
        summary = {"object": kind, "id": obj.get("id"), "url": obj.get("url")}
        if kind == "database":
            summary["title"] = self._plain_text(obj.get("title", []))
        elif kind == "page":
            title = ""
            for prop in (obj.get("properties") or {}).values():
                if prop.get("type") == "title":
                    title = self._plain_text(prop.get("title", []))
                    break
            summary["title"] = title
            parent = obj.get("parent", {})
            if parent.get("type") == "database_id":
                summary["parent_database_id"] = parent["database_id"]
        return summary

    # ------------------------------------------------------------- Databases

    def get_database(self, database_id: str) -> dict:
        return self._request("GET", f"/databases/{database_id}")

    def get_database_schema(self, database_id: str) -> dict:
        """Return a compact, model-friendly description of a database's fields."""
        db = self.get_database(database_id)
        fields: dict[str, Any] = {}
        for name, prop in (db.get("properties") or {}).items():
            ptype = prop.get("type")
            entry: dict[str, Any] = {"type": ptype, "writable": ptype in WRITABLE_TYPES}
            if ptype in ("select", "multi_select", "status"):
                options = prop.get(ptype, {}).get("options", [])
                entry["options"] = [o.get("name") for o in options]
            if ptype == "relation":
                entry["related_database_id"] = prop.get("relation", {}).get("database_id")
            fields[name] = entry
        return {
            "id": db.get("id"),
            "title": self._plain_text(db.get("title", [])),
            "url": db.get("url"),
            "fields": fields,
        }

    def query_database(self, database_id: str, page_size: int = 5) -> list[dict]:
        data = self._request(
            "POST", f"/databases/{database_id}/query", {"page_size": min(page_size, 25)}
        )
        return [self._summarize_object(obj) for obj in data.get("results", [])]

    # -------------------------------------------------------- Property build

    def build_properties(self, database_id: str, values: dict[str, Any]) -> dict:
        """Convert plain {field name: value} pairs into typed Notion payloads,
        validated against the live database schema."""
        db = self.get_database(database_id)
        schema = db.get("properties") or {}
        # Case-insensitive field lookup so the model doesn't have to match casing.
        by_lower = {name.lower(): name for name in schema}

        built: dict[str, Any] = {}
        problems: list[str] = []
        for raw_name, value in values.items():
            name = by_lower.get(raw_name.strip().lower())
            if name is None:
                problems.append(
                    f"Unknown field '{raw_name}'. Available fields: {', '.join(schema)}"
                )
                continue
            ptype = schema[name].get("type")
            if ptype not in WRITABLE_TYPES:
                problems.append(f"Field '{name}' has read-only type '{ptype}'.")
                continue
            try:
                built[name] = _property_payload(ptype, value)
            except ValueError as exc:
                problems.append(f"Field '{name}': {exc}")
        if problems:
            raise NotionAPIError("; ".join(problems))
        return built

    # ----------------------------------------------------------------- Pages

    def create_database_entry(
        self, database_id: str, values: dict[str, Any], content: str | None = None
    ) -> dict:
        properties = self.build_properties(database_id, values)
        payload: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        blocks = _text_to_blocks(content) if content else []
        if blocks:
            payload["children"] = blocks[:_MAX_CHILDREN_PER_REQUEST]
        page = self._request("POST", "/pages", payload)
        self._append_children(page["id"], blocks[_MAX_CHILDREN_PER_REQUEST:])
        return self._summarize_object(page)

    def update_database_entry(self, page_id: str, values: dict[str, Any]) -> dict:
        page = self._request("GET", f"/pages/{page_id}")
        parent = page.get("parent", {})
        if parent.get("type") != "database_id":
            raise NotionAPIError("Page is not a database entry; cannot update its fields.")
        properties = self.build_properties(parent["database_id"], values)
        updated = self._request("PATCH", f"/pages/{page_id}", {"properties": properties})
        return self._summarize_object(updated)

    def get_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{page_id}")

    def _append_children(self, block_id: str, blocks: list[dict]) -> None:
        """Append blocks in chunks of 100 (Notion's per-request limit)."""
        for start in range(0, len(blocks), _MAX_CHILDREN_PER_REQUEST):
            chunk = blocks[start : start + _MAX_CHILDREN_PER_REQUEST]
            if chunk:
                self._request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})

    # ---------------------------------------------------------------- Blocks

    def get_block_children(self, block_id: str) -> list[dict]:
        results: list[dict] = []
        cursor: str | None = None
        while True:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._request("GET", path)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                return results
            cursor = data.get("next_cursor")

    def page_text(self, page_id: str, max_depth: int = 3) -> str:
        """Flatten a page's blocks into plain indented text (for reading
        templates or profile pages)."""
        lines: list[str] = []
        self._collect_text(page_id, lines, depth=0, max_depth=max_depth)
        return "\n".join(lines)

    def _collect_text(self, block_id: str, lines: list[str], depth: int, max_depth: int) -> None:
        for block in self.get_block_children(block_id):
            btype = block.get("type", "")
            data = block.get(btype, {}) or {}
            text = self._plain_text(data.get("rich_text", []))
            if btype == "to_do":
                text = ("[x] " if data.get("checked") else "[ ] ") + text
            elif btype == "divider":
                text = "---"
            elif btype == "child_page":
                text = f"(sub-page) {data.get('title', '')}"
            elif btype == "child_database":
                text = f"(database) {data.get('title', '')}"
            if text:
                lines.append("  " * depth + text)
            if block.get("has_children") and depth + 1 < max_depth and btype != "child_page":
                self._collect_text(block["id"], lines, depth + 1, max_depth)

    # ------------------------------------------------------------- Templates

    def create_page_from_template(
        self,
        template_page_id: str,
        parent_id: str,
        parent_type: str,
        title: str,
        replacements: dict[str, str] | None = None,
        values: dict[str, Any] | None = None,
    ) -> dict:
        """Copy a template page's blocks, substitute {{placeholders}}, and
        create the result as a new page.

        parent_type is 'page' or 'database'. When the parent is a database,
        ``values`` may fill the entry's fields (built against its schema).
        """
        replacements = replacements or {}
        blocks = self._copy_blocks(template_page_id, replacements, depth=0)

        if parent_type == "database":
            properties = self.build_properties(parent_id, {**(values or {})})
            # Ensure the title lands in the database's title field.
            db = self.get_database(parent_id)
            title_field = next(
                (n for n, p in (db.get("properties") or {}).items() if p.get("type") == "title"),
                None,
            )
            if title_field and title_field not in properties:
                properties[title_field] = _property_payload("title", title)
            payload: dict[str, Any] = {
                "parent": {"database_id": parent_id},
                "properties": properties,
            }
        elif parent_type == "page":
            payload = {
                "parent": {"page_id": parent_id},
                "properties": {"title": _property_payload("title", title)},
            }
        else:
            raise NotionAPIError("parent_type must be 'page' or 'database'.")

        payload["children"] = blocks[:_MAX_CHILDREN_PER_REQUEST]
        page = self._request("POST", "/pages", payload)
        self._append_children(page["id"], blocks[_MAX_CHILDREN_PER_REQUEST:])
        return self._summarize_object(page)

    def _copy_blocks(
        self, block_id: str, replacements: dict[str, str], depth: int, max_depth: int = 3
    ) -> list[dict]:
        copied: list[dict] = []
        for block in self.get_block_children(block_id):
            btype = block.get("type", "")
            if btype not in _COPYABLE_TYPES:
                continue
            source = block.get(btype, {}) or {}
            body: dict[str, Any] = {}
            if btype in _TEXT_BLOCK_TYPES or btype == "code":
                text = replace_placeholders(
                    self._plain_text(source.get("rich_text", [])), replacements
                )
                body["rich_text"] = [
                    {"type": "text", "text": {"content": text[:_MAX_RICH_TEXT]}}
                ]
            if btype == "to_do":
                body["checked"] = bool(source.get("checked", False))
            if btype == "code":
                body["language"] = source.get("language", "plain text")
            if btype == "callout" and source.get("icon"):
                icon = source["icon"]
                if icon.get("type") == "emoji":
                    body["icon"] = icon
            if (
                block.get("has_children")
                and depth + 1 < max_depth
                and btype in ("toggle", "bulleted_list_item", "numbered_list_item", "to_do", "paragraph", "callout", "quote")
            ):
                children = self._copy_blocks(block["id"], replacements, depth + 1, max_depth)
                if children:
                    body["children"] = children
            copied.append({"object": "block", "type": btype, btype: body})
        return copied


# ---------------------------------------------------------------- Utilities


def replace_placeholders(text: str, replacements: dict[str, str]) -> str:
    """Replace {{ key }} markers with values (case-insensitive keys).
    Unknown placeholders are left untouched."""
    lookup = {str(k).strip().lower(): str(v) for k, v in replacements.items()}

    def _sub(match: re.Match) -> str:
        key = match.group(1).strip().lower()
        return lookup.get(key, match.group(0))

    return _PLACEHOLDER_RE.sub(_sub, text)


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and "," in value:
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def _property_payload(ptype: str, value: Any) -> dict:
    """Build the typed payload for one property from a plain value."""
    if value is None:
        # Explicit clear where the API supports it.
        if ptype in ("select", "status", "date"):
            return {ptype: None}
        if ptype in ("number", "url", "email", "phone_number"):
            return {ptype: None}
        if ptype in ("title", "rich_text"):
            return {ptype: []}
        if ptype in ("multi_select", "people", "relation", "files"):
            return {ptype: []}
        raise ValueError("null is not a valid value for this field type")

    if ptype == "title":
        return {"title": [{"type": "text", "text": {"content": str(value)[:_MAX_RICH_TEXT]}}]}
    if ptype == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": str(value)[:_MAX_RICH_TEXT]}}]}
    if ptype == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"expected a number, got {value!r}")
        return {"number": int(number) if number.is_integer() else number}
    if ptype == "select":
        return {"select": {"name": str(value)}}
    if ptype == "status":
        return {"status": {"name": str(value)}}
    if ptype == "multi_select":
        return {"multi_select": [{"name": str(v)} for v in _as_list(value)]}
    if ptype == "date":
        if isinstance(value, dict) and "start" in value:
            return {"date": value}
        return {"date": {"start": str(value)}}
    if ptype == "checkbox":
        if isinstance(value, str):
            value = value.strip().lower() in ("true", "yes", "1", "checked", "done")
        return {"checkbox": bool(value)}
    if ptype in ("url", "email", "phone_number"):
        return {ptype: str(value)}
    if ptype == "people":
        return {"people": [{"object": "user", "id": str(v)} for v in _as_list(value)]}
    if ptype == "relation":
        return {"relation": [{"id": str(v)} for v in _as_list(value)]}
    if ptype == "files":
        return {
            "files": [
                {"type": "external", "name": str(v)[:100], "external": {"url": str(v)}}
                for v in _as_list(value)
            ]
        }
    raise ValueError(f"unsupported field type '{ptype}'")


def _text_to_blocks(text: str) -> list[dict]:
    """Convert plain text (blank-line separated paragraphs, '-' bullets,
    '#' headings) into simple Notion blocks."""
    blocks: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            btype, content = "heading_3", line[4:]
        elif line.startswith("## "):
            btype, content = "heading_2", line[3:]
        elif line.startswith("# "):
            btype, content = "heading_1", line[2:]
        elif line.startswith(("- ", "* ")):
            btype, content = "bulleted_list_item", line[2:]
        else:
            btype, content = "paragraph", line
        blocks.append(
            {
                "object": "block",
                "type": btype,
                btype: {
                    "rich_text": [{"type": "text", "text": {"content": content[:_MAX_RICH_TEXT]}}]
                },
            }
        )
    return blocks

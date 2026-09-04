"""Playwright-based web form reading and filling (for forms outside Notion,
including public Notion Forms links).

Uses the sync Playwright API — callers on an asyncio loop must run these
functions in a worker thread (the CLI/web/telegram entry points already do).
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

_EXTRACT_FIELDS_JS = """
() => {
  const fields = [];
  const labelFor = (el) => {
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return lab.innerText.trim();
    }
    const wrapping = el.closest('label');
    if (wrapping) return wrapping.innerText.trim();
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const parts = labelledBy.split(/\\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((n) => n.innerText.trim());
      if (parts.length) return parts.join(' ');
    }
    return el.getAttribute('placeholder') || '';
  };

  const controls = document.querySelectorAll(
    'input, textarea, select, [role="radio"], [role="checkbox"], [contenteditable="true"]'
  );
  let index = 0;
  controls.forEach((el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : tag)).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) return;
    if (el.disabled || el.getAttribute('aria-hidden') === 'true') return;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;

    el.setAttribute('data-nfa-index', String(index));
    const field = {
      index,
      tag,
      type: el.getAttribute('role') || type,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      label: labelFor(el).slice(0, 200),
      required: el.required || el.getAttribute('aria-required') === 'true' || false,
      value: '',
      options: [],
    };
    if (tag === 'select') {
      field.options = Array.from(el.options).map((o) => o.label || o.value).slice(0, 50);
    }
    if (type === 'radio' || type === 'checkbox') {
      field.value = el.value || '';
    }
    fields.push(field);
    index += 1;
  });
  return { title: document.title, fields };
}
"""


class BrowserError(RuntimeError):
    pass


def _launch(playwright):
    # NOTION_AI_CHROMIUM lets users point at an existing Chrome/Chromium
    # binary instead of downloading Playwright's own build.
    executable = os.environ.get("NOTION_AI_CHROMIUM")
    if executable:
        return playwright.chromium.launch(headless=True, executable_path=executable)
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        fallback = "/opt/pw-browsers/chromium"
        if os.path.exists(fallback):
            return playwright.chromium.launch(headless=True, executable_path=fallback)
        raise


def _open(url: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from exc
    pw = sync_playwright().start()
    try:
        browser = _launch(pw)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass  # dynamic pages may never go idle; proceed with what loaded
        return pw, browser, page
    except Exception:
        pw.stop()
        raise


def read_form(url: str) -> dict:
    """Open a URL and describe every fillable field on it."""
    pw, browser, page = _open(url)
    try:
        result = page.evaluate(_EXTRACT_FIELDS_JS)
        result["url"] = page.url
        return result
    finally:
        try:
            browser.close()
        finally:
            pw.stop()


def fill_form(
    url: str,
    fields: list[dict],
    submit: bool = False,
    screenshot_dir: str | None = None,
) -> dict:
    """Fill fields on a page and optionally submit.

    Each entry in ``fields`` needs a ``value`` plus one locator key:
    ``index`` (from read_form), ``name``, or ``label``.
    """
    pw, browser, page = _open(url)
    try:
        # Re-tag controls so index-based locators from read_form line up.
        page.evaluate(_EXTRACT_FIELDS_JS)
        filled, errors = [], []
        for spec in fields:
            try:
                _fill_one(page, spec)
                filled.append(spec.get("label") or spec.get("name") or f"#{spec.get('index')}")
            except Exception as exc:
                errors.append(
                    f"{spec.get('label') or spec.get('name') or spec.get('index')}: {exc}"
                )

        shot_path = _screenshot(page, screenshot_dir, "filled")
        result: dict[str, Any] = {
            "url": page.url,
            "filled": filled,
            "errors": errors,
            "submitted": False,
            "screenshot": shot_path,
        }

        if submit and not errors:
            _submit(page)
            time.sleep(1.5)
            result["submitted"] = True
            result["final_url"] = page.url
            result["final_title"] = page.title()
            result["after_screenshot"] = _screenshot(page, screenshot_dir, "submitted")
        return result
    finally:
        try:
            browser.close()
        finally:
            pw.stop()


def _locate(page, spec: dict):
    if spec.get("index") is not None:
        loc = page.locator(f'[data-nfa-index="{int(spec["index"])}"]')
        if loc.count():
            return loc.first
    if spec.get("name"):
        loc = page.locator("[name=%s]" % json.dumps(str(spec["name"])))
        if loc.count():
            return loc.first
    if spec.get("label"):
        loc = page.get_by_label(spec["label"], exact=False)
        if loc.count():
            return loc.first
        # Fall back to placeholder text.
        loc = page.get_by_placeholder(spec["label"], exact=False)
        if loc.count():
            return loc.first
    raise BrowserError("no matching field found (tried index, name, label)")


def _fill_one(page, spec: dict) -> None:
    value = spec.get("value", "")
    locator = _locate(page, spec)
    tag = locator.evaluate("el => el.tagName.toLowerCase()")
    input_type = (locator.get_attribute("type") or "").lower()
    role = (locator.get_attribute("role") or "").lower()

    if tag == "select":
        try:
            locator.select_option(label=str(value))
        except Exception:
            locator.select_option(value=str(value))
    elif input_type == "checkbox":
        truthy = str(value).strip().lower() in ("true", "yes", "1", "on", "checked")
        locator.set_checked(truthy)
    elif input_type == "radio":
        # Prefer the radio in the same group whose value/label matches.
        name = locator.get_attribute("name")
        if name:
            group = page.locator("input[type=radio][name=%s]" % json.dumps(name))
            for i in range(group.count()):
                option = group.nth(i)
                ovalue = option.get_attribute("value") or ""
                if ovalue.strip().lower() == str(value).strip().lower():
                    option.check()
                    return
        locator.check()
    elif role in ("radio", "checkbox"):
        locator.click()
    elif locator.evaluate("el => el.isContentEditable"):
        locator.click()
        locator.type(str(value), delay=10)
    else:
        locator.fill(str(value))


def _submit(page) -> None:
    candidates = [
        'button[type="submit"]',
        'input[type="submit"]',
    ]
    for css in candidates:
        loc = page.locator(css)
        if loc.count():
            loc.first.click()
            _wait_settled(page)
            return
    # Buttons/divs labeled like a submit action (covers Google/Notion forms).
    pattern = re.compile(r"^(submit|send|apply|next|done|finish)$", re.I)
    loc = page.get_by_role("button", name=pattern)
    if loc.count():
        loc.first.click()
        _wait_settled(page)
        return
    raise BrowserError("could not find a submit button on the page")


def _wait_settled(page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass


def _screenshot(page, directory: str | None, suffix: str) -> str:
    directory = directory or os.path.join(os.getcwd(), "form_screenshots")
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"form_{int(time.time() * 1000)}_{suffix}.png")
        page.screenshot(path=path, full_page=False)
        return path
    except Exception:
        return ""


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)

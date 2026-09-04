"""Terminal chat interface: `notion-ai` (interactive) or `notion-ai -m "..."`."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .agent import NotionFormAgent
from .config import Settings

console = Console()


def _print_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "tool_use":
        args = json.dumps(event.get("input", {}), ensure_ascii=False)
        if len(args) > 160:
            args = args[:160] + "…"
        console.print(f"[dim cyan]  ⚙ {event['name']} {args}[/dim cyan]")
    elif kind == "tool_result" and event.get("is_error"):
        console.print(f"[dim red]  ✗ {event['name']}: {event.get('result', '')[:200]}[/dim red]")


def _chat_once(agent: NotionFormAgent, text: str) -> None:
    with console.status("[bold green]working…", spinner="dots"):
        reply = agent.run(text)
    console.print(Panel(Markdown(reply), title="notion-ai", border_style="green"))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="notion-ai",
        description="AI assistant that fills Notion databases, templates, and web forms.",
    )
    parser.add_argument("-m", "--message", help="Run a single request and exit")
    args = parser.parse_args()

    settings = Settings()
    if not settings.notion_token:
        console.print(
            "[yellow]NOTION_TOKEN is not set — Notion tools will fail until you add it "
            "(see README).[/yellow]"
        )
    if not settings.anthropic_api_key:
        console.print(
            "[yellow]ANTHROPIC_API_KEY is not set — set it (or run `ant auth login`) "
            "before chatting.[/yellow]"
        )

    agent = NotionFormAgent(settings, on_event=_print_event)
    try:
        if args.message:
            _chat_once(agent, args.message)
            return

        console.print(
            Panel(
                "Tell me what to fill in — e.g. [bold]“log a $40 dinner expense for "
                "yesterday”[/bold] or [bold]“fill the sign-up form at <url> with my "
                "details”[/bold].\nCommands: [cyan]/reset[/cyan] clears the "
                "conversation, [cyan]/quit[/cyan] exits.",
                title="notion-ai",
                border_style="cyan",
            )
        )
        while True:
            try:
                text = console.input("[bold]you ›[/bold] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text in ("/quit", "/exit", "quit", "exit"):
                break
            if text == "/reset":
                agent.reset()
                console.print("[dim]conversation cleared[/dim]")
                continue
            try:
                _chat_once(agent, text)
            except KeyboardInterrupt:
                console.print("[dim]interrupted[/dim]")
            except Exception as exc:
                console.print(f"[red]error: {exc}[/red]")
    finally:
        agent.close()


if __name__ == "__main__":
    sys.exit(main())

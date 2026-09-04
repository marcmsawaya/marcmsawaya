"""Telegram bot interface: message the bot, it fills your forms.

Setup: create a bot with @BotFather, put the token in TELEGRAM_BOT_TOKEN,
then run `notion-ai-telegram`.
"""

from __future__ import annotations

import asyncio
import logging

from .agent import NotionFormAgent
from .config import Settings

logger = logging.getLogger("notion-ai-telegram")

_MAX_MESSAGE = 4000  # Telegram's hard limit is 4096 chars


def main() -> None:
    try:
        from telegram import Update
        from telegram.constants import ChatAction
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        raise SystemExit(
            "python-telegram-bot is not installed. Run: pip install 'notion-form-ai[telegram]'"
        )

    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set (get one from @BotFather).")

    agents: dict[int, NotionFormAgent] = {}
    locks: dict[int, asyncio.Lock] = {}

    def _agent_for(chat_id: int) -> tuple[NotionFormAgent, asyncio.Lock]:
        if chat_id not in agents:
            agents[chat_id] = NotionFormAgent(settings)
            locks[chat_id] = asyncio.Lock()
        return agents[chat_id], locks[chat_id]

    async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message:
            await message.reply_text(
                "Hi! I fill forms for you: Notion database entries, page templates, "
                "Notion forms, and web forms.\n\n"
                "Try: “log a $40 dinner expense for yesterday” or send a form URL.\n"
                "/reset clears our conversation."
            )

    async def reset(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        agent = agents.get(chat_id)
        if agent:
            agent.reset()
        if update.effective_message:
            await update.effective_message.reply_text("Conversation cleared.")

    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # effective_message covers both new and edited messages (update.message
        # is None for edits and would raise).
        message = update.effective_message
        if message is None:
            return
        chat_id = update.effective_chat.id
        text = (message.text or "").strip()
        if not text:
            return
        agent, lock = _agent_for(chat_id)
        async with lock:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            try:
                # The agent is synchronous (and uses sync Playwright), so run
                # it off the event loop.
                reply = await asyncio.to_thread(agent.run, text)
            except Exception as exc:
                logger.exception("agent error")
                reply = f"Something went wrong: {exc}"
        for start_idx in range(0, len(reply), _MAX_MESSAGE):
            await message.reply_text(reply[start_idx : start_idx + _MAX_MESSAGE])

    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    logger.info("bot running — press Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()

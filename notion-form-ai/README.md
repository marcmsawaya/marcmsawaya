# 🤖 Notion Form AI

An AI agent (powered by Claude) that **fills forms for you from plain English**:

| What it fills | Example request |
|---|---|
| **Notion database entries** | “Log a $40 dinner expense for yesterday in my Expenses tracker” |
| **Notion page templates** | “Create this week’s review from my Weekly Review template” |
| **Notion Forms** | “Submit my availability to the team’s scheduling form” |
| **External web forms** | “Fill the sign-up form at https://… with my details from Notion” |

It looks up the right database, reads its schema, matches your values to the
field types and select options, resolves dates like “next Friday”, and fills
everything in. For web forms it uses a headless browser, fills the fields,
shows you a screenshot, and **only submits after you confirm**.

Use it four ways: **CLI**, **web app**, **Telegram bot** — or **no code at
all** via Claude with the Notion connector (see the last section).

---

## 1. Setup

Requires Python 3.10+.

```bash
cd notion-form-ai
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all,dev]"
playwright install chromium        # only needed for web-form filling
cp .env.example .env               # then edit .env
```

You need two secrets in `.env` (or exported in your shell):

1. **`ANTHROPIC_API_KEY`** — from [platform.claude.com](https://platform.claude.com/).
2. **`NOTION_TOKEN`** — create an *internal integration* at
   [notion.so/my-integrations](https://www.notion.so/my-integrations), copy the
   secret, then **share your pages/databases with it** (page ⋯ menu →
   Connections → your integration). The agent can only see what you share.

Optional: **`TELEGRAM_BOT_TOKEN`** from [@BotFather](https://t.me/BotFather)
if you want the Telegram bot.

---

## 2. CLI

```bash
notion-ai                          # interactive chat
notion-ai -m "add 'Buy textbooks' to my Tasks database, due next Monday, priority High"
```

The CLI shows each tool step (`⚙ search_notion …`) while it works.

## 3. Web app

```bash
notion-ai-web                      # http://127.0.0.1:8377
```

A minimal chat UI; each session keeps its own conversation. Runs locally —
don’t expose it to the internet as-is (it has no authentication).

## 4. Telegram bot

```bash
notion-ai-telegram
```

Message your bot: `/start`, then talk to it like the CLI. `/reset` clears the
conversation. Great for logging things from your phone.

## 5. How the four fill targets work

- **Database entries** — the agent finds the database (`search_notion`), reads
  its fields and select options (`get_database_schema`), then creates a fully
  typed entry (`create_database_entry`). It can also update existing entries.
- **Page templates** — put `{{placeholders}}` in any Notion template page
  (e.g. `{{week}}`, `{{goals}}`). The agent reads the template, fills the
  placeholders from your request, and creates the new page under any parent
  page or database.
- **Notion Forms** — a Notion form’s responses live in a backing database; if
  you share that database with the integration, the agent submits responses
  directly. Otherwise give it the public form URL and it fills it in the
  browser like any web form.
- **Web forms** — `read_web_form` lists a page’s fields; the agent fills them
  (`fill_web_form`), saves a screenshot to `form_screenshots/`, and asks for
  your explicit go-ahead before pressing submit. Tip: keep a “My Info” page in
  Notion (name, email, address, links) and say “use my details from Notion”.

## 6. Programmatic use

```python
from notion_form_ai import NotionFormAgent

agent = NotionFormAgent()
print(agent.run("Log a $40 dinner expense for yesterday"))
print(agent.run("Actually make it $45"))   # conversation is remembered
agent.close()
```

## 7. No-code option: Claude + Notion connector

If you use Claude (claude.ai / Claude Cowork) with the **Notion connector**
enabled, you already have this capability with zero hosting: just ask Claude
“log this expense in my tracker” or “fill this template for the week”, and it
uses the same Notion access this project automates. This repo is for when you
want it as your **own** app — scriptable, on Telegram, or embedded elsewhere.

## 8. Tests

```bash
pytest
```

## Notes & limits

- The agent never submits an external web form without your explicit
  confirmation, and treats web/Notion content as data, not instructions.
- Notion fields with read-only types (formula, rollup, created time…) are
  reported as such rather than written.
- Heavily custom form widgets (some Google Forms questions) may need you to
  pass values by field label; the screenshot shows exactly what was filled.
- If you already have Chrome/Chromium installed, set `NOTION_AI_CHROMIUM` to
  its binary path to skip `playwright install chromium`.

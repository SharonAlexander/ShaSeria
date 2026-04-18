"""
bot.py — Telegram bot that reads JSON files from GitHub
Run: python bot.py
"""

import logging
import json
from datetime import date

import requests as req
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── GitHub raw URL helpers ─────────────────────────────────────────────────────

GITHUB_RAW  = f"https://raw.githubusercontent.com/{config.GITHUB_USER}/{config.GITHUB_REPO}/main"
GITHUB_API  = f"https://api.github.com/repos/{config.GITHUB_USER}/{config.GITHUB_REPO}/contents/data"
PAGES_URL   = f"https://{config.GITHUB_USER}.github.io/{config.GITHUB_REPO}"


def fetch_json_for_date(for_date: str) -> dict | None:
    """Fetch serials_YYYY-MM-DD.json from GitHub raw."""
    url = f"{GITHUB_RAW}/data/serials_{for_date}.json"
    try:
        r = req.get(url, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.error(f"GitHub fetch failed: {e}")
    return None


def fetch_available_dates() -> list[str]:
    """List all dated JSON files in data/ via GitHub API, newest first."""
    try:
        headers = {}
        if config.GITHUB_TOKEN:
            headers["Authorization"] = f"token {config.GITHUB_TOKEN}"
        r = req.get(GITHUB_API, headers=headers, timeout=15)
        if r.status_code == 200:
            files = r.json()
            dates = []
            for f in files:
                name = f.get("name", "")
                if name.startswith("serials_") and name.endswith(".json"):
                    d = name.replace("serials_", "").replace(".json", "")
                    dates.append(d)
            return sorted(dates, reverse=True)
    except Exception as e:
        log.error(f"GitHub API fetch failed: {e}")
    return []


# ── Message formatting ─────────────────────────────────────────────────────────

def format_message(data: dict, for_date: str) -> list[str]:
    if not data:
        return [f"No data found for {for_date}."]

    serials  = data.get("serials", [])
    found    = data.get("found", 0)
    total    = data.get("total", 0)
    page_url = f"{PAGES_URL}/{for_date}.html"

    header = (
        f"📺 *Serials — {for_date}*\n"
        f"_{found}/{total} links found_\n"
        f"[🌐 Open full page]({page_url})\n"
        f"{'─' * 28}\n"
    )

    lines = []
    for s in sorted(serials, key=lambda x: x["name"]):
        name = s["name"]
        url  = s.get("video_url")
        if url:
            lines.append(f"▶ [{name}]({url})")
        else:
            lines.append(f"❌ ~{name}~")

    chunks = []
    current = header
    for line in lines:
        if len(current) + len(line) + 1 > 4096:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current:
        chunks.append(current)
    return chunks


# ── Keyboards ──────────────────────────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 Today's Serials",  callback_data="today")],
        [InlineKeyboardButton("📅 Pick a Date",      callback_data="history:0")],
        [InlineKeyboardButton("🌐 Open Web Archive", url=PAGES_URL)],
    ])


def date_picker(offset: int = 0) -> InlineKeyboardMarkup:
    dates = fetch_available_dates()
    if not dates:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("No history yet", callback_data="noop")],
            [InlineKeyboardButton("⬅ Back", callback_data="back")],
        ])

    page    = dates[offset: offset + 5]
    buttons = [[InlineKeyboardButton(d, callback_data=f"date:{d}")] for d in page]

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("⬅ Newer", callback_data=f"history:{offset-5}"))
    if offset + 5 < len(dates):
        nav.append(InlineKeyboardButton("Older ➡", callback_data=f"history:{offset+5}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("⬅ Back", callback_data="back")])
    return InlineKeyboardMarkup(buttons)


# ── Send helper ────────────────────────────────────────────────────────────────

async def send_serials(chat_id, context, for_date: str, edit_message=None):
    data   = fetch_json_for_date(for_date)
    chunks = format_message(data, for_date)

    first = True
    for chunk in chunks:
        if first and edit_message:
            await edit_message.edit_text(
                chunk,
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=main_menu() if len(chunks) == 1 else None,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        first = False

    if len(chunks) > 1:
        await context.bot.send_message(
            chat_id=chat_id,
            text="─" * 20,
            reply_markup=main_menu(),
        )


# ── Handlers ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *ShaSeria Bot*\n\nFetch today's serial links or browse history.",
        parse_mode="Markdown",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    chat  = query.message.chat_id

    if data == "today":
        today = date.today().isoformat()
        await query.edit_message_text("⏳ Fetching today's links …")
        await send_serials(chat, ctx, today, edit_message=query.message)

    elif data.startswith("history:"):
        offset = int(data.split(":")[1])
        await query.edit_message_text(
            "📅 *Select a date:*",
            parse_mode="Markdown",
            reply_markup=date_picker(offset),
        )

    elif data.startswith("date:"):
        chosen = data.split(":", 1)[1]
        await query.edit_message_text(f"⏳ Fetching {chosen} …")
        await send_serials(chat, ctx, chosen, edit_message=query.message)

    elif data == "back":
        await query.edit_message_text(
            "Choose an option:",
            reply_markup=main_menu(),
        )

    elif data == "noop":
        pass


# ── Scheduled daily push ───────────────────────────────────────────────────────

async def scheduled_push(app):
    """
    Runs daily — waits for GitHub Actions to finish, then pushes to your chat.
    Set PUSH_DELAY_MINUTES in config.py to wait after scrape completes.
    """
    import asyncio
    log.info("⏰ Scheduled push — waiting for GitHub Actions to finish …")
    await asyncio.sleep(config.PUSH_DELAY_MINUTES * 60)

    today  = date.today().isoformat()
    data   = fetch_json_for_date(today)
    chunks = format_message(data, today)

    for chunk in chunks:
        await app.bot.send_message(
            chat_id=config.YOUR_CHAT_ID,
            text=chunk,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    await app.bot.send_message(
        chat_id=config.YOUR_CHAT_ID,
        text="✅ Daily update complete.",
        reply_markup=main_menu(),
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(button_handler))

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "Open main menu"),
        ])
    app.post_init = post_init

    # Daily push scheduler — fires after GitHub Actions finishes
    # Scheduler — start inside post_init so the event loop is already running
    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "Open main menu"),
        ])
        scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
        scheduler.add_job(
            scheduled_push,
            trigger="cron",
            hour=config.PUSH_HOUR,
            minute=config.PUSH_MINUTE,
            args=[application],
        )
        scheduler.start()
        log.info(f"Scheduler set — daily push at {config.PUSH_HOUR:02d}:{config.PUSH_MINUTE:02d} {config.TIMEZONE}")

    app.post_init = post_init
    log.info(f"Bot started — daily push at {config.PUSH_HOUR:02d}:{config.PUSH_MINUTE:02d} {config.TIMEZONE}")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

import os
import json
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

DB_PATH = "clipboard.db"

# ---- Database Setup ----
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            title TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_clip(user_id, content, title=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if not title:
        # Auto-generate title from first few words
        title = content[:50].replace("\n", " ") + ("..." if len(content) > 50 else "")
    c.execute("INSERT INTO clips (user_id, content, title) VALUES (?, ?, ?)", (user_id, content, title))
    clip_id = c.lastrowid
    conn.commit()
    conn.close()
    return clip_id

def get_user_clips(user_id, limit=10, offset=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, content, title, created_at FROM clips WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset)
    )
    clips = c.fetchall()
    conn.close()
    return clips

def get_clip_by_id(clip_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT content, title FROM clips WHERE id = ? AND user_id = ?", (clip_id, user_id))
    clip = c.fetchone()
    conn.close()
    return clip

def delete_clip(clip_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM clips WHERE id = ? AND user_id = ?", (clip_id, user_id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def search_clips(user_id, query):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, content, title, created_at FROM clips WHERE user_id = ? AND (content LIKE ? OR title LIKE ?) ORDER BY created_at DESC LIMIT 10",
        (user_id, f"%{query}%", f"%{query}%")
    )
    clips = c.fetchall()
    conn.close()
    return clips

# ---- Handlers ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 <b>Clipboard Sync Bot</b>\n\n"
        "Send any text and I'll save it to your clipboard.\n\n"
        "<b>Commands:</b>\n"
        "• /list - View saved clips\n"
        "• /search &lt;query&gt; - Search clips\n"
        "• /clear - Delete all clips\n"
        "• /help - Show this message\n\n"
        "Your clips sync across all devices via Telegram!",
        parse_mode="HTML"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def save_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Skip if it's a command
    if text.startswith("/"):
        return

    clip_id = save_clip(user_id, text)
    await update.message.reply_text(
        f"✅ Saved! (Clip #{clip_id})\n"
        f"📝 <i>{text[:100]}{'...' if len(text) > 100 else ''}</i>\n\n"
        "Use /list to view all clips.",
        parse_mode="HTML"
    )

async def list_clips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    page = int(context.args[0]) if context.args and context.args[0].isdigit() else 0
    limit = 5
    offset = page * limit

    clips = get_user_clips(user_id, limit, offset)
    if not clips:
        await update.message.reply_text(
            "📭 No clips saved yet.\nSend any text to save it!"
        )
        return

    keyboard = []
    for clip in clips:
        clip_id, content, title, created = clip
        preview = content[:60].replace("\n", " ") + ("..." if len(content) > 60 else "")
        btn = InlineKeyboardButton(
            f"📋 {title[:30]}",
            callback_data=f"view_{clip_id}"
        )
        keyboard.append([btn])

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page_{page-1}"))
    if len(clips) == limit:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"📋 <b>Your Clips</b> (Page {page+1})\nClick to copy:",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <query>")
        return

    user_id = update.effective_user.id
    query = " ".join(context.args)
    clips = search_clips(user_id, query)

    if not clips:
        await update.message.reply_text(f"🔍 No clips found for: {query}")
        return

    keyboard = []
    for clip in clips:
        clip_id, content, title, created = clip
        preview = content[:60].replace("\n", " ") + ("..." if len(content) > 60 else "")
        btn = InlineKeyboardButton(
            f"📋 {title[:30]}",
            callback_data=f"view_{clip_id}"
        )
        keyboard.append([btn])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"🔍 <b>Search Results for "{query}"</b>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def clear_clips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM clips WHERE user_id = ?", (user_id,))
    count = c.rowcount
    conn.commit()
    conn.close()
    await update.message.reply_text(f"🗑️ Deleted {count} clip(s).")

# ---- Callback Handlers ----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("view_"):
        clip_id = int(data.split("_")[1])
        clip = get_clip_by_id(clip_id, user_id)
        if clip:
            content, title = clip
            keyboard = [
                [
                    InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{clip_id}"),
                    InlineKeyboardButton("📋 Copy", callback_data=f"copy_{clip_id}"),
                ],
                [InlineKeyboardButton("◀️ Back to List", callback_data="page_0")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"<b>{title}</b>\n\n"
                f"<code>{content[:1500]}</code>"
                f"{'...' if len(content) > 1500 else ''}",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text("❌ Clip not found.")

    elif data.startswith("delete_"):
        clip_id = int(data.split("_")[1])
        if delete_clip(clip_id, user_id):
            await query.edit_message_text("🗑️ Clip deleted!")
        else:
            await query.edit_message_text("❌ Could not delete clip.")

    elif data.startswith("copy_"):
        clip_id = int(data.split("_")[1])
        clip = get_clip_by_id(clip_id, user_id)
        if clip:
            content, title = clip
            await query.edit_message_text(
                f"<b>📋 Copy this text:</b>\n\n"
                f"<code>{content[:1500]}</code>"
                f"{'...' if len(content) > 1500 else ''}",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text("❌ Clip not found.")

    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        # Re-create the list for this page
        limit = 5
        offset = page * limit
        clips = get_user_clips(user_id, limit, offset)

        if not clips:
            await query.edit_message_text("📭 No clips on this page.")
            return

        keyboard = []
        for clip in clips:
            clip_id, content, title, created = clip
            btn = InlineKeyboardButton(
                f"📋 {title[:30]}",
                callback_data=f"view_{clip_id}"
            )
            keyboard.append([btn])

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page_{page-1}"))
        if len(clips) == limit:
            nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"page_{page+1}"))
        if nav_buttons:
            keyboard.append(nav_buttons)

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"📋 <b>Your Clips</b> (Page {page+1})",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

def main():
    init_db()
    app = Application.builder().token(os.environ["BOT_TOKEN"]).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_clips))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("clear", clear_clips))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, save_text))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()

if __name__ == '__main__':
    main()

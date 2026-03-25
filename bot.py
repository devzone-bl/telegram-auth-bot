import logging
import os
import threading
import asyncio
import shutil
import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ---------- CONFIGURATION ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")

ADMIN_ID = os.environ.get("ADMIN_ID") 

KEYS_FILE = "KEYS.txt"
USERS_FILE = "USERS.txt"
USERS_BACKUP_FILE = "USERS_BACKUP.txt"

# State Constants
(
    MENU_HUB,
    WAITING_FOR_REG,
    WAITING_FOR_GRANT,
    WAITING_FOR_BAN,
    WAITING_FOR_EXEC_USERS,
    WAITING_FOR_EXEC_TEXT,
    WAITING_FOR_DELETE,
    WAITING_FOR_RENAME_OLD,
    WAITING_FOR_RENAME_NEW,
    WAITING_FOR_KILL
) = range(10)

app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CORE HELPER FUNCTIONS ----------

def ban_all_users_sync():
    if not os.path.exists(USERS_FILE): return 0
    shutil.copyfile(USERS_FILE, USERS_BACKUP_FILE)
    updated_count = 0
    new_lines = []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            username_part = line.split(" -> ")[0].strip()
            new_lines.append(f"{username_part} -> BAN\n")
            updated_count += 1
        else:
            new_lines.append(line)
    with open(USERS_FILE, "w") as f:
        f.writelines(new_lines)
    return updated_count

def undo_ban_all_sync():
    if not os.path.exists(USERS_BACKUP_FILE):
        return False
    shutil.copyfile(USERS_BACKUP_FILE, USERS_FILE)
    return True

def rename_user_sync(old_name: str, new_name: str):
    if not os.path.exists(USERS_FILE): return False
    updated = False
    new_lines = []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            parts = line.split(" -> ")
            current_name = parts[0].strip()
            status = parts[1].strip()
            if current_name == old_name.strip():
                new_lines.append(f"{new_name.strip()} -> {status}\n")
                updated = True
            else: new_lines.append(line)
        else: new_lines.append(line)
    if updated:
        with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated

def write_to_files(mac: str, username: str, status: str):
    try:
        for filename, content in [(KEYS_FILE, mac.strip()), (USERS_FILE, f"{username.strip()} -> {status}")]:
            needs_newline = False
            if os.path.isfile(filename) and os.path.getsize(filename) > 0:
                with open(filename, "rb+") as f:
                    f.seek(-1, 2)
                    if f.read(1) != b'\n': needs_newline = True
            with open(filename, "a") as f:
                if needs_newline: f.write("\n")
                f.write(content + "\n")
    except Exception as e: logger.error(f"File write error: {e}")

def batch_update_users(target_input: str, new_status_base: str, extra_text: str = ""):
    if not os.path.exists(USERS_FILE): return 0, []
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    updated_users, new_lines = [], []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            username_part = line.split(" -> ")[0].strip()
            if username_part in targets:
                status_str = f"{new_status_base} {extra_text}".strip()
                new_lines.append(f"{username_part} -> {status_str}\n")
                updated_users.append(username_part)
            else: new_lines.append(line)
        else: new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return len(updated_users), updated_users

def delete_sync_users(target_input: str):
    if not os.path.exists(USERS_FILE) or not os.path.exists(KEYS_FILE): return 0
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    with open(USERS_FILE, "r") as f: u_lines = f.readlines()
    with open(KEYS_FILE, "r") as f: k_lines = f.readlines()
    indices_to_remove = [i for i, l in enumerate(u_lines) if " -> " in l and l.split(" -> ")[0].strip() in targets]
    new_u_lines = [line for i, line in enumerate(u_lines) if i not in indices_to_remove]
    new_k_lines = [line for i, line in enumerate(k_lines) if i not in indices_to_remove]
    with open(USERS_FILE, "w") as f: f.writelines(new_u_lines)
    with open(KEYS_FILE, "w") as f: f.writelines(new_k_lines)
    return len(indices_to_remove)

async def send_daily_backup(context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID: return
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'rb') as f:
                await context.bot.send_document(chat_id=ADMIN_ID, document=f, caption="📅 Daily USERS Backup")
        if os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, 'rb') as f:
                await context.bot.send_document(chat_id=ADMIN_ID, document=f, caption="📅 Daily KEYS Backup")
    except Exception as e:
        logger.error(f"Failed to send daily backup: {e}")

# ---------- UI COMPONENTS ----------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("☠️ KILL", callback_data="m_kill")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="m_del"), InlineKeyboardButton("✏️ Rename", callback_data="m_rename")],
        [InlineKeyboardButton("⚡ Execute", callback_data="m_exec"), InlineKeyboardButton("📋 List", callback_data="m_list")],
        [InlineKeyboardButton("💀 BAN ALL USERS", callback_data="m_ban_all"), InlineKeyboardButton("↩️ Undo Ban All", callback_data="m_undo_ban")],
        [InlineKeyboardButton("📥 Get Backups", callback_data="m_backup"), InlineKeyboardButton("ℹ️ Help", callback_data="m_help")],
        [InlineKeyboardButton("✖️ Close Session", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Operation", callback_data="m_stop")]])

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = "✨ **System Hub Online**\n━━━━━━━━━━━━━━\nSelect administrative action:"
    reply_markup = main_menu_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    c = query.data

    if c == "m_stop":
        await query.edit_message_text("❌ **Action Cancelled.**")
        return await start(update, context)
    
    if c == "m_reg": 
        await query.edit_message_text("📝 **Registration**\nSend: `KEY USERNAME`", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_REG
    if c == "m_grant": 
        await query.edit_message_text("✅ **Grant SAFE**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_GRANT
    if c == "m_ban": 
        await query.edit_message_text("🚫 **Set BAN**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_BAN
    if c == "m_kill": 
        await query.edit_message_text("☠️ **Set KILL**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_KILL
    if c == "m_del": 
        await query.edit_message_text("🗑️ **Sync Delete**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_DELETE
    if c == "m_rename":
        await query.edit_message_text("✏️ **Rename User**\nStep 1: Send the **current** username:", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_RENAME_OLD
    if c == "m_exec": 
        await query.edit_message_text("⚡ **Execute**\nStep 1: Send Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_EXEC_USERS
    
    if c == "m_ban_all":
        count = ban_all_users_sync()
        await query.edit_message_text(f"💀 **Mass Ban Applied**\n{count} users were moved to BAN status.", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB
    
    if c == "m_undo_ban":
        msg = "✅ **Undo Successful**" if undo_ban_all_sync() else "❌ **No backup found.**"
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB

    if c == "m_backup":
        # We don't edit the message here because send_document creates new messages.
        # Instead, we send the files and then a fresh menu.
        chat_id = update.effective_chat.id
        try:
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'rb') as f: await context.bot.send_document(chat_id=chat_id, document=f)
            if os.path.exists(KEYS_FILE):
                with open(KEYS_FILE, 'rb') as f: await context.bot.send_document(chat_id=chat_id, document=f)
            await context.bot.send_message(chat_id=chat_id, text="✅ **Backups sent successfully!**", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        except Exception as e:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}", reply_markup=main_menu_keyboard())
        return MENU_HUB

    if c == "m_list":
        try:
            with open(USERS_FILE, "r") as f: content = f.read().strip()
            msg = f"📋 **Database**\n```\n{content if content else 'Empty'}\n```"
        except: msg = "❌ File not found."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    
    if c == "m_help":
        await query.edit_message_text("🚀 **Help Menu**\nUse buttons to manage users.", reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    
    if c == "m_cancel": 
        await query.edit_message_text("💤 **Session Closed.**", parse_mode="Markdown")
        return ConversationHandler.END

# (Handlers for registration, rename, etc. remain the same as your version)
async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) < 2: return WAITING_FOR_REG
    write_to_files(parts[0], " ".join(parts[1:]), "SAFE")
    return await start(update, context)

async def handle_rename_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rename_old"] = update.message.text.strip()
    await update.message.reply_text("✏️ Send NEW name:", reply_markup=cancel_keyboard())
    return WAITING_FOR_RENAME_NEW

async def handle_rename_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rename_user_sync(context.user_data.get("rename_old"), update.message.text.strip())
    return await start(update, context)

async def handle_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    batch_update_users(update.message.text, "SAFE")
    return await start(update, context)

async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    batch_update_users(update.message.text, "BAN")
    return await start(update, context)

async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    batch_update_users(update.message.text, "KILL")
    return await start(update, context)

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    delete_sync_users(update.message.text)
    return await start(update, context)

async def handle_exec_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["exec_targets"] = update.message.text
    await update.message.reply_text("📝 Send text to append:", reply_markup=cancel_keyboard())
    return WAITING_FOR_EXEC_TEXT

async def handle_exec_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    batch_update_users(context.user_data.get("exec_targets", ""), "SAFE", update.message.text)
    return await start(update, context)

# ---------- APP SETUP ----------
application = Application.builder().token(BOT_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        MENU_HUB: [CallbackQueryHandler(menu_callback)],
        WAITING_FOR_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_GRANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_grant), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_KILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_kill), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_RENAME_OLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rename_old), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_RENAME_NEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rename_new), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_EXEC_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_users), CallbackQueryHandler(menu_callback)],
        WAITING_FOR_EXEC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_final), CallbackQueryHandler(menu_callback)],
    },
    fallbacks=[CallbackQueryHandler(menu_callback, pattern="^m_stop$")],
    conversation_timeout=120
)
application.add_handler(conv_handler)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def init_app():
    await application.initialize()
    if application.job_queue:
        t = datetime.time(hour=0, minute=0, tzinfo=datetime.timezone.utc)
        application.job_queue.run_daily(send_daily_backup, time=t)
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if domain: await application.bot.set_webhook(url=f"https://{domain}/webhook")

loop.create_task(init_app())

def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, daemon=True).start()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return "OK", 200

@app.route('/')
def home(): return "Bot is running", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
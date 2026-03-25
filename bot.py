import logging
import os
import threading
import asyncio
import shutil
import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
# Extract ADMIN_ID from environment and ensure it's an integer for comparison
raw_admin_id = os.environ.get("ADMIN_ID")
try:
    ADMIN_ID = int(raw_admin_id) if raw_admin_id else None
except ValueError:
    ADMIN_ID = None

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")

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

# ---------- SECURITY CHECK ----------
def is_admin(update: Update):
    """Checks if the user sending the message is the authorized Admin."""
    return update.effective_user.id == ADMIN_ID

# ---------- CORE HELPER FUNCTIONS ----------

def ban_all_users_sync():
    """Backs up current users, then sets every user to BAN status."""
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
    """Restores USERS_FILE from the backup created by Ban All."""
    if not os.path.exists(USERS_BACKUP_FILE): return False
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
            if parts[0].strip() == old_name.strip():
                new_lines.append(f"{new_name.strip()} -> {parts[1].strip()}\n")
                updated = True
                continue
        new_lines.append(line)
    if updated:
        with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated

def write_to_files(mac: str, username: str, status: str):
    """Registers a new user: Key to KEYS.txt and Username -> Status to USERS.txt."""
    try:
        with open(KEYS_FILE, "a") as f:
            f.write(mac.strip() + "\n")
        with open(USERS_FILE, "a") as f:
            f.write(f"{username.strip()} -> {status}\n")
    except Exception as e:
        logger.error(f"File write error: {e}")

def batch_update_users(target_input: str, status_text: str):
    """Updates status for multiple users separated by '-'."""
    if not os.path.exists(USERS_FILE): return 0
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    updated_count = 0
    new_lines = []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            username_part = line.split(" -> ")[0].strip()
            if username_part in targets:
                new_lines.append(f"{username_part} -> {status_text}\n")
                updated_count += 1
                continue
        new_lines.append(line)
    with open(USERS_FILE, "w") as f:
        f.writelines(new_lines)
    return updated_count

def delete_sync_users(target_input: str):
    if not os.path.exists(USERS_FILE) or not os.path.exists(KEYS_FILE): return 0
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    with open(USERS_FILE, "r") as f: u_lines = f.readlines()
    with open(KEYS_FILE, "r") as f: k_lines = f.readlines()
    indices = [i for i, l in enumerate(u_lines) if " -> " in l and l.split(" -> ")[0].strip() in targets]
    new_u = [l for i, l in enumerate(u_lines) if i not in indices]
    new_k = [l for i, l in enumerate(k_lines) if i not in indices]
    with open(USERS_FILE, "w") as f: f.writelines(new_u)
    with open(KEYS_FILE, "w") as f: f.writelines(new_k)
    return len(indices)

# ---------- UI COMPONENTS ----------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant SAFE", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("☠️ KILL", callback_data="m_kill")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="m_del"), InlineKeyboardButton("✏️ Rename", callback_data="m_rename")],
        [InlineKeyboardButton("⚡ Send Message", callback_data="m_exec"), InlineKeyboardButton("📋 List", callback_data="m_list")],
        [InlineKeyboardButton("💀 BAN ALL", callback_data="m_ban_all"), InlineKeyboardButton("↩️ Undo Ban", callback_data="m_undo_ban")],
        [InlineKeyboardButton("📥 Get Backups", callback_data="m_backup"), InlineKeyboardButton("✖️ Close", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="m_stop")]])

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END # Ignore unauthorized
    
    text = "✨ **System Hub Online**\nSelect administrative action:"
    reply_markup = main_menu_keyboard()
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    c = query.data

    if c == "m_stop":
        await query.edit_message_text("❌ Action Cancelled."); return await start(update, context)
    if c == "m_reg": 
        await query.edit_message_text("📝 **Register**\nSend: `KEY USERNAME`", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_REG
    if c == "m_grant": 
        await query.edit_message_text("✅ **Grant SAFE**\nSend Username(s):", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_GRANT
    if c == "m_ban": 
        await query.edit_message_text("🚫 **Set BAN**\nSend Username(s):", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_BAN
    if c == "m_kill": 
        await query.edit_message_text("☠️ **Set KILL**\nSend Username(s):", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_KILL
    if c == "m_del": 
        await query.edit_message_text("🗑️ **Delete**\nSend Username(s):", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_DELETE
    if c == "m_rename":
        await query.edit_message_text("✏️ **Rename**\nStep 1: Send CURRENT username:", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_RENAME_OLD
    if c == "m_exec": 
        await query.edit_message_text("⚡ **Send Message**\nStep 1: Send Username(s):", reply_markup=cancel_keyboard(), parse_mode="Markdown"); return WAITING_FOR_EXEC_USERS
    
    if c == "m_ban_all":
        count = ban_all_users_sync()
        await query.edit_message_text(f"💀 **Mass Ban Applied**\n{count} users locked out. Backup created.", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB
    
    if c == "m_undo_ban":
        if undo_ban_all_sync(): msg = "✅ **Undo Successful**\nUsers restored from backup."
        else: msg = "❌ **No backup found.**"
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB

    if c == "m_backup":
        for f_path in [USERS_FILE, KEYS_FILE]:
            if os.path.exists(f_path):
                with open(f_path, 'rb') as f: await context.bot.send_document(chat_id=update.effective_chat.id, document=f)
        await context.bot.send_message(chat_id=update.effective_chat.id, text="📥 **Backups Sent.**", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB

    if c == "m_list":
        try:
            with open(USERS_FILE, "r") as f: content = f.read().strip()
            msg = f"📋 **Database**\n```\n{content if content else 'Empty'}\n```"
        except: msg = "❌ File not found."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    
    if c == "m_cancel": 
        await query.edit_message_text("💤 Session Closed."); return ConversationHandler.END

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split(None, 1)
    if len(parts) < 2: return WAITING_FOR_REG
    write_to_files(parts[0], parts[1], "SAFE")
    await update.message.reply_text(f"✅ Registered `{parts[1]}` as SAFE")
    return await start(update, context)

async def handle_rename_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rename_old"] = update.message.text.strip()
    await update.message.reply_text(f"✏️ Target: `{update.message.text}`\nSend **NEW** username:", reply_markup=cancel_keyboard())
    return WAITING_FOR_RENAME_NEW

async def handle_rename_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    old, new = context.user_data.get("rename_old"), update.message.text.strip()
    if rename_user_sync(old, new): await update.message.reply_text(f"✅ Renamed `{old}` to `{new}`")
    else: await update.message.reply_text(f"❌ User `{old}` not found.")
    return await start(update, context)

async def handle_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = batch_update_users(update.message.text, "SAFE")
    await update.message.reply_text(f"✅ Updated {count} users to SAFE"); return await start(update, context)

async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = batch_update_users(update.message.text, "BAN")
    await update.message.reply_text(f"🚫 {count} users BANNED"); return await start(update, context)

async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = batch_update_users(update.message.text, "KILL")
    await update.message.reply_text(f"☠️ {count} users set to KILL"); return await start(update, context)

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = delete_sync_users(update.message.text)
    await update.message.reply_text(f"🗑️ Deleted {count} users."); return await start(update, context)

async def handle_exec_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["exec_targets"] = update.message.text
    await update.message.reply_text("📝 **Step 2:** Send the message text for the popup:", reply_markup=cancel_keyboard())
    return WAITING_FOR_EXEC_TEXT

async def handle_exec_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.replace('"', '""') # Escape quotes for VBScript
    status_str = f'SAFE mshta vbscript:Execute("msgbox ""{msg}"":close")'
    count = batch_update_users(context.user_data.get("exec_targets", ""), status_str)
    await update.message.reply_text(f"⚡ Applied message to {count} users."); return await start(update, context)

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

@app.route('/USERS.txt')
def get_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f: return f.read(), 200, {'Content-Type': 'text/plain'}
    return "Not found", 404

@app.route('/KEYS.txt')
def get_keys():
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, 'r') as f: return f.read(), 200, {'Content-Type': 'text/plain'}
    return "Not found", 404

@app.route('/')
def home(): return "Bot Active", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
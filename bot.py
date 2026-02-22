import logging
import os
import threading
import asyncio
import traceback
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
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")

KEYS_FILE = "KEYS.txt"
USERS_FILE = "USERS.txt"

# Conversation states
(
    MENU_HUB,
    WAITING_FOR_REG,
    WAITING_FOR_GRANT,
    WAITING_FOR_BAN,
    WAITING_FOR_EXEC_USERS,
    WAITING_FOR_EXEC_TEXT,
    WAITING_FOR_DELETE
) = range(7)

app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CORE HELPER FUNCTIONS ----------

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
    except Exception as e:
        logger.error(f"File write error: {e}")

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
    """Deletes lines from USERS and KEYS files by matching the line index."""
    if not os.path.exists(USERS_FILE) or not os.path.exists(KEYS_FILE): return 0
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    
    with open(USERS_FILE, "r") as f: u_lines = f.readlines()
    with open(KEYS_FILE, "r") as f: k_lines = f.readlines()

    indices_to_remove = []
    deleted_names = []

    # Find indices where the username matches
    for idx, line in enumerate(u_lines):
        if " -> " in line:
            name = line.split(" -> ")[0].strip()
            if name in targets:
                indices_to_remove.append(idx)
                deleted_names.append(name)

    # Filter out the lines. We use index matching to ensure Line 34 in USERS = Line 34 in KEYS.
    new_u_lines = [line for i, line in enumerate(u_lines) if i not in indices_to_remove]
    new_k_lines = [line for i, line in enumerate(k_lines) if i not in indices_to_remove]

    with open(USERS_FILE, "w") as f: f.writelines(new_u_lines)
    with open(KEYS_FILE, "w") as f: f.writelines(new_k_lines)
    
    return len(deleted_names)

# ---------- UI COMPONENTS ----------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("🗑️ Delete", callback_data="m_del")],
        [InlineKeyboardButton("⚡ Execute", callback_data="m_exec"), InlineKeyboardButton("📋 List", callback_data="m_list")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="m_help"), InlineKeyboardButton("✖️ Close", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- CONVERSATION HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = "✨ **System Hub Online**\n━━━━━━━━━━━━━━\nSelect administrative action:"
    if update.message: await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    else: await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    c = query.data
    if c == "m_reg": await query.edit_message_text("📝 **Registration**\nSend: `KEY USERNAME`", parse_mode="Markdown"); return WAITING_FOR_REG
    if c == "m_grant": await query.edit_message_text("✅ **Grant SAFE**\nSend Username(s):", parse_mode="Markdown"); return WAITING_FOR_GRANT
    if c == "m_ban": await query.edit_message_text("🚫 **Set BAN**\nSend Username(s):", parse_mode="Markdown"); return WAITING_FOR_BAN
    if c == "m_del": await query.edit_message_text("🗑️ **Sync Delete**\nSend Username(s) to remove from both files:", parse_mode="Markdown"); return WAITING_FOR_DELETE
    if c == "m_exec": await query.edit_message_text("⚡ **Execute**\nStep 1: Send Username(s):", parse_mode="Markdown"); return WAITING_FOR_EXEC_USERS
    if c == "m_list":
        try:
            with open(USERS_FILE, "r") as f: content = f.read().strip()
            msg = f"📋 **Database**\n```\n{content if content else 'Empty'}\n```"
        except: msg = "❌ File not found."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    if c == "m_help":
        await query.edit_message_text("🚀 **Help**\nDelete : removes the user and their specific Key from the same line in both files.\nRegiter : Zid chi user jdid blkey dyalo \nBan : Bani chi user mn lpanel perma \nGrant : 7yd lban lchi user \nExecute : command ydirha loader mli ytft7 \nList : lit dyal ga3 li msjlin db \nClose : Killi Lworking Session", reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    if c == "m_cancel": await query.edit_message_text("💤 Session Closed."); return ConversationHandler.END

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.split()
    if len(parts) < 2: return WAITING_FOR_REG
    write_to_files(parts[0], " ".join(parts[1:]), "SAFE")
    await update.message.reply_text(f"✅ Registered `{parts[1]}`"); return await start(update, context)

async def handle_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count, _ = batch_update_users(update.message.text, "SAFE")
    await update.message.reply_text(f"✅ Updated {count} users to SAFE"); return await start(update, context)

async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count, _ = batch_update_users(update.message.text, "BAN")
    await update.message.reply_text(f"🚫 {count} users BANNED"); return await start(update, context)

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count = delete_sync_users(update.message.text)
    await update.message.reply_text(f"🗑️ Successfully deleted {count} users and their keys."); return await start(update, context)

async def handle_exec_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["exec_targets"] = update.message.text
    await update.message.reply_text("📝 **Step 2:** Send text to append:"); return WAITING_FOR_EXEC_TEXT

async def handle_exec_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count, _ = batch_update_users(context.user_data.get("exec_targets", ""), "SAFE", update.message.text)
    await update.message.reply_text(f"⚡ Modified {count} users."); return await start(update, context)

# ---------- APP SETUP ----------
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "❌ **Action Cancelled.**\nReturning to main menu...", 
        parse_mode="Markdown"
    )
    # Clear any temporary data stored during the process
    context.user_data.clear()
    
    # Return to the start menu
    return await start(update, context)
application = Application.builder().token(BOT_TOKEN).build()
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("begin", start), CommandHandler("start", start)],
    states={
        MENU_HUB: [CallbackQueryHandler(menu_callback)],
        WAITING_FOR_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration)],
        WAITING_FOR_GRANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_grant)],
        WAITING_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban)],
        WAITING_FOR_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete)],
        WAITING_FOR_EXEC_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_users)],
        WAITING_FOR_EXEC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_final)],
    },
    fallbacks=[CommandHandler("cancel", cancel_command)],
)
application.add_handler(conv_handler)




# [Your existing Flask / Webhook startup code here]
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
async def init_app():
    await application.initialize()
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        await application.bot.set_webhook(url=f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN')}/webhook")
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
@app.route('/health')
def health():
    return "OK", 200

@app.route('/')
def home():
    return "Bot is running", 200

# This is the part that was missing or broken:
@app.route('/USERS.txt')
def get_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r') as f:
                return f.read(), 200, {'Content-Type': 'text/plain'}
        else:
            return "File not found", 404
    except Exception as e:
        logger.error(f"Error serving USERS.txt: {e}")
        return "Internal Error", 500

@app.route('/KEYS.txt')
def get_keys():
    try:
        if os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, 'r') as f:
                return f.read(), 200, {'Content-Type': 'text/plain'}
        else:
            return "File not found", 404
    except Exception as e:
        logger.error(f"Error serving KEYS.txt: {e}")
        return "Internal Error", 500

# ---------- START FLASK ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
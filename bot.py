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
    WAITING_FOR_EXEC_TEXT
) = range(6)

# Flask app
app = Flask(__name__)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- CORE HELPER FUNCTIONS ----------

def write_to_files(mac: str, username: str, status: str):
    """Handles initial registration logic."""
    try:
        for filename, content in [(KEYS_FILE, mac.strip()), (USERS_FILE, f"{username.strip()} -> {status}")]:
            file_exists = os.path.isfile(filename)
            needs_newline = False
            if file_exists and os.path.getsize(filename) > 0:
                with open(filename, "rb+") as f:
                    f.seek(-1, 2)
                    if f.read(1) != b'\n':
                        needs_newline = True
            
            with open(filename, "a") as f:
                if needs_newline:
                    f.write("\n")
                f.write(content + "\n")
    except Exception as e:
        logger.error(f"File write error: {e}")

def batch_update_users(target_input: str, new_status_base: str, extra_text: str = ""):
    """Updates multiple users at once. Support for Grant, Ban, and Execute."""
    if not os.path.exists(USERS_FILE):
        return 0, []

    # Split input by spaces to support multi-selection
    targets = [u.strip() for u in target_input.split() if u.strip()]
    updated_users = []
    new_lines = []

    with open(USERS_FILE, "r") as f:
        lines = f.readlines()

    for line in lines:
        if " -> " in line:
            username_part = line.split(" -> ")[0].strip()
            if username_part in targets:
                # Format: Username -> SAFE/BAN [optional extra text]
                status_str = f"{new_status_base} {extra_text}".strip()
                new_lines.append(f"{username_part} -> {status_str}\n")
                updated_users.append(username_part)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    with open(USERS_FILE, "w") as f:
        f.writelines(new_lines)
    
    return len(updated_users), updated_users

# ---------- UI COMPONENTS ----------

def main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📝 Register", callback_data="m_reg"),
            InlineKeyboardButton("✅ Grant", callback_data="m_grant")
        ],
        [
            InlineKeyboardButton("🚫 Ban", callback_data="m_ban"),
            InlineKeyboardButton("📋 List", callback_data="m_list")
        ],
        [
            InlineKeyboardButton("⚡ Execute", callback_data="m_exec"),
            InlineKeyboardButton("ℹ️ Help", callback_data="m_help")
        ],
        [InlineKeyboardButton("✖️ Close Menu", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- CONVERSATION HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (
        "✨ **Welcome Administrator**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "System is online. Please choose an operation:"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "m_reg":
        await query.edit_message_text("📝 **Registration Mode**\nSend the `KEY` and `USERNAME` separated by space:", parse_mode="Markdown")
        return WAITING_FOR_REG
    
    elif choice == "m_grant":
        await query.edit_message_text("✅ **Grant Status (SAFE)**\nSend the Username(s) to authorize (space separated):", parse_mode="Markdown")
        return WAITING_FOR_GRANT

    elif choice == "m_ban":
        await query.edit_message_text("🚫 **Ban Status (BAN)**\nSend the Username(s) to restrict (space separated):", parse_mode="Markdown")
        return WAITING_FOR_BAN

    elif choice == "m_exec":
        await query.edit_message_text("⚡ **Execute Command**\nStep 1: Send the target Username(s):", parse_mode="Markdown")
        return WAITING_FOR_EXEC_USERS

    elif choice == "m_list":
        try:
            with open(USERS_FILE, "r") as f:
                content = f.read().strip()
            msg = f"📋 **User Database**\n```\n{content if content else 'No users found.'}\n```"
        except FileNotFoundError:
            msg = "❌ Error: `USERS.txt` not found."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB

    elif choice == "m_help":
        help_txt = (
            "🚀 **Command Reference**\n\n"
            "• **Register**: Adds new Key + User.\n"
            "• **Grant**: Sets users to `SAFE` status.\n"
            "• **Ban**: Sets users to `BAN` status.\n"
            "• **Execute**: Appends custom text to `SAFE` status.\n"
            "• **Multi-Select**: Send multiple names (e.g. `User1 User2`) to update all at once."
        )
        await query.edit_message_text(help_txt, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB

    elif choice == "m_cancel":
        await query.edit_message_text("💤 Session closed. Use `/begin` to restart.")
        return ConversationHandler.END

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parts = update.message.text.split()
    if len(parts) < 2:
        await update.message.reply_text("❌ **Format Error!** Send: `[KEY] [USERNAME]`")
        return WAITING_FOR_REG
    
    mac, username = parts[0], " ".join(parts[1:])
    write_to_files(mac, username, "SAFE")
    await update.message.reply_text(f"✅ Registered `{username}` successfully!", parse_mode="Markdown")
    return await start(update, context)

async def handle_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count, names = batch_update_users(update.message.text, "SAFE")
    await update.message.reply_text(f"✅ **Success!** {count} users updated to SAFE: `{', '.join(names)}`", parse_mode="Markdown")
    return await start(update, context)

async def handle_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    count, names = batch_update_users(update.message.text, "BAN")
    await update.message.reply_text(f"🚫 **Banned!** {count} users set to BAN: `{', '.join(names)}`", parse_mode="Markdown")
    return await start(update, context)

async def handle_exec_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["exec_targets"] = update.message.text
    await update.message.reply_text("📝 **Step 2:** Send the custom text to append (e.g. `hy faveloxx`):")
    return WAITING_FOR_EXEC_TEXT

async def handle_exec_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    custom_text = update.message.text
    targets = context.user_data.get("exec_targets", "")
    count, names = batch_update_users(targets, "SAFE", custom_text)
    await update.message.reply_text(f"⚡ **Execution Complete!** Modified {count} users.", parse_mode="Markdown")
    return await start(update, context)

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# ---------- APPLICATION SETUP ----------

application = Application.builder().token(BOT_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("begin", start), CommandHandler("start", start)],
    states={
        MENU_HUB: [CallbackQueryHandler(menu_callback)],
        WAITING_FOR_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration)],
        WAITING_FOR_GRANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_grant)],
        WAITING_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban)],
        WAITING_FOR_EXEC_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_users)],
        WAITING_FOR_EXEC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_final)],
    },
    fallbacks=[CommandHandler("cancel", cancel_cmd)],
)

application.add_handler(conv_handler)

# ---------- ASYNC / FLASK INTEGRATION ----------

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def init_app():
    await application.initialize()
    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if public_domain:
        webhook_url = f"https://{public_domain}/webhook"
        await application.bot.set_webhook(url=webhook_url)

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
def health(): return "OK", 200

@app.route('/USERS.txt')
def get_users():
    try:
        with open(USERS_FILE, 'r') as f: return f.read(), 200, {'Content-Type': 'text/plain'}
    except: return "", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
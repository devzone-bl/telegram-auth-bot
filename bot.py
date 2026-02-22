import logging
import os
import threading
import asyncio
from flask import Flask
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

# ---------- CONFIGURATION ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")

APPROVED_FILE = "approved.txt"
BANNED_FILE = "banned.txt"

# Flask app for health checks
app = Flask(__name__)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- HANDLERS ----------
async def start(update, context):
    await update.message.reply_text(
        "Auth Bot is running!\n"
        "Commands:\n"
        "/approve MAC - Approve a user\n"
        "/deny MAC - Deny a user\n"
        "/list - Show approved users\n"
        "/banall - Remove all approvals"
    )

async def approve_command(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /approve MAC_ADDRESS")
        return
    mac = context.args[0]
    with open(APPROVED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"✅ Approved {mac}")

async def deny_command(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /deny MAC_ADDRESS")
        return
    mac = context.args[0]
    with open(BANNED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"❌ Denied {mac}")

async def list_approved(update, context):
    try:
        with open(APPROVED_FILE, "r") as f:
            approved = f.read().strip()
        if approved:
            await update.message.reply_text(f"✅ Approved users:\n{approved}")
        else:
            await update.message.reply_text("No approved users")
    except FileNotFoundError:
        await update.message.reply_text("No approved users")

async def ban_all(update, context):
    open(APPROVED_FILE, "w").close()
    await update.message.reply_text("⚠️ All users banned (approved list cleared)")

async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data  # Format: "action|MAC"
    action, mac = data.split('|')
    if action == "approve":
        with open(APPROVED_FILE, "a") as f:
            f.write(mac + "\n")
        await query.edit_message_text(text=f"✅ Approved {mac}")
    elif action == "deny":
        with open(BANNED_FILE, "a") as f:
            f.write(mac + "\n")
        await query.edit_message_text(text=f"❌ Denied {mac}")

# ---------- BUILD APPLICATION ----------
application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("approve", approve_command))
application.add_handler(CommandHandler("deny", deny_command))
application.add_handler(CommandHandler("list", list_approved))
application.add_handler(CommandHandler("banall", ban_all))
application.add_handler(CallbackQueryHandler(button_callback))

# ---------- FLASK HEALTH ENDPOINT ----------
@app.route('/health')
def health():
    return "OK", 200

# ---------- FUNCTION TO RUN FLASK ----------
def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ---------- MAIN ----------
if __name__ == "__main__":
    # Start Flask in a background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run the bot in the main thread
    application.run_polling()
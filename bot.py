import logging
import os
import threading
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ---------- CONFIGURATION ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")

APPROVED_FILE = "approved.txt"
BANNED_FILE = "banned.txt"

# Flask app
app = Flask(__name__)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Auth Bot is running!\n"
        "Commands:\n"
        "/approve MAC - Approve a user\n"
        "/deny MAC - Deny a user\n"
        "/list - Show approved users\n"
        "/banall - Remove all approvals"
    )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /approve MAC_ADDRESS")
        return
    mac = context.args[0]
    with open(APPROVED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"✅ Approved {mac}")

async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /deny MAC_ADDRESS")
        return
    mac = context.args[0]
    with open(BANNED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"❌ Denied {mac}")

async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(APPROVED_FILE, "r") as f:
            approved = f.read().strip()
        if approved:
            await update.message.reply_text(f"✅ Approved users:\n{approved}")
        else:
            await update.message.reply_text("No approved users")
    except FileNotFoundError:
        await update.message.reply_text("No approved users")

async def ban_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    open(APPROVED_FILE, "w").close()
    await update.message.reply_text("⚠️ All users banned (approved list cleared)")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

# ---------- ASYNC LOOP IN BACKGROUND ----------
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def init_app():
    await application.initialize()
    # Set webhook info (optional, just for logging)
    webhook_url = f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost')}/webhook"
    await application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

loop.create_task(init_app())

def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, daemon=True).start()

# ---------- FLASK WEBHOOK ENDPOINT ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    """Receive Telegram update and dispatch to bot loop."""
    if request.method == 'POST':
        update = Update.de_json(request.get_json(force=True), application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        logger.info("Update processed")
        return "OK", 200
    return "Method Not Allowed", 405

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

@app.route('/')
def home():
    return "Bot is running", 200
@app.route('/approved.txt')
def get_approved():
    try:
        with open(APPROVED_FILE, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}
    except FileNotFoundError:
        return "", 200, {'Content-Type': 'text/plain'}

@app.route('/banned.txt')
def get_banned():
    try:
        with open(BANNED_FILE, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}
    except FileNotFoundError:
        return "", 200, {'Content-Type': 'text/plain'}
# ---------- START FLASK ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
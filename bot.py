import logging
import os
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ---------- CONFIGURATION ----------
BOT_TOKEN = os.environ.get("8384623189:AAH22WOwmsszqWfzct1Ieh4hZVXbMNK70jw")  # Railway will set this
APPROVED_FILE = "approved.txt"
BANNED_FILE = "banned.txt"

# Flask app for Railway health checks
app = Flask(__name__)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- TELEGRAM BOT HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    await update.message.reply_text(
        "Auth Bot is running!\n"
        "Commands:\n"
        "/approve MAC - Approve a user\n"
        "/deny MAC - Deny a user\n"
        "/list - Show approved users\n"
        "/banall - Remove all approvals"
    )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually approve a MAC address"""
    if not context.args:
        await update.message.reply_text("Usage: /approve MAC_ADDRESS")
        return
    
    mac = context.args[0]
    with open(APPROVED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"✅ Approved {mac}")

async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually deny a MAC address"""
    if not context.args:
        await update.message.reply_text("Usage: /deny MAC_ADDRESS")
        return
    
    mac = context.args[0]
    with open(BANNED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"❌ Denied {mac}")

async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all approved MACs"""
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
    """Remove all approvals"""
    open(APPROVED_FILE, "w").close()
    await update.message.reply_text("⚠️ All users banned (approved list cleared)")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses from your C++ app"""
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

# ---------- FLASK WEBHOOK ENDPOINT ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    """Receives updates from Telegram"""
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.process_update(update)
    return "OK", 200

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for Railway"""
    return "OK", 200

# ---------- MAIN ----------
def main():
    global application
    # Create bot application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("deny", deny_command))
    application.add_handler(CommandHandler("list", list_approved))
    application.add_handler(CommandHandler("banall", ban_all))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Set webhook (instead of polling)
    WEBHOOK_URL = f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN')}/webhook"
    application.bot.set_webhook(url=WEBHOOK_URL)
    
    # Flask will run the bot
    return application

# Initialize bot when module loads
application = main()

# Run Flask if executed directly
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
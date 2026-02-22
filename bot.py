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
WAITING_FOR_MAC_USERNAME, WAITING_FOR_CUSTOM_STATUS = range(2)

# Flask app
app = Flask(__name__)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- HELPER FUNCTIONS ----------
def write_to_files(mac: str, username: str, status: str):
    """
    Appends the MAC to KEYS.txt and the username/status to USERS.txt.
    Each entry is forced onto a new line to keep both files synced.
    """
    try:
        # 1. Handle KEYS.txt (Only the MAC/HWID)
        with open(KEYS_FILE, "a") as f:
            # strip() removes accidental whitespace, \n ensures a new line
            f.write(mac.strip() + "\n")
            
        # 2. Handle USERS.txt (The Username and their Status)
        with open(USERS_FILE, "a") as f:
            f.write(f"{username.strip()} -> {status}\n")
            
        logger.info(f"Sync Success: {mac} saved to KEYS, {username} saved to USERS.")
    except Exception as e:
        logger.error(f"File write error: {e}")
# ---------- CONVERSATION HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Please send me the MAC address and username.\n"
        "You can send them in one message separated by space or newline.\n"
        "Example: `AA:BB:CC:DD:EE:FF JohnDoe`\n"
        "Or send /cancel to abort."
    )
    return WAITING_FOR_MAC_USERNAME

async def receive_mac_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text.strip()
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("I need both! Format: [HWID] [Username]") 
            return WAITING_FOR_MAC_USERNAME

        mac = parts[0]
        username = " ".join(parts[1:]) 
    
        context.user_data["mac"] = mac
        context.user_data["username"] = username
        # Create inline keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data="approve"),
                InlineKeyboardButton("❌ Deny", callback_data="deny"),
            ],
            [
                InlineKeyboardButton("🚫 Ban", callback_data="ban"),
                InlineKeyboardButton("🔄 Other", callback_data="other"),
            ],
            [InlineKeyboardButton("❎ Cancel", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"MAC: {mac}\nUsername: {username}\n\nChoose an action:",
            reply_markup=reply_markup,
        )
        logger.info(f"Received MAC/Username from {update.effective_user.id}: {mac} / {username}")
        return WAITING_FOR_MAC_USERNAME  # stay to wait for button click

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data

    mac = context.user_data.get("mac")
    username = context.user_data.get("username")
    if not mac or not username:
        await query.edit_message_text("Error: missing data. Please start over with /start.")
        return ConversationHandler.END

    try:
        if action == "approve":
            write_to_files(mac, username, "SAFE")
            await query.edit_message_text(f"✅ Approved {username} with MAC {mac}")
        elif action == "deny":
            write_to_files(mac, username, "DELETE")
            await query.edit_message_text(f"❌ Denied {username} with MAC {mac}")
        elif action == "ban":
            write_to_files(mac, username, "BAN")
            await query.edit_message_text(f"🚫 Banned {username} with MAC {mac}")
        elif action == "other":
            await query.edit_message_text(
                "Please send the custom status you want to assign to this user.\n"
                "Example: `VIP` or `TRIAL`\n"
                "Send /cancel to abort."
            )
            return WAITING_FOR_CUSTOM_STATUS
        elif action == "cancel":
            await query.edit_message_text("Operation cancelled.")
        else:
            await query.edit_message_text("Unknown action.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in button_callback: {e}\n{traceback.format_exc()}")
        await query.edit_message_text("An error occurred. Please try again.")
        return ConversationHandler.END

async def receive_custom_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        custom_status = update.message.text.strip()
        mac = context.user_data.get("mac")
        username = context.user_data.get("username")
        if not mac or not username:
            await update.message.reply_text("Error: missing data. Please start over with /start.")
            return ConversationHandler.END

        write_to_files(mac, username, custom_status)
        await update.message.reply_text(f"✅ {username} with MAC {mac} set to '{custom_status}'")
        logger.info(f"Custom status for {username}: {custom_status}")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in receive_custom_status: {e}\n{traceback.format_exc()}")
        await update.message.reply_text("An error occurred. Please try again.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# ---------- NON‑CONVERSATION COMMANDS ----------
async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(USERS_FILE, "r") as f:
            users = f.read().strip()
        if users:
            await update.message.reply_text(f"📋 Registered users:\n{users}")
        else:
            await update.message.reply_text("No users registered yet.")
    except FileNotFoundError:
        await update.message.reply_text("No users registered yet.")
    except Exception as e:
        logger.error(f"Error in list_approved: {e}")
        await update.message.reply_text("Error reading users file.")

# ---------- BUILD APPLICATION ----------
application = Application.builder().token(BOT_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        WAITING_FOR_MAC_USERNAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_mac_username),
            CallbackQueryHandler(button_callback),  # for button presses
        ],
        WAITING_FOR_CUSTOM_STATUS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_status),
            CallbackQueryHandler(button_callback),  # in case user clicks again
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
application.add_handler(conv_handler)
application.add_handler(CommandHandler("list", list_approved))

# ---------- ASYNC LOOP IN BACKGROUND ----------
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def init_app():
    await application.initialize()
    # Set webhook using public domain from environment (e.g., Railway)
    public_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if public_domain:
        webhook_url = f"https://{public_domain}/webhook"
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    else:
        logger.warning("RAILWAY_PUBLIC_DOMAIN not set; webhook not configured.")

loop.create_task(init_app())

def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=run_loop, daemon=True).start()

# ---------- FLASK WEBHOOK ENDPOINT ----------
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            update = Update.de_json(request.get_json(force=True), application.bot)
            asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
            logger.info("Update processed")
        except Exception as e:
            logger.error(f"Webhook error: {e}")
        return "OK", 200
    return "Method Not Allowed", 405

@app.route('/health', methods=['GET'])
def health():
    return "OK", 200

@app.route('/')
def home():
    return "Bot is running", 200

@app.route('/KEYS.txt')
def get_keys():
    try:
        with open(KEYS_FILE, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}
    except FileNotFoundError:
        return "", 200, {'Content-Type': 'text/plain'}

@app.route('/USERS.txt')
def get_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/plain'}
    except FileNotFoundError:
        return "", 200, {'Content-Type': 'text/plain'}

# ---------- START FLASK ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
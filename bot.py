import logging
import os
import threading
import asyncio
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

KEYS_FILE = "KEYS.txt"      # stores MAC addresses (one per line)
USERS_FILE = "USERS.txt"    # stores "username -> status" (one per line)

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
    """Append MAC to KEYS.txt and username with status to USERS.txt."""
    with open(KEYS_FILE, "a") as f:
        f.write(mac.strip() + "\n")
    with open(USERS_FILE, "a") as f:
        f.write(f"{username.strip()} -> {status}\n")

# ---------- CONVERSATION HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation, ask for MAC and username."""
    await update.message.reply_text(
        "Please send me the MAC address and username.\n"
        "You can send them in one message separated by space or newline.\n"
        "Example: `AA:BB:CC:DD:EE:FF JohnDoe`\n"
        "Or send /cancel to abort."
    )
    return WAITING_FOR_MAC_USERNAME

async def receive_mac_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parse MAC and username, store them, and show action buttons."""
    text = update.message.text.strip()
    # Try to split by space or newline
    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text(
            "Please provide both MAC address and username.\n"
            "Example: `AA:BB:CC:DD:EE:FF JohnDoe`"
        )
        return WAITING_FOR_MAC_USERNAME

    mac, username = parts[0], parts[1]
    # Store in user_data for later use
    context.user_data["mac"] = mac
    context.user_data["username"] = username

    # Create inline keyboard with four actions
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
    # Stay in the same state? Actually we now wait for button click.
    # We'll handle button clicks with CallbackQueryHandler that doesn't change state automatically.
    # But we need to return a state that will be overridden by button handler.
    # Since button handler will end conversation or move to custom status, we can return None or a special state.
    # We'll just return WAITING_FOR_MAC_USERNAME and let button handler change state.
    return WAITING_FOR_MAC_USERNAME

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle button presses from the action menu."""
    query = update.callback_query
    await query.answer()
    action = query.data

    # Retrieve stored data
    mac = context.user_data.get("mac")
    username = context.user_data.get("username")
    if not mac or not username:
        await query.edit_message_text("Error: missing data. Please start over with /start.")
        return ConversationHandler.END

    if action == "approve":
        write_to_files(mac, username, "SAFE")
        await query.edit_message_text(f"✅ Approved {username} with MAC {mac}")
        return ConversationHandler.END
    elif action == "deny":
        write_to_files(mac, username, "DELETE")
        await query.edit_message_text(f"❌ Denied {username} with MAC {mac}")
        return ConversationHandler.END
    elif action == "ban":
        write_to_files(mac, username, "BAN")
        await query.edit_message_text(f"🚫 Banned {username} with MAC {mac}")
        return ConversationHandler.END
    elif action == "other":
        # Ask for custom status
        await query.edit_message_text(
            "Please send the custom status you want to assign to this user.\n"
            "Example: `VIP` or `TRIAL`\n"
            "Send /cancel to abort."
        )
        return WAITING_FOR_CUSTOM_STATUS
    elif action == "cancel":
        await query.edit_message_text("Operation cancelled.")
        return ConversationHandler.END
    else:
        await query.edit_message_text("Unknown action.")
        return ConversationHandler.END

async def receive_custom_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive custom status, write to files, and end conversation."""
    custom_status = update.message.text.strip()
    mac = context.user_data.get("mac")
    username = context.user_data.get("username")
    if not mac or not username:
        await update.message.reply_text("Error: missing data. Please start over with /start.")
        return ConversationHandler.END

    write_to_files(mac, username, custom_status)
    await update.message.reply_text(f"✅ {username} with MAC {mac} set to '{custom_status}'")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# ---------- NON‑CONVERSATION COMMANDS ----------
async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show contents of USERS.txt (approved users with status)."""
    try:
        with open(USERS_FILE, "r") as f:
            users = f.read().strip()
        if users:
            await update.message.reply_text(f"📋 Registered users:\n{users}")
        else:
            await update.message.reply_text("No users registered yet.")
    except FileNotFoundError:
        await update.message.reply_text("No users registered yet.")

# ---------- BUILD APPLICATION ----------
application = Application.builder().token(BOT_TOKEN).build()

# Conversation handler for the main flow
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        WAITING_FOR_MAC_USERNAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_mac_username),
            CallbackQueryHandler(button_callback),  # to handle buttons from that state
        ],
        WAITING_FOR_CUSTOM_STATUS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_status),
            CallbackQueryHandler(button_callback),  # in case user clicks a button again (should not happen)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
application.add_handler(conv_handler)

# Additional command to list all users (optional)
application.add_handler(CommandHandler("list", list_approved))

# ---------- ASYNC LOOP IN BACKGROUND ----------
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

async def init_app():
    await application.initialize()
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
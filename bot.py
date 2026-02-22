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
WAITING_FOR_MAC_USERNAME, WAITING_FOR_CUSTOM_STATUS, WAITING_FOR_BAN_TARGET, WAITING_FOR_ALLOW_TARGET = range(4)

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
    try:
        for filename, content in [(KEYS_FILE, mac.strip()), (USERS_FILE, f"{username.strip()} -> {status}")]:
            # Check if file exists and if it ends with a newline
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
        logger.info(f"Successfully synced: {username}")
    except Exception as e:
        logger.error(f"File write error: {e}")
# 3. The "Allow" Command (To re-enable a user)
async def allow_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please send the Username to set as SAFE:")
    return WAITING_FOR_ALLOW_TARGET        


async def process_allow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_user = update.message.text.strip()
    found = False
    new_lines = []

    if not os.path.exists(USERS_FILE):
        await update.message.reply_text("File not found.")
        return ConversationHandler.END

    with open(USERS_FILE, "r") as f:
        lines = f.readlines()

    for line in lines:
        if " -> " in line:
            name_part = line.split(" -> ")[0].strip()
            if name_part == target_user:
                new_lines.append(f"{name_part} -> SAFE\n")
                found = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if found:
        with open(USERS_FILE, "w") as f:
            f.writelines(new_lines)
        await update.message.reply_text(f"✅ User '{target_user}' is now SAFE.")
    else:
        await update.message.reply_text("User not found.")
    
    return ConversationHandler.END

async def ban_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please send the exact Username you want to ban:")
    return WAITING_FOR_BAN_TARGET

async def process_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_user = update.message.text.strip()
    found = False
    new_lines = []

    if not os.path.exists(USERS_FILE):
        await update.message.reply_text("User file doesn't exist yet.")
        return ConversationHandler.END

    with open(USERS_FILE, "r") as f:
        lines = f.readlines()

    for line in lines:
        if " -> " in line:
            name_part = line.split(" -> ")[0].strip()
            if name_part == target_user:
                new_lines.append(f"{name_part} -> BAN\n")
                found = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if found:
        with open(USERS_FILE, "w") as f:
            f.writelines(new_lines)
        await update.message.reply_text(f"🚫 User '{target_user}' has been set to BAN status.")
    else:
        await update.message.reply_text(f"❓ Could not find user '{target_user}'. Check the spelling and try again.")
    
    return ConversationHandler.END        
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
    entry_points=[
        CommandHandler("start", start),
        CommandHandler("ban", ban_start) # Entry for banning
        CommandHandler("allow", allow_start) # Added this for you
    ],
    states={
        WAITING_FOR_MAC_USERNAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_mac_username),
            CallbackQueryHandler(button_callback),
        ],
        WAITING_FOR_CUSTOM_STATUS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_status),
        ],
        WAITING_FOR_BAN_TARGET: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_ban),
        ],
        WAITING_FOR_ALLOW_TARGET: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_allow),
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
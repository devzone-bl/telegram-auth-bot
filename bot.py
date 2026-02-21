import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# -------------------- CONFIGURATION --------------------
BOT_TOKEN = "8384623189:AAH22WOwmsszqWfzct1Ieh4hZVXbMNK70jw"
ADMIN_CHAT_ID = "-5295119518"  # Your personal chat ID
APPROVED_FILE = "approved.txt"
BANNED_FILE = "banned.txt"
# -------------------------------------------------------

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a welcome message when the command /start is issued."""
    await update.message.reply_text("Auth Bot is running. Use /help for commands.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a help message."""
    await update.message.reply_text(
        "Commands:\n"
        "/start - Welcome\n"
        "/help - This help\n"
        "/list - List approved users\n"
        "/banall - Remove all approved users\n"
        "/add <MAC> - Manually approve a MAC\n"
        "/remove <MAC> - Remove a specific MAC"
    )

async def list_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the list of approved MACs."""
    try:
        with open(APPROVED_FILE, "r") as f:
            approved = f.read().strip()
        if approved:
            await update.message.reply_text(f"Approved MACs:\n{approved}")
        else:
            await update.message.reply_text("No approved users.")
    except FileNotFoundError:
        await update.message.reply_text("No approved users.")

async def ban_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete the approved file, effectively banning everyone."""
    open(APPROVED_FILE, "w").close()  # Clear file
    await update.message.reply_text("All users have been banned (approved list cleared).")

async def add_mac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually add a MAC to approved list."""
    if not context.args:
        await update.message.reply_text("Usage: /add <MAC>")
        return
    mac = context.args[0]
    with open(APPROVED_FILE, "a") as f:
        f.write(mac + "\n")
    await update.message.reply_text(f"MAC {mac} added to approved list.")

async def remove_mac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a MAC from approved list."""
    if not context.args:
        await update.message.reply_text("Usage: /remove <MAC>")
        return
    mac = context.args[0]
    try:
        with open(APPROVED_FILE, "r") as f:
            lines = f.readlines()
        with open(APPROVED_FILE, "w") as f:
            for line in lines:
                if line.strip() != mac:
                    f.write(line)
        await update.message.reply_text(f"MAC {mac} removed if it existed.")
    except FileNotFoundError:
        await update.message.reply_text("Approved list is empty.")

# This function will be called when your C++ app sends a request
async def send_approval_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """This is not a command; it's triggered by an external call.
       We'll use a separate method to actually send the request from the app."""
    pass  # We'll handle this in the C++ side by calling sendMessage directly

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press

    data = query.data  # format: "action|MAC"
    action, mac = data.split('|')
    username = context.user_data.get("username", "Unknown")  # you could store username when sending

    if action == "approve":
        # Add to approved list
        with open(APPROVED_FILE, "a") as f:
            f.write(mac + "\n")
        await query.edit_message_text(text=f"✅ Approved {mac}")
    elif action == "deny":
        # Optionally add to banned list
        with open(BANNED_FILE, "a") as f:
            f.write(mac + "\n")
        await query.edit_message_text(text=f"❌ Denied {mac}")
    elif action == "optionA":
        # Example: add to a special list
        with open("optionA.txt", "a") as f:
            f.write(mac + "\n")
        await query.edit_message_text(text=f"⚙️ Option A applied to {mac}")
    elif action == "optionB":
        with open("optionB.txt", "a") as f:
            f.write(mac + "\n")
        await query.edit_message_text(text=f"⚙️ Option B applied to {mac}")

def main():
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_approved))
    application.add_handler(CommandHandler("banall", ban_all))
    application.add_handler(CommandHandler("add", add_mac))
    application.add_handler(CommandHandler("remove", remove_mac))

    # Register callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(button_callback))

    # Run the bot
    application.run_polling()

if __name__ == "__main__":
    main()
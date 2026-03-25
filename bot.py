import logging
import os
import asyncio
import shutil
from datetime import datetime
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
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 8080))
DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN")

KEYS_FILE = "KEYS.txt"
USERS_FILE = "USERS.txt"
USERS_BACKUP_FILE = "USERS_BACKUP.txt"

# State Constants
(
    MENU_HUB,
    WAITING_FOR_REG,
    WAITING_FOR_GRANT,
    WAITING_FOR_BAN,
    WAITING_FOR_DELETE,
    WAITING_FOR_RENAME_OLD,
    WAITING_FOR_RENAME_NEW,
    WAITING_FOR_KILL,
    WAITING_FOR_MSG_USERS,
    WAITING_FOR_MSG_TEXT
) = range(10)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CORE UTILITIES ----------

def check_admin(update: Update):
    return update.effective_user.id == ADMIN_ID

def write_to_files(mac: str, username: str, status: str):
    try:
        for filename, content in [(KEYS_FILE, mac.strip()), (USERS_FILE, f"{username.strip()} -> {status}")]:
            with open(filename, "a") as f:
                f.write(content + "\n")
    except Exception as e:
        logger.error(f"File write error: {e}")

def get_db_content():
    if not os.path.exists(USERS_FILE): return "Database empty."
    with open(USERS_FILE, "r") as f:
        return f.read() or "Database empty."

def batch_update(targets_str: str, status_text: str):
    if not os.path.exists(USERS_FILE): return 0
    targets = [u.strip() for u in targets_str.split('-') if u.strip()]
    new_lines = []
    count = 0
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            name = line.split(" -> ")[0].strip()
            if name in targets:
                new_lines.append(f"{name} -> {status_text}\n")
                count += 1
                continue
        new_lines.append(line)
    with open(USERS_FILE, "w") as f:
        f.writelines(new_lines)
    return count

# ---------- UI KEYBOARDS ----------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("☠️ KILL", callback_data="m_kill")],
        [InlineKeyboardButton("💬 Send Message", callback_data="m_msg"), InlineKeyboardButton("✏️ Rename", callback_data="m_rename")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="m_del"), InlineKeyboardButton("📋 List", callback_data="m_list")],
        [InlineKeyboardButton("💀 BAN ALL", callback_data="m_ban_all"), InlineKeyboardButton("↩️ Undo Ban", callback_data="m_undo_ban")],
        [InlineKeyboardButton("📥 Get Backups", callback_data="m_backup"), InlineKeyboardButton("✖️ Close", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="m_stop")]])

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    
    text = "🛠 **System Control Hub**\nSelect administrative action:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "m_stop": return await start(update, context)
    if query.data == "m_cancel":
        await query.edit_message_text("💤 Session Closed.")
        return ConversationHandler.END

    if query.data == "m_reg":
        await query.edit_message_text("📝 **Registration**\nSend: `KEY USERNAME`", parse_mode="Markdown", reply_markup=back_btn())
        return WAITING_FOR_REG
    
    if query.data == "m_msg":
        await query.edit_message_text("💬 **Message Injector**\nStep 1: Send Username(s) (dash-separated):", parse_mode="Markdown", reply_markup=back_btn())
        return WAITING_FOR_MSG_USERS

    if query.data == "m_grant":
        await query.edit_message_text("✅ **Grant SAFE**\nSend Username(s):", reply_markup=back_btn()); return WAITING_FOR_GRANT
        
    if query.data == "m_ban":
        await query.edit_message_text("🚫 **Set BAN**\nSend Username(s):", reply_markup=back_btn()); return WAITING_FOR_BAN

    if query.data == "m_kill":
        await query.edit_message_text("☠️ **Set KILL**\nSend Username(s):", reply_markup=back_btn()); return WAITING_FOR_KILL

    if query.data == "m_del":
        await query.edit_message_text("🗑️ **Sync Delete**\nSend Username(s):", reply_markup=back_btn()); return WAITING_FOR_DELETE

    if query.data == "m_list":
        await query.edit_message_text(f"📋 **Database**\n```\n{get_db_content()}\n```", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return MENU_HUB

    if query.data == "m_ban_all":
        if os.path.exists(USERS_FILE):
            shutil.copyfile(USERS_FILE, USERS_BACKUP_FILE)
            count = batch_update("-".join([l.split(" -> ")[0] for l in open(USERS_FILE).readlines() if " -> " in l]), "BAN")
            await query.edit_message_text(f"💀 Banned {count} users.", reply_markup=main_menu_keyboard())
        return MENU_HUB

    if query.data == "m_backup":
        for f_path in [USERS_FILE, KEYS_FILE]:
            if os.path.exists(f_path):
                with open(f_path, 'rb') as doc:
                    await context.bot.send_document(chat_id=ADMIN_ID, document=doc)
        await query.message.reply_text("📥 Backups Sent.", reply_markup=main_menu_keyboard())
        return MENU_HUB

    return MENU_HUB

# ---------- SUB-HANDLERS ----------

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text("⚠️ Invalid Format. Use: `KEY USERNAME`", reply_markup=back_btn())
        return WAITING_FOR_REG
    write_to_files(parts[0], parts[1], "SAFE")
    await update.message.reply_text(f"✅ Registered `{parts[1]}`")
    return await start(update, context)

async def handle_msg_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["msg_targets"] = update.message.text
    await update.message.reply_text("💬 **Step 2:** Enter the message text for the popup:", reply_markup=back_btn())
    return WAITING_FOR_MSG_TEXT

async def handle_msg_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.replace('"', '""') # Escape quotes for VBScript
    cmd = f'SAFE mshta vbscript:Execute("msgbox ""{user_text}"":close")'
    count = batch_update(context.user_data.get("msg_targets", ""), cmd)
    await update.message.reply_text(f"⚡ Injected message to {count} users.")
    return await start(update, context)

async def handle_generic_batch(update: Update, context: ContextTypes.DEFAULT_TYPE, status: str):
    count = batch_update(update.message.text, status)
    await update.message.reply_text(f"✅ Processed {count} users.")
    return await start(update, context)

# ---------- MAIN RUNNER ----------

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU_HUB: [CallbackQueryHandler(menu_callback)],
            WAITING_FOR_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_GRANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_generic_batch(u, c, "SAFE")), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_generic_batch(u, c, "BAN")), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_KILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: handle_generic_batch(u, c, "KILL")), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_MSG_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg_users), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg_final), CallbackQueryHandler(menu_callback)],
        },
        fallbacks=[CommandHandler("start", start), CallbackQueryHandler(start, pattern="^m_stop$")],
        conversation_timeout=300
    )

    application.add_handler(conv_handler)

    # Railway Webhook Logic
    if DOMAIN:
        logger.info(f"Starting Webhook on port {PORT}...")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=f"https://{DOMAIN}/webhook",
            secret_token="RailwaySecret"
        )
    else:
        logger.info("No Domain found, starting Polling...")
        application.run_polling()

if __name__ == "__main__":
    main()
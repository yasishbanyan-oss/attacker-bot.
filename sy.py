import time
import logging
import random
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# تنظیمات لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- تنظیمات اولیه ---
BOT_TOKEN = "8791724770:AAE7iltb0hh9Wd2TwkK70s7UyKMFI1Jx_Qg"  # توکن ربات
OWNER_ID = 6749949992                                       # آیدی عددی مالک

# --- پایگاه داده در حافظه ---
bot_data = {
    "messages": [],           # لیست پیام‌های تنظیم‌شده
    "interval": 10,           # زمان پیش‌فرض ارسال پیام (ثانیه)
    "is_running": False,      # وضعیت ارسال خودکار
    "saved_users": set(),     # کاربران تنظیم‌شده (/set)
    "admins": {
        6749949992: {
            "type": "permanent",
            "permissions": ["admins", "messages", "commands"]
        }
    },
    "temp_admin_data": {}     # داده‌های موقت
}

# حالات FSM
WAITING_FOR_MSG, WAITING_FOR_CUSTOM_TIME, WAITING_FOR_ADMIN_ID, WAITING_FOR_ADMIN_TIME = range(4)

# --- بررسی دسترسی‌ها ---
def is_admin(user_id: int) -> bool:
    now = time.time()
    to_delete = []
    for uid, info in bot_data["admins"].items():
        if info["type"] == "hourly" and info.get("expires_at", 0) < now:
            to_delete.append(uid)
    for uid in to_delete:
        del bot_data["admins"][uid]

    return user_id in bot_data["admins"] or user_id == OWNER_ID

def has_permission(user_id: int, perm: str) -> bool:
    if user_id == OWNER_ID:
        return True
    if not is_admin(user_id):
        return False
    return perm in bot_data["admins"][user_id].get("permissions", [])

# --- کیبوردهای شیشه‌ای (Inline) ---
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("1️⃣ تنظیم پیام‌ها", callback_data="menu_set_msg")],
        [InlineKeyboardButton("2️⃣ تنظیم زمان ارسال", callback_data="menu_time")],
        [InlineKeyboardButton("3️⃣ مدیریت ادمین‌ها", callback_data="menu_admins")],
        [InlineKeyboardButton("4️⃣ راهنما", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_time_menu():
    keyboard = [
        [InlineKeyboardButton("2 ثانیه", callback_data="time_2"), InlineKeyboardButton("5 ثانیه", callback_data="time_5")],
        [InlineKeyboardButton("10 ثانیه", callback_data="time_10"), InlineKeyboardButton("30 ثانیه", callback_data="time_30")],
        [InlineKeyboardButton("⏱ دلخواه", callback_data="time_custom")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_menu():
    keyboard = [
        [InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add")],
        [InlineKeyboardButton("➖ حذف ادمین", callback_data="admin_del")],
        [InlineKeyboardButton("👑 مالک‌ها", callback_data="admin_owners")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_permissions_menu(user_id_target):
    perms = bot_data["temp_admin_data"].get("permissions", [])
    
    p1 = "✅" if "admins" in perms else "❌"
    p2 = "✅" if "messages" in perms else "❌"
    p3 = "✅" if "commands" in perms else "❌"

    keyboard = [
        [InlineKeyboardButton(f"{p1} دسترسی به ادمین‌ها", callback_data="perm_admins")],
        [InlineKeyboardButton(f"{p2} دسترسی به تنظیم پیام", callback_data="perm_messages")],
        [InlineKeyboardButton(f"{p3} دسترسی به دستورات ربات", callback_data="perm_commands")],
        [InlineKeyboardButton("💾 ثبت و نهایی‌سازی ادمین", callback_data="perm_save")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_admins")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- دستور /start ---
# --- دستور /start ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("به توپم دست نزن")
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 به پنل مدیریت ربات خوش آمدید.\nلطفاً یک بخش را انتخاب کنید:",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END

# --- مدیریت کلیک روی دکمه‌های شیشه‌ای ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_admin(user_id):
        await query.message.reply_text("به توپم دست نزن")
        return ConversationHandler.END

    data = query.data

    if data == "menu_main":
        await query.edit_message_text("👋 پنل اصلی مدیریت:", reply_markup=get_main_menu())
        return ConversationHandler.END

    elif data == "menu_set_msg":
        if not has_permission(user_id, "messages"):
            await query.edit_message_text("❌ شما دسترسی به این بخش را ندارید.", reply_markup=get_main_menu())
            return ConversationHandler.END
        
        await query.edit_message_text("📝 پیام‌های خود را ارسال کنید.\n\nهر پیامی بفرستید ذخیره می‌شود.\nدر پایان جهت ثبت نهایی دستور /done را ارسال کنید.")
        return WAITING_FOR_MSG

    elif data == "menu_time":
        await query.edit_message_text(f"⏱ تنظیم زمان ارسال پیام\nزمان فعلی: {bot_data['interval']} ثانیه\nیکی از گزینه‌ها را انتخاب کنید:", reply_markup=get_time_menu())
        return ConversationHandler.END

    elif data.startswith("time_"):
        if data == "time_custom":
            await query.edit_message_text("لطفاً زمان مدنظر خود را بر حسب ثانیه (فقط عدد) وارد کنید:")
            return WAITING_FOR_CUSTOM_TIME
        else:
            sec = int(data.split("_")[1])
            bot_data["interval"] = sec
            await query.edit_message_text(f"✅ زمان ارسال پیام روی {sec} ثانیه تنظیم شد.", reply_markup=get_main_menu())
            return ConversationHandler.END

    elif data == "menu_admins":
        if user_id != OWNER_ID and not has_permission(user_id, "admins"):
            await query.edit_message_text("❌ فقط مالک ربات یا ادمین‌های مجاز به این بخش دسترسی دارند.", reply_markup=get_main_menu())
            return ConversationHandler.END
        await query.edit_message_text("👥 بخش مدیریت ادمین‌ها:", reply_markup=get_admin_menu())
        return ConversationHandler.END

    elif data == "admin_add":
        await query.edit_message_text("لطفاً آیدی عددی ادمین جدید را وارد کنید:")
        return WAITING_FOR_ADMIN_ID

    elif data == "admin_del":
        await query.edit_message_text("برای حذف ادمین از دستور /del استفاده کنید یا آیدی عددی آن را بفرستید.")
        return ConversationHandler.END

    elif data == "admin_owners":
        await query.edit_message_text(f"👑 مالک ربات:\nآیدی عددی: {OWNER_ID}", parse_mode="Markdown", reply_markup=get_admin_menu())
        return ConversationHandler.END

    elif data.startswith("type_"):
        admin_type = data.split("_")[1]
        bot_data["temp_admin_data"]["type"] = admin_type
        if admin_type == "hourly":
            await query.edit_message_text("مدت زمان دسترسی ادمین را بر حسب ثانیه وارد کنید:")
            return WAITING_FOR_ADMIN_TIME
        else:
            await query.edit_message_text("⚙️ تعیین دسترسی‌های ادمین دائمی:", reply_markup=get_permissions_menu(bot_data["temp_admin_data"]["id"]))
            return ConversationHandler.END

    elif data.startswith("perm_"):
        p = data.split("_")[1]
        if p == "save":
            target_id = bot_data["temp_admin_data"]["id"]
            bot_data["admins"][target_id] = {
                "type": bot_data["temp_admin_data"]["type"],
                "permissions": bot_data["temp_admin_data"].get("permissions", []),
                "expires_at": bot_data["temp_admin_data"].get("expires_at", None)
                 }
            await query.edit_message_text("✅ ادمین با موفقیت ثبت شد.", reply_markup=get_admin_menu())
        else:
            perms = bot_data["temp_admin_data"].setdefault("permissions", [])
            if p in perms:
                perms.remove(p)
            else:
                perms.append(p)
            await query.edit_message_text("⚙️ تعیین دسترسی‌ها:", reply_markup=get_permissions_menu(bot_data["temp_admin_data"]["id"]))
        return ConversationHandler.END

    elif data == "menu_help":
        help_text = (
            "📖 راهنمای دستورات ربات:\n\n"
            "/set یا /set ID - افزودن کاربر به لیست\n"
            "/list - مشاهده کاربران تنظیم‌شده\n"
            "/del یا /del ID - حذف کاربر از لیست\n"
            "/delallsave - پاکسازی کامل لیست کاربران\n"
            "/go - شروع ارسال خودکار پیام‌ها\n"
            "/stop - توقف ارسال خودکار پیام‌ها\n"
            "/adminlist - لیست مدیران ربات\n"
            "/status - مشاهده وضعیت و آمار ربات\n"
        )
        await query.edit_message_text(help_text, parse_mode="Markdown", reply_markup=get_main_menu())
        return ConversationHandler.END

# --- دریافت پیام‌ها ---
async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data["messages"].append(update.message.text)
    await update.message.reply_text(f"✅ پیام ذخیره شد. (تعداد پیام‌های ثبت‌شده: {len(bot_data['messages'])})\nپیام بعدی را بفرستید یا جهت اتمام /done را ارسال کنید.")
    return WAITING_FOR_MSG

async def done_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = len(bot_data["messages"])
    await update.message.reply_text(f"✅ روند ثبت پیام تمام شد.\nتعداد کل پیام‌های ذخیره‌شده: {count}", reply_markup=get_main_menu())
    return ConversationHandler.END

# --- دریافت زمان دلخواه ---
async def receive_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.isdigit():
        sec = int(text)
        bot_data["interval"] = sec
        await update.message.reply_text(f"✅ زمان ارسال روی {sec} ثانیه تنظیم شد.", reply_markup=get_main_menu())
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ لطفاً فقط یک عدد معتبر به ثانیه وارد کنید:")
        return WAITING_FOR_CUSTOM_TIME

# --- ساخت ادمین ---
async def receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.isdigit():
        new_admin_id = int(text)
        bot_data["temp_admin_data"] = {"id": new_admin_id, "permissions": []}
        
        keyboard = [
            [InlineKeyboardButton("ساعتی (مؤقت)", callback_data="type_hourly")],
            [InlineKeyboardButton("دائمی", callback_data="type_permanent")]
        ]
        await update.message.reply_text("نوع ادمین را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ لطفاً آیدی عددی معتبر وارد کنید:")
        return WAITING_FOR_ADMIN_ID

async def receive_admin_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.isdigit():
        sec = int(text)
        bot_data["temp_admin_data"]["expires_at"] = time.time() + sec
        await update.message.reply_text("⚙️ تعیین دسترسی‌های ادمین ساعتی:", reply_markup=get_permissions_menu(bot_data["temp_admin_data"]["id"]))
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ لطفاً زمان را به ثانیه (عدد) وارد کنید:")
        return WAITING_FOR_ADMIN_TIME

# --- دستورات متنی /commands ---
async def set_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    target_id = None
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args:
        target_id = context.args[0]
    if target_id:
        bot_data["saved_users"].add(str(target_id))
        await update.message.reply_text(f"✅ کاربر {target_id} به لیست اضافه شد.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ لطفاً روی یک پیام ریپلی کنید یا آیدی عددی را جلوی دستور بنویسید.")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    users = list(bot_data["saved_users"])
    if not users:
        await update.message.reply_text("لیست سیو شده‌ها خالی است.")
    else:
        text = "📋 لیست کاربران تنظیم‌شده:\n" + "\n".join([f"• {u}" for u in users])
        await update.message.reply_text(text, parse_mode="Markdown")

async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    target_id = None
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
    elif context.args:
        target_id = str(context.args[0])

    if target_id and target_id in bot_data["saved_users"]:
        bot_data["saved_users"].remove(target_id)
        await update.message.reply_text(f"❌ کاربر {target_id} از لیست حذف شد.", parse_mode="Markdown")
    else:
        await update.message.reply_text("کاربر یافت نشد.")

async def delallsave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    bot_data["saved_users"].clear()
    await update.message.reply_text("🧹 تمامی کاربران سیو شده پاکسازی شدند.")

# --- تابع ارسال خودکار بدون نیاز به JobQueue ---
async def start_auto_sending(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    while bot_data["is_running"]:
        if bot_data["messages"]:
            random_msg = random.choice(bot_data["messages"])
            
            # تگ کردن کاربران
            if bot_data["saved_users"]:
                tags_list = [f"[\u200b](tg://user?id={u})[{u}](tg://user?id={u})" for u in bot_data["saved_users"]]
                tags_text = " ".join(tags_list)
                full_text = f"{random_msg}\n\n📢 {tags_text}"
            else:
                full_text = random_msg

            try:
                await context.bot.send_message(chat_id=chat_id, text=full_text, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=random_msg)

        # منتظر ماندن به میزان ثانیه تنظیم‌شده
        await asyncio.sleep(bot_data["interval"])

# --- تابع ارسال خودکار ---
async def start_auto_sending(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    while bot_data["is_running"]:
        if bot_data["messages"]:
            random_msg = random.choice(bot_data["messages"])
            
            # تگ کردن کاربران با متن "شخص سیو شده"
            if bot_data["saved_users"]:
                tags_list = [f"[شخص پدر مرده](tg://user?id={u})" for u in bot_data["saved_users"]]
                tags_text = " ".join(tags_list)
                full_text = f"{random_msg}\n\n{tags_text}"
            else:
                full_text = random_msg

            try:
                await context.bot.send_message(chat_id=chat_id, text=full_text, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=random_msg)

        # منتظر ماندن به میزان ثانیه تنظیم‌شده
        await asyncio.sleep(bot_data["interval"])


async def go_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    if not bot_data["messages"]:
        await update.message.reply_text("❌ هیچ پیامی تنظیم نشده است! اول پیام بسازید.")
        return

    if bot_data["is_running"]:
        await update.message.reply_text("⚠️ ارسال خودکار از قبل فعال است.")
        return

    bot_data["is_running"] = True
    chat_id = update.effective_chat.id

    # اجرای ارسال در پس‌زمینه
    asyncio.create_task(start_auto_sending(chat_id, context))

    await update.message.reply_text(f"🚀 ارسال خودکار پیام‌ها با فاصله {bot_data['interval']} ثانیه شروع شد.")
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    bot_data["is_running"] = False
    await update.message.reply_text("🛑 ارسال خودکار پیام‌ها متوقف شد.")

async def adminlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    text = "👑 لیست مدیران ربات:\n"
    for uid, info in bot_data["admins"].items():
        text += f"• آیدی عددی: {uid} ({info['type']})\n"
    await update.message.reply_text(text, parse_mode="Markdown")
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")
        return

    start_time = time.time()
    msg = await update.message.reply_text("در حال محاسبه پینگ...")
    ping = round((time.time() - start_time) * 1000, 2)

    status_text = (
        f"📊 وضعیت ربات:\n\n"
        f"⚡️ پینگ ربات: {ping}ms\n"
        f"👥 تعداد ادمین‌ها: {len(bot_data['admins'])}\n"
        f"🎯 تعداد افراد تنظیم‌شده: {len(bot_data['saved_users'])}\n"
        f"👑 مالک ربات: {OWNER_ID}\n"
        f"💬 تعداد پیام‌های تنظیم‌شده: {len(bot_data['messages'])}\n"
        f"⏱ فاصله ارسال: {bot_data['interval']} ثانیه\n"
    )
    await msg.edit_text(status_text, parse_mode="Markdown")

async def unauthorized_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("به توپم دست نزن")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_cmd),
            CallbackQueryHandler(handle_callback)
        ],
        states={
            WAITING_FOR_MSG: [
                CommandHandler("done", done_messages),
                MessageHandler(filters.TEXT & ~filters.COMMAND, collect_messages)
            ],
            WAITING_FOR_CUSTOM_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_time)],
            WAITING_FOR_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_id)],
            WAITING_FOR_ADMIN_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_time)],
        },
        fallbacks=[
            CommandHandler("start", start_cmd),
            CallbackQueryHandler(handle_callback)
        ],
        allow_reentry=True,
        per_message=False
    )

    app.add_handler(conv_handler)

    # سایر دستورات متنی
    app.add_handler(CommandHandler("set", set_user_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("del", del_cmd))
    app.add_handler(CommandHandler("delallsave", delallsave_cmd))
    app.add_handler(CommandHandler("go", go_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("adminlist", adminlist_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    app.add_handler(MessageHandler(filters.COMMAND, unauthorized_commands))

    print("ربات آنلاین شد...")
    app.run_polling()

if __name__ == "__main__":
    main()               
import time
import logging
import random
import asyncio
import json
import os
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- تنظیمات اولیه ---
BOT_TOKEN = "8791724770:AAFVk9FHklBaZ7o5pOE1-2LWNJKx7k68yQE"
OWNER_ID = 6749949992
DB_FILE = "database.json"

# --- دیتابیس پیش‌فرض ---
bot_data = {
    "messages": [],           # لیست پیام‌های متنی
    "medias": [],            # لیست مدیا (عکس، ویس، گیف، استیکر)
    "interval": 10,           # زمان ارسال (ثانیه)
    "is_running": False,      # وضعیت اتک
    "attack_mode": "random",  # حالت اتک: random | sequential | bomb
    "tag_text": "شخص پدر مرده", # متن تگ دلخواه
    "unauth_msg": "به توپم دست نزن", # متن پاسخ به غیر ادمین‌ها
    "saved_users": [],       # لیست کاربران سیو شده
    "admins": {
        str(OWNER_ID): {
            "type": "permanent",
            "permissions": ["admins", "messages", "commands"]
        }
    },
    "history": []             # تاریخچه اتفاقات ۲۴ ساعت اخیر
}

# حالات FSM
(
    WAITING_FOR_MSG, 
    WAITING_FOR_CUSTOM_TIME, 
    WAITING_FOR_ADMIN_ID, 
    WAITING_FOR_ADMIN_TIME,
    WAITING_FOR_TAG_TEXT,
    WAITING_FOR_UNAUTH_MSG,
    WAITING_FOR_MEDIA
) = range(7)

# --- مدیریت دیتابیس (سیو/لود/پاکسازی) ---
def save_db():
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(bot_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Error saving DB: {e}")

def load_db():
    global bot_data
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                bot_data.update(loaded)
        except Exception as e:
            logging.error(f"Error loading DB: {e}")

load_db()

# --- سیستم ثبت لاگ ۲۴ ساعته (/recent) ---
def log_event(event_text: str):
    now = time.time()
    bot_data["history"].append({"time": now, "event": event_text})
    bot_data["history"] = [h for h in bot_data["history"] if now - h["time"] <= 86400]
    save_db()

# --- بررسی دسترسی‌ها ---
def is_admin(user_id: int) -> bool:
    uid_str = str(user_id)
    now = time.time()
    to_delete = []
    
    for uid, info in bot_data["admins"].items():
        if info["type"] == "hourly" and info.get("expires_at", 0) < now:
            to_delete.append(uid)
            
    for uid in to_delete:
        del bot_data["admins"][uid]
        log_event(f"⏰ انقضای دسترسی ادمین ساعتی: {uid}")
    if to_delete:
        save_db()

    return uid_str in bot_data["admins"] or user_id == OWNER_ID

def has_permission(user_id: int, perm: str) -> bool:
    if user_id == OWNER_ID:
        return True
    if not is_admin(user_id):
        return False
    return perm in bot_data["admins"][str(user_id)].get("permissions", [])

# --- کیبوردهای شیشه‌ای ---
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("1️⃣ تنظیم پیام‌ها", callback_data="menu_set_msg"), InlineKeyboardButton("🖼 تنظیم مدیا", callback_data="menu_set_media")],
        [InlineKeyboardButton("2️⃣ تنظیم زمان ارسال", callback_data="menu_time"), InlineKeyboardButton("🏷 تغییر کلمه تگ", callback_data="menu_tag_text")],
        [InlineKeyboardButton("💬 تغییر متن غیرادمین", callback_data="menu_unauth_msg")],
        [InlineKeyboardButton("3️⃣ مدیریت ادمین‌ها", callback_data="menu_admins"), InlineKeyboardButton("4️⃣ راهنما", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_attack_mode_menu():
    keyboard = [
        [InlineKeyboardButton("🎲 تصادفی (Random)", callback_data="mode_random")],
        [InlineKeyboardButton("🔢 ترتیبی (Sequential)", callback_data="mode_sequential")],
        [InlineKeyboardButton("💣 خشاب تک‌پیامی (Single Bomb)", callback_data="mode_bomb")]
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
    perms = bot_data.get("temp_admin_data", {}).get("permissions", [])
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
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return ConversationHandler.END

    await update.message.reply_text(
        f"👋 به پنل مدیریت ربات اتکر خوش آمدید.\n🏷 متن تگ فعلی: [{bot_data['tag_text']}]\n💬 متن غیرادمین فعلی: [{bot_data.get('unauth_msg', 'به توپم دست نزن')}]\nلطفاً یک بخش را انتخاب کنید:",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END

# --- مدیریت کلیک روی دکمه‌ها ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_admin(user_id):
        await query.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return ConversationHandler.END

    data = query.data

    if data == "menu_main":
        await query.edit_message_text("👋 پنل اصلی مدیریت:", reply_markup=get_main_menu())
        return ConversationHandler.END

    elif data == "menu_set_msg":
        if not has_permission(user_id, "messages"):
            await query.edit_message_text("❌ شما دسترسی به این بخش را ندارید.", reply_markup=get_main_menu())
            return ConversationHandler.END
        await query.edit_message_text("📝 پیام‌های متنی خود را ارسال کنید.\nدر پایان دستور /done را ارسال کنید.")
        return WAITING_FOR_MSG

    elif data == "menu_set_media":
        if not has_permission(user_id, "messages"):
            await query.edit_message_text("❌ شما دسترسی به این بخش را ندارید.", reply_markup=get_main_menu())
            return ConversationHandler.END
        await query.edit_message_text("🖼 عکس، ویس، گیف یا استیکر مورد نظر خود را بفرستید.\nدر پایان دستور /done را ارسال کنید.")
        return WAITING_FOR_MEDIA

    elif data == "menu_tag_text":
        await query.edit_message_text(f"🏷 کلمه تگ فعلی: [{bot_data['tag_text']}]\n\nلطفاً کلمه جدید برای تگ کردن را بفرستید:")
        return WAITING_FOR_TAG_TEXT

    elif data == "menu_unauth_msg":
        await query.edit_message_text(f"💬 متن فعلی پاسخ به افراد غیرادمین: [{bot_data.get('unauth_msg', 'به توپم دست نزن')}]\n\nلطفاً متن یا جمله جدیدی که می‌خواهید به غیرادمین‌ها نشان داده شود را بفرستید:")
        return WAITING_FOR_UNAUTH_MSG

    elif data == "menu_time":
        await query.edit_message_text(f"⏱ تنظیم زمان ارسال پیام\nزمان فعلی: {bot_data['interval']} ثانیه\nیکی را انتخاب کنید:", reply_markup=get_time_menu())
        return ConversationHandler.END

    elif data.startswith("time_"):
        if data == "time_custom":
            await query.edit_message_text("لطفاً زمان مدنظر خود را بر حسب ثانیه (عدد) وارد کنید:")
            return WAITING_FOR_CUSTOM_TIME
        else:
            sec = int(data.split("_")[1])
            bot_data["interval"] = sec
            save_db()
            await query.edit_message_text(f"✅ زمان ارسال روی {sec} ثانیه تنظیم شد.", reply_markup=get_main_menu())
            return ConversationHandler.END

    elif data.startswith("mode_"):
        mode = data.split("_")[1]
        bot_data["attack_mode"] = mode
        bot_data["is_running"] = True
        save_db()
        
        chat_id = query.message.chat_id
        asyncio.create_task(start_auto_sending(chat_id, context))
        
        log_event(f"🚀 شروع اتک با حالت {mode} توسط کاربر {user_id}")
        await query.edit_message_text(f"🚀 اتک با حالت **{mode}** و فاصله {bot_data['interval']} ثانیه استارت خورد!")
        return ConversationHandler.END

    elif data == "menu_admins":
        if user_id != OWNER_ID and not has_permission(user_id, "admins"):
            await query.edit_message_text("❌ فقط مالک یا ادمین‌های مجاز دسترسی دارند.", reply_markup=get_main_menu())
            return ConversationHandler.END
        await query.edit_message_text("👥 بخش مدیریت ادمین‌ها:", reply_markup=get_admin_menu())
        return ConversationHandler.END

    elif data == "admin_add":
        await query.edit_message_text("لطفاً آیدی عددی ادمین جدید را وارد کنید:")
        return WAITING_FOR_ADMIN_ID

    elif data == "admin_del":
        await query.edit_message_text("برای حذف ادمین آیدی عددی اونو بفرستید.")
        return ConversationHandler.END

    elif data == "admin_owners":
        await query.edit_message_text(f"👑 مالک ربات:\nآیدی عددی: {OWNER_ID}", parse_mode="Markdown", reply_markup=get_admin_menu())
        return ConversationHandler.END

    elif data.startswith("type_"):
        admin_type = data.split("_")[1]
        bot_data.setdefault("temp_admin_data", {})["type"] = admin_type
        if admin_type == "hourly":
            await query.edit_message_text("مدت زمان دسترسی ادمین را به ثانیه وارد کنید:")
            return WAITING_FOR_ADMIN_TIME
        else:
            await query.edit_message_text("⚙️ تعیین دسترسی‌های ادمین دائمی:", reply_markup=get_permissions_menu(bot_data["temp_admin_data"]["id"]))
            return ConversationHandler.END

    elif data.startswith("perm_"):
        p = data.split("_")[1]
        if p == "save":
            target_id = str(bot_data["temp_admin_data"]["id"])
            bot_data["admins"][target_id] = {
                "type": bot_data["temp_admin_data"]["type"],
                "permissions": bot_data["temp_admin_data"].get("permissions", []),
                "expires_at": bot_data["temp_admin_data"].get("expires_at", None)
            }
            save_db()
            log_event(f"➕ ثبت ادمین جدید: {target_id} ({bot_data['temp_admin_data']['type']})")
            await query.edit_message_text("✅ ادمین با موفقیت ثبت شد.", reply_markup=get_admin_menu())
        else:
            perms = bot_data["temp_admin_data"].setdefault("permissions", [])
            if p in perms: perms.remove(p)
            else: perms.append(p)
            await query.edit_message_text("⚙️ تعیین دسترسی‌ها:", reply_markup=get_permissions_menu(bot_data["temp_admin_data"]["id"]))
        return ConversationHandler.END

    elif data == "menu_help":
        help_text = (
            "📖 راهنمای کامل دستورات:\n\n"
            "/set ID1 ID2 ID3 - افزودن دسته‌ای آیدی‌ها\n"
            "/list - مشاهده افراد سیو شده\n"
            "/listmsg - مشاهده پیام‌ها و مدیاهای ثبت‌شده\n"
            "/del ID - حذف یک فرد\n"
            "/delallsave - پاکسازی کامل افراد\n"
            "/deldata - پاکسازی دیتابیس پیام‌ها و مدیاها\n"
            "/go - شروع اتک با منوی انتخاب حالت\n"
            "/stop - توقف اتک\n"
            "/recent - گزارش اتفاقات ۲۴ ساعت اخیر\n"
            "/backup - دریافت فایل بکاپ دیتابیس\n"
            "/restore - ریستور بکاپ با آپلود فایل\n"
            "/status - وضعیت فنی ربات\n"
        )
        await query.edit_message_text(help_text, parse_mode="Markdown", reply_markup=get_main_menu())
        return ConversationHandler.END

# --- دریافت پیام‌های متنی ---
async def collect_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data["messages"].append(update.message.text)
    save_db()
    log_event(f"📝 افزودن پیام متنی جدید (تعداد کل: {len(bot_data['messages'])})")
    await update.message.reply_text(f"✅ پیام ذخیره شد. (تعداد پیام‌ها: {len(bot_data['messages'])})\nپیام بعدی را بفرستید یا /done را بزنید.")
    return WAITING_FOR_MSG

# --- دریافت مدیا ---
async def collect_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media_item = None
    
    if msg.photo:
        media_item = {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": msg.caption or ""}
    elif msg.voice:
        media_item = {"type": "voice", "file_id": msg.voice.file_id}
    elif msg.animation:
        media_item = {"type": "animation", "file_id": msg.animation.file_id, "caption": msg.caption or ""}
    elif msg.sticker:
        media_item = {"type": "sticker", "file_id": msg.sticker.file_id}

    if media_item:
        bot_data["medias"].append(media_item)
        save_db()
        log_event(f"🖼 افزودن مدیای جدید ({media_item['type']})")
        await update.message.reply_text(f"✅ مدیا ذخیره شد! (تعداد مدیاها: {len(bot_data['medias'])})\nمدیای بعدی را بفرستید یا /done را بزنید.")
    else:
        await update.message.reply_text("❌ فرمت نامعتبر! فقط عکس، ویس، گیف یا استیکر بفرستید.")
    return WAITING_FOR_MEDIA

async def done_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ ثبت با موفقیت تمام شد.", reply_markup=get_main_menu())
    return ConversationHandler.END

async def receive_tag_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_tag = update.message.text.strip()
    bot_data["tag_text"] = new_tag
    save_db()
    log_event(f"🏷 تغییر کلمه تگ به: [{new_tag}]")
    await update.message.reply_text(f"✅ کلمه تگ روی [{new_tag}] تنظیم شد.", reply_markup=get_main_menu())
    return ConversationHandler.END

async def receive_unauth_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_unauth = update.message.text.strip()
    bot_data["unauth_msg"] = new_unauth
    save_db()
    log_event(f"💬 تغییر متن پاسخ به غیرادمین به: [{new_unauth}]")
    await update.message.reply_text(f"✅ متن پاسخ به غیرادمین‌ها روی [{new_unauth}] تنظیم شد.", reply_markup=get_main_menu())
    return ConversationHandler.END

async def receive_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.isdigit():
        sec = int(text)
        bot_data["interval"] = sec
        save_db()
        await update.message.reply_text(f"✅ زمان ارسال روی {sec} ثانیه تنظیم شد.", reply_markup=get_main_menu())
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کنید:")
        return WAITING_FOR_CUSTOM_TIME

async def receive_admin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.isdigit():
        new_admin_id = int(text)
        bot_data["temp_admin_data"] = {"id": new_admin_id, "permissions": []}
        keyboard = [
            [InlineKeyboardButton("ساعتی (موقت)", callback_data="type_hourly")],
            [InlineKeyboardButton("دائمی", callback_data="type_permanent")]
        ]
        await update.message.reply_text("نوع ادمین را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ آیدی عددی معتبر وارد کنید:")
        return WAITING_FOR_ADMIN_ID

async def receive_admin_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.isdigit():
        sec = int(text)
        bot_data["temp_admin_data"]["expires_at"] = time.time() + sec
        await update.message.reply_text("⚙️ تعیین دسترسی‌های ادمین ساعتی:", reply_markup=get_permissions_menu(bot_data["temp_admin_data"]["id"]))
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ زمان را به ثانیه وارد کنید:")
        return WAITING_FOR_ADMIN_TIME

async def set_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    added = []
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
        if target_id not in bot_data["saved_users"]:
            bot_data["saved_users"].append(target_id)
            added.append(target_id)
    elif context.args:
        for arg in context.args:
            if arg.isdigit() and arg not in bot_data["saved_users"]:
                bot_data["saved_users"].append(arg)
                added.append(arg)

    if added:
        save_db()
        log_event(f"👥 افزودن همزمان کاربر(ها): {', '.join(added)}")
        await update.message.reply_text(f"✅ کاربر(های) زیر اضافه شدند:\n" + "\n".join(added))
    else:
        await update.message.reply_text("❌ آیدی جدیدی وارد نشده یا تکراری بود.\nمثال: `/set 1234 5678 91011`", parse_mode="Markdown")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    users = bot_data["saved_users"]
    if not users:
        await update.message.reply_text("لیست سیو شده‌ها خالی است.")
    else:
        text = "📋 لیست کاربران تنظیم‌شده:\n" + "\n".join([f"• `{u}`" for u in users])
        await update.message.reply_text(text, parse_mode="Markdown")

async def listmsg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    messages = bot_data.get("messages", [])
    medias = bot_data.get("medias", [])

    if not messages and not medias:
        await update.message.reply_text("❌ هیچ پیام یا مدیایی در خشاب ذخیره نشده است!")
        return

    text = "📝 **لیست پیام‌ها و مدیاهای ذخیره‌شده در خشاب:**\n\n"

    if messages:
        text += "💬 **پیام‌های متنی:**\n"
        for idx, msg in enumerate(messages, 1):
            text += f"{idx}. {msg}\n"
        text += "\n"

    if medias:
        text += "🖼 **مدیاهای ذخیره‌شده:**\n"
        media_names = {"photo": "عکس 📷", "voice": "ویس 🎙", "animation": "گیف 🎬", "sticker": "استیکر 🎭"}
        for idx, m in enumerate(medias, 1):
            m_type_fa = media_names.get(m["type"], m["type"])
            cap = f" (کپشن: {m['caption']})" if m.get("caption") else ""
            text += f"{idx}. {m_type_fa}{cap}\n"

    await update.message.reply_text(text)

async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    target_id = None
    if update.message.reply_to_message:
        target_id = str(update.message.reply_to_message.from_user.id)
    elif context.args:
        target_id = str(context.args[0])

    if target_id and target_id in bot_data["saved_users"]:
        bot_data["saved_users"].remove(target_id)
        save_db()
        log_event(f"➖ حذف کاربر از لیست: {target_id}")
        await update.message.reply_text(f"❌ کاربر {target_id} حذف شد.")
    else:
        await update.message.reply_text("کاربر یافت نشد.")

async def delallsave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    bot_data["saved_users"].clear()
    save_db()
    log_event("🧹 پاکسازی کامل لیست کاربران سیو شده")
    await update.message.reply_text("🧹 تمامی کاربران سیو شده پاکسازی شدند.")

async def deldata_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    bot_data["messages"].clear()
    bot_data["medias"].clear()
    save_db()
    log_event("🗑 پاکسازی کامل پیام‌ها و مدیاها توسط /deldata")
    await update.message.reply_text("🗑 تمامی پیام‌ها و مدیاهای ذخیره‌شده پاکسازی شدند!")

# --- موتور ارسال خودکار اتک ---
async def start_auto_sending(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    seq_index = 0
    tag_word = bot_data.get("tag_text", "شخص پدر مرده")

    while bot_data["is_running"]:
        messages = bot_data["messages"]
        medias = bot_data["medias"]
        mode = bot_data.get("attack_mode", "random")

        tags_text = ""
        if bot_data["saved_users"]:
            tags_list = [f"[{tag_word}](tg://user?id={u})" for u in bot_data["saved_users"]]
            tags_text = " ".join(tags_list)

        try:
            if mode == "bomb":
                if messages:
                    bomb_text = "\n\n".join(messages)
                    if tags_text:
                        bomb_text += f"\n\n{tags_text}"
                    await context.bot.send_message(chat_id=chat_id, text=bomb_text, parse_mode="Markdown")

            elif mode == "sequential":
                if messages:
                    current_msg = messages[seq_index % len(messages)]
                    if tags_text:
                        current_msg += f"\n\n{tags_text}"
                    await context.bot.send_message(chat_id=chat_id, text=current_msg, parse_mode="Markdown")
                    seq_index += 1

            else:
                use_media = medias and (random.choice([True, False]) or not messages)
                
                if use_media:
                    m = random.choice(medias)
                    m_type = m["type"]
                    f_id = m["file_id"]

                    if m_type == "photo":
                        cap = m.get("caption", "")
                        if tags_text:
                            cap = f"{cap}\n\n{tags_text}" if cap else tags_text
                        await context.bot.send_photo(chat_id=chat_id, photo=f_id, caption=cap, parse_mode="Markdown")

                    elif m_type == "animation":
                        cap = m.get("caption", "")
                        if tags_text:
                            cap = f"{cap}\n\n{tags_text}" if cap else tags_text
                        await context.bot.send_animation(chat_id=chat_id, animation=f_id, caption=cap, parse_mode="Markdown")

                    elif m_type == "voice":
                        await context.bot.send_voice(chat_id=chat_id, voice=f_id)
                        if tags_text:
                            await context.bot.send_message(chat_id=chat_id, text=tags_text, parse_mode="Markdown")

                    elif m_type == "sticker":
                        await context.bot.send_sticker(chat_id=chat_id, sticker=f_id)
                        if tags_text:
                            await context.bot.send_message(chat_id=chat_id, text=tags_text, parse_mode="Markdown")

                elif messages:
                    rand_msg = random.choice(messages)
                    if tags_text:
                        rand_msg += f"\n\n{tags_text}"
                    await context.bot.send_message(chat_id=chat_id, text=rand_msg, parse_mode="Markdown")

        except Exception as e:
            logging.error(f"Error in auto send: {e}")

        await asyncio.sleep(bot_data["interval"])

async def go_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    if not bot_data["messages"] and not bot_data["medias"]:
        await update.message.reply_text("❌ هیچ پیام یا مدیایی تنظیم نشده است!")
        return

    if bot_data["is_running"]:
        await update.message.reply_text("⚠️ ارسال خودکار از قبل فعال است.")
        return

    await update.message.reply_text("⚙️ لطفاً حالت ارسال پیام را انتخاب کنید:", reply_markup=get_attack_mode_menu())

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    bot_data["is_running"] = False
    save_db()
    log_event(f"🛑 توقف اتک توسط کاربر {update.effective_user.id}")
    await update.message.reply_text("🛑 ارسال خودکار پیام‌ها متوقف شد.")

async def recent_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    now = time.time()
    recent_logs = [h for h in bot_data["history"] if now - h["time"] <= 86400]

    if not recent_logs:
        await update.message.reply_text("📜 هیچ اتفاقی در ۲۴ ساعت اخیر ثبت نشده است.")
        return

    text = "📜 **گزارش اتفاقات ۲۴ ساعت اخیر:**\n\n"
    for log in reversed(recent_logs):
        time_str = time.strftime('%H:%M:%S', time.localtime(log['time']))
        text += f"⏱ [{time_str}] {log['event']}\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    save_db()
    log_event("📦 دریافت بکاپ از دیتابیس")
    await update.message.reply_document(
        document=open(DB_FILE, "rb"),
        filename="backup_database.json",
        caption="📦 فایل بکاپ دیتابیس ربات خدمت شما."
    )

async def restore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.document:
        doc = msg.reply_to_message.document
        file = await context.bot.get_file(doc.file_id)
        await file.download_to_drive(DB_FILE)
        load_db()
        log_event("🔄 بازیابی (Restore) کامل دیتابیس از فایل")
        await update.message.reply_text("✅ دیتابیس با موفقیت ریستور شد و اطلاعات لود گردید!")
    else:
        await update.message.reply_text("❌ لطفاً روی یک فایل بکاپ `.json` ریپلی کنید و دستور `/restore` را بزنید.", parse_mode="Markdown")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))
        return

    start_time = time.time()
    msg = await update.message.reply_text("در حال محاسبه پینگ...")
    ping = round((time.time() - start_time) * 1000, 2)

    status_text = (
        f"📊 **وضعیت ربات اتکر:**\n\n"
        f"⚡️ پینگ ربات: {ping}ms\n"
        f"👥 تعداد ادمین‌ها: {len(bot_data['admins'])}\n"
        f"🎯 افراد سیو شده: {len(bot_data['saved_users'])}\n"
        f"💬 پیام‌های متنی: {len(bot_data['messages'])}\n"
        f"🖼 تعداد مدیاها: {len(bot_data['medias'])}\n"
        f"🏷 کلمه تگ فعلی: [{bot_data['tag_text']}]\n"
        f"💬 متن غیرادمین: [{bot_data.get('unauth_msg', 'به توپم دست نزن')}]\n"
        f"⏱ فاصله ارسال: {bot_data['interval']} ثانیه\n"
        f"🚀 حالت فعلی: {bot_data.get('attack_mode', 'نامشخص')}\n"
    )
    await msg.edit_text(status_text, parse_mode="Markdown")

async def unauthorized_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(bot_data.get("unauth_msg", "به توپم دست نزن"))

# --- وب‌سرور داخلی جهت دور زدن تایم‌اوت Web Service در Render ---
async def handle_ping(request):
    return web.Response(text="Attacker Bot is Alive!")

async def main():
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
            WAITING_FOR_MEDIA: [
                CommandHandler("done", done_messages),
                MessageHandler((filters.PHOTO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL) & ~filters.COMMAND, collect_media)
            ],
            WAITING_FOR_TAG_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tag_text)],
            WAITING_FOR_UNAUTH_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_unauth_msg)],
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

    app.add_handler(CommandHandler("set", set_user_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("listmsg", listmsg_cmd))
    app.add_handler(CommandHandler("del", del_cmd))
    app.add_handler(CommandHandler("delallsave", delallsave_cmd))
    app.add_handler(CommandHandler("deldata", deldata_cmd))
    app.add_handler(CommandHandler("go", go_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("recent", recent_cmd))
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("restore", restore_cmd))
    app.add_handler(CommandHandler("status", status_cmd))

    app.add_handler(MessageHandler(filters.COMMAND, unauthorized_commands))

    # راه‌اندازی وب‌سرور aiohttp
    web_app = web.Application()
    web_app.router.add_get('/', handle_ping)
    runner = web.AppRunner(web_app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    print("ربات اتکر با وب‌سرور داخلی آنلاین شد...")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await asyncio.sleep(1)
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())

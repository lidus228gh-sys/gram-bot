import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from supabase import create_client, Client

# ========== ИНИЦИАЛИЗАЦИЯ SUPABASE ==========
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ========== КОНФИГ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

GIF_FILE = "gif_id.txt"
waiting_for_gif = False

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("👤 Профиль"), KeyboardButton("🔮 Хогвартс")],
        [KeyboardButton("📋 Команды"), KeyboardButton("🛒 Донат")],
        [KeyboardButton("🏆 Турниры")],
        [KeyboardButton("💬 Чаты"), KeyboardButton("🏰 Кланы")],
        [KeyboardButton("🎮 Игры"), KeyboardButton("🎁 Бонус")],
        [KeyboardButton("Политика"), KeyboardButton("Изменить язык")]
    ], resize_keyboard=True)

def get_user_data(user_id: int):
    uid = str(user_id)
    res = supabase.table("users_data").select("*").eq("user_id", uid).execute()
    if not res.data:
        new_user = {"user_id": uid, "balance": 0, "last_bonus": None}
        supabase.table("users_data").insert(new_user).execute()
        return new_user
    return res.data[0]

def get_user_balance(user_id: int) -> int:
    data = get_user_data(user_id)
    return data["balance"]

def set_user_balance(user_id: int, amount: int):
    uid = str(user_id)
    get_user_data(user_id)
    supabase.table("users_data").update({"balance": max(0, amount)}).eq("user_id", uid).execute()

def add_balance(user_id: int, amount: int):
    current = get_user_balance(user_id)
    set_user_balance(user_id, current + amount)

def can_take_bonus(user_id: int):
    if user_id in ADMIN_IDS:
        return True, None
    user_data = get_user_data(user_id)
    last_bonus_str = user_data.get("last_bonus")
    if not last_bonus_str:
        return True, None
    last_time = datetime.fromisoformat(last_bonus_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    if now >= last_time + timedelta(hours=24):
        return True, None
    remaining = int((last_time + timedelta(hours=24) - now).total_seconds())
    return False, remaining

def set_bonus_taken(user_id: int):
    if user_id not in ADMIN_IDS:
        uid = str(user_id)
        now_str = datetime.now(timezone.utc).isoformat()
        supabase.table("users_data").update({"last_bonus": now_str}).eq("user_id", uid).execute()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Добро пожаловать!\n\nGRAM — развлекательный бот для вашего чата", reply_markup=get_main_keyboard())

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📱 Меню:", reply_markup=get_main_keyboard())

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    balance = get_user_balance(update.effective_user.id)
    await update.message.reply_text(f"{update.effective_user.first_name}\n💰 Баланс: *{balance}* GRAM", parse_mode="Markdown")

async def bonus_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    can, remaining = can_take_bonus(user_id)
    if can:
        add_balance(user_id, 2500)
        set_bonus_taken(user_id)
        await update.message.reply_text(f"🎁 Вам начислено: 2500 GRAM\n💰 Новый баланс: {get_user_balance(user_id)}")
    else:
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        await update.message.reply_text(f"⏳ Осталось подождать {hours:02d}:{minutes:02d} до следующего бонуса")

async def placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Функция в разработке")

async def adm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Загрузить гифку", callback_data="upload_gif")],
        [InlineKeyboardButton("💰 Выдать GRAM", callback_data="give_gram")],
        [InlineKeyboardButton("💸 Забрать GRAM", callback_data="take_gram")]
    ])
    await update.message.reply_text("🔧 Админ-панель", reply_markup=keyboard)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        return
    global waiting_for_gif
    if query.data == "upload_gif":
        waiting_for_gif = True
        await query.message.reply_text("Отправьте гифку")
    elif query.data == "give_gram":
        await query.message.reply_text("Формат: /givegram 123456789 1000")
    elif query.data == "take_gram":
        await query.message.reply_text("Формат: /takegram 123456789 500")

async def give_gram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Формат: /givegram 123456789 1000")
        return
    try:
        user_id = int(args[0])
        amount = int(args[1])
        add_balance(user_id, amount)
        await update.message.reply_text(f"✅ Выдано {amount} GRAM")
    except:
        await update.message.reply_text("Ошибка: укажите ID и сумму")

async def take_gram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Формат: /takegram 123456789 500")
        return
    try:
        user_id = int(args[0])
        amount = int(args[1])
        current = get_user_balance(user_id)
        set_user_balance(user_id, max(0, current - amount))
        await update.message.reply_text(f"✅ Забрано {amount} GRAM")
    except:
        await update.message.reply_text("Ошибка")

async def save_gif(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global waiting_for_gif
    if waiting_for_gif and update.effective_user.id in ADMIN_IDS:
        if update.message.animation:
            file_id = update.message.animation.file_id
            with open(GIF_FILE, "w") as f:
                f.write(file_id)
            waiting_for_gif = False
            await update.message.reply_text("✅ Гифка сохранена!")

def main():
    PORT = int(os.environ.get("PORT", 8443))
    APP_URL = os.environ.get("APP_URL")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("adm", adm))
    app.add_handler(CommandHandler("givegram", give_gram))
    app.add_handler(CommandHandler("takegram", take_gram))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(б|B|в)$"), check_balance))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🎁 Бонус$"), bonus_button))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(👤 Профиль|🔮 Хогвартс|📋 Команды|🛒 Донат|🏆 Турниры|💬 Чаты|🏰 Кланы|🎮 Игры|Политика|Изменить язык)$"), placeholder))
    app.add_handler(MessageHandler(filters.ANIMATION, save_gif))
    app.add_handler(CallbackQueryHandler(admin_callback))
    print(f"✅ Бот запускается на Webhook...")
    app.run_webhook(listen="0.0.0.0", port=PORT, url_path=TOKEN, webhook_url=f"{APP_URL}/{TOKEN}")

if __name__ == "__main__":
    main()

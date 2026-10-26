import random
import logging
import json
import os
import time
import asyncio
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, PreCheckoutQuery
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, PreCheckoutQueryHandler
)

# ================== تنظیمات ==================
BOT_TOKEN = "8862201484:AAEkzV5B-7weZBTf_CneWfoQAKY2NC9zRRE"
DATA_FILE = "users_data.json"
ADMIN_IDS = [338266658]

# تنظیمات اقتصاد
START_COINS = 100
DAILY_BASE = 100
WORK_COOLDOWN = 1800
DUEL_TIMEOUT = 120
TRIVIA_TIMEOUT = 15

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== دیتابیس ==================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"users": {}, "duels": {}, "clans": {}, "tournament": {}}
    return {"users": {}, "duels": {}, "clans": {}, "tournament": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

db = load_data()
if "users" not in db:
    db = {"users": {}, "duels": {}, "clans": {}, "tournament": {}}

def get_user(user_id):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "name": "", "coins": START_COINS, "gems": 0,
            "level": 1, "xp": 0,
            "wins": 0, "losses": 0, "draws": 0, "games_played": 0,
            "total_earned": 0, "total_spent": 0,
            "daily_last": 0, "daily_streak": 0,
            "last_work": 0, "last_gamble": 0,
            "inventory": [], "active_boost": None, "boost_expire": 0,
            "vip_until": 0, "referrals": 0, "referred_by": None,
            "achievements": [], "current_game": None,
            "game_data": {}, "missions": {}, "missions_last": 0,
            "clan_id": None, "title": "🌱 تازه‌کار",
            "shield_until": 0, "lucky_charm": 0,
            "pvp_wins": 0, "duel_wins": 0, "trivia_wins": 0,
            "created_at": time.time()
        }
        save_data()
    return db["users"][uid]

def save_user(user_id, data):
    db["users"][str(user_id)] = data
    save_data()

# ================== سطح و XP ==================
def xp_for_level(level):
    return 100 + (level - 1) * 60

def get_title(level):
    titles = [
        (1, "🌱 تازه‌کار"), (5, "⚔️ ماجراجو"), (10, "🔥 جنگجو"),
        (20, "💎 قهرمان"), (30, "👑 استاد"), (50, "🌟 افسانه"),
        (75, "🏆 نابغه"), (100, "🌌 خدای بازی")
    ]
    t = "🌱 تازه‌کار"
    for lvl, name in titles:
        if level >= lvl:
            t = name
    return t

def add_xp(user_id, amount):
    user = get_user(user_id)
    user["xp"] += amount
    leveled_up = False
    reward = 0
    while user["xp"] >= xp_for_level(user["level"]):
        user["xp"] -= xp_for_level(user["level"])
        user["level"] += 1
        lvl_reward = 50 * user["level"]
        user["coins"] += lvl_reward
        user["total_earned"] += lvl_reward
        reward += lvl_reward
        leveled_up = True
    user["title"] = get_title(user["level"])
    save_user(user_id, user)
    return leveled_up, reward

# ================== بوست ==================
def get_coin_multiplier(user_id):
    user = get_user(user_id)
    m = 1.0
    now = time.time()
    if user.get("active_boost") and now < user.get("boost_expire", 0):
        if user["active_boost"] == "double_coins":
            m = 2.0
        elif user["active_boost"] == "triple_coins":
            m = 3.0
    if user.get("vip_until", 0) > now:
        m += 0.5
    if user.get("lucky_charm", 0) > now:
        m += 0.2
    return m

def add_coins(user_id, amount):
    user = get_user(user_id)
    final = int(amount * get_coin_multiplier(user_id))
    user["coins"] += final
    user["total_earned"] += final
    save_user(user_id, user)
    return final

def remove_coins(user_id, amount):
    user = get_user(user_id)
    if user["coins"] < amount:
        return False
    user["coins"] -= amount
    user["total_spent"] += amount
    save_user(user_id, user)
    return True

# ================== دستاوردها ==================
ACHIEVEMENTS = {
    "first_win": {"name": "🥇 اولین برد", "reward": 50, "desc": "اولین بازی رو ببر"},
    "ten_wins": {"name": "🏆 ده برد", "reward": 200, "desc": "۱۰ بازی ببر"},
    "fifty_wins": {"name": "👑 پنجاه برد", "reward": 1000, "desc": "۵۰ بازی ببر"},
    "hundred_wins": {"name": "🌟 صد برد", "reward": 3000, "desc": "۱۰۰ بازی ببر"},
    "rich": {"name": "💰 پولدار", "reward": 500, "desc": "به ۱۰۰۰ سکه برس"},
    "millionaire": {"name": "💎 میلیونر", "reward": 5000, "desc": "به ۱۰,۰۰۰ سکه برس"},
    "level_10": {"name": "⭐ سطح ۱۰", "reward": 300, "desc": "به سطح ۱۰ برس"},
    "level_25": {"name": "🔥 سطح ۲۵", "reward": 1000, "desc": "به سطح ۲۵ برس"},
    "level_50": {"name": "👑 سطح ۵۰", "reward": 3000, "desc": "به سطح ۵۰ برس"},
    "daily_7": {"name": "🔥 استریک ۷ روزه", "reward": 700, "desc": "۷ روز متوالی"},
    "daily_30": {"name": "💎 استریک ۳۰ روزه", "reward": 5000, "desc": "۳۰ روز متوالی"},
    "rps_master": {"name": "✊ استاد RPS", "reward": 400, "desc": "۲۰ بار RPS ببر"},
    "slots_jackpot": {"name": "🎰 جکپات", "reward": 1000, "desc": "در اسلات 777 بزن"},
    "duel_winner": {"name": "⚔️ دوئلیست", "reward": 500, "desc": "۵ بار در دوئل ببر"},
    "trivia_master": {"name": "🧠 نابغه", "reward": 800, "desc": "۱۰ بار تریویا ببر"},
    "clan_member": {"name": "🏰 عضو کلن", "reward": 200, "desc": "به یک کلن بپیوند"},
    "referrer": {"name": "📢 مبلغ", "reward": 300, "desc": "۳ نفر رو دعوت کن"},
}

def check_achievements(user_id):
    user = get_user(user_id)
    unlocked = []
    checks = {
        "first_win": user["wins"] >= 1,
        "ten_wins": user["wins"] >= 10,
        "fifty_wins": user["wins"] >= 50,
        "hundred_wins": user["wins"] >= 100,
        "rich": user["coins"] >= 1000,
        "millionaire": user["coins"] >= 10000,
        "level_10": user["level"] >= 10,
        "level_25": user["level"] >= 25,
        "level_50": user["level"] >= 50,
        "daily_7": user["daily_streak"] >= 7,
        "daily_30": user["daily_streak"] >= 30,
        "rps_master": user.get("rps_wins", 0) >= 20,
        "slots_jackpot": user.get("jackpots", 0) >= 1,
        "duel_winner": user.get("duel_wins", 0) >= 5,
        "trivia_master": user.get("trivia_wins", 0) >= 10,
        "clan_member": user.get("clan_id") is not None,
        "referrer": user["referrals"] >= 3,
    }
    for key, cond in checks.items():
        if cond and key not in user["achievements"]:
            user["achievements"].append(key)
            user["coins"] += ACHIEVEMENTS[key]["reward"]
            unlocked.append(key)
    if unlocked:
        save_user(user_id, user)
    return unlocked

# ================== ماموریت روزانه ==================
DAILY_MISSIONS = {
    "play_5": {"name": "۵ بازی انجام بده", "reward": 100, "target": 5},
    "win_3": {"name": "۳ بازی ببر", "reward": 150, "target": 3},
    "gamble_1": {"name": "۱ بار قمار کن", "reward": 80, "target": 1},
    "work_2": {"name": "۲ بار کار کن", "reward": 100, "target": 2},
    "rps_3": {"name": "۳ بار RPS بازی کن", "reward": 90, "target": 3},
}

def reset_missions(user_id):
    user = get_user(user_id)
    today = datetime.now().date().isoformat()
    if user.get("missions_last") != today:
        user["missions"] = {k: 0 for k in DAILY_MISSIONS}
        user["missions_last"] = today
        save_user(user_id, user)

def add_mission_progress(user_id, mission_key):
    user = get_user(user_id)
    reset_missions(user_id)
    user = get_user(user_id)
    if mission_key in user["missions"]:
        user["missions"][mission_key] = user["missions"].get(mission_key, 0) + 1
        save_user(user_id, user)

def check_missions(user_id):
    """چک کردن ماموریت‌های تکمیل‌شده"""
    user = get_user(user_id)
    reset_missions(user_id)
    user = get_user(user_id)
    completed = []
    for key, mission in DAILY_MISSIONS.items():
        progress = user["missions"].get(key, 0)
        if progress >= mission["target"]:
            claim_key = f"claimed_{key}"
            if claim_key not in user["missions"]:
                user["missions"][claim_key] = True
                user["coins"] += mission["reward"]
                completed.append((key, mission))
    if completed:
        save_user(user_id, user)
    return completed

# ================== کیبوردها ==================
def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 حدس عدد", callback_data="game_number"),
         InlineKeyboardButton("✊✋✌️ RPS", callback_data="game_rps")],
        [InlineKeyboardButton("🧠 ریاضی", callback_data="game_math"),
         InlineKeyboardButton("🎲 تاس", callback_data="game_dice")],
        [InlineKeyboardButton("🔤 حدس کلمه", callback_data="game_word"),
         InlineKeyboardButton("🎰 اسلات", callback_data="game_slots")],
        [InlineKeyboardButton("🎡 گردونه شانس", callback_data="wheel"),
         InlineKeyboardButton("🪙 شیر یا خط", callback_data="coinflip")],
        [InlineKeyboardButton("⚔️ دوئل PvP", callback_data="pvp_duel"),
         InlineKeyboardButton("🧠 تریویا", callback_data="trivia")],
        [InlineKeyboardButton("🏆 لیدربورد", callback_data="leaderboard"),
         InlineKeyboardButton("🛒 فروشگاه", callback_data="shop")],
        [InlineKeyboardButton("🎁 جایزه روزانه", callback_data="daily"),
         InlineKeyboardButton("💼 کار", callback_data="work")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile"),
         InlineKeyboardButton("🏅 دستاوردها", callback_data="achievements")],
        [InlineKeyboardButton("📋 ماموریت‌ها", callback_data="missions"),
         InlineKeyboardButton("🏰 کلن‌ها", callback_data="clans")],
        [InlineKeyboardButton("🎰 کازینو", callback_data="casino"),
         InlineKeyboardButton("📊 آمار جهانی", callback_data="global_stats")],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="main_menu")]])

# ================== فروشگاه ==================
SHOP_ITEMS = {
    "double_coins": {"name": "💰 بوست ۲x", "price": 300, "type": "boost",
                     "desc": "۳۰ دقیقه سکه ۲ برابر", "duration": 1800},
    "triple_coins": {"name": "💎 بوست ۳x", "price": 700, "type": "boost",
                     "desc": "۳۰ دقیقه سکه ۳ برابر", "duration": 1800},
    "vip": {"name": "👑 VIP (۲۴h)", "price": 500, "type": "vip",
            "desc": "+۵۰٪ سکه تا ۲۴h", "duration": 86400},
    "vip_week": {"name": "👑 VIP هفتگی", "price": 2500, "type": "vip",
                 "desc": "+۵۰٪ سکه تا ۷ روز", "duration": 604800},
    "shield": {"name": "🛡️ سپر (۱ ساعت)", "price": 200, "type": "shield",
               "desc": "از دوئل محافظت", "duration": 3600},
    "lucky_charm": {"name": "🍀 شانس (۱h)", "price": 400, "type": "charm",
                    "desc": "+۲۰٪ سکه ۱h", "duration": 3600},
}

def shop_keyboard():
    buttons = []
    for key, item in SHOP_ITEMS.items():
        buttons.append([InlineKeyboardButton(
            f"{item['name']} - {item['price']}💰",
            callback_data=f"buy_{key}"
        )])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

# ================== دستورات پایه ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = get_user(user.id)
    u["name"] = user.first_name
    save_user(user.id, u)
    
    if context.args and context.args[0].startswith("ref"):
        try:
            ref_id = int(context.args[0][3:])
            if ref_id != user.id and u["referred_by"] is None:
                u["referred_by"] = ref_id
                save_user(user.id, u)
                ref = get_user(ref_id)
                ref["referrals"] += 1
                ref["coins"] += 100
                save_user(ref_id, ref)
                try:
                    await context.bot.send_message(
                        ref_id,
                        f"🎉 {user.first_name} با لینک شما اومد! +۱۰۰ سکه"
                    )
                except: pass
        except: pass
    
    text = (
        f"🎮 سلام {user.first_name}!\n"
        f"{u['title']} | ⭐ سطح {u['level']}\n"
        f"💰 {u['coins']} سکه | 💎 {u['gems']} جم\n\n"
        "به ربات بازی خوش اومدی!\n"
        "از منو انتخاب کن:"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())
    else:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 راهنمای کامل\n\n"
        "🎯 بازی‌ها (۱۰+):\n"
        "• حدس عدد، RPS، ریاضی، تاس، اسلات، حدس کلمه\n"
        "• گردونه شانس، شیر یا خط، دوئل، تریویا\n\n"
        "💰 اقتصاد:\n"
        "/daily - جایزه روزانه\n"
        "/work - کار کن\n"
        "/profile - پروفایل\n"
        "/balance - موجودی\n"
        "/shop - فروشگاه\n"
        "/top - لیدربورد\n"
        "/ref - دعوت\n"
        "/achievements - دستاوردها\n"
        "/missions - ماموریت روزانه\n"
        "/clans - کلن‌ها\n\n"
        "⚔️ PvP:\n"
        "/duel - دوئل با کاربر\n"
        "/pay - انتقال پول\n"
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = get_user(update.effective_user.id)
    await update.message.reply_text(
        f"💰 سکه: {u['coins']}\n"
        f"💎 جم: {u['gems']}\n"
        f"⭐ سطح: {u['level']} ({u['xp']}/{xp_for_level(u['level'])} XP)\n"
        f"{u['title']}"
    )

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = get_user(query.from_user.id)
    await query.edit_message_text(
        f"🎮 منوی اصلی\n"
        f"💰 {u['coins']} | ⭐ {u['level']} | {u['title']}\n\n"
        "انتخاب کن:",
        reply_markup=main_menu_keyboard(),
    )

# ================== پروفایل ==================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        uid = query.from_user.id
    else:
        uid = update.effective_user.id
    
    u = get_user(uid)
    total = u["wins"] + u["losses"] + u["draws"]
    wr = (u["wins"] / total * 100) if total > 0 else 0
    
    boost = "❌"
    if u.get("active_boost") and time.time() < u.get("boost_expire", 0):
        rem = int((u["boost_expire"] - time.time()) / 60)
        boost = f"✅ {u['active_boost']} ({rem}m)"
    
    vip = "❌"
    if u.get("vip_until", 0) > time.time():
        hrs = int((u["vip_until"] - time.time()) / 3600)
        vip = f"✅ ({hrs}h)"
    
    clan = "❌"
    if u.get("clan_id"):
        c = db.get("clans", {}).get(u["clan_id"], {})
        clan = f"🏰 {c.get('name', 'نامشخص')}"
    
    text = (
        f"👤 پروفایل {u['name']}\n"
        f"{u['title']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 سکه: {u['coins']}\n"
        f"💎 جم: {u['gems']}\n"
        f"⭐ سطح: {u['level']} ({u['xp']}/{xp_for_level(u['level'])} XP)\n"
        f"🏰 کلن: {clan}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏆 برد: {u['wins']} | 💔 {u['losses']} | 🤝 {u['draws']}\n"
        f"🎯 نرخ برد: {wr:.1f}%\n"
        f"🎮 بازی‌ها: {u['games_played']}\n"
        f"⚔️ دوئل بردها: {u.get('duel_wins', 0)}\n"
        f"🧠 تریویا بردها: {u.get('trivia_wins', 0)}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔥 استریک: {u['daily_streak']} روز\n"
        f"💼 کل درآمد: {u['total_earned']}💰\n"
        f"💸 کل خرج: {u['total_spent']}💰\n"
        f"👥 دعوت: {u['referrals']}\n"
        f"🚀 بوست: {boost}\n"
        f"👑 VIP: {vip}\n"
        f"🏅 دستاورد: {len(u['achievements'])}/{len(ACHIEVEMENTS)}"
    )
    if query:
        await query.edit_message_text(text, reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# ================== جایزه روزانه ==================
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        uid = query.from_user.id
    else:
        uid = update.effective_user.id
    
    u = get_user(uid)
    now = time.time()
    
    if now - u["daily_last"] < 86400:
        rem = int(86400 - (now - u["daily_last"]))
        h, m = rem // 3600, (rem % 3600) // 60
        msg = f"⏰ بعدی: {h}h {m}m"
        if query:
            await query.edit_message_text(msg, reply_markup=back_keyboard())
        else:
            await update.message.reply_text(msg)
        return
    
    if 86400 <= now - u["daily_last"] < 172800:
        u["daily_streak"] += 1
    else:
        u["daily_streak"] = 1
    
    base = DAILY_BASE
    streak_bonus = min(u["daily_streak"] * 25, 500)
    reward = base + streak_bonus
    final = add_coins(uid, reward)
    u["daily_last"] = now
    save_user(uid, u)
    
    ach = check_achievements(uid)
    text = (
        f"🎁 جایزه روزانه!\n\n"
        f"💰 +{final} سکه\n"
        f"🔥 استریک: {u['daily_streak']} روز\n"
        f"🎯 بونوس: {streak_bonus}💰\n"
        f"🚀 ضریب: {get_coin_multiplier(uid)}x"
    )
    if ach:
        text += "\n\n🏅 " + "\n".join(f"{ACHIEVEMENTS[a]['name']}" for a in ach)
    
    if query:
        await query.edit_message_text(text, reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# ================== کار ==================
async def work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        uid = query.from_user.id
    else:
        uid = update.effective_user.id
    
    u = get_user(uid)
    now = time.time()
    
    if now - u.get("last_work", 0) < WORK_COOLDOWN:
        rem = int(WORK_COOLDOWN - (now - u["last_work"]))
        msg = f"⏰ {rem // 60} دقیقه دیگه"
        if query:
            await query.edit_message_text(msg, reply_markup=back_keyboard())
        else:
            await update.message.reply_text(msg)
        return
    
    jobs = [
        ("👨‍💻 برنامه‌نویسی", 50, 120), ("🚕 رانندگی", 30, 80),
        ("🍔 فست‌فود", 25, 60), ("📚 تدریس", 60, 150),
        ("🎨 نقاشی", 40, 100), ("💼 اداری", 45, 110),
        ("🏗️ ساخت‌وساز", 35, 90), ("🎵 موسیقی", 55, 130),
    ]
    job, mn, mx = random.choice(jobs)
    base = random.randint(mn, mx)
    final = add_coins(uid, base)
    u["last_work"] = now
    save_user(uid, u)
    add_mission_progress(uid, "work_2")
    
    text = f"💼 {job}\n\n💰 +{final} سکه\n⏰ ۳۰ دقیقه استراحت"
    if query:
        await query.edit_message_text(text, reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# ================== فروشگاه ==================
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = get_user(query.from_user.id)
    text = f"🛒 فروشگاه\n💰 سکه: {u['coins']}\n\n"
    for k, i in SHOP_ITEMS.items():
        text += f"• {i['name']}\n  {i['desc']}\n  {i['price']}💰\n\n"
    await query.edit_message_text(text, reply_markup=shop_keyboard())

async def buy_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    key = query.data.replace("buy_", "")
    
    if key not in SHOP_ITEMS:
        await query.edit_message_text("❌", reply_markup=back_keyboard())
        return
    
    item = SHOP_ITEMS[key]
    u = get_user(uid)
    
    if u["coins"] < item["price"]:
        await query.edit_message_text(
            f"❌ کمبود سکه!\nنیاز: {item['price']}💰\nموجودی: {u['coins']}💰",
            reply_markup=back_keyboard()
        )
        return
    
    remove_coins(uid, item["price"])
    u = get_user(uid)
    
    if item["type"] == "boost":
        u["active_boost"] = key
        u["boost_expire"] = time.time() + item["duration"]
    elif item["type"] == "vip":
        u["vip_until"] = time.time() + item["duration"]
    elif item["type"] == "shield":
        u["shield_until"] = time.time() + item["duration"]
    elif item["type"] == "charm":
        u["lucky_charm"] = time.time() + item["duration"]
    
    u["inventory"].append(key)
    save_user(uid, u)
    
    await query.edit_message_text(
        f"✅ خرید موفق!\n{item['name']}\n-{item['price']}💰\nموجودی: {u['coins']}💰",
        reply_markup=back_keyboard()
    )

# ================== لیدربورد ==================
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not db["users"]:
        await query.edit_message_text("خالی!", reply_markup=back_keyboard())
        return
    
    sorted_u = sorted(db["users"].items(), key=lambda x: x[1].get("coins", 0), reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 لیدربورد - Top 10\n━━━━━━━━━━━━━━━\n"
    for i, (uid, d) in enumerate(sorted_u):
        p = medals[i] if i < 3 else f"{i+1}."
        text += f"{p} {d.get('name', '?')} - {d.get('coins', 0)}💰 (Lv.{d.get('level', 1)})\n"
    
    await query.edit_message_text(text, reply_markup=back_keyboard())

# ================== آمار جهانی ==================
async def global_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    total_users = len(db["users"])
    total_coins = sum(u.get("coins", 0) for u in db["users"].values())
    total_games = sum(u.get("games_played", 0) for u in db["users"].values())
    total_clans = len(db.get("clans", {}))
    
    text = (
        f"📊 آمار جهانی ربات\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👥 کاربران: {total_users}\n"
        f"💰 کل سکه‌ها: {total_coins:,}\n"
        f"🎮 کل بازی‌ها: {total_games:,}\n"
        f"🏰 کلن‌ها: {total_clans}\n"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())

# ================== دستاوردها ==================
async def achievements_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        uid = query.from_user.id
    else:
        uid = update.effective_user.id
    
    u = get_user(uid)
    text = f"🏅 دستاوردها ({len(u['achievements'])}/{len(ACHIEVEMENTS)})\n━━━━━━━━━━━━━━━\n\n"
    for k, a in ACHIEVEMENTS.items():
        s = "✅" if k in u["achievements"] else "🔒"
        text += f"{s} {a['name']}\n   {a['desc']} (+{a['reward']}💰)\n\n"
    if query:
        await query.edit_message_text(text, reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# ================== ماموریت‌ها ==================
async def missions_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        uid = query.from_user.id
    else:
        uid = update.effective_user.id
    
    reset_missions(uid)
    u = get_user(uid)
    text = "📋 ماموریت‌های روزانه\n━━━━━━━━━━━━━━━\n\n"
    for k, m in DAILY_MISSIONS.items():
        prog = u["missions"].get(k, 0)
        done = "✅" if prog >= m["target"] else "⏳"
        text += f"{done} {m['name']}\n   {prog}/{m['target']} (+{m['reward']}💰)\n\n"
    
    if query:
        await query.edit_message_text(text, reply_markup=back_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())

# ================== رفرال ==================
async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    u = get_user(update.effective_user.id)
    link = f"https://t.me/{me.username}?start=ref{update.effective_user.id}"
    await update.message.reply_text(
        f"👥 دعوت دوستان\n\n"
        f"لینک شما:\n{link}\n\n"
        f"🎁 هر دعوت: +۱۰۰💰\n"
        f"👥 تعداد: {u['referrals']}"
    )

# ================== انتقال پول ==================
async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("روی پیام کاربر ریپلای کن:\n/pay 100")
        return
    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except:
        await update.message.reply_text("مقدار معتبر بفرست: /pay 100")
        return
    
    sender = update.effective_user.id
    receiver = update.message.reply_to_message.from_user.id
    
    if sender == receiver:
        await update.message.reply_text("❌ به خودت نمی‌تونی")
        return
    
    if not remove_coins(sender, amount):
        await update.message.reply_text("❌ سکه کافی نداری")
        return
    
    add_coins(receiver, amount)
    await update.message.reply_text(f"✅ {amount}💰 منتقل شد")

# ================== دوئل PvP ==================
async def pvp_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    u = get_user(uid)
    
    entry = 100
    if u["coins"] < entry:
        await query.edit_message_text(
            f"❌ حداقل {entry}💰 برای دوئل لازم است",
            reply_markup=back_keyboard()
        )
        return
    
    text = (
        "⚔️ دوئل PvP\n\n"
        "برای دوئل با یک کاربر:\n"
        "`/duel @username 100`\n"
        "یا روی پیام کاربر ریپلای کن و بزن:\n"
        "`/duel 100`\n\n"
        "💰 ورودی حداقل: 100 سکه\n"
        "🏆 برنده: کل مبلغ"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard())

async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    challenger = update.effective_user
    target = None
    amount = 100
    
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        if context.args:
            try: amount = int(context.args[0])
            except: pass
    elif context.args:
        try:
            amount = int(context.args[0])
            if len(context.args) > 1:
                uname = context.args[1].lstrip("@")
                for uid_str, d in db["users"].items():
                    if d.get("username") == uname:
                        target = type("X", (), {"id": int(uid_str), "first_name": d["name"]})()
                        break
        except:
            pass
    
    if not target:
        await update.message.reply_text(
            "روی پیام کاربر ریپلای کن:\n`/duel 100`",
            parse_mode="Markdown"
        )
        return
    
    if target.id == challenger.id:
        await update.message.reply_text("❌ به خودت؟!")
        return
    
    cu = get_user(challenger.id)
    if cu["coins"] < amount:
        await update.message.reply_text(f"❌ نیاز به {amount}💰")
        return
    
    duel_id = f"{challenger.id}_{target.id}_{int(time.time())}"
    db["duels"][duel_id] = {
        "challenger": challenger.id,
        "target": target.id,
        "amount": amount,
        "created": time.time(),
        "expires": time.time() + DUEL_TIMEOUT
    }
    save_data()
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ قبول", callback_data=f"duel_accept_{duel_id}")],
        [InlineKeyboardButton("❌ رد", callback_data=f"duel_reject_{duel_id}")],
    ])
    
    await update.message.reply_text(
        f"⚔️ دوئل!\n\n"
        f"از طرف: {challenger.first_name}\n"
        f"به: {target.first_name}\n"
        f"💰 مبلغ: {amount}\n"
        f"⏰ {DUEL_TIMEOUT} ثانیه",
        reply_markup=kb
    )

async def duel_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    duel_id = query.data.replace("duel_accept_", "")
    if duel_id not in db["duels"]:
        await query.edit_message_text("❌ منقضی شده")
        return
    
    d = db["duels"][duel_id]
    if time.time() > d["expires"]:
        del db["duels"][duel_id]
        save_data()
        await query.edit_message_text("⏰ منقضی شد")
        return
    
    tu = get_user(d["target"])
    if tu["coins"] < d["amount"]:
        await query.edit_message_text("❌ سکه کافی نداری!")
        return
    
    winner = random.choice([d["challenger"], d["target"]])
    loser = d["target"] if winner == d["challenger"] else d["challenger"]
    
    remove_coins(loser, d["amount"])
    add_coins(winner, d["amount"] * 2)
    
    wu = get_user(winner)
    wu["duel_wins"] = wu.get("duel_wins", 0) + 1
    wu["wins"] += 1
    save_user(winner, wu)
    
    lu = get_user(loser)
    lu["losses"] += 1
    save_user(loser, lu)
    
    del db["duels"][duel_id]
    save_data()
    
    check_achievements(winner)
    
    await query.edit_message_text(
        f"⚔️ دوئل تموم شد!\n\n"
        f"🏆 برنده: {wu['name']}\n"
        f"💰 جایزه: {d['amount'] * 2}"
    )

async def duel_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    duel_id = query.data.replace("duel_reject_", "")
    if duel_id in db["duels"]:
        del db["duels"][duel_id]
        save_data()
    await query.edit_message_text("❌ دوئل رد شد")

# ================== گردونه شانس ==================
WHEEL_PRIZES = [
    ("💎 ۱۰۰ سکه", 100, 20), ("💰 ۵۰ سکه", 50, 25),
    ("🎁 ۲۵۰ سکه", 250, 10), ("💵 ۲۰ سکه", 20, 20),
    ("😢 هیچی", 0, 15), ("👑 ۵۰۰ سکه", 500, 5),
    ("🎰 ۱۰۰۰ سکه!", 1000, 3), ("⭐ ۱۰۰ سکه", 100, 2),
]

async def wheel_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 50
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    prizes, weights = [], []
    for name, val, w in WHEEL_PRIZES:
        prizes.append((name, val))
        weights.append(w)
    
    name, reward = random.choices(prizes, weights=weights, k=1)[0]
    u = get_user(uid)
    u["games_played"] += 1
    
    if reward > 0:
        final = add_coins(uid, reward)
        u["wins"] += 1
        msg = f"🎉 {name}!\n+{final}💰"
    else:
        u["losses"] += 1
        msg = f"😢 {name}"
    
    save_user(uid, u)
    check_achievements(uid)
    add_mission_progress(uid, "play_5")
    add_mission_progress(uid, "gamble_1")
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎡 دوباره", callback_data="wheel")],
        [InlineKeyboardButton("🔙 منو", callback_data="main_menu")],
    ])
    await query.edit_message_text(
        f"🎡 گردونه شانس\n\n{msg}\n💰 موجودی: {get_user(uid)['coins']}",
        reply_markup=kb
    )

# ================== شیر یا خط ==================
async def coinflip_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 50
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    player = random.choice(["شیر", "خط"])
    guess = random.choice(["شیر", "خط"])
    u = get_user(uid)
    u["games_played"] += 1
    
    if player == guess:
        final = add_coins(uid, 100)
        u["wins"] += 1
        msg = f"🎉 بردی!\n{player}\n+{final}💰"
    else:
        u["losses"] += 1
        msg = f"😢 باختی!\n{player}"
    
    save_user(uid, u)
    check_achievements(uid)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 دوباره", callback_data="coinflip")],
        [InlineKeyboardButton("🔙 منو", callback_data="main_menu")],
    ])
    await query.edit_message_text(
        f"🪙 شیر یا خط\n\n{msg}\n💰 موجودی: {get_user(uid)['coins']}",
        reply_markup=kb
    )

# ================== تریویا ==================
TRIVIA_QUESTIONS = [
    ("پایتخت ایران؟", ["تهران", "شیراز", "مشهد", "تبریز"], 0),
    ("۲+۲×۲ = ?", ["۶", "۸", "۴", "۱۰"], 0),
    ("آب از چه چیزی ساخته شده؟", ["H2O", "CO2", "O2", "NaCl"], 0),
    ("بزرگ‌ترین سیاره؟", ["مشتری", "زحل", "زمین", "مریخ"], 0),
    ("سریع‌ترین حیوان؟", ["یوزپلنگ", "شیر", "اسب", "عقاب"], 0),
    ("تعداد قاره‌ها؟", ["۷", "۵", "۶", "۸"], 0),
    ("سال جهانی؟", ["۱۹۴۵", "۱۹۱۴", "۱۹۳۹", "۱۹۰۰"], 0),
    ("پایتخت فرانسه؟", ["پاریس", "لندن", "برلین", "روم"], 0),
]

async def trivia_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 30
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    q, opts, ans = random.choice(TRIVIA_QUESTIONS)
    # shuffle
    correct = opts[ans]
    random.shuffle(opts)
    new_ans = opts.index(correct)
    
    u = get_user(uid)
    u["current_game"] = "trivia"
    u["game_data"] = {"correct": new_ans}
    save_user(uid, u)
    
    kb = []
    for i, opt in enumerate(opts):
        kb.append([InlineKeyboardButton(opt, callback_data=f"trivia_ans_{i}")])
    
    await query.edit_message_text(
        f"🧠 سوال:\n\n{q}\n\n⏰ {TRIVIA_TIMEOUT} ثانیه\n💰 جایزه: 100",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def trivia_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    u = get_user(uid)
    
    if u.get("current_game") != "trivia":
        return
    
    ans = int(query.data.replace("trivia_ans_", ""))
    correct = u["game_data"].get("correct")
    
    u["current_game"] = None
    u["games_played"] += 1
    
    if ans == correct:
        final = add_coins(uid, 100)
        u["wins"] += 1
        u["trivia_wins"] = u.get("trivia_wins", 0) + 1
        msg = f"✅ درست!\n+{final}💰"
    else:
        u["losses"] += 1
        msg = "❌ اشتباه!"
    
    save_user(uid, u)
    check_achievements(uid)
    
    await query.edit_message_text(msg, reply_markup=back_keyboard())

# ================== کلن‌ها ==================
async def clans_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    u = get_user(query.from_user.id)
    
    if u.get("clan_id"):
        c = db["clans"].get(u["clan_id"], {})
        members = c.get("members", [])
        text = (
            f"🏰 کلن شما: {c.get('name', '?')}\n"
            f"👥 اعضا: {len(members)}\n"
            f"💰 خزانه: {c.get('treasury', 0)}\n\n"
        )
        kb = [
            [InlineKeyboardButton("📤 خروج از کلن", callback_data="clan_leave")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
        ]
    else:
        text = "🏰 کلن‌ها\n\nشما عضو هیچ کلنی نیستید."
        kb = [
            [InlineKeyboardButton("➕ ساخت کلن", callback_data="clan_create")],
            [InlineKeyboardButton("📋 لیست کلن‌ها", callback_data="clan_list")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")]
        ]
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def clan_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "➕ ساخت کلن\n\n"
        "دستور بزن:\n`/createclan نام کلن`\n\n"
        "💰 هزینه: 500 سکه",
        parse_mode="Markdown",
        reply_markup=back_keyboard()
    )

async def createclan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    
    if u.get("clan_id"):
        await update.message.reply_text("❌ قبلاً عضو کلنی هستی")
        return
    
    if not context.args:
        await update.message.reply_text("استفاده: /createclan نام")
        return
    
    if not remove_coins(uid, 500):
        await update.message.reply_text("❌ نیاز به 500💰")
        return
    
    clan_id = f"clan_{int(time.time())}_{uid}"
    name = " ".join(context.args)
    
    db["clans"][clan_id] = {
        "name": name, "owner": uid, "members": [uid],
        "treasury": 0, "created": time.time()
    }
    u = get_user(uid)
    u["clan_id"] = clan_id
    save_user(uid, u)
    save_data()
    
    await update.message.reply_text(f"✅ کلن {name} ساخته شد!")

async def clan_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if not db.get("clans"):
        await query.edit_message_text("هیچ کلنی نیست!", reply_markup=back_keyboard())
        return
    
    text = "🏰 لیست کلن‌ها\n━━━━━━━━━━━━━━━\n\n"
    for cid, c in list(db["clans"].items())[:10]:
        text += f"• {c['name']} ({len(c['members'])} عضو)\n"
    
    await query.edit_message_text(text, reply_markup=back_keyboard())

async def clan_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    u = get_user(uid)
    cid = u.get("clan_id")
    
    if cid and cid in db["clans"]:
        c = db["clans"][cid]
        if uid in c["members"]:
            c["members"].remove(uid)
        if not c["members"]:
            del db["clans"][cid]
        u["clan_id"] = None
        save_user(uid, u)
        save_data()
    
    await query.edit_message_text("✅ خارج شدی", reply_markup=back_keyboard())

# ================== بازی: حدس عدد ==================
async def start_number_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    u = get_user(uid)
    cost = 20
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    u = get_user(uid)
    u["current_game"] = "number"
    u["game_data"] = {
        "target": random.randint(1, 100),
        "tries": 0,
        "max_tries": 7
    }
    save_user(uid, u)
    
    await query.edit_message_text(
        f"🎯 حدس عدد\n"
        f"💰 ورودی: -{cost}\n\n"
        f"عددی بین 1 تا 100 حدس بزن!\n"
        f"۷ تلاش داری\n"
        f"🏆 جایزه: تا ۲۲۰ سکه",
        reply_markup=back_keyboard(),
    )

# ================== بازی: RPS ==================
async def start_rps_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = [
        [InlineKeyboardButton("✊ سنگ", callback_data="rps_rock"),
         InlineKeyboardButton("✋ کاغذ", callback_data="rps_paper"),
         InlineKeyboardButton("✌️ قیچی", callback_data="rps_scissors")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        "✊✋✌️ سنگ کاغذ قیچی\n\n"
        "💰 برد: +۵۰ | مساوی: +۱۰ | باخت: -۱۰\n\n"
        "انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def handle_rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    uc = query.data.replace("rps_", "")
    u = get_user(uid)
    
    if u["coins"] < 10:
        await query.edit_message_text("❌ حداقل 10💰", reply_markup=back_keyboard())
        return
    
    emojis = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
    bc = random.choice(list(emojis.keys()))
    
    u["games_played"] += 1
    add_mission_progress(uid, "play_5")
    add_mission_progress(uid, "rps_3")
    
    if uc == bc:
        final = add_coins(uid, 10)
        u["draws"] += 1
        result = f"🤝 مساوی (+{final}💰)"
    elif ((uc == "rock" and bc == "scissors") or
          (uc == "paper" and bc == "rock") or
          (uc == "scissors" and bc == "paper")):
        final = add_coins(uid, 50)
        u["wins"] += 1
        u["rps_wins"] = u.get("rps_wins", 0) + 1
        result = f"🎉 بردی! (+{final}💰)"
        add_mission_progress(uid, "win_3")
    else:
        remove_coins(uid, 10)
        u["losses"] += 1
        result = "😢 باختی (-10💰)"
    
    save_user(uid, u)
    check_achievements(uid)
    check_missions(uid)
    add_xp(uid, 8)
    
    kb = [
        [InlineKeyboardButton("🔄 دوباره", callback_data="game_rps")],
        [InlineKeyboardButton("🔙 منو", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        f"تو: {emojis[uc]}\nربات: {emojis[bc]}\n\n"
        f"{result}\n"
        f"💰 {get_user(uid)['coins']}",
        reply_markup=InlineKeyboardMarkup(kb),
    )

# ================== بازی: اسلات ==================
async def start_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 50
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    syms = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
    res = [random.choice(syms) for _ in range(3)]
    
    u = get_user(uid)
    u["games_played"] += 1
    reward = 0
    extra = ""
    
    if res[0] == res[1] == res[2]:
        if res[0] == "7️⃣":
            reward = 1000; extra = "🎉🎉 JACKPOT!!"
            u["jackpots"] = u.get("jackpots", 0) + 1
        elif res[0] == "💎":
            reward = 500; extra = "💎 DIAMOND!"
        elif res[0] == "⭐":
            reward = 300; extra = "⭐ STARS!"
        else:
            reward = 150; extra = "🎊 سه‌تایی!"
    elif res[0] == res[1] or res[1] == res[2] or res[0] == res[2]:
        reward = 75; extra = "👍 دوتایی"
    else:
        extra = "😢"
    
    if reward:
        final = add_coins(uid, reward)
        u["wins"] += 1
        extra += f"\n+{final}💰"
        add_mission_progress(uid, "win_3")
    else:
        u["losses"] += 1
    
    save_user(uid, u)
    check_achievements(uid)
    check_missions(uid)
    add_mission_progress(uid, "play_5")
    add_mission_progress(uid, "gamble_1")
    add_xp(uid, 15)
    
    kb = [
        [InlineKeyboardButton("🎰 دوباره", callback_data="game_slots")],
        [InlineKeyboardButton("🔙 منو", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        f"🎰 اسلات\n\n┃ {res[0]} ┃ {res[1]} ┃ {res[2]} ┃\n\n"
        f"{extra}\n💰 {get_user(uid)['coins']}",
        reply_markup=InlineKeyboardMarkup(kb),
    )

# ================== بازی: تاس ==================
async def start_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 30
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    p = random.randint(1, 6)
    b = random.randint(1, 6)
    dice = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
    u = get_user(uid)
    u["games_played"] += 1
    
    if p > b:
        final = add_coins(uid, 70)
        u["wins"] += 1
        result = f"🎉 بردی! +{final}💰"
        add_mission_progress(uid, "win_3")
    elif p < b:
        u["losses"] += 1
        result = "😢 باختی!"
    else:
        final = add_coins(uid, 30)
        u["draws"] += 1
        result = f"🤝 مساوی +{final}💰"
    
    save_user(uid, u)
    check_achievements(uid)
    check_missions(uid)
    add_mission_progress(uid, "play_5")
    add_mission_progress(uid, "gamble_1")
    add_xp(uid, 10)
    
    kb = [
        [InlineKeyboardButton("🎲 دوباره", callback_data="game_dice")],
        [InlineKeyboardButton("🔙 منو", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        f"🎲 تاس\n\nتو: {dice[p]}({p})\nربات: {dice[b]}({b})\n\n"
        f"{result}\n💰 {get_user(uid)['coins']}",
        reply_markup=InlineKeyboardMarkup(kb),
    )

# ================== بازی: حدس کلمه ==================
WORDS = ["سیب", "کتاب", "مدرسه", "آسمان", "دریا", "خورشید", "ماه", "ستاره",
         "گل", "درخت", "پنجره", "دوستان", "خانواده", "شهر", "روستا", "کامپیوتر",
         "موبایل", "تلگرام", "اینترنت", "برنامه"]

async def start_word_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 40
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    word = random.choice(WORDS)
    sc = list(word)
    while True:
        random.shuffle(sc)
        if "".join(sc) != word:
            break
    
    u = get_user(uid)
    u["current_game"] = "word"
    u["game_data"] = {"answer": word, "tries": 0}
    save_user(uid, u)
    
    await query.edit_message_text(
        f"🔤 حدس کلمه\n"
        f"💰 ورودی: -{cost}\n\n"
        f"کلمه درهم: {' '.join(sc)}\n\n"
        f"🏆 جایزه: ۱۵۰💰\n"
        f"⏰ ۲ تلاش\n\n"
        "کلمه رو بفرست:",
        reply_markup=back_keyboard(),
    )

# ================== بازی: ریاضی ==================
async def start_math_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 15
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    a = random.randint(1, 50)
    b = random.randint(1, 50)
    op = random.choice(["+", "-", "×"])
    ans = a + b if op == "+" else (a - b if op == "-" else a * b)
    
    u = get_user(uid)
    u["current_game"] = "math"
    u["game_data"] = {"answer": ans}
    save_user(uid, u)
    
    await query.edit_message_text(
        f"🧠 ریاضی\n💰 ورودی: -{cost}\n\n"
        f"{a} {op} {b} = ?\n\n"
        f"🏆 جایزه: ۵۰💰",
        reply_markup=back_keyboard(),
    )

# ================== کازینو ==================
async def casino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    kb = [
        [InlineKeyboardButton("🎰 اسلات", callback_data="game_slots"),
         InlineKeyboardButton("🎲 تاس", callback_data="game_dice")],
        [InlineKeyboardButton("🎡 گردونه", callback_data="wheel"),
         InlineKeyboardButton("🪙 شیر یا خط", callback_data="coinflip")],
        [InlineKeyboardButton("💣 مین", callback_data="mines")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        "🎰 کازینو\n\nبازی انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def mines_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    cost = 50
    
    if not remove_coins(uid, cost):
        await query.edit_message_text(f"❌ نیاز به {cost}💰", reply_markup=back_keyboard())
        return
    
    # 3x3 grid with 2 mines
    grid = list(range(9))
    mines = random.sample(grid, 2)
    
    kb = []
    for row in range(3):
        r = []
        for col in range(3):
            idx = row * 3 + col
            r.append(InlineKeyboardButton("❓", callback_data=f"mines_{idx}"))
        kb.append(r)
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    
    u = get_user(uid)
    u["current_game"] = "mines"
    u["game_data"] = {"mines": mines, "revealed": [], "opened": 0}
    save_user(uid, u)
    
    await query.edit_message_text(
        f"💣 بازی مین\n"
        f"💰 ورودی: -{cost}\n\n"
        f"۲ مین در ۹ خانه!\n"
        f"چند خانه امن باز کن و جایزه بگیر.\n"
        f"هر خانه: +30💰 | اگر مین بزنی: -همه",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def mines_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    u = get_user(uid)
    
    if u.get("current_game") != "mines":
        return
    
    idx = int(query.data.replace("mines_", ""))
    gd = u["game_data"]
    
    if idx in gd["revealed"]:
        return
    
    kb = []
    for row in range(3):
        r = []
        for col in range(3):
            i = row * 3 + col
            if i in gd["revealed"]:
                r.append(InlineKeyboardButton("💎" if i not in gd["mines"] else "💣", callback_data=f"mines_{i}"))
            else:
                r.append(InlineKeyboardButton("❓", callback_data=f"mines_{i}"))
        kb.append(r)
    kb.append([InlineKeyboardButton("💰 برداشت", callback_data="mines_cashout")])
    kb.append([InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")])
    
    if idx in gd["mines"]:
        # باخت
        u["current_game"] = None
        u["losses"] += 1
        u["games_played"] += 1
        save_user(uid, u)
        
        # نمایش همه مین‌ها
        kb = []
        for row in range(3):
            r = []
            for col in range(3):
                i = row * 3 + col
                if i in gd["mines"]:
                    r.append(InlineKeyboardButton("💣", callback_data="none"))
                else:
                    r.append(InlineKeyboardButton("💎", callback_data="none"))
            kb.append(r)
        kb.append([InlineKeyboardButton("🔙 منو", callback_data="main_menu")])
        
        await query.edit_message_text(
            f"💥 بوم! مین زدی!\n\n💰 موجودی: {u['coins']}",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    
    gd["revealed"].append(idx)
    gd["opened"] += 1
    u["game_data"] = gd
    save_user(uid, u)
    
    await query.edit_message_text(
        f"💎 امن! ({gd['opened']} خانه)\n"
        f"💰 برداشت: {gd['opened'] * 30}",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def mines_cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    uid = query.from_user.id
    u = get_user(uid)
    
    if u.get("current_game") != "mines":
        return
    
    gd = u["game_data"]
    reward = gd["opened"] * 30
    u["current_game"] = None
    u["wins"] += 1
    u["games_played"] += 1
    save_user(uid, u)
    
    if reward > 0:
        final = add_coins(uid, reward)
        msg = f"💰 +{final} سکه!"
    else:
        msg = "❌ هیچی برداشت نکردی"
    
    await query.edit_message_text(
        f"{msg}\n💰 موجودی: {get_user(uid)['coins']}",
        reply_markup=back_keyboard()
    )

# ================== هندلر پیام ==================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    game = u.get("current_game")
    gd = u.get("game_data", {})
    
    if game == "number":
        try:
            guess = int(update.message.text)
        except:
            await update.message.reply_text("⚠️ عدد بفرست!")
            return
        if not 1 <= guess <= 100:
            await update.message.reply_text("⚠️ 1-100")
            return
        
        gd["tries"] += 1
        target = gd["target"]
        tries_left = gd["max_tries"] - gd["tries"]
        
        if guess == target:
            reward = 100 + max(0, (gd["max_tries"] - gd["tries"]) * 20)
            final = add_coins(uid, reward)
            u = get_user(uid)
            u["wins"] += 1
            u["games_played"] += 1
            u["current_game"] = None
            save_user(uid, u)
            check_achievements(uid)
            check_missions(uid)
            add_mission_progress(uid, "play_5")
            add_mission_progress(uid, "win_3")
            lvl, rw = add_xp(uid, 25)
            
            msg = f"🎉 بردی!\nعدد: {target}\n💰 +{final}"
            if lvl:
                msg += f"\n⭐ لول‌آپ! +{rw}💰"
            await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
        elif gd["tries"] >= gd["max_tries"]:
            u["losses"] += 1
            u["games_played"] += 1
            u["current_game"] = None
            save_user(uid, u)
            add_mission_progress(uid, "play_5")
            await update.message.reply_text(
                f"😢 باختی!\nعدد: {target}",
                reply_markup=main_menu_keyboard()
            )
        else:
            hint = "🔺 بزرگتره" if guess < target else "🔻 کوچیکتره"
            save_user(uid, u)
            await update.message.reply_text(f"{hint}\nباقی: {tries_left}")
    
    elif game == "math":
        try:
            ans = int(update.message.text)
        except:
            await update.message.reply_text("⚠️ عدد بفرست!")
            return
        
        u["current_game"] = None
        u["games_played"] += 1
        add_mission_progress(uid, "play_5")
        
        if ans == gd["answer"]:
            final = add_coins(uid, 50)
            u["wins"] += 1
            msg = f"✅ درست! +{final}💰"
            add_mission_progress(uid, "win_3")
            lvl, _ = add_xp(uid, 10)
            if lvl:
                msg += "\n⭐ لول‌آپ!"
        else:
            u["losses"] += 1
            msg = f"❌ اشتباه! جواب: {gd['answer']}"
        
        save_user(uid, u)
        check_achievements(uid)
        check_missions(uid)
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    
    elif game == "word":
        ans = update.message.text.strip()
        gd["tries"] += 1
        
        if ans == gd["answer"]:
            final = add_coins(uid, 150)
            u["wins"] += 1
            u["games_played"] += 1
            u["current_game"] = None
            save_user(uid, u)
            check_achievements(uid)
            check_missions(uid)
            add_mission_progress(uid, "play_5")
            add_mission_progress(uid, "win_3")
            add_xp(uid, 20)
            await update.message.reply_text(
                f"🎉 آفرین! {gd['answer']}\n💰 +{final}",
                reply_markup=main_menu_keyboard()
            )
        elif gd["tries"] >= 2:
            u["losses"] += 1
            u["games_played"] += 1
            u["current_game"] = None
            save_user(uid, u)
            add_mission_progress(uid, "play_5")
            await update.message.reply_text(
                f"😢 باختی! جواب: {gd['answer']}",
                reply_markup=main_menu_keyboard()
            )
        else:
            save_user(uid, u)
            await update.message.reply_text("❌ یه تلاش دیگه")
    else:
        await update.message.reply_text(
            "از منو انتخاب کن:",
            reply_markup=main_menu_keyboard()
        )

# ================== ادمین ==================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    await update.message.reply_text(
        "👑 پنل ادمین\n\n"
        "/give [id] [amount] - سکه دادن\n"
        "/broadcast [msg] - پیام همگانی\n"
        "/stats - آمار کلی\n"
        "/addadmin [id] - افزودن ادمین"
    )

async def admin_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        tid = int(context.args[0])
        amt = int(context.args[1])
        u = get_user(tid)
        u["coins"] += amt
        save_user(tid, u)
        await update.message.reply_text(f"✅ {amt}💰 به {tid}")
    except:
        await update.message.reply_text("استفاده: /give ID AMOUNT")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("پیام بده: /broadcast متن")
        return
    msg = " ".join(context.args)
    count = 0
    for uid in list(db["users"].keys()):
        try:
            await context.bot.send_message(int(uid), f"📢 {msg}")
            count += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ ارسال به {count} کاربر")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    total = len(db["users"])
    coins = sum(u.get("coins", 0) for u in db["users"].values())
    games = sum(u.get("games_played", 0) for u in db["users"].values())
    await update.message.reply_text(
        f"📊 آمار کلی\n\n"
        f"👥 کاربران: {total}\n"
        f"💰 کل سکه: {coins:,}\n"
        f"🎮 کل بازی: {games:,}\n"
        f"🏰 کلن‌ها: {len(db.get('clans', {}))}"
    )

# ================== main ==================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("work", work))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("top", leaderboard))
    app.add_handler(CommandHandler("ref", referral))
    app.add_handler(CommandHandler("achievements", achievements_view))
    app.add_handler(CommandHandler("missions", missions_view))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("duel", duel_command))
    app.add_handler(CommandHandler("createclan", createclan_command))
    
    # Admin
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("give", admin_give))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("stats", admin_stats))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(daily, pattern="^daily$"))
    app.add_handler(CallbackQueryHandler(work, pattern="^work$"))
    app.add_handler(CallbackQueryHandler(shop, pattern="^shop$"))
    app.add_handler(CallbackQueryHandler(buy_item, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(leaderboard, pattern="^leaderboard$"))
    app.add_handler(CallbackQueryHandler(achievements_view, pattern="^achievements$"))
    app.add_handler(CallbackQueryHandler(missions_view, pattern="^missions$"))
    app.add_handler(CallbackQueryHandler(global_stats, pattern="^global_stats$"))
    app.add_handler(CallbackQueryHandler(casino, pattern="^casino$"))
    
    # Games
    app.add_handler(CallbackQueryHandler(start_number_game, pattern="^game_number$"))
    app.add_handler(CallbackQueryHandler(start_rps_game, pattern="^game_rps$"))
    app.add_handler(CallbackQueryHandler(handle_rps, pattern="^rps_"))
    app.add_handler(CallbackQueryHandler(start_math_game, pattern="^game_math$"))
    app.add_handler(CallbackQueryHandler(start_dice, pattern="^game_dice$"))
    app.add_handler(CallbackQueryHandler(start_slots, pattern="^game_slots$"))
    app.add_handler(CallbackQueryHandler(start_word_game, pattern="^game_word$"))
    app.add_handler(CallbackQueryHandler(wheel_game, pattern="^wheel$"))
    app.add_handler(CallbackQueryHandler(coinflip_game, pattern="^coinflip$"))
    app.add_handler(CallbackQueryHandler(trivia_game, pattern="^trivia$"))
    app.add_handler(CallbackQueryHandler(trivia_answer, pattern="^trivia_ans_"))
    app.add_handler(CallbackQueryHandler(mines_game, pattern="^mines$"))
    app.add_handler(CallbackQueryHandler(mines_click, pattern="^mines_\\d+$"))
    app.add_handler(CallbackQueryHandler(mines_cashout, pattern="^mines_cashout$"))
    
    # PvP
    app.add_handler(CallbackQueryHandler(pvp_duel, pattern="^pvp_duel$"))
    app.add_handler(CallbackQueryHandler(duel_accept, pattern="^duel_accept_"))
    app.add_handler(CallbackQueryHandler(duel_reject, pattern="^duel_reject_"))
    
    # Clans
    app.add_handler(CallbackQueryHandler(clans_view, pattern="^clans$"))
    app.add_handler(CallbackQueryHandler(clan_create, pattern="^clan_create$"))
    app.add_handler(CallbackQueryHandler(clan_list, pattern="^clan_list$"))
    app.add_handler(CallbackQueryHandler(clan_leave, pattern="^clan_leave$"))
    
    # Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"🤖 ربات در حال اجراست...")
    print(f"👑 ادمین‌ها: {ADMIN_IDS}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
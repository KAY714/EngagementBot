import os
import requests
import asyncio
import sqlite3
from datetime import datetime, timedelta
from collections import Counter
from flask import Flask, request
from threading import Thread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# This is the secret password Meta will use to verify your webhook
WEBHOOK_VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "my_secure_token_123")

API_VER = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VER}"

# --- DATABASE SETUP ---
db = sqlite3.connect("bot_users.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, meta_token TEXT, page_id TEXT)")
# NEW: Table to store live Instagram Story tags
db.execute("CREATE TABLE IF NOT EXISTS ig_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, ig_account_id TEXT, sender_id TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
db.commit()

# --- WEBHOOK & SERVER (FLASK) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is awake!"

# NEW: Meta Webhook Verification Route
@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    
    if mode and token:
        if mode == 'subscribe' and token == WEBHOOK_VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Forbidden", 403
    return "OK", 200

# NEW: Meta Webhook Event Receiver (Saves Tags to Database)
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    data = request.json
    if data and data.get("object") == "instagram":
        for entry in data.get("entry", []):
            ig_account_id = entry.get("id")
            
            # Instagram sends tags/mentions as messaging events
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event.get("sender", {}).get("id")
                
                # If someone tagged this IG account, save their ID to the database!
                if sender_id and ig_account_id:
                    db.execute("INSERT INTO ig_tags (ig_account_id, sender_id) VALUES (?, ?)", (ig_account_id, sender_id))
                    db.commit()
                    
    return "EVENT_RECEIVED", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- API FETCH FUNCTIONS ---
def fetch_fb_top_user(meta_token, page_id, since=None, until=None):
    interactions = []
    user_names = {} 
    
    url = f"{BASE_URL}/{page_id}/posts?limit=100&access_token={meta_token}"
    if since: url += f"&since={since}"
    if until: url += f"&until={until}"
        
    res = requests.get(url).json()
    if 'error' in res: return f"❌ خطأ في فيسبوك API: {res['error'].get('message')}"
        
    posts = res.get('data', [])
    if not posts: return "❌ لم يتم العثور على أي منشورات في هذه الفترة الزمنية."
    
    for post in posts:
        post_id = post['id']
        comments_res = requests.get(f"{BASE_URL}/{post_id}/comments?limit=100&access_token={meta_token}").json()
        for c in comments_res.get('data', []):
            if 'from' in c:
                user_id = str(c['from'].get('id'))
                name = c['from'].get('name', 'مستخدم غير معروف')
                if user_id != str(page_id): 
                    interactions.append(user_id)
                    user_names[user_id] = name
        
        reactions_res = requests.get(f"{BASE_URL}/{post_id}/reactions?limit=100&access_token={meta_token}").json()
        for r in reactions_res.get('data', []):
            user_id = str(r.get('id'))
            name = r.get('name', 'مستخدم غير معروف')
            if user_id != str(page_id): 
                interactions.append(user_id)
                user_names[user_id] = name

    if not interactions: return "لم يتم العثور على أي تفاعل حديث على فيسبوك."
    
    top_user_id, count = Counter(interactions).most_common(1)[0]
    top_name = user_names.get(top_user_id, "مستخدم غير معروف")
    
    return f"🏆 أكثر متفاعل على فيسبوك: <b>{top_name}</b> ({count} تفاعلات)"

def fetch_ig_top_user(meta_token, page_id, since=None, until=None):
    ig_res = requests.get(f"{BASE_URL}/{page_id}?fields=instagram_business_account{{id,username}}&access_token={meta_token}").json()
    if 'error' in ig_res: return f"❌ خطأ في API: {ig_res['error'].get('message')}"
    if 'instagram_business_account' not in ig_res: return "❌ خطأ: لا يوجد حساب إنستغرام أعمال مرتبط بصفحة الفيسبوك هذه."
    
    ig_account = ig_res['instagram_business_account']
    ig_id = ig_account['id']
    ig_username = ig_account.get('username', '')
    
    interactions = []
    
    url = f"{BASE_URL}/{ig_id}/media?limit=100&access_token={meta_token}"
    if since: url += f"&since={since}"
    if until: url += f"&until={until}"
        
    media = requests.get(url).json().get('data', [])
    if not media: return "❌ لم يتم العثور على أي منشورات إنستغرام في هذه الفترة الزمنية."
    
    for m in media:
        media_id = m['id']
        comments = requests.get(f"{BASE_URL}/{media_id}/comments?fields=username&limit=100&access_token={meta_token}").json().get('data', [])
        for c in comments:
            uname = c.get('username')
            if uname and uname != ig_username: interactions.append(uname)
            
    if not interactions: return "لم يتم العثور على أي تعليقات حديثة على إنستغرام."
    
    top_username, count = Counter(interactions).most_common(1)[0]
    profile_url = f"https://www.instagram.com/{top_username}/"
    return f"🏆 أكثر متفاعل على إنستغرام: <a href='{profile_url}'>@{top_username}</a> ({count} تعليقات)"

def parse_dates(args):
    since, until = None, None
    if args == "week":
        since = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    elif args and len(args.split()) == 2:
        parts = args.split()
        since = parts[0]
        until = parts[1]
    return since, until

# --- TELEGRAM COMMANDS & MENUS ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 هاتف", callback_data="show_usage"),
            InlineKeyboardButton(text="💻 حاسوب", callback_data="show_usage")
        ]
    ])
    await message.reply("👋 <b>مرحباً بك في بوت المتفاعلين!</b>\n\nلتقديم أفضل تجربة لك، ما هو الجهاز الذي تستخدمه حالياً؟", reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query(F.data == "show_usage")
async def show_usage_menu(callback: types.CallbackQuery):
    usage_text = (
        "✅ <b>ممتاز! إليك طريقة استخدام البوت:</b>\n\n"
        "⚙️ <b>1. أوامر الإعداد (مطلوبة أولاً):</b>\n"
        "• <code>/settoken YOUR_META_TOKEN</code> : لربط رمز التوكن الخاص بك.\n"
        "• <code>/setpage YOUR_PAGE_ID</code> : لربط معرف صفحة فيسبوك الخاصة بك.\n\n"
        "📊 <b>2. أوامر التحليلات:</b>\n"
        "• <code>/topfb</code> : لاستخراج أكثر متفاعل على فيسبوك.\n"
        "• <code>/topig</code> : لاستخراج أكثر معلق على إنستغرام.\n"
        "• <code>/toptagger</code> : لمعرفة أكثر شخص أشار إليك (منذ تشغيل البوت).\n\n"
        "📅 <b>3. عوامل تصفية التواريخ المتقدمة (اختياري):</b>\n"
        "• <code>/topfb week</code> : الأنشط في الأيام الـ 7 الماضية.\n"
        "• <code>/topig 2026-09-03 2026-09-08</code> : الأنشط بين تواريخ محددة."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 شرح كيفية الحصول على Token و Page ID", callback_data="show_tutorial")]
    ])
    
    await callback.message.edit_text(usage_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "show_tutorial")
async def show_tutorial_menu(callback: types.CallbackQuery):
    tutorial_text = (
        "<b>📖 شرح كيفية الحصول على Token و Page ID:</b>\n\n"
        "1️⃣ اذهب إلى موقع <a href='https://developers.facebook.com/tools/explorer/'>مستكشف Meta Graph API</a>.\n"
        "2️⃣ في خانة <b>Meta App</b> اختر تطبيقك.\n"
        "3️⃣ في خانة <b>User or Page</b>، انقر على القائمة المنسدلة واختر <b>Get Page Access Token</b>.\n"
        "4️⃣ قم بتسجيل الدخول، ووافق على الصلاحيات واختر صفحتك.\n"
        "5️⃣ من قسم الأذونات (Permissions) تأكد من إضافة ما يلي:\n"
        "  • <code>pages_show_list</code>\n"
        "  • <code>pages_read_engagement</code>\n"
        "  • <code>pages_read_user_content</code>\n"
        "  • <code>instagram_basic</code>\n"
        "  • <code>instagram_manage_comments</code>\n"
        "6️⃣ اضغط على الزر الأزرق <b>Generate Access Token</b>.\n"
        "7️⃣ انسخ الرمز الطويل الذي سيظهر (هذا هو <code>META_TOKEN</code>).\n"
        "8️⃣ في نفس الصفحة، ستجد رقم معرف الصفحة بجوار اسمها (هذا هو <code>PAGE_ID</code>).\n\n"
        "🔙 <i>بعد الانتهاء، قم بنسخها واستخدم أوامر <code>/settoken</code> و <code>/setpage</code> في البوت.</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 العودة للقائمة السابقة", callback_data="show_usage")]
    ])
    
    await callback.message.edit_text(tutorial_text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()

@dp.message(Command("settoken"))
async def set_token(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("الرجاء إرسال التوكن (Token). مثال:\n<code>/settoken EAAX...</code>", parse_mode="HTML")
        return
    db.execute("INSERT INTO users (user_id, meta_token) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET meta_token=excluded.meta_token", (message.from_user.id, command.args))
    db.commit()
    await message.reply("✅ تم حفظ توكن ميتا (Meta Token) الخاص بك بنجاح وبشكل آمن!")

@dp.message(Command("setpage"))
async def set_page(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("الرجاء إرسال معرف الصفحة (Page ID). مثال:\n<code>/setpage 1305500382646988</code>", parse_mode="HTML")
        return
    db.execute("INSERT INTO users (user_id, page_id) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET page_id=excluded.page_id", (message.from_user.id, command.args))
    db.commit()
    await message.reply("✅ تم حفظ معرف صفحة فيسبوك (Page ID) الخاص بك بنجاح!")

def get_user_creds(user_id):
    cursor = db.execute("SELECT meta_token, page_id FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()

@dp.message(Command("topfb"))
async def get_top_fb(message: types.Message, command: CommandObject):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]:
        return await message.reply("⚠️ الرجاء استخدام الأمر <code>/settoken</code> والأمر <code>/setpage</code> أولاً لربط حسابك!", parse_mode="HTML")
    
    since, until = parse_dates(command.args)
    await message.reply(f"جاري جلب بيانات فيسبوك... {'(مع تصفية التاريخ)' if since else ''}")
    result = fetch_fb_top_user(creds[0], creds[1], since, until)
    
    await message.reply(result, parse_mode="HTML", disable_web_page_preview=True)
    
@dp.message(Command("topig"))
async def get_top_ig(message: types.Message, command: CommandObject):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]:
        return await message.reply("⚠️ الرجاء استخدام الأمر <code>/settoken</code> والأمر <code>/setpage</code> أولاً لربط حسابك!", parse_mode="HTML")
    
    since, until = parse_dates(command.args)
    await message.reply(f"جاري جلب بيانات إنستغرام... {'(مع تصفية التاريخ)' if since else ''}")
    result = fetch_ig_top_user(creds[0], creds[1], since, until)
    
    await message.reply(result, parse_mode="HTML", disable_web_page_preview=True)

# NEW: Fetch the Top Tagger from the Webhook Database
@dp.message(Command("toptagger"))
async def get_top_tagger(message: types.Message):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]:
        return await message.reply("⚠️ الرجاء استخدام الأمر <code>/settoken</code> والأمر <code>/setpage</code> أولاً لربط حسابك!", parse_mode="HTML")
        
    await message.reply("جاري البحث في قاعدة البيانات...")
    
    # 1. Fetch the IG Account ID using the provided Facebook Page ID
    ig_res = requests.get(f"{BASE_URL}/{creds[1]}?fields=instagram_business_account{{id}}&access_token={creds[0]}").json()
    if 'instagram_business_account' not in ig_res:
        return await message.reply("❌ خطأ: لا يوجد حساب إنستغرام أعمال مرتبط بصفحة الفيسبوك هذه.")
        
    ig_account_id = ig_res['instagram_business_account']['id']
    
    # 2. Query the SQLite Database for this specific IG Account
    cursor = db.execute("SELECT sender_id, COUNT(*) as count FROM ig_tags WHERE ig_account_id=? GROUP BY sender_id ORDER BY count DESC LIMIT 1", (ig_account_id,))
    top_tagger = cursor.fetchone()
    
    if not top_tagger:
        return await message.reply("❌ لم يتم العثور على أي إشارات (Tags) جديدة منذ تفعيل النظام.")
        
    sender_id = top_tagger[0]
    count = top_tagger[1]
    
    # 3. Use the Graph API to convert the User ID into a readable Username
    user_res = requests.get(f"{BASE_URL}/{sender_id}?fields=username&access_token={creds[0]}").json()
    username = user_res.get('username', 'Unknown User')
    
    profile_url = f"https://www.instagram.com/{username}/"
    await message.reply(f"🏆 أكثر شخص أشار إليك (منذ تفعيل البوت): <a href='{profile_url}'>@{username}</a> ({count} إشارات)", parse_mode="HTML", disable_web_page_preview=True)


async def main():
    Thread(target=run_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

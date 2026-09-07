import os
import requests
import asyncio
import sqlite3
from datetime import datetime, timedelta
from collections import Counter
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.filters.command import CommandObject

# --- ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

API_VER = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VER}"

# --- DATABASE SETUP ---
db = sqlite3.connect("bot_users.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, meta_token TEXT, page_id TEXT)")
db.commit()

# --- DUMMY SERVER (KEEPS HOST AWAKE) ---
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is awake!"

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- API FETCH FUNCTIONS ---

def fetch_fb_top_user(meta_token, page_id, since=None, until=None):
    interactions = []
    user_names = {} # Dictionary to remember names based on their ID
    
    url = f"{BASE_URL}/{page_id}/posts?limit=100&access_token={meta_token}"
    if since: url += f"&since={since}"
    if until: url += f"&until={until}"
        
    res = requests.get(url).json()
    if 'error' in res: return f"❌ خطأ في فيسبوك API: {res['error'].get('message')}"
        
    posts = res.get('data', [])
    if not posts: return "❌ لم يتم العثور على أي منشورات في هذه الفترة الزمنية."
    
    for post in posts:
        post_id = post['id']
        # Tally Comments by ID
        comments_res = requests.get(f"{BASE_URL}/{post_id}/comments?limit=100&access_token={meta_token}").json()
        for c in comments_res.get('data', []):
            if 'from' in c:
                user_id = str(c['from'].get('id'))
                name = c['from'].get('name', 'Unknown User')
                if user_id != str(page_id): 
                    interactions.append(user_id)
                    user_names[user_id] = name
        
        # Tally Reactions by ID
        reactions_res = requests.get(f"{BASE_URL}/{post_id}/reactions?limit=100&access_token={meta_token}").json()
        for r in reactions_res.get('data', []):
            user_id = str(r.get('id'))
            name = r.get('name', 'مستخدم غير معروف')
            if user_id != str(page_id): 
                interactions.append(user_id)
                user_names[user_id] = name

    if not interactions: return ".لم يتم العثور على أي تفاعل حديث على فيسبوك"
    
    # Get the ID of the winner, then look up their name
    top_user_id, count = Counter(interactions).most_common(1)[0]
    top_name = user_names.get(top_user_id, "مستخدم غير معروف")
    
    # Removed the broken URL and simply format the name in bold
    return f"🏆 أكثر متفاعل على فيسبوك: <b> {top_name}</b> ({count} تفاعلات)"


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

# --- HELPER LOGIC FOR DATES ---
def parse_dates(args):
    since, until = None, None
    if args == "week":
        since = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    elif args and len(args.split()) == 2:
        parts = args.split()
        since = parts[0]
        until = parts[1]
    return since, until

# --- TELEGRAM COMMANDS ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    welcome_text = (
        "👋 <b>أهلاً بك في بوت أكثر المتفاعلين!</b> 🏆\n\n"
        "يمكنني مساعدتك في العثور على المعجبين الأكثر نشاطاً على صفحتك في فيسبوك وإنستغرام.\n\n"
        "⚙️ <b>1. أوامر الإعداد (قم بتشغيلها أولاً):</b>\n"
        "• <code>/settoken YOUR_META_TOKEN</code> : ربط رمز التوكن (Token) الخاص بك.\n"
        "• <code>/setpage YOUR_PAGE_ID</code> : ربط معرف صفحة فيسبوك الخاص بك (Page ID).\n\n"
        "📊 <b>2. أوامر التحليلات:</b>\n"
        "• <code>/topfb</code> : احصل على المعجب الأنشط في فيسبوك (آخر 100 منشور).\n"
        "• <code>/topig</code> : احصل على المعجب الأنشط في إنستغرام (آخر 100 منشور).\n\n"
        "📅 <b>3. عوامل تصفية التواريخ المتقدمة:</b>\n"
        "يمكنك إضافة نطاقات زمنية لأوامرك!\n"
        "• <code>/topfb week</code> : المعجب الأنشط في الأيام الـ 7 الماضية.\n"
        "• <code>/topig 2026-09-03 2026-09-08</code> : المعجب الأنشط بين تواريخ محددة (YYYY-MM-DD)."
    )
    await message.reply(welcome_text, parse_mode="HTML")
    
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

async def main():
    Thread(target=run_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

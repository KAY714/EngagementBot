import os
import requests
import asyncio
import sqlite3
from datetime import datetime, timedelta
from collections import Counter
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")

API_VER = "v26.0"
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

def fetch_fb_top_user(meta_token, page_id, since=None, until=None):

    # 👉 YOUR PIPEDREAM ENDPOINT URL:
    PIPEDREAM_URL = "https://eorp3shvzsg7mf2.m.pipedream.net"
    
    user_stats = {}
    
    try:
        # Ask Pipedream for the data
        response = requests.get(PIPEDREAM_URL, timeout=20)
        
        # We try to convert Pipedream's response to JSON
        try:
            res = response.json()
        except Exception:
            # If Pipedream returns empty text or HTML instead of JSON, print it so we can debug!
            return f"❌ خطأ في إعداد Pipedream. الرد كان:\n<code>{response.text[:200]}</code>"
            
    except Exception as e:
        return f"❌ فشل في الاتصال بـ Pipedream: {str(e)}"

    # Catch Facebook API errors sent through Pipedream
    if 'error' in res:
        return f"❌ خطأ من فيسبوك داخل Pipedream: {res['error'].get('message')}"

    posts = res.get('data', [])
    if not posts: return "❌ لم يتم العثور على أي تفاعلات عامة (أو الصفحة فارغة)."
    
    for post in posts:
        
        # 1. Tally Comments (Already inside the Pipedream response!)
        comments = post.get('comments', {}).get('data', [])
        for c in comments:
            if 'from' in c:
                user_id = str(c['from'].get('id'))
                name = c['from'].get('name', 'مستخدم غير معروف')
                if user_id != str(page_id): 
                    if user_id not in user_stats:
                        user_stats[user_id] = {'name': name, 'comments': 0, 'likes': 0, 'reactions': 0, 'total': 0}
                    user_stats[user_id]['comments'] += 1
                    user_stats[user_id]['total'] += 1
        
        # 2. Tally Reactions (Already inside the Pipedream response!)
        reactions = post.get('reactions', {}).get('data', [])
        for r in reactions:
            user_id = str(r.get('id'))
            name = r.get('name', 'مستخدم غير معروف')
            rtype = r.get('type', 'LIKE') 
            
            if user_id != str(page_id): 
                if user_id not in user_stats:
                    user_stats[user_id] = {'name': name, 'comments': 0, 'likes': 0, 'reactions': 0, 'total': 0}
                
                if rtype == 'LIKE':
                    user_stats[user_id]['likes'] += 1
                else:
                    user_stats[user_id]['reactions'] += 1
                    
                user_stats[user_id]['total'] += 1

    if not user_stats: return "لم يتم العثور على أي تفاعل حديث على فيسبوك."
    
    # Get the ID of the winner based on the highest 'total'
    top_user_id = max(user_stats, key=lambda x: user_stats[x]['total'])
    top_user = user_stats[top_user_id]
    
    return (f"🏆 أكثر متفاعل على فيسبوك: <b>{top_user['name']}</b>\n\n"
            f"📈 <b>إجمالي التفاعلات:</b> {top_user['total']}\n"
            f"👍 <b>الإعجابات (Likes):</b> {top_user['likes']}\n"
            f"❤️ <b>تفاعلات أخرى (Reactions):</b> {top_user['reactions']}\n"
            f"💬 <b>التعليقات (Comments):</b> {top_user['comments']}")


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


# --- TELEGRAM COMMANDS ---
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
        "• <code>/topig</code> : لاستخراج أكثر معلق على إنستغرام.\n\n"
        "📅 <b>3. عوامل تصفية التواريخ المتقدمة (اختياري):</b>\n"
        "• <code>/topfb week</code> : الأنشط في الأيام الـ 7 الماضية."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 شرح كيفية الحصول على Token و Page ID", callback_data="show_tutorial")]
    ])
    await callback.message.edit_text(usage_text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "show_tutorial")
async def show_tutorial_menu(callback: types.CallbackQuery):
    tutorial_text = (
        "<b>📖 شرح مفصل لربط صفحتك بالبوت:</b>\n\n"
        "<b>📍 أولاً: الحصول على Page ID (معرف الصفحة)</b>\n"
        "1️⃣ اذهب لصفحتك على فيسبوك من المتصفح.\n"
        "2️⃣ ادخل إلى <b>حول (About)</b> ثم <b>شفافية الصفحة (Page Transparency)</b>.\n"
        "3️⃣ انسخ <b>معرف الصفحة (Page ID)</b> واستخدم هذا الأمر:\n"
        "👉 <code>/setpage هنا_الرقم</code>\n\n"
        "<b>📍 ثانياً: الحصول على Meta Token</b>\n"
        "1️⃣ افتح <a href='https://developers.facebook.com/tools/explorer/'>مستكشف Meta Graph API</a>.\n"
        "2️⃣ من قائمة (User or Page)، اختر <b>Get Page Access Token</b>.\n"
        "3️⃣ سجل الدخول. <b>(مهم جداً: بعد تسجيل الدخول، انقر على القائمة مرة أخرى واختر 'اسم صفحتك' تحديداً)</b>.\n"
        "4️⃣ في خانة (Permissions)، أضف الأذونات التالية:\n"
        "▫️ <code>pages_read_engagement</code>\n"
        "▫️ <code>pages_read_user_content</code>\n"
        "▫️ <code>instagram_basic</code>\n"
        "5️⃣ انقر <b>Generate Access Token</b> واستخدم الرمز في البوت:\n"
        "👉 <code>/settoken هنا_الرمز</code>\n\n"
        "<b>⚠️ هل واجهت خطأ (Invalid OAuth)؟</b>\n"
        "هذا يعني أنك نسخت رمز المستخدم بدلاً من رمز الصفحة. لحل المشكلة فوراً، انسخ الرابط التالي، ضعه في متصفحك، واستبدل (رقم_صفحتك) و (الرمز_القديم) ببياناتك:\n"
        "<code>https://graph.facebook.com/v26.0/رقم_صفحتك?fields=access_token&access_token=الرمز_القديم</code>\n\n"
        "ستظهر لك صفحة بيضاء بها <code>access_token</code> جديد.. انسخه، فهو الرمز الصحيح!"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 العودة للقائمة السابقة", callback_data="show_usage")]
    ])
    await callback.message.edit_text(tutorial_text, reply_markup=keyboard, parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()

@dp.message(Command("settoken"))
async def set_token(message: types.Message, command: CommandObject):
    if not command.args: return await message.reply("الرجاء إرسال التوكن. مثال:\n<code>/settoken EAAX...</code>", parse_mode="HTML")
    db.execute("INSERT INTO users (user_id, meta_token) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET meta_token=excluded.meta_token", (message.from_user.id, command.args))
    db.commit()
    await message.reply("✅ تم حفظ توكن ميتا بنجاح!")

@dp.message(Command("setpage"))
async def set_page(message: types.Message, command: CommandObject):
    if not command.args: return await message.reply("الرجاء إرسال معرف الصفحة. مثال:\n<code>/setpage 1305500382646988</code>", parse_mode="HTML")
    db.execute("INSERT INTO users (user_id, page_id) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET page_id=excluded.page_id", (message.from_user.id, command.args))
    db.commit()
    await message.reply("✅ تم حفظ معرف صفحة فيسبوك بنجاح!")

def get_user_creds(user_id):
    cursor = db.execute("SELECT meta_token, page_id FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()

@dp.message(Command("topfb"))
async def get_top_fb(message: types.Message, command: CommandObject):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]: return await message.reply("⚠️ استخدم /settoken و /setpage أولاً!")
    since, until = parse_dates(command.args)
    await message.reply("جاري جلب بيانات فيسبوك... 🔍")
    
    await message.reply(fetch_fb_top_user(creds[0], creds[1], since, until), parse_mode="HTML", disable_web_page_preview=True)
    
@dp.message(Command("topig"))
async def get_top_ig(message: types.Message, command: CommandObject):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]: return await message.reply("⚠️ استخدم /settoken و /setpage أولاً!")
    since, until = parse_dates(command.args)
    await message.reply("جاري جلب بيانات إنستغرام... 🔍")
    await message.reply(fetch_ig_top_user(creds[0], creds[1], since, until), parse_mode="HTML", disable_web_page_preview=True)

@dp.message(Command("mypage"))
async def check_my_page(message: types.Message):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]: 
        return await message.reply("⚠️ استخدم /settoken و /setpage أولاً!")
    
    meta_token, page_id = creds[0], creds[1]
    await message.reply("جاري فحص الاتصال بفيسبوك... 🔍")
    
    fb_res = requests.get(f"{BASE_URL}/{page_id}?access_token={meta_token}").json()
    if 'error' in fb_res: return await message.reply(f"❌ خطأ في الاتصال: {fb_res['error'].get('message')}")
    
    page_name = fb_res.get('name', 'اسم غير معروف')
    
    ig_res = requests.get(f"{BASE_URL}/{page_id}?fields=instagram_business_account{{username}}&access_token={meta_token}").json()
    ig_username = "غير متصل ❌"
    
    if 'instagram_business_account' in ig_res:
        ig_username = f"@{ig_res['instagram_business_account'].get('username', 'Unknown')} ✅"
        
    info_text = (
        f"📊 <b>معلومات الحساب المرتبط:</b>\n\n"
        f"📘 <b>صفحة فيسبوك:</b> {page_name}\n"
        f"🆔 <b>معرف الصفحة:</b> <code>{page_id}</code>\n"
        f"📸 <b>إنستغرام:</b> {ig_username}"
    )
    await message.reply(info_text, parse_mode="HTML")

async def main():
    Thread(target=run_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

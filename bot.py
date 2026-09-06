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
# We ONLY need the BOT_TOKEN now. Users will provide their own Meta credentials.
BOT_TOKEN = os.environ.get("BOT_TOKEN")

API_VER = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VER}"

# --- DATABASE SETUP ---
# Creates a simple local database to store user credentials
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
    
    # Add time filters if provided
    url = f"{BASE_URL}/{page_id}/posts?limit=100&access_token={meta_token}"
    if since: url += f"&since={since}"
    if until: url += f"&until={until}"
        
    res = requests.get(url).json()
    if 'error' in res: return f"❌ Facebook API Error: {res['error'].get('message')}"
        
    posts = res.get('data', [])
    if not posts: return "❌ No posts found in this timeframe."
    
    for post in posts:
        post_id = post['id']
        # Tally Comments
        comments_res = requests.get(f"{BASE_URL}/{post_id}/comments?limit=100&access_token={meta_token}").json()
        for c in comments_res.get('data', []):
            if 'from' in c:
                user_id = str(c['from'].get('id'))
                if user_id != str(page_id): interactions.append(c['from']['name'])
        
        # Tally Reactions
        reactions_res = requests.get(f"{BASE_URL}/{post_id}/reactions?limit=100&access_token={meta_token}").json()
        for r in reactions_res.get('data', []):
            user_id = str(r.get('id'))
            if user_id != str(page_id): interactions.append(r['name'])

    if not interactions: return "No recent Facebook activity found."
    top_user = Counter(interactions).most_common(1)[0]
    return f"🏆 Top Facebook Fan: {top_user[0]} ({top_user[1]} interactions)"

def fetch_ig_top_user(meta_token, page_id, since=None, until=None):
    ig_res = requests.get(f"{BASE_URL}/{page_id}?fields=instagram_business_account{{id,username}}&access_token={meta_token}").json()
    if 'error' in ig_res: return f"❌ API Error: {ig_res['error'].get('message')}"
    if 'instagram_business_account' not in ig_res: return "Error: No IG account linked."
    
    ig_account = ig_res['instagram_business_account']
    ig_id = ig_account['id']
    ig_username = ig_account.get('username', '')
    
    interactions = []
    
    # Add time filters to Media
    url = f"{BASE_URL}/{ig_id}/media?limit=100&access_token={meta_token}"
    if since: url += f"&since={since}"
    if until: url += f"&until={until}"
        
    media = requests.get(url).json().get('data', [])
    if not media: return "❌ No IG posts found in this timeframe."
    
    for m in media:
        media_id = m['id']
        comments = requests.get(f"{BASE_URL}/{media_id}/comments?fields=username&limit=100&access_token={meta_token}").json().get('data', [])
        for c in comments:
            uname = c.get('username')
            if uname and uname != ig_username: interactions.append(uname)
            
    if not interactions: return "No recent Instagram comments found."
    top_user = Counter(interactions).most_common(1)[0]
    return f"🏆 Top Instagram Fan: @{top_user[0]} ({top_user[1]} comments)"

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
        "👋 <b>Welcome to the Top Engager Bot!</b> 🏆\n\n"
        "I can help you find the most active fans on your Facebook and Instagram pages.\n\n"
        "⚙️ <b>1. Setup Commands (Run these first):</b>\n"
        "• <code>/settoken YOUR_META_TOKEN</code> : Connect your Meta Page Token.\n"
        "• <code>/setpage YOUR_PAGE_ID</code> : Connect your Facebook Page ID.\n\n"
        "📊 <b>2. Analytics Commands:</b>\n"
        "• <code>/topfb</code> : Get your top Facebook fan (recent 100 posts).\n"
        "• <code>/topig</code> : Get your top Instagram fan (recent 100 posts).\n\n"
        "📅 <b>3. Advanced Date Filters:</b>\n"
        "You can add timeframes to your commands!\n"
        "• <code>/topfb week</code> : Top fan in the past 7 days.\n"
        "• <code>/topig 2026-09-03 2026-09-08</code> : Top fan between specific dates (YYYY-MM-DD)."
    )
    # Using parse_mode="HTML" makes the text bold and formats the commands nicely
    await message.reply(welcome_text, parse_mode="HTML")
    
@dp.message(Command("settoken"))
async def set_token(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("Please provide a token. Example: `/settoken EAAX...`")
        return
    db.execute("INSERT INTO users (user_id, meta_token) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET meta_token=excluded.meta_token", (message.from_user.id, command.args))
    db.commit()
    await message.reply("✅ Meta Token saved securely for your account!")

@dp.message(Command("setpage"))
async def set_page(message: types.Message, command: CommandObject):
    if not command.args:
        await message.reply("Please provide a Page ID. Example: `/setpage 1305500382646988`")
        return
    db.execute("INSERT INTO users (user_id, page_id) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET page_id=excluded.page_id", (message.from_user.id, command.args))
    db.commit()
    await message.reply("✅ Facebook Page ID saved for your account!")

def get_user_creds(user_id):
    cursor = db.execute("SELECT meta_token, page_id FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()

@dp.message(Command("topfb"))
async def get_top_fb(message: types.Message, command: CommandObject):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]:
        return await message.reply("⚠️ Please use `/settoken` and `/setpage` first!")
    
    since, until = parse_dates(command.args)
    await message.reply(f"Fetching Facebook data... {'(Filtered by date)' if since else ''}")
    result = fetch_fb_top_user(creds[0], creds[1], since, until)
    await message.reply(result)

@dp.message(Command("topig"))
async def get_top_ig(message: types.Message, command: CommandObject):
    creds = get_user_creds(message.from_user.id)
    if not creds or not creds[0] or not creds[1]:
        return await message.reply("⚠️ Please use `/settoken` and `/setpage` first!")
    
    since, until = parse_dates(command.args)
    await message.reply(f"Fetching Instagram data... {'(Filtered by date)' if since else ''}")
    result = fetch_ig_top_user(creds[0], creds[1], since, until)
    await message.reply(result)


async def main():
    Thread(target=run_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

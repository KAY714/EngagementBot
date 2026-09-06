import os
import requests
import asyncio
from collections import Counter
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# --- ENVIRONMENT VARIABLES ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
META_TOKEN = os.environ.get("META_TOKEN")
PAGE_ID = os.environ.get("PAGE_ID")

API_VER = "v19.0"
BASE_URL = f"https://graph.facebook.com/{API_VER}"

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

def fetch_fb_top_user():
    interactions = []
    
    # 1. Get up to 100 recent posts
    res = requests.get(f"{BASE_URL}/{PAGE_ID}/posts?limit=100&access_token={META_TOKEN}").json()
    posts = res.get('data', [])
    
    for post in posts:
        post_id = post['id']
        
        # 2. Tally Comments (Limit 100)
        comments = requests.get(f"{BASE_URL}/{post_id}/comments?limit=100&access_token={META_TOKEN}").json().get('data', [])
        for c in comments:
            if 'from' in c:
                user_id = str(c['from'].get('id'))
                # Prevent the bot/page from counting itself
                if user_id != str(PAGE_ID):
                    interactions.append(c['from']['name'])
        
        # 3. Tally Reactions (Limit 100)
        reactions = requests.get(f"{BASE_URL}/{post_id}/reactions?limit=100&access_token={META_TOKEN}").json().get('data', [])
        for r in reactions:
            user_id = str(r.get('id'))
            if user_id != str(PAGE_ID):
                interactions.append(r['name'])

    if not interactions: return "No recent Facebook activity found."
    top_user = Counter(interactions).most_common(1)[0]
    return f"🏆 Top Facebook Fan: {top_user[0]} ({top_user[1]} interactions)"


def fetch_ig_top_user():
    # 1. Fetch the connected IG Account ID and Username
    ig_res = requests.get(f"{BASE_URL}/{PAGE_ID}?fields=instagram_business_account{{id,username}}&access_token={META_TOKEN}").json()
    if 'instagram_business_account' not in ig_res:
        return "Error: No Instagram Business account linked to this Facebook Page."
    
    ig_account = ig_res['instagram_business_account']
    ig_id = ig_account['id']
    ig_username = ig_account.get('username', '')
    
    interactions = []
    
    # 2. Get up to 100 IG Posts (Media)
    media = requests.get(f"{BASE_URL}/{ig_id}/media?limit=100&access_token={META_TOKEN}").json().get('data', [])
    
    for m in media:
        media_id = m['id']
        # 3. Tally Comments - We MUST request the 'username' field explicitly! Limit to 100.
        comments = requests.get(f"{BASE_URL}/{media_id}/comments?fields=username&limit=100&access_token={META_TOKEN}").json().get('data', [])
        for c in comments:
            uname = c.get('username')
            # Only tally if a username exists AND it is not your own Instagram page
            if uname and uname != ig_username:
                interactions.append(uname)
            
    if not interactions: return "No recent Instagram comments found."
    top_user = Counter(interactions).most_common(1)[0]
    return f"🏆 Top Instagram Fan: @{top_user[0]} ({top_user[1]} comments)"
async def get_top_fb(message: types.Message):
    await message.reply("Fetching Facebook data... this takes a few seconds.")
    # In a production bot, heavy API requests should be run in a separate thread/executor
    # to avoid blocking the async event loop, but this works for light usage.
    result = fetch_fb_top_user()
    await message.reply(result)

@dp.message(Command("topig"))
async def get_top_ig(message: types.Message):
    await message.reply("Fetching Instagram data... this takes a few seconds.")
    result = fetch_ig_top_user()
    await message.reply(result)

async def main():
    Thread(target=run_server, daemon=True).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

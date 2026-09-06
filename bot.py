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
    # 1. Get recent posts
    res = requests.get(f"{BASE_URL}/{PAGE_ID}/posts?access_token={META_TOKEN}").json()
    posts = res.get('data', [])
    
    for post in posts:
        post_id = post['id']
        # 2. Tally Comments
        comments = requests.get(f"{BASE_URL}/{post_id}/comments?access_token={META_TOKEN}").json().get('data', [])
        for c in comments:
            if 'from' in c: interactions.append(c['from']['name'])
        
        # 3. Tally Reactions
        reactions = requests.get(f"{BASE_URL}/{post_id}/reactions?access_token={META_TOKEN}").json().get('data', [])
        for r in reactions:
            interactions.append(r['name'])

    if not interactions: return "No recent Facebook activity found."
    top_user = Counter(interactions).most_common(1)[0]
    return f"🏆 Top Facebook Fan: {top_user[0]} ({top_user[1]} interactions)"

def fetch_ig_top_user():
    # 1. Fetch the connected IG Account ID
    ig_res = requests.get(f"{BASE_URL}/{PAGE_ID}?fields=instagram_business_account&access_token={META_TOKEN}").json()
    if 'instagram_business_account' not in ig_res:
        return "Error: No Instagram Business account linked to this Facebook Page."
    
    ig_id = ig_res['instagram_business_account']['id']
    interactions = []
    
    # 2. Get IG Posts (Media)
    media = requests.get(f"{BASE_URL}/{ig_id}/media?access_token={META_TOKEN}").json().get('data', [])
    for m in media:
        media_id = m['id']
        # 3. Tally Comments
        comments = requests.get(f"{BASE_URL}/{media_id}/comments?access_token={META_TOKEN}").json().get('data', [])
        for c in comments:
            interactions.append(c.get('username', 'Unknown'))
            
    if not interactions: return "No recent Instagram comments found."
    top_user = Counter(interactions).most_common(1)[0]
    return f"🏆 Top Instagram Fan: @{top_user[0]} ({top_user[1]} comments)"

@dp.message(Command("topfb"))
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
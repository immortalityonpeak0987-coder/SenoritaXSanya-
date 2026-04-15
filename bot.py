import os
import logging
import sqlite3
import threading
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from flask import Flask
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ==========================================
# CONFIGURATION & SETUP
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GROK_API_KEY = os.environ.get("GROK_API_KEY", "YOUR_GROK_API_KEY")
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# DATABASE SETUP (SQLite for Filters)
# ==========================================
def init_db():
    conn = sqlite3.connect("senorita.db", check_same_thread=False)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS filters
             (chat_id TEXT, keyword TEXT, reply TEXT, PRIMARY KEY(chat_id, keyword))"""
    )
    conn.commit()
    return conn

db_conn = init_db()

# ==========================================
# FLASK KEEP-ALIVE SERVER (For Render)
# ==========================================
app = Flask(__name__)

@app.route("/")
def home():
    return "Senorita is awake and running!"

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

# ==========================================
# ADMIN COMMANDS
# ==========================================
async def check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    admins = await context.bot.get_chat_administrators(chat_id)
    if any(admin.user.id == user_id for admin in admins):
        return True
    await update.message.reply_text("You need to be an admin to use this command, darling.")
    return False

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to ban them.")
        return
    user_to_ban = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_to_ban.id)
        await update.message.reply_text(f"Banned {user_to_ban.first_name}. Adios!")
    except Exception as e:
        await update.message.reply_text(f"Couldn't ban: {e}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to unban them.")
        return
    user_to_unban = update.message.reply_to_message.from_user
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, user_to_unban.id, only_if_banned=True)
        await update.message.reply_text(f"Unbanned {user_to_unban.first_name}. Welcome back!")
    except Exception as e:
        await update.message.reply_text(f"Couldn't unban: {e}")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to mute them.")
        return
    user_to_mute = update.message.reply_to_message.from_user
    try:
        permissions = ChatPermissions(can_send_messages=False)
        await context.bot.restrict_chat_member(update.effective_chat.id, user_to_mute.id, permissions)
        await update.message.reply_text(f"Muted {user_to_mute.first_name}. Shhh!")
    except Exception as e:
        await update.message.reply_text(f"Couldn't mute: {e}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to unmute them.")
        return
    user_to_unmute = update.message.reply_to_message.from_user
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await context.bot.restrict_chat_member(update.effective_chat.id, user_to_unmute.id, permissions)
        await update.message.reply_text(f"Unmuted {user_to_unmute.first_name}. Speak up!")
    except Exception as e:
        await update.message.reply_text(f"Couldn't unmute: {e}")

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message to promote them.")
        return
    user_to_promote = update.message.reply_to_message.from_user
    try:
        await context.bot.promote_chat_member(
            update.effective_chat.id, 
            user_to_promote.id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_manage_video_chats=True,
            can_restrict_members=True,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=True
        )
        await update.message.reply_text(f"Promoted {user_to_promote.first_name} to Admin!")
    except Exception as e:
        await update.message.reply_text(f"Couldn't promote: {e}")

# ==========================================
# FILTERS FEATURE
# ==========================================
async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addfilter <keyword> <reply message>")
        return
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])
    chat_id = str(update.effective_chat.id)
    
    c = db_conn.cursor()
    c.execute("REPLACE INTO filters (chat_id, keyword, reply) VALUES (?, ?, ?)", (chat_id, keyword, reply))
    db_conn.commit()
    await update.message.reply_text(f"Filter added for '{keyword}'.")

async def rm_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update, context): return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /rmfilter <keyword>")
        return
    keyword = context.args[0].lower()
    chat_id = str(update.effective_chat.id)
    
    c = db_conn.cursor()
    c.execute("DELETE FROM filters WHERE chat_id=? AND keyword=?", (chat_id, keyword))
    db_conn.commit()
    await update.message.reply_text(f"Filter removed for '{keyword}'.")

async def check_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = str(update.effective_chat.id)
    text = update.message.text.lower()
    
    c = db_conn.cursor()
    c.execute("SELECT keyword, reply FROM filters WHERE chat_id=?", (chat_id,))
    filters_list = c.fetchall()
    
    for keyword, reply in filters_list:
        if keyword in text:
            await update.message.reply_text(reply)
            break

# ==========================================
# MEMIFY FEATURE (Stickers/Images)
# ==========================================
async def memify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Reply to a photo with /memify <text>")
        return
    
    text = " ".join(context.args).upper()
    if not text:
        await update.message.reply_text("Please provide text. Example: /memify BOTTOM TEXT")
        return

    msg = await update.message.reply_text("Memifying... Please wait.")
    
    try:
        # Get the highest resolution photo
        photo_file = await update.message.reply_to_message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()
        
        # Open image
        img = Image.open(BytesIO(photo_bytes))
        draw = ImageDraw.Draw(img)
        
        # Try to load a default font, fallback to default if not found
        try:
            font = ImageFont.truetype("arial.ttf", int(img.width / 10))
        except IOError:
            font = ImageFont.load_default()

        # Calculate text size and position (bottom center)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (img.width - text_width) / 2
        y = img.height - text_height - 20
        
        # Draw text with black outline
        outline_color = "black"
        fill_color = "white"
        thickness = 2
        
        for adj_x in range(-thickness, thickness+1):
            for adj_y in range(-thickness, thickness+1):
                draw.text((x+adj_x, y+adj_y), text, font=font, fill=outline_color)
                
        draw.text((x, y), text, font=font, fill=fill_color)
        
        # Save to memory
        out_bio = BytesIO()
        out_bio.name = "meme.webp"
        img.save(out_bio, "WEBP")
        out_bio.seek(0)
        
        await update.message.reply_sticker(sticker=out_bio)
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Failed to memify: {e}")

# ==========================================
# GROK AI CHATBOT FEATURE
# ==========================================
def ask_grok(prompt: str) -> str:
    if GROK_API_KEY == "YOUR_GROK_API_KEY":
        return "Grok API key is not configured!"
        
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "grok-beta",
        "messages": [
            {"role": "system", "content": "You are Senorita, a sassy, helpful, and charming Telegram bot. Keep your responses short, around 80 tokens."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 80
    }
    try:
        response = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Grok API Error: {e}")
        return "Sorry darling, my brain is a bit fuzzy right now. Try again later."

async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only respond if the bot is mentioned or replied to
    bot_username = context.bot.username
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
    is_mention = f"@{bot_username}" in update.message.text
    
    if is_reply or is_mention:
        prompt = update.message.text.replace(f"@{bot_username}", "").strip()
        if not prompt:
            await update.message.reply_text("Yes, darling?")
            return
            
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        # Run Grok API call in a separate thread to avoid blocking the async event loop
        response = await asyncio.to_thread(ask_grok, prompt)
        await update.message.reply_text(response)

# ==========================================
# MAIN BOT RUNNER
# ==========================================
def main():
    # Start Flask server in a background thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("Please set the BOT_TOKEN environment variable.")
        return

    # Initialize Bot Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Register Handlers
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("mute", mute))
    application.add_handler(CommandHandler("unmute", unmute))
    application.add_handler(CommandHandler("promote", promote))
    
    application.add_handler(CommandHandler("addfilter", add_filter))
    application.add_handler(CommandHandler("rmfilter", rm_filter))
    application.add_handler(CommandHandler("memify", memify))

    # Message handler for filters and AI chat
    # We use a combined handler to process both
    async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await check_filters(update, context)
        await ai_chat(update, context)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Start the Bot
    logger.info("Senorita is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    import asyncio
    main()

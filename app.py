# app.py (Main Application)
import os
import logging
import asyncio
import json
import csv
from datetime import datetime
from io import StringIO
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from flask import Flask, render_template, request, redirect, session, send_file
from flask_wtf.csrf import CSRFProtect

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration - UPDATED WITH YOUR CREDENTIALS
TOKEN = '7286908099:AAG7rHzCaSoDl5yVFV1mwF0X5-DrIpHYANI'
ADMIN_USER_ID = 5559075560
CHANNEL_USERNAME = '@REALHLink'
ADMIN_PANEL_USER = 'admin'
ADMIN_PANEL_PASS = 'admin'
DATABASE_FILE = 'data.json'

# Initialize bot and dispatcher
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Consider changing this for production
csrf = CSRFProtect(app)

# Database structure
DATABASE = {
    "users": {},
    "broadcasts": [],
    "broadcast_stats": {}
}

# Load database from file
def load_db():
    try:
        if os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading database: {e}")
    return DATABASE.copy()

# Save database to file
def save_db():
    try:
        with open(DATABASE_FILE, 'w') as f:
            json.dump(DATABASE, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving database: {e}")

# Load initial database
DATABASE.update(load_db())

# Force subscription check
async def is_subscribed(user_id: int) -> bool:
    try:
        chat_member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return chat_member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Subscription check error: {e}")
        return False

# User registration
def register_user(user: types.User):
    user_id = str(user.id)
    if user_id not in DATABASE["users"]:
        DATABASE["users"][user_id] = {
            "id": user.id,
            "full_name": user.full_name,
            "username": user.username,
            "join_date": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "is_subscribed": False
        }
        save_db()
        logger.info(f"New user registered: {user.full_name} ({user.id})")
    return DATABASE["users"][user_id]

# Update user activity
def update_user_activity(user_id: int):
    user_id = str(user_id)
    if user_id in DATABASE["users"]:
        DATABASE["users"][user_id]["last_active"] = datetime.now().isoformat()
        save_db()

# Broadcast message handler
def create_broadcast(text, image_path=None, buttons=None):
    broadcast_id = f"broadcast_{datetime.now().timestamp()}"
    broadcast = {
        "id": broadcast_id,
        "text": text,
        "image_path": image_path,
        "buttons": buttons or [],
        "timestamp": datetime.now().isoformat()
    }
    DATABASE["broadcasts"].append(broadcast)
    DATABASE["broadcast_stats"][broadcast_id] = {
        "sent": 0,
        "clicks": {},
        "button_clicks": {}
    }
    save_db()
    return broadcast_id

# Send broadcast to users
async def send_broadcast(broadcast_id):
    broadcast = next((b for b in DATABASE["broadcasts"] if b["id"] == broadcast_id), None)
    if not broadcast:
        return
    
    stats = DATABASE["broadcast_stats"][broadcast_id]
    sent_count = 0
    
    for user_id_str in DATABASE["users"]:
        try:
            user_id = int(user_id_str)
            # Create keyboard if buttons exist
            kb_builder = InlineKeyboardBuilder()
            for idx, btn in enumerate(broadcast["buttons"]):
                callback_data = f"broadcast_click:{broadcast_id}:{idx}"
                kb_builder.add(InlineKeyboardButton(
                    text=btn["text"],
                    url=btn["url"],
                    callback_data=callback_data
                ))
            
            # Send message with or without image
            if broadcast.get("image_path"):
                with open(broadcast["image_path"], 'rb') as photo:
                    await bot.send_photo(
                        chat_id=user_id,
                        photo=photo,
                        caption=broadcast["text"],
                        reply_markup=kb_builder.as_markup()
                    )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=broadcast["text"],
                    reply_markup=kb_builder.as_markup()
                )
            
            sent_count += 1
        except Exception as e:
            logger.error(f"Error sending broadcast to {user_id_str}: {e}")
    
    stats["sent"] = sent_count
    save_db()
    return sent_count

# Bot Handlers
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user = register_user(message.from_user)
    update_user_activity(message.from_user.id)
    
    # Check subscription
    subscribed = await is_subscribed(message.from_user.id)
    DATABASE["users"][str(message.from_user.id)]["is_subscribed"] = subscribed
    save_db()
    
    if not subscribed:
        # Send force subscribe message
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Join Channel", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")
        ]])
        await message.answer_photo(
            photo="https://via.placeholder.com/600x300?text=Join+Our+Channel",
            caption="📢 Please join our channel to continue!\n\n"
                    "Click the button below to join, then press /start again.",
            reply_markup=keyboard
        )
        return
    
    # Welcome message for subscribed users
    await message.answer(
        "👋 Welcome to the bot!\n\n"
        "You now have full access to all features."
    )

@dp.message(Command("stats"))
async def stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    total_users = len(DATABASE["users"])
    active_users = sum(
        1 for u in DATABASE["users"].values() 
        if (datetime.now() - datetime.fromisoformat(u["last_active"])).days < 30
    )
    
    await message.answer(
        f"📊 Bot Statistics:\n\n"
        f"• Total Users: {total_users}\n"
        f"• Active Users (last 30 days): {active_users}"
    )

@dp.message(Command("broadcast_stats"))
async def broadcast_stats_handler(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    if not DATABASE["broadcasts"]:
        await message.answer("No broadcasts yet")
        return
    
    last_broadcast = DATABASE["broadcasts"][-1]
    stats = DATABASE["broadcast_stats"][last_broadcast["id"]]
    total_clicks = sum(stats["clicks"].values())
    
    await message.answer(
        f"📨 Last Broadcast Stats:\n\n"
        f"• Sent to: {stats['sent']} users\n"
        f"• Total Clicks: {total_clicks}\n"
        f"• Sent at: {last_broadcast['timestamp']}"
    )

@dp.message(Command("users"))
async def users_handler(message: types.Message):
    if message.from_user.id != ADMIN_USER_ID:
        return
    
    # Create CSV in memory
    csv_file = StringIO()
    writer = csv.writer(csv_file)
    writer.writerow(["ID", "Name", "Username", "Join Date", "Last Active"])
    
    for user in DATABASE["users"].values():
        writer.writerow([
            user["id"],
            user["full_name"],
            user["username"],
            user["join_date"],
            user["last_active"]
        ])
    
    csv_file.seek(0)
    await message.answer_document(
        types.BufferedInputFile(
            csv_file.getvalue().encode(),
            filename="users.csv"
        )
    )

@dp.callback_query(F.data.startswith("broadcast_click"))
async def broadcast_click_handler(callback: types.CallbackQuery):
    _, broadcast_id, button_idx = callback.data.split(':')
    user_id = str(callback.from_user.id)
    
    # Update broadcast stats
    if broadcast_id in DATABASE["broadcast_stats"]:
        stats = DATABASE["broadcast_stats"][broadcast_id]
        stats["clicks"][user_id] = stats["clicks"].get(user_id, 0) + 1
        stats["button_clicks"][button_idx] = stats["button_clicks"].get(button_idx, 0) + 1
        save_db()
    
    await callback.answer()

# Flask Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if (request.form['username'] == ADMIN_PANEL_USER and 
            request.form['password'] == ADMIN_PANEL_PASS):
            session['admin_logged_in'] = True
            return redirect('/admin')
        return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin/login')

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    
    # Calculate stats for dashboard
    total_users = len(DATABASE["users"])
    active_users = sum(
        1 for u in DATABASE["users"].values() 
        if (datetime.now() - datetime.fromisoformat(u["last_active"])).days < 30
    )
    broadcast_count = len(DATABASE["broadcasts"])
    
    if request.method == 'POST':
        # Handle broadcast creation
        text = request.form['message']
        image = request.files.get('image')
        image_path = None
        
        if image:
            image_path = f"uploads/{datetime.now().timestamp()}_{image.filename}"
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            image.save(image_path)
        
        buttons = []
        for i in range(1, 6):  # Support up to 5 buttons
            btn_text = request.form.get(f'btn_text_{i}')
            btn_url = request.form.get(f'btn_url_{i}')
            if btn_text and btn_url:
                buttons.append({"text": btn_text, "url": btn_url})
        
        broadcast_id = create_broadcast(text, image_path, buttons)
        
        # Send broadcast if requested
        if 'send_now' in request.form:
            asyncio.run(send_broadcast(broadcast_id))
            return render_template('admin.html', 
                                  success="Broadcast sent successfully!",
                                  total_users=total_users,
                                  active_users=active_users,
                                  broadcast_count=broadcast_count)
        
        return render_template('admin.html', 
                              success="Broadcast saved!",
                              total_users=total_users,
                              active_users=active_users,
                              broadcast_count=broadcast_count)
    
    return render_template('admin.html', 
                          total_users=total_users,
                          active_users=active_users,
                          broadcast_count=broadcast_count)

@app.route('/admin/users')
def admin_users():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    
    # Prepare data for template
    users = sorted(
        DATABASE["users"].values(),
        key=lambda u: u["join_date"],
        reverse=True
    )
    
    # Calculate days since last active
    current_date = datetime.now()
    for user in users:
        last_active = datetime.fromisoformat(user["last_active"])
        user["days_since_active"] = (current_date - last_active).days
    
    return render_template('users.html', users=users)

@app.route('/admin/export')
def export_users():
    if not session.get('admin_logged_in'):
        return redirect('/admin/login')
    
    # Create CSV in memory
    csv_file = StringIO()
    writer = csv.writer(csv_file)
    writer.writerow(["ID", "Name", "Username", "Join Date", "Last Active"])
    
    for user in DATABASE["users"].values():
        writer.writerow([
            user["id"],
            user["full_name"],
            user["username"],
            user["join_date"],
            user["last_active"]
        ])
    
    csv_file.seek(0)
    return send_file(
        csv_file,
        mimetype='text/csv',
        as_attachment=True,
        download_name='users.csv'
    )

# Start the application
async def start_bot():
    await dp.start_polling(bot)

def start_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == '__main__':
    import threading
    # Create uploads directory if not exists
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=start_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Run the bot in main thread
    asyncio.run(start_bot())

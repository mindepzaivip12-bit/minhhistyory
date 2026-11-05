import telebot
import requests
import hashlib
import base64
import json
import logging
import threading
import time
import socketio
import random
import os
import re
from flask import Flask

# ==========================================
# ⚙️ CẤU HÌNH HỆ THỐNG
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8627314570:AAG8L2vxe8u-4uDGdnip8gzoW8BlDQ_bg3E")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "8627314570"))
DATA_COLLECTOR_USER = os.environ.get("DATA_COLLECTOR_USER", "")
DATA_COLLECTOR_PASS = os.environ.get("DATA_COLLECTOR_PASS", "")
BALANCE_NOTIFY_THRESHOLD = 200000

bot = telebot.TeleBot(BOT_TOKEN)
vip_users = {ADMIN_ID}
active_sockets = {}
user_states = {}
notified_accounts = set()
USE_MD5_API = True

# ==========================================
# 🌐 FLASK HEALTH CHECK (RENDER)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Tài Xỉu đang chạy 24/7!", 200

@app.route('/health')
def health():
    return {"status": "ok", "time": time.strftime('%Y-%m-%d %H:%M:%S')}, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ==========================================
# 🌐 LE MINH MD5 API (TỰ ĐỘNG FALLBACK NẾU LỖI)
# ==========================================
MD5_API_BASE = "https://leminhapiik.onrender.com"
_md5_state = {"data": None, "timestamp": 0, "last_error": None}

def _extract_str(v):
    if v is None: return None
    s = str(v).upper().strip()
    if "TAI" in s or "TÀI" in s: return "TAI"
    if "XIU" in s or "XỈU" in s: return "XIU"
    return None

def fetch_md5_prediction():
    """Cố gắng lấy dữ liệu từ API, nếu lỗi trả về None ngay lập tức"""
    if not USE_MD5_API: return None
    
    # Cache 15s
    if _md5_state["data"] and (time.time() - _md5_state["timestamp"] < 15):
        return _md5_state["data"]

    try:
        # Vì API thực tế là web yêu cầu key, ta thử gọi vào endpoint giả định
        # Nếu web trả về HTML hoặc lỗi, nó sẽ tự catch và trả về None
        r = requests.get(MD5_API_BASE, timeout=5)
        if r.status_code == 200 and "application/json" in r.headers.get("Content-Type", ""):
            data = r.json()
            pred = None
            # Quét các key có thể có
            for k in ["du_doan", "prediction", "result", "ket_qua"]:
                if k in data:
                    pred = _extract_str(data[k])
                    if pred: break
            
            if pred:
                parsed = {"prediction": pred, "confidence": 75, "session": data.get("session")}
                _md5_state["data"] = parsed
                _md5_state["timestamp"] = time.time()
                return parsed
    except Exception:
        pass # Bỏ qua lỗi API, không làm sập bot
    
    return None

# ==========================================
# 🎯 BẢNG CẦU & XÚC XẮC (DỰ PHÒNG)
# ==========================================
CAU_TABLE = {
    "X3":  ("XIU", 70),  "X4":  ("TAI", 60),  "X5":  ("TAI", 70),  "X6":  ("XIU", 60),
    "X7":  ("TAI", 80),  "X8":  ("XIU", 80),  "X9":  ("XIU", 70),  "X10": ("TAI", 80),
    "T11": ("XIU", 60),  "T12": ("TAI", 80),  "T13": ("TAI", 80),  "T14": ("XIU", 60),
    "T15": ("XIU", 70),  "T16": ("TAI", 60),  "T17": ("XIU", 60),  "T18": ("XIU", 80),
}

DICE_TABLE = {
    3:  {"111": ("XIU", 70)},
    4:  {"112": ("XIU", 60), "121": ("TAI", 65), "211": ("TAI", 65)},
    5:  {"113": ("TAI", 65), "122": ("XIU", 60), "131": ("TAI", 70), "212": ("XIU", 60), "221": ("TAI", 60), "311": ("XIU", 65)},
    6:  {"114": ("TAI", 60), "123": ("TAI", 65), "132": ("XIU", 60), "141": ("TAI", 60), "213": ("TAI", 65), "222": ("XIU", 75), "231": ("TAI", 60), "312": ("XIU", 60)},
    7:  {"115": ("TAI", 65), "124": ("XIU", 60), "133": ("TAI", 65), "142": ("XIU", 60), "151": ("TAI", 60), "214": ("XIU", 65), "223": ("TAI", 60), "232": ("XIU", 70), "313": ("TAI", 65), "322": ("XIU", 60), "331": ("TAI", 60)},
    8:  {"116": ("TAI", 60), "125": ("XIU", 65), "134": ("TAI", 60), "143": ("XIU", 60), "152": ("TAI", 65), "215": ("XIU", 60), "224": ("TAI", 65), "233": ("XIU", 60), "242": ("TAI", 60), "251": ("XIU", 65), "314": ("TAI", 60), "323": ("XIU", 60), "332": ("TAI", 60), "413": ("XIU", 65)},
    9:  {"126": ("TAI", 60), "135": ("XIU", 65), "144": ("TAI", 60), "153": ("XIU", 65), "162": ("TAI", 60), "216": ("XIU", 60), "225": ("TAI", 65), "234": ("XIU", 60), "243": ("TAI", 60), "252": ("XIU", 60), "315": ("TAI", 65), "324": ("XIU", 60), "333": ("TAI", 70), "342": ("XIU", 60), "414": ("TAI", 60), "423": ("XIU", 65)},
    10: {"136": ("TAI", 65), "145": ("XIU", 60), "154": ("TAI", 60), "163": ("XIU", 65), "226": ("TAI", 60), "235": ("XIU", 60), "244": ("TAI", 65), "253": ("XIU", 60), "316": ("TAI", 60), "325": ("XIU", 65), "334": ("TAI", 60), "343": ("XIU", 60), "415": ("TAI", 60), "424": ("XIU", 65), "433": ("TAI", 60), "514": ("XIU", 60)},
    11: {"146": ("XIU", 65), "155": ("TAI", 60), "164": ("XIU", 60), "236": ("TAI", 60), "245": ("XIU", 65), "254": ("TAI", 60), "326": ("XIU", 60), "335": ("TAI", 65), "344": ("XIU", 60), "416": ("TAI", 60), "425": ("XIU", 65), "434": ("TAI", 60), "515": ("XIU", 60), "524": ("TAI", 60), "614": ("XIU", 65)},
    12: {"156": ("XIU", 60), "165": ("TAI", 65), "246": ("XIU", 60), "255": ("TAI", 60), "264": ("XIU", 65), "336": ("TAI", 60), "345": ("XIU", 60), "354": ("TAI", 60), "426": ("XIU", 65), "435": ("TAI", 60), "444": ("XIU", 65), "453": ("TAI", 60), "516": ("XIU", 60), "525": ("TAI", 60), "534": ("XIU", 65), "615": ("TAI", 60), "624": ("XIU", 60), "633": ("TAI", 60)},
    13: {"166": ("XIU", 60), "256": ("TAI", 65), "265": ("XIU", 60), "346": ("TAI", 60), "355": ("XIU", 65), "364": ("TAI", 60), "436": ("XIU", 60), "445": ("TAI", 65), "454": ("XIU", 60), "463": ("TAI", 60), "526": ("XIU", 65), "535": ("TAI", 60), "544": ("XIU", 60), "553": ("TAI", 60), "616": ("XIU", 65), "625": ("TAI", 60), "634": ("XIU", 60), "643": ("TAI", 60)},
    14: {"266": ("XIU", 60), "356": ("TAI", 65), "365": ("XIU", 60), "446": ("TAI", 60), "455": ("XIU", 65), "464": ("TAI", 60), "536": ("XIU", 60), "545": ("TAI", 65), "554": ("XIU", 60), "563": ("TAI", 60), "626": ("XIU", 65), "635": ("TAI", 60), "644": ("XIU", 60), "653": ("TAI", 60)},
    15: {"366": ("XIU", 65), "456": ("TAI", 60), "465": ("XIU", 65), "546": ("TAI", 60), "555": ("XIU", 70), "564": ("TAI", 60), "636": ("XIU", 65), "645": ("TAI", 60), "654": ("XIU", 60), "663": ("TAI", 60)},
    16: {"466": ("XIU", 65), "556": ("TAI", 60), "565": ("XIU", 65), "646": ("TAI", 60), "655": ("XIU", 70), "664": ("TAI", 60)},
    17: {"566": ("XIU", 65), "656": ("TAI", 60), "665": ("XIU", 65)},
    18: {"666": ("XIU", 80)},
}

def init_user_state(chat_id):
    if chat_id not in user_states:
        user_states[chat_id] = {
            "profit_loss": 0, "auto_bet_enabled": False, "x2_mode": False,
            "reverse_mode": False, "win_streak": 0, "base_bet_amount": 10000,
            "current_bet": 10000, "target_profit": None, "current_prediction": None,
            "waiting_for_result": False, "has_bet_this_session": False,
            "session_id": None, "session_count": 0, "balance": 0,
            "username": None, "password": None, "nickname": None, "last_dice": None,
        }

def is_vip(chat_id): return chat_id in vip_users

def get_cau_key(session_count):
    pos = (session_count - 3 + 1)
    if pos > len(CAU_TABLE): pos = ((pos - 1) % len(CAU_TABLE)) + 1
    keys = list(CAU_TABLE.keys())
    if 1 <= pos <= len(keys): return keys[pos - 1]
    return None

def make_prediction(chat_id):
    state = user_states[chat_id]
    state["session_count"] += 1
    count = state["session_count"]

    # 1. Ưu tiên MD5 API
    md5 = fetch_md5_prediction()
    if md5:
        pred, conf, src = md5["prediction"], md5["confidence"], "MD5_API"
    else:
        # 2. Xúc xắc
        last_dice = state.get("last_dice")
        if last_dice:
            s_dice = sorted(last_dice)
            d_str = "".join(str(x) for x in s_dice)
            total = sum(s_dice)
            if total in DICE_TABLE and d_str in DICE_TABLE[total]:
                pred, conf = DICE_TABLE[total][d_str]
                src = f"DICE({d_str})"
            else:
                pred, conf, src = random.choice(["TAI", "XIU"]), 50, "RANDOM"
        else:
            # 3. Bảng cầu
            key = get_cau_key(count)
            if key:
                pred, conf = CAU_TABLE[key]
                src = key
            else:
                pred, conf, src = random.choice(["TAI", "XIU"]), 50, "RANDOM"

    if state.get("reverse_mode"):
        pred = "XIU" if pred == "TAI" else "TAI"
        conf = 100 - conf

    return pred, conf, src

# ==========================================
# 🌐 API GAME & WEBSOCKET
# ==========================================
def md5_hash(text): return hashlib.md5(text.encode('utf-8')).hexdigest()

def login_and_get_token(username, password):
    try:
        url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={md5_hash(password)}&cp=R&cl=R&pf=web&at="
        r = requests.get(url, timeout=10).json()
        if not r.get("success"): return {"_error": "Sai thông tin đăng nhập"}
        sk = r["sessionKey"]; sk += "=" * ((4 - len(sk) % 4) % 4)
        nick = json.loads(base64.b64decode(sk).decode('utf-8')).get("nickname")
        r2 = requests.post("https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=", 
            json={"nickName": nick, "accessToken": r["accessToken"]}, timeout=10).json()
        return {"token": r2.get("token"), "nickname": nick, "money": r2.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": str(e)}

def start_websocket(chat_id, token, is_background=False):
    if chat_id in active_sockets and not is_background:
        try: active_sockets[chat_id].disconnect()
        except: pass
    sio = socketio.Client(reconnection=True, reconnection_attempts=5)
    if not is_background:
        active_sockets[chat_id] = sio

    @sio.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        if is_background: return
        state = user_states[chat_id]
        state["session_id"] = data.get('id', 'N/A')
        state["has_bet_this_session"] = False

        pred, conf, src = make_prediction(chat_id)
        state["current_prediction"] = pred
        state["current_bet"] = state["base_bet_amount"] * (2 if state["x2_mode"] and state["win_streak"] >= 1 else 1)

        emo = "🔵 TÀI" if pred == "TAI" else "🔴 XỈU"
        msg = f"🔔 <b>PHIÊN MỚI:</b> <code>#{state['session_id']}</code>\n🔥 <b>DỰ ĐOÁN: {emo}</b> ({conf}%)\n📌 Nguồn: {src}\n"
        if state["auto_bet_enabled"]:
            msg += f"⏳ <i>Chuẩn bị vào: {state['current_bet']:,} Win</i>"
        bot.send_message(chat_id, msg, parse_mode="HTML")

    @sio.on('tick-update', namespace='/txmd5')
    def on_tick_update(data):
        if is_background: return
        state = user_states[chat_id]
        if data.get('state') == 'BETTING' and state["auto_bet_enabled"] and not state["has_bet_this_session"]:
            sio.emit('bet', {"type": state["current_prediction"], "amount": state["current_bet"]}, namespace='/txmd5')
            state["has_bet_this_session"] = True
            state["waiting_for_result"] = True
            bot.send_message(chat_id, f"🚀 <b>ĐÃ VÀO CƯỢC:</b> {state['current_bet']:,}", parse_mode="HTML")

    @sio.on('session-result', namespace='/txmd5')
    def on_session_result(data):
        if is_background: return
        state = user_states[chat_id]
        res = data.get('resultTruyenThong')
        dices = data.get('dices', [])
        if len(dices) == 3: state["last_dice"] = dices
        
        msg = f"🎲 <b>KẾT QUẢ: {'TÀI' if res=='TAI' else 'XỈU'}</b> ({dices})\n"
        if state["waiting_for_result"]:
            if state["current_prediction"] == res:
                win = int(state["current_bet"] * 0.98)
                state["profit_loss"] += win
                state["win_streak"] += 1
                msg += f"✅ <b>THẮNG!</b> +{win:,}\n"
            else:
                state["profit_loss"] -= state["current_bet"]
                state["win_streak"] = 0
                msg += f"❌ <b>THUA!</b>\n"
            state["waiting_for_result"] = False
        bot.send_message(chat_id, msg, parse_mode="HTML")

    try:
        sio.connect('https://wtxmd52.tele68.com', socketio_path='txmd5/', namespaces=['/txmd5'], transports=['websocket'], auth={"token": token})
        sio.wait()
    except:
        if not is_background: bot.send_message(chat_id, "⚠️ Mất kết nối Server Game.")

# ==========================================
# 🤖 LỆNH TELEGRAM
# ==========================================
@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    if message.chat.id not in vip_users:
        return bot.reply_to(message, f"⛔ Bạn cần là VIP. ID: <code>{message.chat.id}</code>", parse_mode="HTML")
    init_user_state(message.chat.id)
    bot.reply_to(message, "🤖 <b>BOT ĐÃ SẴN SÀNG</b>\n\n/login tk mk\n/autobet on 10000\n/x2 on\n/api (Test API)", parse_mode="HTML")

@bot.message_handler(commands=['login'])
def handle_login(message):
    if message.chat.id not in vip_users: return
    parts = message.text.split()
    if len(parts) != 3: return bot.reply_to(message, "👉 /login tk mk")
    m = bot.reply_to(message, "🔄 Đang đăng nhập...")
    res = login_and_get_token(parts[1], parts[2])
    if "_error" in res: return bot.edit_message_text(f"❌ Lỗi: {res['_error']}", message.chat.id, m.message_id)
    
    init_user_state(message.chat.id)
    user_states[message.chat.id].update({"balance": res['money'], "session_count": 0})
    bot.edit_message_text(f"✅ Đăng nhập OK: {res['nickname']}\n💰 {res['money']:,}", message.chat.id, m.message_id)
    threading.Thread(target=start_websocket, args=(message.chat.id, res['token']), daemon=True).start()

@bot.message_handler(commands=['autobet'])
def handle_autobet(message):
    if message.chat.id not in user_states: return
    parts = message.text.split()
    if len(parts) > 1 and parts[1] == "on":
        amt = int(parts[2]) if len(parts) > 2 else 10000
        user_states[message.chat.id]["auto_bet_enabled"] = True
        user_states[message.chat.id]["base_bet_amount"] = amt
        bot.reply_to(message, f"✅ Auto BẬT - Cược: {amt:,}")
    else:
        user_states[message.chat.id]["auto_bet_enabled"] = False
        bot.reply_to(message, "🔴 Auto TẮT")

@bot.message_handler(commands=['api'])
def check_api(message):
    m = bot.reply_to(message, "🔄 Đang test API Le Minh...")
    res = fetch_md5_prediction()
    if res:
        bot.edit_message_text(f"🟢 API ONLINE\nDự đoán: {res['prediction']}", message.chat.id, m.message_id)
    else:
        bot.edit_message_text("🔴 API OFFLINE (Do web yêu cầu key)\nBot sẽ tự động dùng Cầu + Xúc Xắc để chạy tiếp!", message.chat.id, m.message_id)

@bot.message_handler(commands=['stats'])
def check_stats(message):
    if message.chat.id not in user_states: return
    s = user_states[message.chat.id]
    bot.reply_to(message, f"📊 Lãi/Lỗ: {s['profit_loss']:,}\n💰 Dư: {s['balance']:,}\n🤖 Auto: {'BẬT' if s['auto_bet_enabled'] else 'TẮT'}\n📌 Phiên: {s['session_count']}")

# ==========================================
# 🚀 MAIN (FIX LỖI 409)
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    # XÓA WEBHOOK CŨ ĐỂ TRÁNH LỖI 409
    try:
        bot.remove_webhook()
        time.sleep(1)
    except:
        pass

    print("🚀 BOT ĐANG KHỞI ĐỘNG...")
    # skip_pending=True là chìa khóa để không bị lỗi 409 khi deploy lại
    bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)

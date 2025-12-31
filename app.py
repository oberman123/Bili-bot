import os
import re
import random
import datetime as dt
from datetime import timedelta

from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from tinydb import TinyDB, Query

# ====================================================
# 0) App + Storage (TinyDB on Render)
# ====================================================
app = Flask(__name__)

DATA_DIR = os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "users_data.json")

db = TinyDB(DB_PATH)
User = Query()

# ====================================================
# I) Keys
# ====================================================
KEY_STAGE = "stage"
KEY_MOM_NAME = "mom_name"

KEY_BABY_SEX = "baby_sex"          # 'm' / 'f'
KEY_BABY_NAME = "baby_name"
KEY_DOB = "dob"                    # YYYY-MM-DD

KEY_FEEDING_MODE = "feeding_mode"  # 'breast'/'bottle'/'mixed'/'pumping'
KEY_PARTNER_PHONE = "partner_phone"

KEY_EVENTS = "events"
KEY_SLEEP_START = "sleep_start_time"   # ISO
KEY_PENDING = "pending_action"         # dict context for next numeric reply

# Breastfeeding timer
KEY_BF_TIMER = "bf_timer"              # {"start_iso": "...", "side": "ימין"/"שמאל"/None}

# milestone logic (לא שרירותי)
KEY_MILESTONE_STATE = "milestone_state"  # {date: {"count": int, "last_count": int}}

# ====================================================
# II) RTL / Time / Utils
# ====================================================
RLM = "\u200F"  # Right-to-left mark

def rtl(text: str) -> str:
    return RLM + text

def get_now_tz() -> dt.datetime:
    # היתכנות: UTC+2
    return dt.datetime.utcnow() + timedelta(hours=2)

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

def parse_hhmm(text: str):
    m = re.search(r"\b([01]\d|2[0-3]):([0-5]\d)\b", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))

def validate_and_format_dob(dob_str: str):
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            d = dt.datetime.strptime(dob_str.strip(), fmt).date()
            today = get_now_tz().date()
            if d > today or d < today - timedelta(days=1100):
                return None
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def baby_pronouns(user):
    sex = user.get(KEY_BABY_SEX, "m")
    if sex == "f":
        return {"awake_word": "ערה", "ate_word": "אכלה"}
    return {"awake_word": "ער", "ate_word": "אכל"}

def get_user(uid_norm: str):
    user = db.get(User.id == uid_norm)
    if not user:
        user = db.get(User[KEY_PARTNER_PHONE] == uid_norm)
    return user

def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(max(0, delta.total_seconds()))
    hours, minutes = divmod(total_seconds // 60, 60)
    if hours > 0:
        h_str = f"{hours} שעות" if hours > 1 else "שעה"
        m_str = f" ו-{minutes} דקות" if minutes > 0 else ""
        return f"לפני {h_str}{m_str}"
    return f"לפני {minutes} דקות"

# ====================================================
# III) Help Topics (כולל סעיף 5)
# ====================================================
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
        "keywords": ["חלב", "טיפול", "אחסון", "שאוב", "הקפאה", "מקרר", "צידנית", "הפשרה"],
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
        "keywords": ["הנקה", "תפיסה", "בליעה", "כאב", "פטמה", "צד"],
        "text": (
            "דברים חשובים לשים לב בהנקה 🤱\n"
            "• לשים לב לבליעה (ולא רק מציצה).\n"
            "• כאב מתמשך לא אמור להיות \"רגיל\".\n"
            "• אם יש חשש ללשון קשורה/תפיסה – שווה בדיקה מקצועית.\n"
        ),
    },

    "3": {
        "keywords": ["אזהרה", "נורות", "חום", "אודם", "דלקת", "פחות", "חיתולים", "ישנוניות"],
        "text": (
            "נורות אזהרה 🚨\n"
            "• חום גבוה.\n"
            "• אודם/כאב משמעותי בשד.\n"
            "• ירידה חדה בכמות חיתולים רטובים.\n"
            "• ישנוניות קיצונית / תינוק/ת שלא מתעורר/ת כרגיל.\n"
            "בכל חשש – לפנות לגורם רפואי."
        ),
    },

    "4": {
        "keywords": ["טיפים", "המלצות", "שתייה", "מים", "מנוחה", "תזונה"],
        "text": (
            "המלצות כלליות להנקה 💧\n"
            "• להחליף צדדים לפי הצורך.\n"
            "• לשתות, לאכול ולנוח כשאפשר.\n"
            "• אם משהו מרגיש לא תקין – לבדוק, לא להישאר לבד עם זה."
        ),
    },

    "5": {
        "keywords": ["איך", "משתמשים", "שימוש", "פקודות", "תיעוד", "עזרה"],
        "text": (
            "איך משתמשים בי 🌱\n\n"
            "תיעוד:\n"
            "• הנקה: \"ימין\" / \"שמאל\" (אפשר גם עם דקות: \"ימין 10\")\n"
            "• טיימר הנקה: \"התחל הנקה\" ואז \"סיים הנקה\" (אפשר גם עם צד)\n"
            "• בקבוק: \"בקבוק 120\"\n"
            "• שאיבה: \"שאיבה 200\"\n"
            "• חיתול: \"פיפי\" / \"קקי\" / \"חיתול מלא\"\n"
            "• שינה: \"הלך לישון\" / \"התעורר\" (אפשר גם עם שעה)\n\n"
            "דוחות:\n"
            "• \"סטטוס\" – סיכום מהיום\n"
            "• \"סיכום 12\" – סיכום 12 שעות אחרונות\n"
            "• \"השוואה שבוע\" / \"השוואה 7\" – דוח שבוע\n"
            "• \"השוואה 3\" – דוח 3 ימים\n\n"
            "ניהול:\n"
            "• \"מחק\" – מוחק את הרישום האחרון\n"
        ),
    },
}

LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי._"

# ====================================================
# IV) Events
# ====================================================
def add_event(user_id, event_type, details, timestamp=None):
    uid = normalize_phone(user_id)
    user = get_user(uid)
    if not user:
        return None

    ts = timestamp or get_now_tz().strftime("%Y-%m-%d %H:%M:%S")
    event = {"type": event_type, "timestamp": ts, "details": details or {}}

    if not isinstance(user.get(KEY_EVENTS), list):
        user[KEY_EVENTS] = []
    user[KEY_EVENTS].append(event)

    db.upsert(user, User.id == user["id"])
    return event

def get_last_event_by_types(user, types):
    events = user.get(KEY_EVENTS, [])
    filtered = [e for e in events if e.get("type") in types]
    if not filtered:
        return None
    return sorted(filtered, key=lambda x: x.get("timestamp", ""))[-1]

def get_last_wake_time(user):
    events = user.get(KEY_EVENTS, [])
    wakes = []
    for e in events:
        if e.get("type") == "sleep":
            end_ts = e.get("details", {}).get("end_ts")
            if end_ts:
                try:
                    wakes.append(dt.datetime.strptime(end_ts, "%Y-%m-%d %H:%M:%S"))
                except:
                    pass
    if not wakes:
        return None
    return sorted(wakes)[-1]

def iter_recent_events(events, cutoff_dt):
    for e in reversed(events or []):
        try:
            e_dt = dt.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
            if e_dt < cutoff_dt:
                break
            yield e
        except:
            continue

# ====================================================
# V) Reports
# ====================================================
def get_summary(user, hours=None):
    events = user.get(KEY_EVENTS, [])
    now = get_now_tz()

    if hours is None:
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "מהיום"
    else:
        cutoff = now - timedelta(hours=hours)
        label = f"ב-{hours} השעות האחרונות"

    relevant = list(iter_recent_events(events, cutoff))
    if not relevant:
        return f"לא מצאתי אירועים {label}."

    bottles = sum(to_int(e.get("details", {}).get("amount_ml", 0)) for e in relevant if e.get("type") == "bottle")
    pumps = sum(to_int(e.get("details", {}).get("amount_ml", 0)) for e in relevant if e.get("type") == "pumping")
    breasts = sum(1 for e in relevant if e.get("type") == "breastfeeding")
    diapers = sum(1 for e in relevant if e.get("type") == "diaper")

    sleep_starts = sum(1 for e in relevant if e.get("type") == "sleep" and e.get("details", {}).get("start_ts"))
    sleep_ends = sum(1 for e in relevant if e.get("type") == "sleep" and e.get("details", {}).get("end_ts"))

    baby_name = user.get(KEY_BABY_NAME) or "הבייבי"
    p = baby_pronouns(user)

    res = f"📌 סטטוס {baby_name}:\n\n"
    res += f"🤱 הנקות: {breasts}\n"
    if bottles > 0:
        res += f"🍼 בקבוקים: {bottles} מ״ל\n"
    if pumps > 0:
        res += f"🍼 שאיבות: {pumps} מ״ל\n"
    res += f"🧷 חיתולים: {diapers}\n"
    res += f"😴 הירדמויות: {sleep_starts} | יקיצות: {sleep_ends}\n"

    hints = []
    last_feed = get_last_event_by_types(user, ["bottle", "breastfeeding", "pumping"])
    if last_feed:
        ts = dt.datetime.strptime(last_feed["timestamp"], "%Y-%m-%d %H:%M:%S")
        hints.append(f"⏱️ עברו {format_timedelta(now - ts).replace('לפני ', '')} מאז האכלה")
    last_diaper = get_last_event_by_types(user, ["diaper"])
    if last_diaper:
        ts = dt.datetime.strptime(last_diaper["timestamp"], "%Y-%m-%d %H:%M:%S")
        hints.append(f"⏱️ עברו {format_timedelta(now - ts).replace('לפני ', '')} מאז חיתול")
    last_wake = get_last_wake_time(user)
    if last_wake:
        hints.append(f"⏱️ {baby_name} {p['awake_word']} כבר {format_timedelta(now - last_wake).replace('לפני ', '')}")

    if hints:
        res += "\n" + "\n".join(hints)

    res += "\n\nאפשר גם לבקש: 'השוואה שבוע' / 'השוואה 7' / 'השוואה 3'."

    return res.strip()

def daily_totals(user, days_back: int):
    events = user.get(KEY_EVENTS, [])
    now = get_now_tz()
    start_date = (now - timedelta(days=days_back - 1)).date()
    end_date = now.date()

    totals = {}
    d = start_date
    while d <= end_date:
        totals[d.strftime("%Y-%m-%d")] = {"breast": 0, "bottle_ml": 0, "pump_ml": 0, "diaper": 0}
        d += timedelta(days=1)

    for e in events:
        try:
            ts = dt.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
        except:
            continue
        if ts.date() < start_date or ts.date() > end_date:
            continue
        k = ts.date().strftime("%Y-%m-%d")
        if e["type"] == "breastfeeding":
            totals[k]["breast"] += 1
        elif e["type"] == "bottle":
            totals[k]["bottle_ml"] += to_int(e.get("details", {}).get("amount_ml", 0))
        elif e["type"] == "pumping":
            totals[k]["pump_ml"] += to_int(e.get("details", {}).get("amount_ml", 0))
        elif e["type"] == "diaper":
            totals[k]["diaper"] += 1

    return totals

def get_comparison_report(user, days: int):
    totals = daily_totals(user, days_back=days)
    baby = user.get(KEY_BABY_NAME) or "הבייבי"
    res = f"📊 דוח {days} ימים אחרונים עבור {baby}:\n\n"
    for day in sorted(totals.keys()):
        t = totals[day]
        line = f"{day[-5:]} | 🤱{t['breast']} | 🍼{t['bottle_ml']}ml"
        if t["pump_ml"] > 0:
            line += f" | שאיבה {t['pump_ml']}ml"
        line += f" | 🧷{t['diaper']}"
        res += line + "\n"
    return res.strip()

# ====================================================
# VI) Encouragement (רנדום + מינימום מרחק)
# ====================================================
ENCOURAGEMENT_POOL = [
    "מדהים ❤️",
    "כל הכבוד לך 💪",
    "את עושה עבודה מעולה ✨",
    "איזה ניהול מדויק 👏",
    "את אלופה ❤️",
]
def maybe_encourage(user):
    now_date = get_now_tz().strftime("%Y-%m-%d")
    state = user.get(KEY_MILESTONE_STATE, {})
    day_state = state.get(now_date, {"count": 0, "last_count": 0})

    day_state["count"] = int(day_state.get("count", 0)) + 1
    can = (day_state["count"] - int(day_state.get("last_count", 0))) >= 2
    do = can and (random.random() < 0.30)

    msg = None
    if do:
        day_state["last_count"] = day_state["count"]
        msg = random.choice(ENCOURAGEMENT_POOL)

    state[now_date] = day_state
    user[KEY_MILESTONE_STATE] = state
    db.upsert(user, User.id == user["id"])
    return msg

# ====================================================
# VII) Parsing (multi-actions + טיימר הנקה)
# ====================================================
def split_actions(msg_raw: str):
    parts = []
    for line in (msg_raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        sub = [p.strip() for p in line.split(",") if p.strip()]
        parts.extend(sub)
    return parts if parts else [(msg_raw or "").strip()]

def is_numeric_only(s: str) -> bool:
    return bool(re.fullmatch(r"\d{1,4}", s.strip()))

def parse_action(text: str, user):
    original = text.strip()
    msg = re.sub(r"[^\w\s\u0590-\u05FF:]", "", original.lower()).strip()

    # pending numeric answer
    pending = user.get(KEY_PENDING)
    if pending and is_numeric_only(msg):
        val = to_int(msg)
        ptype = pending.get("type")
        user[KEY_PENDING] = None
        db.upsert(user, User.id == user["id"])

        if ptype == "bottle":
            return {"type": "bottle", "amount": val}
        if ptype == "pumping":
            return {"type": "pumping", "amount": val}
        if ptype == "breastfeeding":
            return {"type": "breastfeeding", "side": pending.get("side"), "duration": val}

    # help
    if msg in ["עזרה", "help", "תפריט", "menu"]:
        return {"type": "help_menu"}
    if msg in ["1", "2", "3", "4", "5"]:
        return {"type": "help_item", "id": msg}
    for tid, content in HELP_TOPICS.items():
        if isinstance(content, dict):
            kws = content.get("keywords", [])
            if any(kw in msg for kw in kws):
                return {"type": "help_item", "id": tid}

    # undo
    if any(w in msg for w in ["מחק", "בטל", "טעות", "undo"]):
        return {"type": "undo"}

    # reports
    if "סטטוס" in msg or "מצב" in msg:
        return {"type": "status"}
    if "סיכום" in msg:
        m = re.search(r"\b(\d{1,2})\b", msg)
        h = int(m.group(1)) if m else None
        return {"type": "summary", "hours": h}
    if "השוואה" in msg or "דוח" in msg:
        if "שבוע" in msg:
            return {"type": "comparison", "days": 7}
        m = re.search(r"\b(\d{1,2})\b", msg)
        days = int(m.group(1)) if m else 7
        days = max(2, min(days, 14))
        return {"type": "comparison", "days": days}

    # breastfeeding timer start/stop
    if any(w in msg for w in ["התחל הנקה", "התחילי הנקה", "התחלה הנקה", "start nursing", "start breastfeeding"]):
        side = "ימין" if "ימין" in msg else "שמאל" if "שמאל" in msg else None
        return {"type": "bf_timer_start", "side": side}

    if any(w in msg for w in ["סיים הנקה", "סיימתי הנקה", "סיום הנקה", "stop nursing", "stop breastfeeding"]):
        return {"type": "bf_timer_stop"}

    # queries "מתי"
    if "מתי" in msg:
        if any(w in msg for w in ["אכל", "אכלה", "האכלה", "בקבוק", "הנקה", "שאיבה"]):
            return {"type": "query_last", "targets": ["bottle", "breastfeeding", "pumping"], "label": "האכלה"}
        if any(w in msg for w in ["חיתול", "החלפנו", "קקי", "פיפי"]):
            return {"type": "query_last", "targets": ["diaper"], "label": "החיתול"}
        if any(w in msg for w in ["התעורר", "יקיצה", "קם", "קמה"]):
            hhmm = parse_hhmm(original)
            return {"type": "query_wake", "hhmm": hhmm}

    if any(w in msg for w in ["כמה זמן ער", "חלון ערות", "זמן ערות"]):
        hhmm = parse_hhmm(original)
        return {"type": "query_awake", "hhmm": hhmm}

    # sleep
    if any(w in msg for w in ["הלך לישון", "נרדם", "נרדמה"]):
        hhmm = parse_hhmm(original)
        return {"type": "sleep_start", "hhmm": hhmm}
    if any(w in msg for w in ["התעורר", "קם", "קמה"]):
        hhmm = parse_hhmm(original)
        return {"type": "sleep_end", "hhmm": hhmm}

    # diaper
    if any(w in msg for w in ["קקי", "פיפי", "חיתול"]):
        dtype = "קקי" if "קקי" in msg else "פיפי" if "פיפי" in msg else "חיתול מלא" if "מלא" in msg else "החלפה"
        return {"type": "diaper", "diaper_type": dtype}

    # pumping
    if any(w in msg for w in ["שאיבה", "שאבתי", "שואבת"]):
        m = re.search(r"\b(\d{1,4})\b", msg)
        amt = int(m.group(1)) if m else 0
        return {"type": "pumping", "amount": amt}

    # bottle
    if "בקבוק" in msg:
        m = re.search(r"\b(\d{1,4})\b", msg)
        amt = int(m.group(1)) if m else 0
        return {"type": "bottle", "amount": amt}

    # breastfeeding (duration optional)
    if any(w in msg for w in ["ימין", "שמאל", "הנקה", "ינק", "ינקה"]):
        side = "ימין" if "ימין" in msg else "שמאל" if "שמאל" in msg else None
        m = re.search(r"\b(\d{1,3})\b", msg)
        dur = int(m.group(1)) if m else 0
        return {"type": "breastfeeding", "side": side, "duration": dur}

    # numeric-only => ask what it is
    if is_numeric_only(msg):
        user[KEY_PENDING] = {"type": "ambiguous_number"}
        db.upsert(user, User.id == user["id"])
        return {"type": "ask_number_context", "number": to_int(msg)}

    return {"type": "unknown", "raw": original}

# ====================================================
# VIII) Business Logic
# ====================================================
def handle_action(uid, action, user):
    baby = user.get(KEY_BABY_NAME) or "הבייבי"
    p = baby_pronouns(user)
    t = action.get("type")

    # undo
    if t == "undo":
        if user.get(KEY_PENDING):
            user[KEY_PENDING] = None
            db.upsert(user, User.id == user["id"])
            return ["בוטל. ✅"]
        events = user.get(KEY_EVENTS, [])
        if events:
            events.pop()
            user[KEY_EVENTS] = events
            db.upsert(user, User.id == user["id"])
            return ["נמחק. ✅"]
        return ["אין מה למחוק."]

    # help
    if t == "help_menu":
        return [HELP_TOPICS["menu"]]
    if t == "help_item":
        item = HELP_TOPICS.get(action["id"])
        if isinstance(item, dict):
            return [item["text"] + LEGAL_DISCLAIMER]
        return [HELP_TOPICS["menu"]]

    # ask number context
    if t == "ask_number_context":
        n = action.get("number", 0)
        return [f"{n} זה מה? כתבי: בקבוק / שאיבה / הנקה"]

    # reports
    if t == "status":
        return [get_summary(user, hours=None)]
    if t == "summary":
        return [get_summary(user, hours=action.get("hours"))]
    if t == "comparison":
        return [get_comparison_report(user, days=action.get("days", 7))]

    # query last
    if t == "query_last":
        last = get_last_event_by_types(user, action.get("targets", []))
        if not last:
            return [f"לא מצאתי תיעוד של {action.get('label','זה')}."]

        ts = dt.datetime.strptime(last["timestamp"], "%Y-%m-%d %H:%M:%S")
        diff = format_timedelta(get_now_tz() - ts).replace("לפני ", "")
        return [f"{action.get('label','הפעולה')} האחרונה הייתה לפני {diff} ({ts.strftime('%H:%M')})."]

    # query wake / awake
    if t == "query_wake":
        hhmm = action.get("hhmm")
        now = get_now_tz()
        if hhmm:
            hh, mm = hhmm
            ts = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if ts > now:
                ts -= timedelta(days=1)
            diff = format_timedelta(now - ts).replace("לפני ", "")
            return [f"{baby} {p['awake_word']} כבר {diff}."]

        last_wake = get_last_wake_time(user)
        if not last_wake:
            return ["אין לי תיעוד של יקיצה."]
        diff = format_timedelta(now - last_wake).replace("לפני ", "")
        return [f"{baby} {p['awake_word']} כבר {diff}."]

    if t == "query_awake":
        hhmm = action.get("hhmm")
        now = get_now_tz()
        if hhmm:
            hh, mm = hhmm
            ts = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if ts > now:
                ts -= timedelta(days=1)
            diff = format_timedelta(now - ts).replace("לפני ", "")
            return [f"{baby} {p['awake_word']} כבר {diff}."]

        last_wake = get_last_wake_time(user)
        if not last_wake:
            return ["אין לי תיעוד של יקיצה."]
        diff = format_timedelta(now - last_wake).replace("לפני ", "")
        return [f"{baby} {p['awake_word']} כבר {diff}."]

    # breastfeeding timer start
    if t == "bf_timer_start":
        now = get_now_tz()
        side = action.get("side")
        user[KEY_BF_TIMER] = {"start_iso": now.isoformat(), "side": side}
        db.upsert(user, User.id == user["id"])
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    # breastfeeding timer stop
    if t == "bf_timer_stop":
        timer = user.get(KEY_BF_TIMER)
        if not timer or not timer.get("start_iso"):
            return ["אין טיימר הנקה פעיל."]
        try:
            start_dt = dt.datetime.fromisoformat(timer["start_iso"])
        except:
            user[KEY_BF_TIMER] = None
            db.upsert(user, User.id == user["id"])
            return ["אין טיימר הנקה פעיל."]

        end_dt = get_now_tz()
        mins = int((end_dt - start_dt).total_seconds() / 60)
        mins = max(1, mins)  # מינימום 1 דקה כדי לא לרשום 0

        details = {"duration_min": mins}
        if timer.get("side"):
            details["side"] = timer["side"]

        add_event(uid, "breastfeeding", details)
        user[KEY_BF_TIMER] = None
        db.upsert(user, User.id == user["id"])
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    # bottle
    if t == "bottle":
        amt = int(action.get("amount", 0))
        if amt <= 0:
            user[KEY_PENDING] = {"type": "bottle"}
            db.upsert(user, User.id == user["id"])
            return [f"כמה מ״ל {baby} {p['ate_word']}?"]
        add_event(uid, "bottle", {"amount_ml": amt})
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    # pumping
    if t == "pumping":
        amt = int(action.get("amount", 0))
        if amt <= 0:
            user[KEY_PENDING] = {"type": "pumping"}
            db.upsert(user, User.id == user["id"])
            return ["כמה מ״ל נשאב?"]
        add_event(uid, "pumping", {"amount_ml": amt})
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    # breastfeeding (duration optional)
    if t == "breastfeeding":
        side = action.get("side")
        dur = int(action.get("duration", 0))
        details = {}
        if side:
            details["side"] = side
        if dur > 0:
            details["duration_min"] = dur
        add_event(uid, "breastfeeding", details)
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    # diaper
    if t == "diaper":
        dtype = action.get("diaper_type", "החלפה")
        add_event(uid, "diaper", {"type": dtype})
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    # sleep start / end (עם שעה)
    if t == "sleep_start":
        now = get_now_tz()
        hhmm = action.get("hhmm")
        if hhmm:
            hh, mm = hhmm
            start_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            # אם השעה עתידית ביחס לעכשיו -> כנראה התכוונה ליום קודם
            if start_dt > now:
                start_dt -= timedelta(days=1)
        else:
            start_dt = now

        # אם כבר יש התחלת שינה פתוחה — נדרוס/נעדכן להתחלה הזו
        user[KEY_SLEEP_START] = start_dt.isoformat()
        db.upsert(user, User.id == user["id"])
        add_event(uid, "sleep", {"start_ts": start_dt.strftime("%Y-%m-%d %H:%M:%S")})
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    if t == "sleep_end":
        now = get_now_tz()
        hhmm = action.get("hhmm")
        if hhmm:
            hh, mm = hhmm
            end_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if end_dt > now:
                end_dt -= timedelta(days=1)
        else:
            end_dt = now

        start_str = user.get(KEY_SLEEP_START)
        start_dt = None
        if start_str:
            try:
                start_dt = dt.datetime.fromisoformat(start_str)
            except:
                start_dt = None

        user[KEY_SLEEP_START] = None
        db.upsert(user, User.id == user["id"])

        details = {"end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")}
        if start_dt and end_dt >= start_dt:
            details["start_ts"] = start_dt.strftime("%Y-%m-%d %H:%M:%S")
            details["duration_min"] = int((end_dt - start_dt).total_seconds() / 60)

        add_event(uid, "sleep", details)
        msg = "נרשם. ✅"
        e = maybe_encourage(user)
        return [msg] + ([e] if e else [])

    return ["לא הבנתי. נסי: 'סטטוס' / 'עזרה' / 'בקבוק 120' / 'ימין' / 'התחל הנקה' / 'השוואה שבוע'"]

# ====================================================
# IX) Registration flow
# ====================================================
def registration_prompt(stage, user):
    if stage == 1:
        return (
            "היי! 👋 אני בילי...\n"
            "אני פה כדי לעזור לך לתעד ולהקל עלייך בחודשים הראשונים! 🤱\n\n"
            "את אלופה! ❤️ כדי שנתחיל - איך קוראים לך?"
        )
    if stage == 2:
        mom = user.get(KEY_MOM_NAME, "")
        return f"נעים מאוד {mom} 😊\nמה מין היילוד?\n1) בן\n2) בת"
    if stage == 3:
        return "איך קוראים ליילוד/ה? (שם פרטי)"
    if stage == 4:
        return "ומה תאריך הלידה? (DD/MM/YYYY)\nאפשר למשל: 01/01/2025"
    if stage == 5:
        return (
            "איך צורת ההאכלה כרגע?\n"
            "1) הנקה\n"
            "2) בקבוק\n"
            "3) משולב\n"
            "4) בעיקר שאיבה"
        )
    if stage == 6:
        return (
            "מעולה ❤️ סיימנו רישום.\n\n"
            "אפשר לתעד:\n"
            "• הנקה: \"ימין\" / \"שמאל\" (אופציונלי גם דקות: \"ימין 10\")\n"
            "• טיימר הנקה: \"התחל הנקה\" ואז \"סיים הנקה\" (אפשר גם עם צד)\n"
            "• בקבוק: \"בקבוק 120\"\n"
            "• שאיבה: \"שאיבה 200\"\n"
            "• חיתול: \"פיפי\" / \"קקי\" / \"חיתול מלא\"\n"
            "• שינה: \"הלך לישון\" / \"התעורר\" (אפשר גם עם שעה)\n\n"
            "לדוחות:\n"
            "• \"סטטוס\" (מהיום)\n"
            "• \"השוואה שבוע\"\n"
            "• \"עזרה\"\n"
        )
    return "."

# ====================================================
# X) Webhook
# ====================================================
@app.route("/sms", methods=["POST"])
def whatsapp_webhook():
    msg_raw = (request.values.get("Body", "") or "").strip()
    from_raw = request.values.get("From", "") or ""
    uid = normalize_phone(from_raw)

    user = get_user(uid)
    resp = MessagingResponse()

    # New user
    if not user:
        user = {"id": uid, KEY_STAGE: 1, KEY_EVENTS: []}
        db.insert(user)
        resp.message(rtl(registration_prompt(1, user)))
        return str(resp)

    stage = int(user.get(KEY_STAGE, 6))

    # Registration steps
    if stage == 1:
        user[KEY_MOM_NAME] = msg_raw.strip()
        user[KEY_STAGE] = 2
        db.upsert(user, User.id == user["id"])
        resp.message(rtl(registration_prompt(2, user)))
        return str(resp)

    if stage == 2:
        choice = msg_raw.strip()
        if choice in ["1", "בן", "זכר", "boy"]:
            user[KEY_BABY_SEX] = "m"
        elif choice in ["2", "בת", "נקבה", "girl"]:
            user[KEY_BABY_SEX] = "f"
        else:
            resp.message(rtl("לא הבנתי 🙏 כתבי 1 (בן) או 2 (בת)."))
            return str(resp)

        user[KEY_STAGE] = 3
        db.upsert(user, User.id == user["id"])
        resp.message(rtl(registration_prompt(3, user)))
        return str(resp)

    if stage == 3:
        user[KEY_BABY_NAME] = msg_raw.strip()
        user[KEY_STAGE] = 4
        db.upsert(user, User.id == user["id"])
        resp.message(rtl(registration_prompt(4, user)))
        return str(resp)

    if stage == 4:
        dob = validate_and_format_dob(msg_raw)
        if not dob:
            resp.message(rtl("התאריך לא נראה תקין. נסי למשל: 01/01/2025"))
            return str(resp)
        user[KEY_DOB] = dob
        user[KEY_STAGE] = 5
        db.upsert(user, User.id == user["id"])
        resp.message(rtl(registration_prompt(5, user)))
        return str(resp)

    if stage == 5:
        choice = msg_raw.strip()
        mapping = {"1": "breast", "2": "bottle", "3": "mixed", "4": "pumping"}
        if choice not in mapping:
            resp.message(rtl("לא הבנתי 🙏 כתבי 1/2/3/4."))
            return str(resp)
        user[KEY_FEEDING_MODE] = mapping[choice]
        user[KEY_STAGE] = 6
        db.upsert(user, User.id == user["id"])
        add_event(uid, "feeding_mode", {"mode": user[KEY_FEEDING_MODE]})
        resp.message(rtl(registration_prompt(6, user)))
        return str(resp)

    # Normal operation
    replies = []
    parts = split_actions(msg_raw)

    for part in parts:
        action = parse_action(part, user)
        msgs = handle_action(uid, action, user)
        for m in msgs:
            replies.append(rtl(m))

    for r in replies:
        resp.message(r)

    return str(resp)

@app.route("/", methods=["GET", "HEAD"])
def root():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

# app.py
# WhatsApp Baby Tracker Bot (Twilio + Flask + TinyDB) — MVP for Render
# - Registration flow: mom name -> baby name -> baby gender -> DOB
# - Logging: breastfeeding (multi-line supported), bottle, pumping, diaper, sleep start/end/manual
# - Queries: status, summary, when last, awake time, undo, help
# - Smart insights: "X hours since last feed/diaper/awake" WITHOUT scheduled messages (Twilio-compatible)
# - Render-ready port: uses PORT env var

import datetime as dt
import os
import re
from datetime import timedelta
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from tinydb import TinyDB, Query

# ====================================================
# I. App + DB
# ====================================================
app = Flask(__name__)
db = TinyDB("users_data.json")
User = Query()

# ====================================================
# II. Keys / Constants
# ====================================================
KEY_STAGE = "stage"

KEY_MOM_NAME = "mom_name"

KEY_BABY_NAME = "baby_name"
KEY_BABY_GENDER = "baby_gender"  # "male" / "female"
KEY_DOB = "dob"                  # YYYY-MM-DD

KEY_EVENTS = "events"            # list of events
KEY_PENDING = "pending_action"   # dict for follow-ups
KEY_SLEEP_START = "sleep_start_time"  # ISO str
KEY_PARTNER_PHONE = "partner_phone"   # normalized phone
KEY_REMINDERS = "reminders"           # stored-only reminders (no scheduling)

LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי._"

# Encouragement after N actions (in a day)
MILESTONE_TIERS = {
    3: "איזה יופי! כבר 3 תיעודים היום — את לגמרי על זה. 💪",
    4: "מדהים! עקביות זה שם המשחק. 4 פעולות ואת מנצחת את היום! 🏆",
    8: "וואו, את מנהלת את זה בצורה מושלמת. 👏",
    12: "את שיאנית! קחי נשימה עמוקה — עשית עבודה מעולה היום. ❤️",
}
KEY_ENC_TIER = "enc_tier"  # dict: {YYYY-MM-DD: last_tier}

# Help topics (UPDATED milk storage section as requested)
HELP_TOPICS = {
    "menu": (
        "איך אפשר לעזור? 🌱\n\n"
        "בחרי נושא (או כתבי את המספר):\n"
        "1️⃣ טיפול בחלב אם\n"
        "2️⃣ דברים שחשוב לשים לב בהנקה\n"
        "3️⃣ נורות אזהרה\n"
        "4️⃣ המלצות כלליות להנקה\n\n"
        "(אפשר לבחור במילים או במספר)"
    ),
    "1": {
        "keywords": ["חלב", "טיפול", "אחסון", "קפוא", "מקרר", "מקפיא", "צידנית", "הפשרה", "חימום"],
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
        "keywords": ["בליעה", "הנקה", "תפיסה", "שד", "כאב", "פטמה", "מציצה"],
        "text": "בהנקה: שימי לב לבליעה (ולא רק מציצה), ולכך שהשד מתרכך בסיום. אם יש כאב מתמשך — שווה לבדוק תפיסה.",
    },
    "3": {
        "keywords": ["אזהרה", "נורות", "חום", "אודם", "דלקת", "פחות חיתולים"],
        "text": "🚨 נורות אזהרה: חום גבוה, אודם/כאב משמעותי בשד, או פחות מ-6 חיתולים רטובים ביום (אחרי הימים הראשונים).",
    },
    "4": {
        "keywords": ["המלצות", "טיפים", "מים", "שתייה", "צדדים"],
        "text": "טיפים כלליים: החליפי צדדים בהנקות, שתייה מספקת, ומנוחה כשאפשר. 💧",
    },
}

# ====================================================
# III. Time / Normalization Utilities
# ====================================================
def get_now_tz():
    """
    Render servers run in UTC. For Israel local time:
    - This MVP uses fixed UTC+2. (For DST correctness, use zoneinfo in a later iteration.)
    """
    return dt.datetime.utcnow() + timedelta(hours=2)

def get_today_str():
    return get_now_tz().strftime("%Y-%m-%d")

def to_int(val):
    try:
        if isinstance(val, str):
            val = re.sub(r"[^\d]", "", val)
        return int(val)
    except:
        return 0

def normalize_phone(phone_str: str) -> str:
    if not phone_str:
        return ""
    clean = re.sub(r"[^\d]", "", phone_str.replace("whatsapp:", ""))
    if clean.startswith("05"):
        clean = "972" + clean[1:]
    elif clean.startswith("9720"):
        clean = "972" + clean[4:]
    return clean

def format_timedelta(delta: dt.timedelta) -> str:
    total_seconds = max(0, int(delta.total_seconds()))
    hours, minutes = divmod(total_seconds // 60, 60)
    if hours > 0:
        h_str = f"{hours} שעות" if hours > 1 else "שעה"
        m_str = f" ו-{minutes} דקות" if minutes > 0 else ""
        return f"לפני {h_str}{m_str}"
    return f"לפני {minutes} דקות"

def validate_and_format_dob(dob_str: str):
    """
    Accepts: dd/mm/YYYY, dd/mm/YY, YYYY-mm-dd, dd.mm.YYYY, dd.mm.YY
    Returns: YYYY-mm-dd or None
    """
    s = dob_str.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            d = dt.datetime.strptime(s, fmt).date()
            today = get_now_tz().date()
            if d > today:
                return None
            # Baby bot: limit to ~3 years back
            if d < today - timedelta(days=1100):
                return None
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

# ====================================================
# IV. Gender-aware text helpers
# ====================================================
def baby_label(user) -> str:
    return user.get(KEY_BABY_NAME) or "הבייבי"

def baby_pronoun(user) -> str:
    return "הוא" if user.get(KEY_BABY_GENDER) == "male" else "היא"

def baby_child_word(user) -> str:
    return "בן" if user.get(KEY_BABY_GENDER) == "male" else "בת"

def verb_sleep(user) -> str:
    return "ישן" if user.get(KEY_BABY_GENDER) == "male" else "ישנה"

def verb_awake(user) -> str:
    return "ער" if user.get(KEY_BABY_GENDER) == "male" else "ערה"

def calculate_age(dob_str, user=None) -> str:
    if not dob_str:
        return ""
    try:
        birth_date = dt.datetime.strptime(dob_str, "%Y-%m-%d").date()
        diff_days = (get_now_tz().date() - birth_date).days
        g = baby_child_word(user) if user else "בן/בת"
        if diff_days < 30:
            return f"{g} {diff_days} ימים"
        return f"{g} {diff_days // 30} חודשים"
    except:
        return ""

# ====================================================
# V. DB access helpers
# ====================================================
def get_user_by_uid(uid_norm: str):
    return db.get(User.id == uid_norm) or db.get(User[KEY_PARTNER_PHONE] == uid_norm)

def ensure_events_list(user):
    if not isinstance(user.get(KEY_EVENTS), list):
        user[KEY_EVENTS] = []

def add_event(user_id, event_type, details_dict, timestamp=None):
    uid = normalize_phone(user_id)
    user = get_user_by_uid(uid)
    if not user:
        return None

    ts = timestamp or get_now_tz().strftime("%Y-%m-%d %H:%M:%S")
    event = {"type": event_type, "timestamp": ts, "details": details_dict or {}}

    ensure_events_list(user)
    user[KEY_EVENTS].append(event)
    db.upsert(user, User.id == user["id"])
    return event

def get_last_event(user, types):
    events = user.get(KEY_EVENTS, []) or []
    for e in reversed(events):
        if e.get("type") in types:
            return e
    return None

# ====================================================
# VI. Human formatting + summaries
# ====================================================
def format_event_human(event):
    etype = event.get("type")
    d = event.get("details", {}) or {}
    time = (event.get("timestamp") or "")[-8:-3]

    if etype == "breastfeeding":
        dur = d.get("duration")
        dur_txt = f"{dur} דק'" if dur else "ללא משך"
        side = d.get("side", "לא צוין")
        return f"🤱 הנקה מצד {side} ({dur_txt}) ב-{time}"
    if etype == "bottle":
        return f"🍼 בקבוק {d.get('amount', 0)} מ״ל ב-{time}"
    if etype == "pumping":
        amt = d.get("amount", 0)
        side = d.get("side", "לא צוין")
        return f"🧴 שאיבה {amt} מ״ל ({side}) ב-{time}" if amt else f"🧴 שאיבה ({side}) ב-{time}"
    if etype == "diaper":
        return f"🧷 חיתול ({d.get('type', 'החלפה')}) ב-{time}"
    if etype == "sleep":
        if "duration_min" in d:
            return f"😴 שינה של {d['duration_min']} דק' (הסתיימה ב-{time})"
        return f"☀️ יקיצה ב-{time}"
    return f"✨ {etype} ב-{time}"

def iter_recent_events(events, cutoff_dt):
    # Efficient scan from end
    for e in reversed(events or []):
        try:
            e_dt = dt.datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
            if e_dt < cutoff_dt:
                break
            yield e
        except:
            continue

def get_summary(user, hours=None):
    events = user.get(KEY_EVENTS, []) or []
    now = get_now_tz()

    if hours is None:
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "מהיום מחצות"
    else:
        cutoff = now - timedelta(hours=hours)
        label = f"ב-{hours} השעות האחרונות"

    relevant = list(iter_recent_events(events, cutoff))
    if not relevant:
        return f"לא מצאתי אירועים {label}."

    bottles = sum(to_int(e.get("details", {}).get("amount", 0)) for e in relevant if e.get("type") == "bottle")
    pumps = sum(to_int(e.get("details", {}).get("amount", 0)) for e in relevant if e.get("type") == "pumping")
    breasts = len([e for e in relevant if e.get("type") == "breastfeeding"])
    diapers = len([e for e in relevant if e.get("type") == "diaper"])
    sleep_mins = sum(to_int(e.get("details", {}).get("duration_min", 0)) for e in relevant if e.get("type") == "sleep")

    res = f"📊 *סיכום {label} עבור {baby_label(user)}:*\n"
    res += f"🍼 בקבוקים: {bottles} מ״ל\n"
    if pumps > 0:
        res += f"🧴 שאיבות: {pumps} מ״ל\n"
    res += f"🤱 הנקות: {breasts}\n"
    res += f"🧷 חיתולים: {diapers}\n"
    res += f"😴 שינה: {sleep_mins // 60} שע' ו-{sleep_mins % 60} דק'"
    return res

# ====================================================
# VII. Smart insights (no scheduling)
# ====================================================
def smart_insights(user):
    insights = []
    now = get_now_tz()

    # Feed: bottle or breastfeeding
    last_feed = get_last_event(user, ["bottle", "breastfeeding"])
    if last_feed:
        try:
            ts = dt.datetime.strptime(last_feed["timestamp"], "%Y-%m-%d %H:%M:%S")
            mins = int((now - ts).total_seconds() / 60)
            if mins >= 180:
                insights.append(f"💡 עברו בערך {mins//60} שעות מאז ההאכלה האחרונה.")
        except:
            pass

    # Pumping insight (optional)
    last_pump = get_last_event(user, ["pumping"])
    if last_pump:
        try:
            ts = dt.datetime.strptime(last_pump["timestamp"], "%Y-%m-%d %H:%M:%S")
            mins = int((now - ts).total_seconds() / 60)
            if mins >= 240:
                insights.append(f"💡 עברו בערך {mins//60} שעות מאז השאיבה האחרונה.")
        except:
            pass

    # Diaper
    last_diaper = get_last_event(user, ["diaper"])
    if last_diaper:
        try:
            ts = dt.datetime.strptime(last_diaper["timestamp"], "%Y-%m-%d %H:%M:%S")
            mins = int((now - ts).total_seconds() / 60)
            if mins >= 240:
                insights.append(f"💡 עברו בערך {mins//60} שעות מאז החיתול האחרון.")
        except:
            pass

    # Awake time (based on last sleep end_ts)
    last_sleep = get_last_event(user, ["sleep"])
    if last_sleep and last_sleep.get("details", {}).get("end_ts"):
        try:
            ts = dt.datetime.strptime(last_sleep["details"]["end_ts"], "%Y-%m-%d %H:%M:%S")
            mins = int((now - ts).total_seconds() / 60)
            if mins >= 120:
                insights.append(
                    f"💡 {baby_label(user)} {verb_awake(user)} כבר בערך {mins//60} שעות (התעורר/ה ב-{ts.strftime('%H:%M')})."
                )
        except:
            pass

    return insights

# ====================================================
# VIII. Milestone encouragement (after actions)
# ====================================================
def maybe_add_milestone_message(user):
    today = get_today_str()
    events = user.get(KEY_EVENTS, []) or []
    today_count = sum(1 for e in events if (e.get("timestamp", "").startswith(today)))

    tiers = user.get(KEY_ENC_TIER, {}) or {}
    last_t = tiers.get(today, 0)

    # trigger smallest tier not yet triggered
    for t in sorted(MILESTONE_TIERS.keys()):
        if today_count >= t and last_t < t:
            tiers[today] = t
            user[KEY_ENC_TIER] = tiers
            db.upsert(user, User.id == user["id"])
            return MILESTONE_TIERS[t]
    return None

# ====================================================
# IX. NLP / Parsing
# ====================================================
def clean_msg(s: str) -> str:
    # keep hebrew/letters/digits/whitespace/newlines; remove most punctuation/emoji
    return re.sub(r"[^\w\s\u0590-\u05FF\n]", "", (s or "").lower()).strip()

def parse_breastfeeding_multiline(msg_raw: str):
    """
    Supports:
      "ימין 10 דק"
      "ימין 10\nשמאל 10"
      "שמאל 12"
    Returns list[{"side":..., "duration":...}]
    """
    lines = [clean_msg(x) for x in (msg_raw or "").splitlines() if clean_msg(x)]
    items = []
    for line in lines:
        if any(w in line for w in ["ימין", "שמאל"]):
            side = "ימין" if "ימין" in line else "שמאל" if "שמאל" in line else "לא צוין"
            m = re.search(r"(\d+)", line)
            dur = to_int(m.group(1)) if m else 0
            items.append({"side": side, "duration": dur})
    return items

def parse_input(message_raw: str, user):
    msg = clean_msg(message_raw)

    # Help menu selection by number
    if msg in ["1", "2", "3", "4"]:
        return {"type": "help_item", "id": msg}
    if msg in ["עזרה", "help", "menu", "תפריט"]:
        return {"type": "help_menu"}

    # Undo
    if any(w in msg for w in ["בטל", "מחק", "טעות", "undo"]):
        return {"type": "undo"}

    # Status / Summary
    if any(w in msg for w in ["סטטוס", "מצב"]):
        return {"type": "status"}
    if "סיכום" in msg:
        h = to_int(re.search(r"\d+", msg).group(0)) if re.search(r"\d+", msg) else None
        return {"type": "summary", "hours": h}

    # "מתי" queries
    if "מתי" in msg:
        if any(w in msg for w in ["אכל", "אכלה", "בקבוק", "הנקה", "האכלה"]):
            return {"type": "query_last", "targets": ["bottle", "breastfeeding"], "label": "האכילה"}
        if any(w in msg for w in ["שאב", "שאבה", "שאיבה"]):
            return {"type": "query_last", "targets": ["pumping"], "label": "השאיבה"}
        if any(w in msg for w in ["חיתול", "החלפנו", "קקי", "פיפי"]):
            return {"type": "query_last", "targets": ["diaper"], "label": "החיתול"}
        if any(w in msg for w in ["נרדם", "ישן", "שינה"]):
            return {"type": "query_last", "targets": ["sleep"], "sub_type": "start", "label": "השינה"}

    # Awake time
    if any(w in msg for w in ["כמה זמן ער", "חלון ערות", "זמן ערות"]):
        return {"type": "query_awake"}

    # Partner add
    if any(w in msg for w in ["הוסף בן זוג", "הוסיפי בן זוג", "הוסף בןזוג", "הוסיפי בןזוג"]):
        phone = re.search(r"(05\d{8}|9725\d{8})", msg)
        return {"type": "add_partner", "phone": phone.group(0) if phone else None}

    # Pumping
    if any(w in msg for w in ["שאיבה", "שאבתי", "שאבה", "שואבת", "שאוב", "לשאוב"]):
        # try amount
        m = re.search(r"(\d+)", msg)
        amt = to_int(m.group(1)) if m else 0
        side = "שני הצדדים" if "שני" in msg else ("ימין" if "ימין" in msg else ("שמאל" if "שמאל" in msg else "לא צוין"))
        return {"type": "pumping", "amount": amt, "side": side}

    # Breastfeeding (supports multiline)
    if any(w in msg for w in ["הנקה", "ינק", "ימין", "שמאל"]):
        items = parse_breastfeeding_multiline(message_raw)
        if items:
            return {"type": "breastfeeding_multi", "items": items}
        # fallback single
        side = "ימין" if "ימין" in msg else "שמאל" if "שמאל" in msg else "לא צוין"
        m = re.search(r"(\d+)", msg)
        dur = to_int(m.group(1)) if m else 0
        return {"type": "breastfeeding", "side": side, "duration": dur}

    # Bottle
    if "בקבוק" in msg:
        m = re.search(r"(\d+)", msg)
        amt = to_int(m.group(1)) if m else 0
        return {"type": "bottle", "amount": amt}

    # Diaper
    if any(w in msg for w in ["קקי", "פיפי", "חיתול"]):
        if "קקי" in msg and "פיפי" in msg:
            t = "מלא"
        elif "קקי" in msg:
            t = "קקי"
        elif "פיפי" in msg:
            t = "פיפי"
        else:
            t = "החלפה"
        return {"type": "diaper", "diaper_type": t}

    # Sleep
    if any(w in msg for w in ["נרדם", "הלך לישון", "נכנס לישון", "התחיל לישון"]):
        return {"type": "sleep_start"}
    if any(w in msg for w in ["קם", "התעורר", "סיים לישון", "התעוררה"]):
        return {"type": "sleep_end"}
    # manual sleep: "ישן 40" / "ישנה 30 דקות"
    if any(w in msg for w in ["ישן", "ישנה"]) and re.search(r"\d+", msg):
        m = re.search(r"(\d+)", msg)
        return {"type": "sleep_manual", "duration": to_int(m.group(1))}

    # Pending answer numeric (for bottle/breast/pump/manual sleep)
    pending = user.get(KEY_PENDING)
    if pending and msg.isdigit():
        val = to_int(msg)
        if pending["type"] == "bottle":
            return {"type": "bottle", "amount": val, "_from_pending": True}
        if pending["type"] == "breastfeeding":
            return {"type": "breastfeeding", "side": pending.get("side", "לא צוין"), "duration": val, "_from_pending": True}
        if pending["type"] == "pumping":
            return {"type": "pumping", "amount": val, "side": pending.get("side", "לא צוין"), "_from_pending": True}
        if pending["type"] == "sleep_manual":
            return {"type": "sleep_manual", "duration": val, "_from_pending": True}

    return {"type": "unknown"}

# ====================================================
# X. Registration flow messages
# ====================================================
def reg_message_stage_1():
    return (
        "היי! 👋 אני בילי...\n"
        "אני פה כדי לעזור לך לתעד ולהקל עלייך בחודשים הראשונים! 🤱\n\n"
        "את אלופה! ❤️ כדי שנתחיל — איך קוראים לך?"
    )

def reg_message_stage_2(mom_name):
    return f"נעים מאוד {mom_name} 😊\nאיך קוראים לבייבי?"

def reg_message_stage_3(baby_name):
    return (
        f"איזה שם מתוק — {baby_name} 🥰\n"
        "מה מין היילוד?\n"
        "כתבי:\n"
        "1) בן\n"
        "2) בת"
    )

def reg_message_stage_4():
    return (
        "מעולה! ומה תאריך הלידה? 📅\n"
        "אפשר למשל: 01/01/2025"
    )

def after_registration_welcome(user):
    mom = user.get(KEY_MOM_NAME, "")
    baby = baby_label(user)
    return (
        f"{mom} מהממת ❤️ סיימנו הרשמה!\n\n"
        "אני פה כדי לשמור לך על כל המידע החשוב בצורה מסודרת.\n\n"
        "איך מתעדים?\n"
        "🤱 הנקה:\n"
        "• 'ימין 10'\n"
        "• אפשר גם ריבוי שורות:\n"
        "  ימין 10\n"
        "  שמאל 8\n\n"
        "🍼 בקבוק:\n"
        "• 'בקבוק 120'\n\n"
        "🧴 שאיבה:\n"
        "• 'שאיבה 80'\n"
        "• אפשר גם צד: 'שאיבה ימין 60'\n\n"
        "🧷 חיתול:\n"
        "• 'פיפי' / 'קקי' / 'חיתול'\n\n"
        "😴 שינה:\n"
        "• 'נרדם' / 'התעורר'\n\n"
        f"בכל רגע אפשר לכתוב 'סטטוס' ותקבלי תמונת מצב על {baby}.\n"
        "לעזרה: כתבי 'עזרה'."
    )

# ====================================================
# XI. Core handler
# ====================================================
def handle_command(uid, user, parsed):
    replies = []

    # Clear pending by default when a valid command comes (except unknown)
    if parsed["type"] != "unknown":
        user[KEY_PENDING] = None

    baby = baby_label(user)

    # HELP
    if parsed["type"] == "help_menu":
        replies.append(HELP_TOPICS["menu"])
        return replies

    if parsed["type"] == "help_item":
        item = HELP_TOPICS.get(parsed["id"])
        if item and "text" in item:
            replies.append(item["text"] + LEGAL_DISCLAIMER)
        else:
            replies.append("לא מצאתי את הנושא הזה. כתבי 'עזרה' כדי לראות תפריט.")
        return replies

    # UNDO
    if parsed["type"] == "undo":
        if user.get(KEY_PENDING):
            user[KEY_PENDING] = None
            db.upsert(user, User.id == user["id"])
            replies.append("ביטלתי את השאלה האחרונה. 👍")
            return replies

        events = user.get(KEY_EVENTS, []) or []
        if events:
            removed = events.pop()
            user[KEY_EVENTS] = events
            db.upsert(user, User.id == user["id"])
            replies.append(f"ביטלתי את הרישום האחרון: *{format_event_human(removed)}*")
        else:
            replies.append("אין לי מה לבטל.")
        return replies

    # STATUS
    if parsed["type"] == "status":
        age = calculate_age(user.get(KEY_DOB), user=user)
        replies.append(f"📍 סטטוס {baby} ({age})\n")
        replies.append(get_summary(user, hours=None))
        tips = smart_insights(user)
        replies.extend(tips)
        return replies

    # SUMMARY
    if parsed["type"] == "summary":
        replies.append(get_summary(user, hours=parsed.get("hours")))
        tips = smart_insights(user)
        replies.extend(tips)
        return replies

    # QUERY_LAST
    if parsed["type"] == "query_last":
        events = user.get(KEY_EVENTS, []) or []
        targets = parsed["targets"]

        filtered = [e for e in events if e.get("type") in targets]
        if parsed.get("sub_type") == "start":
            filtered = [e for e in filtered if "start_ts" in (e.get("details", {}) or {})]
            key_func = lambda x: (x.get("details", {}) or {}).get("start_ts", x.get("timestamp", ""))
            ts_format = "%Y-%m-%d %H:%M:%S"
            if filtered:
                last = sorted(filtered, key=key_func)[-1]
                ts_str = key_func(last)
                try:
                    ts = dt.datetime.strptime(ts_str, ts_format)
                    replies.append(f"{parsed['label']} האחרונה הייתה {format_timedelta(get_now_tz()-ts)} ({ts.strftime('%H:%M')}).")
                except:
                    replies.append(f"מצאתי תיעוד של {parsed['label']}, אבל לא הצלחתי לפענח את הזמן.")
            else:
                replies.append(f"לא מצאתי תיעוד של {parsed['label']}.")
            return replies

        # default: use event timestamp
        if filtered:
            last = sorted(filtered, key=lambda x: x.get("timestamp", ""))[-1]
            try:
                ts = dt.datetime.strptime(last["timestamp"], "%Y-%m-%d %H:%M:%S")
                replies.append(f"{parsed['label']} האחרונה הייתה {format_timedelta(get_now_tz()-ts)} ({ts.strftime('%H:%M')}).")
            except:
                replies.append(f"מצאתי תיעוד של {parsed['label']}, אבל לא הצלחתי לפענח את הזמן.")
        else:
            replies.append(f"לא מצאתי תיעוד של {parsed['label']}.")
        return replies

    # QUERY_AWAKE
    if parsed["type"] == "query_awake":
        events = user.get(KEY_EVENTS, []) or []
        sleeps = [e for e in events if e.get("type") == "sleep" and (e.get("details", {}) or {}).get("end_ts")]
        if sleeps:
            last_sleep = sorted(sleeps, key=lambda x: (x.get("details", {}) or {}).get("end_ts", ""))[-1]
            try:
                end_dt = dt.datetime.strptime(last_sleep["details"]["end_ts"], "%Y-%m-%d %H:%M:%S")
                diff = format_timedelta(get_now_tz() - end_dt).replace("לפני ", "")
                replies.append(f"{baby} {verb_awake(user)} כבר {diff}. ⏰")
            except:
                replies.append("מצאתי תיעוד שינה, אבל לא הצלחתי לחשב זמן ערות.")
        else:
            replies.append("אין לי תיעוד של יקיצה אחרונה.")
        return replies

    # ADD_PARTNER
    if parsed["type"] == "add_partner":
        if parsed.get("phone"):
            p_uid = normalize_phone(parsed["phone"])
            user[KEY_PARTNER_PHONE] = p_uid
            db.upsert(user, User.id == user["id"])
            replies.append(f"הוספתי בן/בת זוג (מספר: {p_uid}) 🤝")
        else:
            replies.append("לא מצאתי מספר תקין. נסי: 'הוסף בן זוג 0501234567'")
        return replies

    # LOGGING: BOTTLE
    if parsed["type"] == "bottle":
        amt = to_int(parsed.get("amount", 0))
        if amt > 0:
            add_event(uid, "bottle", {"amount": amt})
            replies.append(f"נרשם בקבוק של {amt} מ״ל. 🍼")
        else:
            user[KEY_PENDING] = {"type": "bottle"}
            db.upsert(user, User.id == user["id"])
            replies.append(f"כמה מ״ל {baby} אכל/ה?")
        # encouragement
        user2 = get_user_by_uid(normalize_phone(uid))
        msg = maybe_add_milestone_message(user2) if user2 else None
        if msg:
            replies.append(msg)
        return replies

    # LOGGING: PUMPING
    if parsed["type"] == "pumping":
        amt = to_int(parsed.get("amount", 0))
        side = parsed.get("side", "לא צוין")
        if amt > 0:
            add_event(uid, "pumping", {"amount": amt, "side": side})
            replies.append(f"נרשמה שאיבה של {amt} מ״ל ({side}). 🧴")
        else:
            user[KEY_PENDING] = {"type": "pumping", "side": side}
            db.upsert(user, User.id == user["id"])
            replies.append("כמה מ״ל שאבת?")
        user2 = get_user_by_uid(normalize_phone(uid))
        msg = maybe_add_milestone_message(user2) if user2 else None
        if msg:
            replies.append(msg)
        return replies

    # LOGGING: BREASTFEEDING MULTI
    if parsed["type"] == "breastfeeding_multi":
        items = parsed.get("items", [])
        # if any item missing duration -> ask
        if any(to_int(x.get("duration", 0)) == 0 for x in items):
            user[KEY_PENDING] = {"type": "breastfeeding", "side": items[0].get("side", "לא צוין")}
            db.upsert(user, User.id == user["id"])
            replies.append("כמה דקות הייתה ההנקה?")
            return replies

        for x in items:
            add_event(uid, "breastfeeding", {"side": x.get("side", "לא צוין"), "duration": to_int(x.get("duration", 0))})
        # response like your screenshot style: list each side
        lines = [f"🤱 נרשמה הנקה: {x.get('side','לא צוין')} {to_int(x.get('duration',0))} דק׳ ✅" for x in items]
        replies.extend(lines)

        user2 = get_user_by_uid(normalize_phone(uid))
        msg = maybe_add_milestone_message(user2) if user2 else None
        if msg:
            replies.append(msg)
        return replies

    # LOGGING: BREASTFEEDING SINGLE
    if parsed["type"] == "breastfeeding":
        side = parsed.get("side", "לא צוין")
        dur = to_int(parsed.get("duration", 0))
        if dur > 0:
            add_event(uid, "breastfeeding", {"side": side, "duration": dur})
            replies.append(f"🤱 נרשמה הנקה: {side} {dur} דק׳ ✅")
        else:
            user[KEY_PENDING] = {"type": "breastfeeding", "side": side}
            db.upsert(user, User.id == user["id"])
            replies.append(f"כמה דקות הייתה ההנקה ב-{side}?")
        user2 = get_user_by_uid(normalize_phone(uid))
        msg = maybe_add_milestone_message(user2) if user2 else None
        if msg:
            replies.append(msg)
        return replies

    # LOGGING: DIAPER
    if parsed["type"] == "diaper":
        dtype = parsed.get("diaper_type", "החלפה")
        add_event(uid, "diaper", {"type": dtype})
        replies.append(f"🧷 נרשם חיתול: {dtype} ✅")

        user2 = get_user_by_uid(normalize_phone(uid))
        msg = maybe_add_milestone_message(user2) if user2 else None
        if msg:
            replies.append(msg)
        return replies

    # LOGGING: SLEEP START
    if parsed["type"] == "sleep_start":
        user[KEY_SLEEP_START] = get_now_tz().isoformat()
        db.upsert(user, User.id == user["id"])
        replies.append(f"לילה טוב ל{baby}... 😴")
        return replies

    # LOGGING: SLEEP END
    if parsed["type"] == "sleep_end":
        start_str = user.get(KEY_SLEEP_START)
        end_dt = get_now_tz()
        if start_str:
            try:
                start_dt = dt.datetime.fromisoformat(start_str)
            except:
                start_dt = None

            if start_dt:
                mins = int((end_dt - start_dt).total_seconds() / 60)
                add_event(
                    uid,
                    "sleep",
                    {
                        "duration_min": mins,
                        "start_ts": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
                replies.append(f"בוקר טוב! {baby} {verb_sleep(user)} {mins} דקות. ☀️")
            else:
                add_event(uid, "sleep", {"action": "wake_up", "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})
                replies.append(f"רשמתי ש{baby_pronoun(user)} התעורר/ה עכשיו (לא הצלחתי לקרוא את תחילת השינה).")
        else:
            add_event(uid, "sleep", {"action": "wake_up", "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})
            replies.append(f"רשמתי ש{baby_pronoun(user)} התעורר/ה עכשיו (לא מצאתי מתי נרדם/ה).")

        user[KEY_SLEEP_START] = None
        db.upsert(user, User.id == user["id"])

        user2 = get_user_by_uid(normalize_phone(uid))
        msg = maybe_add_milestone_message(user2) if user2 else None
        if msg:
            replies.append(msg)

        return replies

    # LOGGING: SLEEP MANUAL
    if parsed["type"] == "sleep_manual":
        mins = to_int(parsed.get("duration", 0))
        if mins > 0:
            add_event(uid, "sleep", {"duration_min": mins})
            replies.append(f"😴 נרשמה שינה של {mins} דקות ✅")
            user2 = get_user_by_uid(normalize_phone(uid))
            msg = maybe_add_milestone_message(user2) if user2 else None
            if msg:
                replies.append(msg)
        else:
            user[KEY_PENDING] = {"type": "sleep_manual"}
            db.upsert(user, User.id == user["id"])
            replies.append("כמה דקות הייתה השינה?")
        return replies

    # Unknown
    replies.append("לא בטוחה שהבנתי... 🧐 נסי: 'ימין 10', 'בקבוק 120', 'שאיבה 80', 'פיפי', 'סטטוס', 'סיכום', או 'עזרה'.")
    return replies

# ====================================================
# XII. Webhook
# ====================================================
@app.route("/sms", methods=["POST"])
def whatsapp_webhook():
    msg_raw = request.values.get("Body", "").strip()
    from_raw = request.values.get("From", "")
    uid = normalize_phone(from_raw)
    resp = MessagingResponse()

    # Fetch user
    user = get_user_by_uid(uid)

    # Reset
    if msg_raw.lower() in ["אפס", "reset"]:
        if user:
            db.remove(User.id == user["id"])
        resp.message("איתחלנו! שלחי הודעה כלשהי כדי להתחיל מחדש. ❤️")
        return str(resp)

    # New user: stage 1 (ask mom name)
    if not user:
        db.insert({"id": uid, KEY_STAGE: 1})
        resp.message(reg_message_stage_1())
        return str(resp)

    stage = user.get(KEY_STAGE, 5)

    # Stage 1: mom name
    if stage == 1:
        mom_name = msg_raw.strip()
        user[KEY_MOM_NAME] = mom_name
        user[KEY_STAGE] = 2
        db.upsert(user, User.id == user["id"])
        resp.message(reg_message_stage_2(mom_name))
        return str(resp)

    # Stage 2: baby name
    if stage == 2:
        baby_name = msg_raw.strip()
        user[KEY_BABY_NAME] = baby_name
        user[KEY_STAGE] = 3
        db.upsert(user, User.id == user["id"])
        resp.message(reg_message_stage_3(baby_name))
        return str(resp)

    # Stage 3: baby gender
    if stage == 3:
        m = clean_msg(msg_raw)
        if m in ["1", "בן", "זכר", "male"]:
            user[KEY_BABY_GENDER] = "male"
        elif m in ["2", "בת", "נקבה", "female"]:
            user[KEY_BABY_GENDER] = "female"
        else:
            resp.message("לא הצלחתי להבין 🙏 כתבי 1) בן או 2) בת")
            return str(resp)

        user[KEY_STAGE] = 4
        db.upsert(user, User.id == user["id"])
        resp.message(reg_message_stage_4())
        return str(resp)

    # Stage 4: DOB
    if stage == 4:
        formatted = validate_and_format_dob(msg_raw)
        if not formatted:
            resp.message("אופס, התאריך לא נראה תקין. נסי שוב בפורמט: 01/01/2025")
            return str(resp)

        user[KEY_DOB] = formatted
        user[KEY_STAGE] = 5
        db.upsert(user, User.id == user["id"])
        resp.message(after_registration_welcome(user))
        return str(resp)

    # Main flow
    parsed = parse_input(msg_raw, user)
    replies = handle_command(uid, user, parsed)

    for r in replies:
        resp.message(r)

    return str(resp)

# ====================================================
# XIII. Run (Render-ready)
# ====================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

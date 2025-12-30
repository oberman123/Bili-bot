# app.py
import os
import re
import json
import datetime as dt
from datetime import timedelta
from threading import RLock

from flask import Flask, request
from tinydb import TinyDB, Query
from twilio.twiml.messaging_response import MessagingResponse


# ====================================================
# 0) Render / TinyDB storage
# ====================================================
# ב-Render מומלץ להגדיר Persistent Disk ולמפות לנתיב הזה (או לשנות לפי הצורך)
DB_DIR = os.getenv("DB_DIR", "/var/data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, os.getenv("DB_FILE", "users_data.json"))

db = TinyDB(DB_PATH)
User = Query()

DB_LOCK = RLock()  # מניעת כתיבות מקבילות לאותו קובץ


# ====================================================
# I. מפתחות DB / קונסטנטות
# ====================================================
KEY_ID = "id"
KEY_NAME = "baby_name"
KEY_GENDER = "baby_gender"          # 'm' / 'f' (בן/בת)
KEY_DOB = "dob"                     # "YYYY-MM-DD"
KEY_STAGE = "stage"                 # onboarding stage
KEY_EVENTS = "events"               # list of events
KEY_SLEEP_START = "sleep_start_time"  # isoformat
KEY_PENDING = "pending_action"      # dict context
KEY_PARTNER_PHONE = "partner_phone" # normalized
KEY_REMINDERS = "reminders"         # list[{text, due_at, created_at, done?}]
KEY_ENC_TIERS = "enc_tier"          # dict {date_str: tier_reached}

MILESTONE_TIERS = {
    4: "מדהים! עקביות זה שם המשחק. רק ארבעה אירועים ואת כבר מנצחת את היום! 🏆",
    8: "וואו, תדעי שאת עוקבת ומנהלת את הכל בצורה מושלמת. 👏",
    12: "את שיאנית! המערכת שלך מסודרת בזכותך. קחי נשימה עמוקה, עשית עבודה מעולה היום. ❤️",
}

LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי._"

HELP_TOPICS = {
    "menu": "איך אפשר לעזור? 🌱\n\nבחרי נושא:\n1️⃣ טיפול בחלב אם\n2️⃣ הנקה\n3️⃣ נורות אזהרה\n4️⃣ המלצות כלליות",
    "1": {
        "keywords": ["חלב", "אחסון", "טיפול", "הקפאה", "קפוא", "מקרר"],
        "text": "❄️ זמני אחסון חלב אם:\n• חדר: 3-4 שעות.\n• מקרר: 3-8 ימים.\n• מקפיא: 3-12 חודשים.\n• חלב שהופשר: 24 שעות במקרר. אין להקפיא שנית.",
    },
    "2": {"keywords": ["בליעה", "הנקה", "תפיסה", "שד"], "text": "שימי לב לבלוע ולא רק למצוץ, ולכך שהשד מתרכך בסיום."},
    "3": {"keywords": ["אזהרה", "נורות", "חום", "אודם", "דלקת"], "text": "🚨 נורות אזהרה: חום גבוה, אודם בשד, או פחות מ-6 חיתולים רטובים ביום."},
    "4": {"keywords": ["המלצות", "טיפים", "מים", "שתייה"], "text": "החליפי צדדים בכל הנקה ושתי המון מים! 💧"},
}


# ====================================================
# II. Utilities
# ====================================================
def get_now_tz() -> dt.datetime:
    return dt.datetime.now()

def today_str() -> str:
    return get_now_tz().strftime("%Y-%m-%d")

def yesterday_str() -> str:
    return (get_now_tz() - timedelta(days=1)).strftime("%Y-%m-%d")

def to_int(val) -> int:
    try:
        if isinstance(val, str):
            val = re.sub(r"[^\d]", "", val)
        return int(val)
    except Exception:
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

def safe_parse_dt(ts: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def format_timedelta(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    hours, minutes = divmod(total_seconds // 60, 60)
    if hours > 0:
        return f"לפני {hours} שעות ו-{minutes} דקות" if minutes > 0 else f"לפני {hours} שעות"
    return f"לפני {minutes} דקות"

def validate_and_format_dob(dob_str: str) -> str | None:
    # תומך גם בשנה מקוצרת
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            d = dt.datetime.strptime(dob_str.strip(), fmt).date()
            if d > dt.date.today():
                return None
            # “בוט תינוקות” – עד בערך 3 שנים
            if d < dt.date.today() - timedelta(days=1100):
                return None
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def calculate_age(dob_yyyy_mm_dd: str | None) -> str:
    if not dob_yyyy_mm_dd:
        return ""
    try:
        birth_date = dt.datetime.strptime(dob_yyyy_mm_dd, "%Y-%m-%d").date()
        diff = dt.date.today() - birth_date
        if diff.days < 30:
            return f"בן {diff.days} ימים"  # גיל תינוק קטן
        return f"בן {diff.days // 30} חודשים"
    except Exception:
        return ""

def baby_pronouns(user: dict) -> dict:
    """
    מחזיר מונחים בעברית בהתאם למגדר:
    - he_she: "הוא"/"היא"
    - son_daughter: "בן"/"בת"
    - ate: "אכל"/"אכלה"
    - slept: "ישן"/"ישנה"
    """
    g = (user.get(KEY_GENDER) or "").lower().strip()
    if g == "f":
        return {"he_she": "היא", "son_daughter": "בת", "ate": "אכלה", "slept": "ישנה"}
    # ברירת מחדל זכר
    return {"he_she": "הוא", "son_daughter": "בן", "ate": "אכל", "slept": "ישן"}


# ====================================================
# III. DB Access (with lock)
# ====================================================
def get_user_by_uid(uid_norm: str) -> dict | None:
    with DB_LOCK:
        user = db.get(User[KEY_ID] == uid_norm)
        if not user:
            user = db.get(User[KEY_PARTNER_PHONE] == uid_norm)
        return user

def upsert_user(user: dict) -> None:
    with DB_LOCK:
        db.upsert(user, User[KEY_ID] == user[KEY_ID])

def remove_user(uid_norm: str) -> None:
    with DB_LOCK:
        u = db.get(User[KEY_ID] == uid_norm) or db.get(User[KEY_PARTNER_PHONE] == uid_norm)
        if u:
            db.remove(User[KEY_ID] == u[KEY_ID])

def add_event(user_id_norm: str, event_type: str, details: dict, timestamp: str | None = None) -> dict | None:
    with DB_LOCK:
        user = get_user_by_uid(user_id_norm)
        if not user:
            return None
        ts = timestamp or get_now_tz().strftime("%Y-%m-%d %H:%M:%S")
        event = {"type": event_type, "timestamp": ts, "details": details or {}}

        if not isinstance(user.get(KEY_EVENTS), list):
            user[KEY_EVENTS] = []
        user[KEY_EVENTS].append(event)
        db.upsert(user, User[KEY_ID] == user[KEY_ID])
        return event


# ====================================================
# IV. Formatting
# ====================================================
def format_event_human(user: dict, event: dict) -> str:
    etype = event.get("type")
    d = event.get("details", {})
    time = (event.get("timestamp") or "")[-8:-3]
    p = baby_pronouns(user)

    if etype == "breastfeeding":
        side = d.get("side", "לא צוין")
        dur = d.get("duration")
        dur_txt = f"{dur} דק'" if dur else "ללא משך"
        return f"🤱 הנקה: צד {side} ({dur_txt}) ב-{time}"
    if etype == "bottle":
        return f"🍼 בקבוק: {d.get('amount', 0)} מ״ל ב-{time}"
    if etype == "diaper":
        return f"🧷 חיתול: {d.get('type', 'החלפה')} ב-{time}"
    if etype == "sleep":
        if "duration_min" in d:
            return f"😴 שינה: {p['slept']} {d['duration_min']} דק' (הסתיימה ב-{time})"
        return f"☀️ יקיצה ב-{time}"
    return f"✨ {etype} ב-{time}"


# ====================================================
# V. Insights / Summaries / Comparisons
# ====================================================
def iter_recent_events(events: list, cutoff_dt: dt.datetime):
    # סריקה מהסוף – יעיל כשמוסיפים אירועים בסוף
    for e in reversed(events):
        e_dt = safe_parse_dt(e.get("timestamp", ""))
        if not e_dt:
            continue
        if e_dt < cutoff_dt:
            break
        yield e

def get_summary(user: dict, hours: int | None = None) -> str:
    events = user.get(KEY_EVENTS, [])
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
    breasts = sum(1 for e in relevant if e.get("type") == "breastfeeding")
    diapers = sum(1 for e in relevant if e.get("type") == "diaper")
    sleep_mins = sum(to_int(e.get("details", {}).get("duration_min", 0)) for e in relevant if e.get("type") == "sleep")

    res = f"📊 *סיכום {label}:*\n"
    res += f"🍼 בקבוקים: {bottles} מ״ל\n"
    res += f"🤱 הנקות: {breasts}\n"
    res += f"🧷 חיתולים: {diapers}\n"
    res += f"😴 שינה: {sleep_mins // 60} שע' ו-{sleep_mins % 60} דק'"
    return res

def get_comparison_report(user: dict) -> str:
    events = user.get(KEY_EVENTS, [])
    t, y = today_str(), yesterday_str()

    def summarize(date_str: str) -> dict:
        day_events = [e for e in events if (e.get("timestamp", "").startswith(date_str))]
        return {
            "breast": sum(1 for e in day_events if e.get("type") == "breastfeeding"),
            "bottle": sum(to_int(e.get("details", {}).get("amount", 0)) for e in day_events if e.get("type") == "bottle"),
            "diaper": sum(1 for e in day_events if e.get("type") == "diaper"),
            "sleep_mins": sum(to_int(e.get("details", {}).get("duration_min", 0)) for e in day_events if e.get("type") == "sleep"),
        }

    s_t, s_y = summarize(t), summarize(y)
    report = f"📊 השוואה עבור {user.get(KEY_NAME, 'הבייבי')}:\n\n"
    report += f"🤱 הנקות: {s_t['breast']} (אתמול: {s_y['breast']})\n"
    report += f"🍼 בקבוקים: {s_t['bottle']} מ\"ל (אתמול: {s_y['bottle']} מ\"ל)\n"
    report += f"🧷 חיתולים: {s_t['diaper']} (אתמול: {s_y['diaper']})\n"
    report += f"😴 שינה: {round(s_t['sleep_mins']/60, 1)} שע' (אתמול: {round(s_y['sleep_mins']/60, 1)} שע')"
    return report

def get_health_insights(user: dict) -> str | None:
    """
    דוגמה קלה: חיתולים עד השעה הזו בהשוואה לממוצע 3 ימים קודמים עד אותה שעה
    (זה "רמז" בלבד, לא המלצה רפואית).
    """
    events = user.get(KEY_EVENTS, [])
    now = get_now_tz()
    current_time = now.time()

    diaper_dts = []
    for e in events:
        if e.get("type") != "diaper":
            continue
        e_dt = safe_parse_dt(e.get("timestamp", ""))
        if e_dt:
            diaper_dts.append(e_dt)

    today_count = sum(1 for d in diaper_dts if d.date() == now.date() and d.time() <= current_time)

    past_counts = []
    for i in range(1, 4):
        target_date = (now - timedelta(days=i)).date()
        count = sum(1 for d in diaper_dts if d.date() == target_date and d.time() <= current_time)
        past_counts.append(count)

    if not past_counts:
        return None

    avg_past = sum(past_counts) / len(past_counts)
    if avg_past > 1.5 and today_count <= (avg_past * 0.4):
        return f"💡 שמתי לב שעד השעה הזו בדרך כלל יש יותר חיתולים ({round(avg_past,1)} בממוצע לעומת {today_count} היום). שווה לעקוב."
    return None


# ====================================================
# VI. Reminders (no scheduling – shown on demand)
# ====================================================
def add_reminder(user: dict, text: str, hours_from_now: int = 0) -> None:
    now = get_now_tz()
    due_at = now + timedelta(hours=hours_from_now)
    rem = {
        "text": text.strip(),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"),
        "done": False,
    }
    reminders = user.get(KEY_REMINDERS, [])
    if not isinstance(reminders, list):
        reminders = []
    reminders.append(rem)
    user[KEY_REMINDERS] = reminders
    upsert_user(user)

def list_due_reminders(user: dict) -> str | None:
    now = get_now_tz()
    reminders = user.get(KEY_REMINDERS, [])
    if not isinstance(reminders, list) or not reminders:
        return None

    due = []
    for r in reminders:
        if r.get("done"):
            continue
        due_at = safe_parse_dt(r.get("due_at", ""))
        if due_at and due_at <= now:
            due.append(r)

    if not due:
        return None

    lines = ["⏰ *תזכורות שהגיע הזמן אליהן:*"]
    for i, r in enumerate(due[-10:], start=1):
        lines.append(f"{i}. {r.get('text', '')}")
    lines.append("\nכדי לסמן שבוצע: כתבי `סיימתי 1` (או מספר אחר).")
    return "\n".join(lines)

def mark_reminder_done(user: dict, idx_from_end_1based: int) -> str:
    reminders = user.get(KEY_REMINDERS, [])
    if not isinstance(reminders, list) or not reminders:
        return "אין תזכורות במערכת."

    # אנחנו מציגים תמיד מהסוף (האחרונות רלוונטיות), אז 1 = האחרונה שלא בוצעה שמוצגת
    open_items = [r for r in reminders if not r.get("done")]
    if not open_items:
        return "אין תזכורות פתוחות."

    if idx_from_end_1based < 1 or idx_from_end_1based > len(open_items):
        return "לא מצאתי תזכורת במספר הזה."

    target = open_items[-idx_from_end_1based]
    target["done"] = True

    # צריך לעדכן את הרשימה המקורית (אותו dict reference לרוב יספיק, אבל נעשה בטוח)
    upsert_user(user)
    return "סימנתי כבוצע ✅"


# ====================================================
# VII. NLP / Parsing
# ====================================================
def clean_msg(message: str) -> str:
    # ניקוי פיסוק/אימוג'י, משאיר עברית/אנגלית/ספרות ורווחים
    return re.sub(r"[^\w\s\u0590-\u05FF]", "", message.lower()).strip()

def parse_input(message: str, user: dict) -> dict:
    msg = clean_msg(message)

    # ---- system commands ----
    if msg in ["עזרה", "help", "menu", "תפריט"]:
        return {"type": "help_menu"}

    if msg in ["השוואה", "השווא"]:
        return {"type": "comparison"}

    if msg.startswith("סיכום"):
        # "סיכום" / "סיכום 12" / "סיכום 24"
        m = re.search(r"סיכום\s*(\d+)?", msg)
        hours = to_int(m.group(1)) if (m and m.group(1)) else None
        return {"type": "summary", "hours": hours}

    if any(w in msg for w in ["בטל", "מחק", "טעות", "undo"]):
        return {"type": "undo"}

    if msg == "סטטוס":
        return {"type": "status"}

    if msg == "תזכורות":
        return {"type": "reminders_list"}

    # "סיימתי 1"
    m_done = re.search(r"סיימתי\s*(\d+)", msg)
    if m_done:
        return {"type": "reminder_done", "idx": to_int(m_done.group(1))}

    # ---- pending completion ----
    pending = user.get(KEY_PENDING)
    if pending and msg.isdigit():
        val = to_int(msg)
        if pending.get("type") == "bottle":
            return {"type": "bottle", "amount": val}
        if pending.get("type") == "breastfeeding":
            return {"type": "breastfeeding", "side": pending.get("side", "לא צוין"), "duration": val}
        if pending.get("type") == "sleep_manual":
            return {"type": "sleep_manual", "duration": val}

    # ---- help topics by number ----
    if msg in ["1", "2", "3", "4"]:
        return {"type": "help_item", "id": msg}

    # ---- smart help by keywords ----
    best_id, best_score = None, 0
    for tid, content in HELP_TOPICS.items():
        if not isinstance(content, dict):
            continue
        score = sum(1 for kw in content.get("keywords", []) if kw in msg)
        if score > best_score:
            best_score, best_id = score, tid
    if best_id and best_score > 0:
        return {"type": "help_item", "id": best_id}

    # ---- "מתי" queries ----
    if "מתי" in msg:
        if any(w in msg for w in ["אכל", "אכלה", "בקבוק", "הנקה"]):
            return {"type": "query_last", "targets": ["bottle", "breastfeeding"], "label": "האכילה"}
        if any(w in msg for w in ["חיתול", "החלפנו", "קקי", "פיפי"]):
            return {"type": "query_last", "targets": ["diaper"], "label": "החלפת החיתול"}
        if any(w in msg for w in ["נרדם", "ישן", "ישנה"]):
            # לשינה נרצה start/end אם יש
            return {"type": "query_last", "targets": ["sleep"], "label": "השינה", "sub_type": "end"}

    if any(w in msg for w in ["כמה זמן ער", "חלון ערות", "זמן ערות"]):
        return {"type": "query_awake"}

    # ---- reminders add ----
    # "תזכורת חיסון עוד 48 שעות" / "תזכורת תרופה עוד 2 שעות"
    if msg.startswith("תזכורת"):
        # מחפש "עוד X שעות"
        m = re.search(r"עוד\s*(\d+)\s*שעות?", msg)
        hrs = to_int(m.group(1)) if m else 0
        text = msg.replace("תזכורת", "").strip()
        if m:
            text = re.sub(r"עוד\s*\d+\s*שעות?", "", text).strip()
        if not text:
            text = "תזכורת"
        return {"type": "add_reminder", "text": text, "hours": hrs}

    # ---- sleep ----
    if any(w in msg for w in ["נרדם", "הלך לישון", "נכנס לישון", "התחיל לישון"]):
        return {"type": "sleep_start"}

    if any(w in msg for w in ["קם", "התעורר", "סיים לישון"]):
        return {"type": "sleep_end"}

    # manual sleep: "ישן 40 דקות"
    m_sleep = re.search(r"(ישן|ישנה)\s*(\d+)\s*(דקות|דק)", msg)
    if m_sleep:
        return {"type": "sleep_manual", "duration": to_int(m_sleep.group(2))}
    # "ישן" בלי מספר
    if any(w in msg for w in ["ישן", "ישנה"]) and not any(w in msg for w in ["נרדם", "קם", "התעורר"]):
        return {"type": "sleep_manual", "duration": 0}

    # ---- breastfeeding ----
    if any(k in msg for k in ["ינק", "הנקה", "ימין", "שמאל"]):
        side = "ימין" if "ימין" in msg else "שמאל" if "שמאל" in msg else "לא צוין"
        dur_match = re.search(r"(\d+)\s*(דקות|דק)", msg)
        dur = to_int(dur_match.group(1)) if dur_match else to_int(re.search(r"\d+", msg).group(0)) if re.search(r"\d+", msg) else 0
        return {"type": "breastfeeding", "side": side, "duration": dur}

    # ---- bottle ----
    if "בקבוק" in msg:
        amt_match = re.search(r"(\d+)\s*(מ\"ל|מ״ל|מל|ml)", msg)
        amt = to_int(amt_match.group(1)) if amt_match else to_int(re.search(r"\d+", msg).group(0)) if re.search(r"\d+", msg) else 0
        return {"type": "bottle", "amount": amt}

    # ---- diaper ----
    if any(w in msg for w in ["קקי", "פיפי", "חיתול"]):
        dtype = "קקי" if "קקי" in msg else "פיפי" if "פיפי" in msg else "שניהם"
        return {"type": "diaper", "diaper_type": dtype}

    # ---- partner ----
    if any(w in msg for w in ["הוסף בן זוג", "הוסיפי בן זוג", "הוסף בןזוג", "הוסיפי בןזוג"]):
        phone = re.search(r"(05\d{8}|9725\d{8})", msg)
        return {"type": "add_partner", "phone": phone.group(0) if phone else None}

    return {"type": "unknown"}


# ====================================================
# VIII. Business Logic
# ====================================================
def get_last_event(user: dict, types: list[str]) -> dict | None:
    events = user.get(KEY_EVENTS, [])
    filtered = [e for e in events if e.get("type") in types]
    if not filtered:
        return None
    # מיון לפי timestamp טקסטואלי עובד כי פורמט אחיד YYYY-MM-DD HH:MM:SS
    return sorted(filtered, key=lambda x: x.get("timestamp", ""))[-1]

def apply_milestones(user: dict) -> list[str]:
    # מחזיר הודעת עידוד אם צריך
    events = user.get(KEY_EVENTS, [])
    today = today_str()
    count = sum(1 for e in events if (e.get("timestamp", "").startswith(today)))

    tiers = user.get(KEY_ENC_TIERS, {})
    if not isinstance(tiers, dict):
        tiers = {}

    last_t = to_int(tiers.get(today, 0))
    for t in sorted(MILESTONE_TIERS.keys()):
        if count >= t and t > last_t:
            tiers[today] = t
            user[KEY_ENC_TIERS] = tiers
            upsert_user(user)
            return [MILESTONE_TIERS[t]]
    return []

def handle_logging(uid_norm: str, parsed: dict, user: dict) -> list[str]:
    baby = user.get(KEY_NAME, "הבייבי")
    p = baby_pronouns(user)
    res: list[str] = []

    # ברירת מחדל: אם התקבלה פקודה “אמיתית”, מאפסים pending
    if parsed.get("type") not in ("unknown",):
        user[KEY_PENDING] = None

    t = parsed["type"]

    # ---- undo ----
    if t == "undo":
        if user.get(KEY_PENDING):
            user[KEY_PENDING] = None
            upsert_user(user)
            return ["ביטלתי את השאלה האחרונה. 👍"]

        events = user.get(KEY_EVENTS, [])
        if events:
            removed = events.pop()
            user[KEY_EVENTS] = events
            upsert_user(user)
            return [f"ביטלתי את הרישום האחרון: *{format_event_human(user, removed)}*"]
        return ["אין לי מה לבטל."]

    # ---- sleep start/end/manual ----
    if t == "sleep_start":
        user[KEY_SLEEP_START] = get_now_tz().isoformat()
        upsert_user(user)
        return [f"לילה טוב ל{baby}... 😴"]

    if t == "sleep_end":
        end_dt = get_now_tz()
        start_str = user.get(KEY_SLEEP_START)
        if start_str:
            try:
                start_dt = dt.datetime.fromisoformat(start_str)
                mins = int((end_dt - start_dt).total_seconds() / 60)
                add_event(user[KEY_ID], "sleep", {
                    "duration_min": mins,
                    "start_ts": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                })
                res.append(f"בוקר טוב! {baby} {p['slept']} {mins} דקות. ☀️")
            except Exception:
                add_event(user[KEY_ID], "sleep", {"action": "wake_up", "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})
                res.append("רשמתי התעוררות עכשיו (הייתה בעיה בקריאת זמן ההירדמות).")
        else:
            add_event(user[KEY_ID], "sleep", {"action": "wake_up", "end_ts": end_dt.strftime("%Y-%m-%d %H:%M:%S")})
            res.append("רשמתי שהוא התעורר עכשיו (לא מצאתי מתי נרדם).")

        user[KEY_SLEEP_START] = None
        upsert_user(user)
        res.extend(apply_milestones(user))
        return res

    if t == "sleep_manual":
        dur = to_int(parsed.get("duration", 0))
        if dur <= 0:
            user[KEY_PENDING] = {"type": "sleep_manual"}
            upsert_user(user)
            return [f"כמה דקות {baby} {p['slept']}?"]
        add_event(user[KEY_ID], "sleep", {"duration_min": dur})
        res.append(f"רשמתי ש{baby} {p['slept']} {dur} דקות. ✅")
        res.extend(apply_milestones(user))
        return res

    # ---- breastfeeding ----
    if t == "breastfeeding":
        dur = to_int(parsed.get("duration", 0))
        side = parsed.get("side", "לא צוין")
        if dur <= 0:
            user[KEY_PENDING] = {"type": "breastfeeding", "side": side}
            upsert_user(user)
            return [f"כמה דקות {baby} ינק?"]
        add_event(user[KEY_ID], "breastfeeding", {"side": side, "duration": dur})
        res.append(f"נרשמה הנקה ({side}, {dur} דק'). ❤️")
        res.extend(apply_milestones(user))
        return res

    # ---- bottle ----
    if t == "bottle":
        amt = to_int(parsed.get("amount", 0))
        if amt <= 0:
            user[KEY_PENDING] = {"type": "bottle"}
            upsert_user(user)
            return [f"כמה מ\"ל {baby} {p['ate']}?"]
        add_event(user[KEY_ID], "bottle", {"amount": amt})
        res.append(f"נרשם בקבוק של {amt} מ\"ל. 🍼")
        res.extend(apply_milestones(user))
        return res

    # ---- diaper ----
    if t == "diaper":
        dtype = parsed.get("diaper_type", "החלפה")
        add_event(user[KEY_ID], "diaper", {"type": dtype})
        res.append(f"חיתול נרשם ({dtype}). ✅")
        res.extend(apply_milestones(user))
        return res

    # ---- add partner ----
    if t == "add_partner":
        phone = parsed.get("phone")
        if not phone:
            return ["לא מצאתי מספר תקין. נסי: 'הוסף בן זוג 0501234567'"]
        p_uid = normalize_phone(phone)
        user[KEY_PARTNER_PHONE] = p_uid
        upsert_user(user)
        return [f"הוספתי את בן הזוג (מספר: {p_uid})! 🤝"]

    # ---- query last ----
    if t == "query_last":
        last = get_last_event(user, parsed.get("targets", []))
        if not last:
            return [f"לא מצאתי תיעוד של {parsed.get('label','זה')}. 🧐"]

        # אם ביקשו “סאב” שונה – משתמשים ב-start_ts/end_ts אם קיים
        sub = parsed.get("sub_type")
        ts_str = last.get("timestamp", "")
        if sub == "start":
            ts_str = last.get("details", {}).get("start_ts") or ts_str
        elif sub == "end":
            ts_str = last.get("details", {}).get("end_ts") or ts_str

        ts = safe_parse_dt(ts_str)
        if not ts:
            return ["מצאתי אירוע, אבל הייתה בעיה לקרוא את הזמן שלו."]

        diff_str = format_timedelta(get_now_tz() - ts)
        return [f"{parsed.get('label','הפעולה')} האחרונה הייתה {diff_str} ({ts.strftime('%H:%M')})."]

    # ---- query awake ----
    if t == "query_awake":
        last_sleep = get_last_event(user, ["sleep"])
        if last_sleep and last_sleep.get("details", {}).get("end_ts"):
            end_ts = safe_parse_dt(last_sleep["details"]["end_ts"])
            if end_ts:
                diff_str = format_timedelta(get_now_tz() - end_ts).replace("לפני ", "")
                return [f"{baby} ער כבר {diff_str}. ⏰"]
        return ["אין לי תיעוד של התעוררות אחרונה."]

    # ---- add reminder ----
    if t == "add_reminder":
        text = parsed.get("text", "תזכורת")
        hrs = to_int(parsed.get("hours", 0))
        add_reminder(user, text=text, hours_from_now=hrs)
        if hrs > 0:
            return [f"רשמתי תזכורת: “{text}” לעוד {hrs} שעות. ✨\n(כרגע אין הודעות מתוזמנות – אציג לך אותה בסטטוס/תזכורות כשהזמן יגיע.)"]
        return [f"רשמתי תזכורת: “{text}”. ✨\n(אציג אותה בסטטוס/תזכורות כשהזמן יגיע.)"]

    # ---- reminders list / done ----
    if t == "reminders_list":
        msg = list_due_reminders(user)
        return [msg] if msg else ["אין תזכורות שהגיע הזמן אליהן כרגע. ✅"]

    if t == "reminder_done":
        idx = to_int(parsed.get("idx", 0))
        return [mark_reminder_done(user, idx)]

    return ["לא בטוחה שהבנתי... 🧐 נסי 'עזרה', 'סטטוס', 'סיכום', 'השוואה' או 'בטל'."]


# ====================================================
# IX. Flask Webhook + Onboarding
# ====================================================
app = Flask(__name__)

@app.route("/sms", methods=["POST"])
def whatsapp_webhook():
    msg_raw = (request.values.get("Body", "") or "").strip()
    from_raw = request.values.get("From", "") or ""
    uid = normalize_phone(from_raw)

    resp = MessagingResponse()

    # 1) RESET
    if msg_raw.lower().strip() in ["אפס", "reset"]:
        remove_user(uid)
        resp.message("איתחלנו! שלחי הודעה כלשהי כדי להתחיל מחדש. ❤️")
        return str(resp)

    # 2) Load / create user
    user = get_user_by_uid(uid)

    if not user:
        user = {KEY_ID: uid, KEY_STAGE: 1, KEY_EVENTS: [], KEY_PENDING: None}
        upsert_user(user)
        resp.message("היי! אני בילי 🧚\nאיך קוראים לבייבי?")
        return str(resp)

    stage = to_int(user.get(KEY_STAGE, 5))

    # Onboarding stage 1: name
    if stage == 1:
        user[KEY_NAME] = msg_raw
        user[KEY_STAGE] = 2
        upsert_user(user)
        resp.message(f"איזה שם מקסים! ומה המגדר? כתבי: בן / בת")
        return str(resp)

    # Onboarding stage 2: gender
    if stage == 2:
        m = clean_msg(msg_raw)
        if "בת" in m or "נקבה" in m:
            user[KEY_GENDER] = "f"
        elif "בן" in m or "זכר" in m:
            user[KEY_GENDER] = "m"
        else:
            resp.message("לא הצלחתי להבין. כתבי בבקשה: בן / בת")
            return str(resp)

        user[KEY_STAGE] = 3
        upsert_user(user)
        resp.message(f"מעולה. ומה תאריך הלידה? (למשל: 01/01/2024)")
        return str(resp)

    # Onboarding stage 3: DOB
    if stage == 3:
        formatted = validate_and_format_dob(msg_raw)
        if not formatted:
            resp.message("אופס, התאריך לא נראה תקין. נסי שוב בפורמט: 01/01/2024")
            return str(resp)
        user[KEY_DOB] = formatted
        user[KEY_STAGE] = 5
        upsert_user(user)
        resp.message("הכל מוכן! ✨\nאפשר לכתוב: 'נרדם', 'הנקה ימין 10', 'בקבוק 120', 'חיתול קקי', 'סטטוס', 'סיכום', 'השוואה', 'בטל'.")
        return str(resp)

    # 3) Normal operation
    parsed = parse_input(msg_raw, user)

    if parsed["type"] == "help_menu":
        resp.message(HELP_TOPICS["menu"])
        return str(resp)

    if parsed["type"] == "help_item":
        resp.message(HELP_TOPICS[parsed["id"]]["text"] + LEGAL_DISCLAIMER)
        return str(resp)

    if parsed["type"] == "status":
        # status includes: last 5 today + insights + due reminders
        baby = user.get(KEY_NAME, "הבייבי")
        age = calculate_age(user.get(KEY_DOB))
        header = f"סטטוס {baby} ({age}):\n\n"

        t = today_str()
        events = [e for e in user.get(KEY_EVENTS, []) if (e.get("timestamp", "").startswith(t))]
        last5 = events[-5:]

        if last5:
            lines = [format_event_human(user, e) for e in last5]
            body = "\n".join(lines)
        else:
            body = "אין תיעוד מהיום עדיין."

        blocks = [header + body]

        insight = get_health_insights(user)
        if insight:
            blocks.append("\n" + insight)

        due = list_due_reminders(user)
        if due:
            blocks.append("\n\n" + due)

        resp.message("\n".join(blocks))
        return str(resp)

    if parsed["type"] == "comparison":
        resp.message(get_comparison_report(user))
        return str(resp)

    if parsed["type"] == "summary":
        resp.message(get_summary(user, hours=parsed.get("hours")))
        return str(resp)

    # everything else through business logic
    for msg in handle_logging(uid, parsed, user):
        resp.message(msg)

    return str(resp)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

import datetime as dt
import re
from datetime import timedelta 
from tinydb import TinyDB, Query
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

# ====================================================
# I. הגדרות תשתית
# ====================================================
db = TinyDB('users_data.json')
User = Query()

KEY_NAME, KEY_DOB, KEY_EVENTS = 'baby_name', 'dob', 'events'
KEY_SLEEP_START, KEY_PENDING = 'sleep_start_time', 'pending_action'
KEY_PARTNER_PHONE, KEY_REMINDERS = 'partner_phone', 'reminders'

def get_now_tz(): return dt.datetime.now()

def to_int(val):
    try:
        if isinstance(val, str): val = re.sub(r"[^\d]", "", val)
        return int(val)
    except: return 0

def normalize_phone(phone_str: str) -> str:
    if not phone_str: return ""
    clean = re.sub(r"[^\d]", "", phone_str.replace("whatsapp:", ""))
    if clean.startswith("05"): clean = "972" + clean[1:]
    elif clean.startswith("9720"): clean = "972" + clean[4:]
    return clean

# ====================================================
# II. ניהול אירועים ופורמט (O(N) Optimized)
# ====================================================
def format_event_human(event):
    etype = event['type']
    d = event.get('details', {})
    time = event['timestamp'][-8:-3]
    
    if etype == 'breastfeeding':
        dur = d.get('duration')
        dur_txt = f"{dur} דק'" if dur else "ללא משך"
        return f"🤱 הנקה מצד {d.get('side', 'לא צוין')} ({dur_txt}) ב-{time}"
    if etype == 'bottle':
        return f"🍼 בקבוק {d.get('amount', 0)} מ״ל ב-{time}"
    if etype == 'diaper':
        return f"🧷 חיתול ({d.get('type', 'החלפה')}) ב-{time}"
    if etype == 'sleep':
        if 'duration_min' in d: return f"😴 שינה של {d['duration_min']} דק' (הסתיימה ב-{time})"
        return f"☀️ יקיצה ב-{time}"
    return f"✨ {etype} ב-{time}"

def iter_recent_events(events, cutoff_dt):
    """סורק מהסוף להתחלה עד שהזמן עובר את ה-cutoff (יעיל מאוד)"""
    for e in reversed(events):
        try:
            e_dt = dt.datetime.strptime(e['timestamp'], "%Y-%m-%d %H:%M:%S")
            if e_dt < cutoff_dt: break
            yield e
        except: continue

# ====================================================
# III. סיכומים ותזכורות
# ====================================================
def get_summary(user, hours=None):
    events = user.get(KEY_EVENTS, [])
    now = get_now_tz()
    
    # אם לא צוינו שעות, הולכים לתחילת היום (חצות)
    if hours is None:
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "מהיום מחצות"
    else:
        cutoff = now - timedelta(hours=hours)
        label = f"ב-{hours} השעות האחרונות"
    
    relevant = list(iter_recent_events(events, cutoff))
    if not relevant: return f"לא מצאתי אירועים {label}."

    bottles = sum(to_int(e['details'].get('amount', 0)) for e in relevant if e['type'] == 'bottle')
    breasts = len([e for e in relevant if e['type'] == 'breastfeeding'])
    diapers = len([e for e in relevant if e['type'] == 'diaper'])
    sleep_mins = sum(to_int(e['details'].get('duration_min', 0)) for e in relevant if e['type'] == 'sleep')
    
    res = f"📊 *סיכום {label}:*\n"
    res += f"🍼 בקבוקים: {bottles} מ״ל\n"
    res += f"🤱 הנקות: {breasts}\n"
    res += f"🧷 חיתולים: {diapers}\n"
    res += f"😴 שינה: {sleep_mins // 60} שע' ו-{sleep_mins % 60} דק'"
    return res

# ====================================================
# IV. לוגיקה עסקית (handle_logging)
# ====================================================
def handle_logging(user_id, parsed, user):
    baby = user.get(KEY_NAME, 'הבייבי')
    res = []

    # 1. תזכורות (Reminders)
    if parsed['type'] == 'add_reminder':
        reminders = user.get(KEY_REMINDERS, [])
        new_rem = {
            'text': parsed['text'],
            'due_in': parsed.get('hours', 0),
            'ts': get_now_tz().strftime("%H:%M")
        }
        reminders.append(new_rem)
        user[KEY_REMINDERS] = reminders
        db.upsert(user, User.id == user['id'])
        res.append(f"רשמתי! אציג לך את התזכורת כשתיכנסי לסטטוס או תבקשי 'תזכורות'. ✨")

    # 2. שאילתות "מתי"
    elif parsed['type'] == 'query_last':
        events = user.get(KEY_EVENTS, [])
        targets = parsed['targets']
        
        # סינון לפי סוג וסאב-טייפ
        filtered = [e for e in events if e['type'] in targets]
        if parsed.get('sub_type') == 'start':
            filtered = [e for e in filtered if 'start_ts' in e.get('details', {})]
            key_func = lambda x: x['details']['start_ts']
        else:
            key_func = lambda x: x['timestamp']

        if filtered:
            last = sorted(filtered, key=key_func)[-1]
            try:
                ts = dt.datetime.strptime(key_func(last), "%Y-%m-%d %H:%M:%S")
            except:
                ts = dt.datetime.strptime(last['timestamp'], "%Y-%m-%d %H:%M:%S")
            
            from utils import format_timedelta # נניח שיש פונקציית עזר
            res.append(f"{parsed['label']} האחרונה הייתה {format_timedelta(get_now_tz()-ts)} ({ts.strftime('%H:%M')}).")
        else: res.append(f"לא מצאתי תיעוד של {parsed['label']}.")

    # 3. סיכום (Summary)
    elif parsed['type'] == 'summary':
        res.append(get_summary(user, hours=parsed.get('hours')))

    # 4. ביטול (Undo)
    elif parsed['type'] == 'undo':
        # ... לוגיקת ה-Undo הקודמת עם format_event_human ...
        pass

    return res or ["לא בטוחה שהבנתי... 🧐 נסי 'סטטוס', 'סיכום' או 'בטל'."]

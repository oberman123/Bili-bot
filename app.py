import os  
import datetime as dt
import re  
import random 
from datetime import timedelta 

from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from tinydb import TinyDB, Query
from flask import Flask, request, jsonify

# ====================================================
# I. הגדרות ו-DB
# ====================================================

account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token) 

db = TinyDB('users_data.json')
User = Query()

# מפתחות קונסטנטיים
KEY_MOM_NAME = 'mom_name' 
KEY_GENDER = 'baby_gender' 
KEY_NAME = 'baby_name'
KEY_DOB = 'dob'
KEY_FEED_METHOD = 'feed_method' 
KEY_EVENTS = 'events'
KEY_ROLE = 'role'
KEY_MAIN_USER = 'main'
KEY_PARTNER_USER = 'partner'
KEY_PARTNER_PHONE = 'partner_phone'
KEY_ENCOURAGEMENT_TIER = 'enc_tier' 
KEY_SLEEP_START = 'sleep_start_time' # מפתח לטיימר שינה

# הודעות עידוד לפי כמות פעולות ביום
MILESTONE_TIERS = { 
    4: "מדהים! עקביות זה שם המשחק. רק ארבעה אירועים ואת כבר מנצחת את היום! 🏆",
    8: "וואו, תדעי שאת עוקבת ומנהלת את הכל בצורה מושלמת. איזו השקעה 👏",
    12: "את שיאנית! המערכת שלך מסודרת בזכותך. קחי נשימה עמוקה, עשית עבודה מעולה היום. ❤️"
}

LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי._"

# תפריט עזרה מעודכן עם החומר ששלחת
HELP_TOPICS = {
    'menu': "איך אפשר לעזור? 🌱\n\nבחרי נושא (או כתבי את המספר):\n1️⃣ טיפול בחלב אם\n2️⃣ דברים שחשוב לשים לב בהנקה\n3️⃣ נורות אזהרה\n4️⃣ המלצות כלליות להנקה",
    '1': {
        'text': "כמה דברים חשובים על אחסון וטיפול בחלב אם 🍼\n\n❄️ זמני אחסון (לחלב שנשאב בתנאים נקיים מאוד):\n• בטמפרטורת החדר: מומלץ 3-4 שעות (אפשרי עד 6 שעות).\n• חלב טרי במקרר: מומלץ 3 ימים (אפשרי עד 8 ימים).\n• מקפיא (דלת נפרדת): מומלץ 3 חודשים (אפשרי עד 12 חודשים).\n• צידנית + קרחונים: עד 24 שעות בצידנית, במגע עם הקרחונים.\n• חלב קפוא שהופשר במקרר: מההפשרה 24 שעות בקירור. אין להקפיא שוב.\n• חלב קפוא שהופשר בטמפרטורת החדר: אין להקפיא שוב ואין להחזיר למקרר.\n\n🌡️ הפשרה וחימום:\n• אופן ההפשרה: מומלץ להפשיר במקרר או בטמפרטורת החדר.\n• אופן החימום: ניתן לחמם בכלי עם מים חמימים. לא רותחים ולא במיקרוגל.\n\n*כל הנתונים הינם עבור חלב שנשאב בתנאים נקיים מאוד.*"
    },
    '2': {'text': "בהנקה, שימי לב ל־ 🤱\n• שהתינוק בולע ולא רק מוצץ\n• שהשד מתרכך במהלך ההנקה\n• שאין כאב מתמשך"},
    '3': {'text': "נורות אזהרה 🚨\n• כאב חזק שלא עובר\n• חום גבוה או אודם בשד\n• מיעוט חיתולים רטובים"},
    '4': {'text': "המלצות 💛\n• להחליף צדדים\n• לשתות מים בכל הנקה\n• לנוח כשהבייבי ישן"},
}

# ====================================================
# II. פונקציות עזר (זמן, גיל, נרמול)
# ====================================================

def get_now_tz(): return dt.datetime.now()
def get_today_tz(): return dt.datetime.now().date()

def normalize_user_id(user_id):
    if not user_id: return ""
    if user_id.startswith('whatsapp:'): return user_id[9:]
    return user_id

def calculate_age(dob_str):
    try:
        birth_date = dt.datetime.strptime(dob_str, "%d/%m/%Y").date()
        diff = get_today_tz() - birth_date
        if diff.days < 30: return f"בן {diff.days} ימים"
        return f"בן {diff.days // 30} חודשים"
    except: return ""

# ====================================================
# III. ניהול DB
# ====================================================

def get_user_data(user_id):
    uid = normalize_user_id(user_id)
    user = db.get(User.id == uid)
    if not user:
        # בדיקה אם מדובר בבן זוג
        main_user = db.get(User.partner_phone == uid)
        if main_user: return main_user
    return user

def save_user_data(user_id, data):
    data['id'] = normalize_user_id(user_id)
    db.upsert(data, User.id == data['id'])

def add_event(user_id, event_type, details):
    user = get_user_data(user_id)
    if not user: return
    event = {
        'type': event_type,
        'timestamp': get_now_tz().strftime("%Y-%m-%d %H:%M:%S"),
        'details': details
    }
    user.setdefault(KEY_EVENTS, []).append(event)
    save_user_data(user['id'], user)

# ====================================================
# IV. NLP וזיהוי פקודות (כולל שינה)
# ====================================================

def parse_input(message):
    msg = message.lower().strip()
    
    # שינה
    if any(w in msg for w in ['נרדם', 'הלך לישון']): return {'type': 'sleep_start'}
    if any(w in msg for w in ['קם', 'התעורר']): return {'type': 'sleep_end'}
    if 'ישן' in msg:
        dur = re.search(r'\d+', msg)
        return {'type': 'sleep_manual', 'duration': f"{dur.group(0)} דקות" if dur else "לא צוין"}

    # הנקה/בקבוק/חיתול/שאיבה (כמו במקור)
    if any(k in msg for k in ['ינק', 'הנקה', 'ימין', 'שמאל']):
        side = 'ימין' if 'ימין' in msg else 'שמאל' if 'שמאל' in msg else 'לא צוין'
        dur = re.search(r'\d+', msg)
        return {'type': 'breastfeeding', 'side': side, 'duration': int(dur.group(0)) if dur else 0}
    
    if 'בקבוק' in msg:
        amt = re.search(r'\d+', msg)
        return {'type': 'bottle', 'amount': int(amt.group(0)) if amt else 0}
    
    if any(w in msg for w in ['קקי', 'פיפי', 'חיתול']):
        dtype = 'קקי' if 'קקי' in msg else 'פיפי' if 'פיפי' in msg else 'שניהם'
        return {'type': 'diaper', 'diaper_type': dtype}

    # פקודות מערכת
    if msg == 'סטטוס': return {'type': 'status'}
    if msg == 'השוואה': return {'type': 'comparison'}
    if msg in ['עזרה', 'help', 'menu']: return {'type': 'help_menu'}
    if msg in ['1', '2', '3', '4']: return {'type': 'help_item', 'id': msg}
    
    return {'type': 'unknown'}

# ====================================================
# V. לוגיקה מרכזית
# ====================================================

def handle_logging(user_id, parsed, user):
    baby = user.get(KEY_NAME, 'הבייבי')
    etype = parsed['type']
    res = []

    if etype == 'sleep_start':
        user[KEY_SLEEP_START] = get_now_tz().isoformat()
        save_user_data(user['id'], user)
        res.append(f"לילה טוב ל{baby}... 😴")
    
    elif etype == 'sleep_end':
        start_str = user.get(KEY_SLEEP_START)
        if not start_str: res.append(f"רשמתי ש{baby} התעורר! ☀️")
        else:
            diff = get_now_tz() - dt.datetime.fromisoformat(start_str)
            mins = int(diff.total_seconds() / 60)
            user[KEY_SLEEP_START] = None
            add_event(user['id'], 'שינה', {'משך': f"{mins} דקות"})
            res.append(f"בוקר טוב! {baby} ישן {mins} דקות. ✨")
            save_user_data(user['id'], user)

    elif etype == 'breastfeeding':
        add_event(user['id'], 'הנקה', {'צד': parsed['side'], 'זמן': f"{parsed['duration']} דק'"})
        res.append(f"רשמתי הנקה ({parsed['side']}). את אלופה! ❤️")

    elif etype == 'bottle':
        add_event(user['id'], 'בקבוק', {'כמות': f"{parsed['amount']} מ\"ל"})
        res.append(f"רשמתי בקבוק של {parsed['amount']} מ\"ל. 🍼")

    elif etype == 'diaper':
        add_event(user['id'], 'חיתול', {'סוג': parsed['diaper_type']})
        res.append(f"חיתול נרשם ({parsed['diaper_type']}). ✅")

    # בדיקת עידוד
    today = get_today_tz().strftime("%Y-%m-%d")
    count = sum(1 for e in user.get(KEY_EVENTS, []) if e['timestamp'].startswith(today))
    tiers = user.get(KEY_ENCOURAGEMENT_TIER, {})
    last_t = tiers.get(today, 0)
    for t, m in MILESTONE_TIERS.items():
        if count >= t and t > last_t:
            tiers[today] = t
            user[KEY_ENCOURAGEMENT_TIER] = tiers
            save_user_data(user['id'], user)
            res.append(m)
            break

    return res

# ====================================================
# VI. Webhook
# ====================================================

app = Flask(__name__)

@app.route("/sms", methods=['POST'])
def whatsapp_webhook():
    msg_text = request.values.get('Body', '').strip()
    from_uid = normalize_user_id(request.values.get('From', ''))
    user = get_user_data(from_uid)
    resp = MessagingResponse()

    if msg_text.lower() in ['אפס', 'reset']:
        db.remove(User.id == from_uid)
        resp.message("איתחלנו! שלחי הודעה להרשמה. ❤️")
        return str(resp)

    # הרשמה
    if not user or user.get('stage', 0) < 5:
        # (כאן תבוא לוגיקת ה-Onboarding המלאה שלך מהקובץ המקורי)
        # למשל: if stage == 0: ...
        resp.message("היי! אני בילי... 😊 איך קוראים לך?") # דוגמה להתחלה
        return str(resp)

    parsed = parse_input(msg_text)
    
    if parsed['type'] == 'help_menu':
        resp.message(HELP_TOPICS['menu'])
    elif parsed['type'] == 'help_item':
        resp.message(HELP_TOPICS[parsed['id']]['text'] + LEGAL_DISCLAIMER)
    elif parsed['type'] == 'status':
        age = calculate_age(user.get(KEY_DOB))
        summary = f"סטטוס עבור {user.get(KEY_NAME)} ({age}):\n"
        for e in user.get(KEY_EVENTS, [])[-5:]:
            summary += f"• {e['type']}: {e['details']} ({e['timestamp'][-8:-3]})\n"
        resp.message(summary)
    else:
        for r in handle_logging(from_uid, parsed, user):
            resp.message(r)

    return str(resp)

if __name__ == "__main__":
    app.run(port=10000)

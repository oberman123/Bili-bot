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
KEY_SLEEP_START = 'sleep_start_time' # מפתח חדש לטיימר שינה

MILESTONE_TIERS = { 
    4: "מדהים! עקביות זה שם המשחק. רק ארבעה אירועים ואת כבר מנצחת את היום! 🏆",
    8: "וואו, תדעי שאת עוקבת ומנהלת את הכל בצורה מושלמת. איזו השקעה 👏",
    12: "את שיאנית! המערכת שלך מסודרת בזכותך. קחי נשימה עמוקה, עשית עבודה מעולה היום. ❤️"
}

HELP_TOPICS = {
    'menu': "איך אפשר לעזור? 🌱\n\nבחרי נושא (או כתבי את המספר):\n1️⃣ טיפול בחלב אם\n2️⃣ דברים שחשוב לשים לב בהנקה\n3️⃣ נורות אזהרה\n4️⃣ המלצות כלליות להנקה\n\n(אפשר לבחור במילים או במספר)",
    '1': {'keywords': ['טיפול'], 'text': "• לשמור בקירור עד 4 ימים..."}, # מקוצר לצורך התצוגה
    '2': {'keywords': ['שים לב'], 'text': "• שהתינוק בולע ולא רק מוצץ..."},
    '3': {'keywords': ['אזהרה'], 'text': "• חום או אודם בשד..."},
    '4': {'keywords': ['המלצות'], 'text': "• להחליף צדדים בין הנקות..."},
}

LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי._"

# ====================================================
# II. פונקציות עזר (זמן, נרמול, DB)
# ====================================================

def get_now_tz() -> dt.datetime:
    return dt.datetime.now()

def get_today_tz() -> dt.date:
    return dt.datetime.now().date()

def normalize_user_id(user_id: str) -> str:
    if user_id.startswith('whatsapp:'):
        user_id = user_id[9:]
    return user_id

def get_user_data_single(user_id: str) -> dict or None:
    return db.get(User.id == normalize_user_id(user_id))

def save_user_data(user_id: str, data: dict):
    data['id'] = normalize_user_id(user_id)
    db.upsert(data, User.id == data['id'])

def add_event(user_id: str, event_type: str, details: dict):
    user = get_user_data_single(user_id)
    if not user: return
    event = {
        'type': event_type,
        'timestamp': get_now_tz().strftime("%Y-%m-%d %H:%M:%S.%f"), 
        'details': details
    }
    user.setdefault(KEY_EVENTS, []).append(event)
    save_user_data(user_id, user)

# ====================================================
# III. NLP - זיהוי קלט (כולל שינה וטיימר)
# ====================================================

def parse_input(message: str) -> dict:
    msg = message.lower().strip()
    
    # זיהוי שינה (טיימר ושינה רגילה)
    if any(w in msg for w in ['נרדם', 'הלך לישון', 'מתחיל לישון']):
        return {'type': 'sleep_start'}
    if any(w in msg for w in ['קם', 'התעורר', 'סיים לישון']):
        return {'type': 'sleep_end'}
    if 'ישן' in msg or 'שינה' in msg:
        # בדיקה אם צוין זמן (למשל "ישן שעה")
        duration_match = re.search(r'(\d+)\s*(דק|דקות|שעה|שעות)', msg)
        return {'type': 'sleep_manual', 'duration': duration_match.group(0) if duration_match else 'לא צוין'}

    # יתר הזיהויים (הנקה, בקבוק, חיתול וכו' - כפי שמופיע בקוד המקור שלך)
    if any(keyword in msg for keyword in ['ינק', 'הנקה', 'ימין', 'שמאל']):
        side_match = re.search(r'(ימין|שמאל)', msg)
        dur_match = re.search(r'\d+', msg)
        return {'type': 'breastfeeding', 'side': side_match.group(1) if side_match else 'לא צוין', 'duration': int(dur_match.group(0)) if dur_match else 0}
    
    if 'בקבוק' in msg:
        amount = re.search(r'\d+', msg)
        return {'type': 'bottle', 'amount': int(amount.group(0)) if amount else 0}

    if any(w in msg for w in ['קקי', 'פיפי', 'חיתול']):
        d_type = 'poo' if 'קקי' in msg else 'pee' if 'פיפי' in msg else 'both'
        return {'type': 'diaper', 'diaper_type': d_type}

    if msg == 'סטטוס': return {'type': 'status'}
    if msg == 'עזרה': return {'type': 'help_menu'}
    
    return {'type': 'unknown'}

# ====================================================
# IV. לוגיקה מרכזית
# ====================================================

def handle_message(user_id: str, message: str) -> list[str]:
    user = get_user_data_single(user_id)
    if not user: # Onboarding (מקוצר כאן, תואם לקוד המקור שלך)
        # ... לוגיקת הרשמה ...
        pass 

    parsed = parse_input(message)
    baby_name = user.get(KEY_NAME, 'הבייבי')

    # טיפול בטיימר שינה
    if parsed['type'] == 'sleep_start':
        user[KEY_SLEEP_START] = get_now_tz().isoformat()
        save_user_data(user_id, user)
        return [f"לילה טוב ל{baby_name}... 😴 רשמתי מתי הוא נרדם. כשנתעורר, פשוט תכתבי לי 'הוא קם'."]

    if parsed['type'] == 'sleep_end':
        start_str = user.get(KEY_SLEEP_START)
        if not start_str:
            return ["לא רשמתי מתי הוא נרדם, אבל אין בעיה - רשמתי שהוא התעורר עכשיו! ✨"]
        
        start_time = dt.datetime.fromisoformat(start_str)
        end_time = get_now_tz()
        duration = end_time - start_time
        minutes = int(duration.total_seconds() / 60)
        
        user[KEY_SLEEP_START] = None # איפוס טיימר
        add_event(user_id, 'sleep', {'duration': f"{minutes} דקות", 'method': 'timer'})
        return [f"בוקר טוב! ☀️ {baby_name} ישן {minutes} דקות. הוספתי ליומן."]

    if parsed['type'] == 'sleep_manual':
        add_event(user_id, 'sleep', {'duration': parsed['duration'], 'method': 'manual'})
        return [f"רשמתי ש{baby_name} ישן ({parsed['duration']})."]

    # לוגיקת תיעוד רגילה (הנקה, חיתול וכו')
    # ... כאן נכנסת הפונקציה handle_logging_action מהקוד המקורי שלך ...
    return ["נרשם!"] # תגובה גנרית לצורך הדוגמה

# ====================================================
# V. Flask Server
# ====================================================

app = Flask(__name__)

@app.route("/sms", methods=['POST'])
def whatsapp_webhook():
    msg = request.values.get('Body', '')
    uid = request.values.get('From', '')
    
    resp = MessagingResponse()
    responses = handle_message(uid, msg)
    for r in responses:
        resp.message(r)
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True, port=5000)

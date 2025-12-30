import os
import datetime as dt
import re
import random
import psycopg2
import psycopg2.extras
from datetime import timedelta
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# ====================================================
# I. הגדרות וחיבור למסד הנתונים
# ====================================================

def get_db_connection():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # מוחקים את הטבלה הישנה כדי לרענן את המבנה לעמודת JSONB
    cur.execute("DROP TABLE IF EXISTS users;") 
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            phone_number TEXT PRIMARY KEY,
            data JSONB DEFAULT '{}'::jsonb,
            registration_step TEXT DEFAULT 'START'
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ====================================================
# II. לוגיקה שפתית (NLP)
# ====================================================

def parse_input(text):
    text = text.lower().strip()
    parsed = {
        'event_type': None,
        'side': None,
        'duration': None,
        'amount': None,
        'is_start': any(word in text for word in ['נרדם', 'מתחילה', 'התחלתי']),
        'is_end': any(word in text for word in ['קם', 'התעורר', 'סיימתי', 'סיימה'])
    }

    # זיהוי דקות
    duration_match = re.search(r'(\d+)\s*(דקות|דק|דקה)', text)
    if duration_match:
        parsed['duration'] = int(duration_match.group(1))
    elif 'חצי שעה' in text: parsed['duration'] = 30
    elif 'רבע שעה' in text: parsed['duration'] = 15

    # סיווג אירוע
    if any(word in text for word in ['הנקה', 'ינק', 'צד', 'ימין', 'שמאל']):
        parsed['event_type'] = 'breastfeeding'
        parsed['side'] = 'ימין' if 'ימין' in text else 'שמאל' if 'שמאל' in text else None
    elif 'בקבוק' in text:
        parsed['event_type'] = 'bottle'
        amount = re.findall(r'\d+', text)
        if amount: parsed['amount'] = amount[0]
    elif any(word in text for word in ['ישן', 'נרדם', 'קם', 'התעורר', 'שינה']):
        parsed['event_type'] = 'sleep'
    elif any(word in text for word in ['סטטוס', 'סיכום', 'פרטי']):
        parsed['event_type'] = 'status'
    elif 'עזרה' in text:
        parsed['event_type'] = 'help'

    return parsed

def get_gender_strings(gender):
    if 'בת' in str(gender):
        return {"suffix": "ה", "verb_sleep": "ישנה", "verb_wake": "התעוררה", "verb_eat": "ינקה", "verb_drink": "שתתה"}
    return {"suffix": "", "verb_sleep": "ישן", "verb_wake": "התעורר", "verb_eat": "ינק", "verb_drink": "שתה"}

# ====================================================
# III. ניהול ה-Webhook (הודעות נכנסות)
# ====================================================

@app.route("/sms", methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    user_phone = request.values.get('From', '')
    resp = MessagingResponse()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT data, registration_step FROM users WHERE phone_number = %s", (user_phone,))
    row = cur.fetchone()
    
    if not row:
        cur.execute("INSERT INTO users (phone_number, registration_step) VALUES (%s, 'START')", (user_phone,))
        conn.commit()
        user_data, step = {}, 'START'
    else:
        user_data, step = row

    # --- תהליך רישום ---
    if step != 'COMPLETED':
        if step == 'START':
            resp.message("היי! 👋 אני בילי... אני כאן כדי לעזור לך לתעד ולהקל על החודשים הראשונים. את אלופה! 😍\n\nאיך קוראים לך?")
            cur.execute("UPDATE users SET registration_step = 'ASK_GENDER' WHERE phone_number = %s", (user_phone,))
        elif step == 'ASK_GENDER':
            user_data['mom_name'] = incoming_msg
            resp.message(f"נעים מאוד {incoming_msg}! ❤️ מה נולד לנו? (בן/בת)")
            cur.execute("UPDATE users SET data = %s, registration_step = 'ASK_BABY_NAME' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
        elif step == 'ASK_BABY_NAME':
            user_data['baby_gender'] = incoming_msg
            resp.message(f"מזל טוב! ואיך קראתם ל{'קטן' if 'בן' in incoming_msg else 'קטנה'}?")
            cur.execute("UPDATE users SET data = %s, registration_step = 'ASK_DOB' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
        elif step == 'ASK_DOB':
            user_data['baby_name'] = incoming_msg
            resp.message(f"שם מהמם! מתי {incoming_msg} נולד/ה? (תאריך)")
            cur.execute("UPDATE users SET data = %s, registration_step = 'COMPLETED' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
        elif step == 'COMPLETED':
            user_data['events'] = []
            resp.message(f"איזה כיף! סיימנו. פשוט כתבי לי מה קורה: 'הנקה ימין', 'נרדם' או 'סטטוס'. שנתחיל?")
            cur.execute("UPDATE users SET data = %s, registration_step = 'COMPLETED' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
        
        conn.commit()
        cur.close()
        conn.close()
        return str(resp)

    # --- לוגיקה לאחר רישום ---
    parsed = parse_input(incoming_msg)
    baby_name = user_data.get('baby_name', 'הבייבי')
    gender_data = get_gender_strings(user_data.get('baby_gender', 'בן'))
    now = dt.datetime.now()

    if parsed['event_type'] in ['breastfeeding', 'sleep']:
        if parsed['duration']:
            action = "הנקה" if parsed['event_type'] == 'breastfeeding' else "שינה"
            resp.message(f"רשמתי ש{baby_name} {action} {parsed['duration']} דקות. את אלופה! ❤️")
            user_data.setdefault('events', []).append({'type': action, 'duration': parsed['duration'], 'time': now.isoformat()})
        elif parsed['is_end']:
            last_event = next((e for e in reversed(user_data.get('events', [])) if e['type'] == parsed['event_type'] and 'end_time' not in e), None)
            if last_event:
                start_time = dt.datetime.fromisoformat(last_event['time'])
                duration = int((now - start_time).total_seconds() / 60)
                last_event['end_time'] = now.isoformat()
                last_event['duration'] = duration
                resp.message(f"בוקר טוב! {baby_

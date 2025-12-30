import os
import psycopg2
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timedelta
import pytz

app = Flask(__name__)
Israel_TZ = pytz.timezone('Asia/Jerusalem')

def get_db_connection():
    return psycopg2.connect(os.environ['DATABASE_URL'])

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            phone_number TEXT PRIMARY KEY,
            user_name TEXT,
            baby_name TEXT,
            baby_gender TEXT,
            baby_birthday TEXT,
            registration_step TEXT DEFAULT 'START'
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id SERIAL PRIMARY KEY,
            phone_number TEXT,
            event_type TEXT,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            value TEXT,
            sub_type TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

@app.route("/sms", methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').strip()
    phone_number = request.values.get('From', '')
    resp = MessagingResponse()
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_name, baby_name, baby_gender, registration_step FROM users WHERE phone_number = %s", (phone_number,))
    user = cur.fetchone()

    # --- תהליך רישום ---
    if not user or user[3] != 'COMPLETED':
        step = user[3] if user else 'START'
        if step == 'START':
            welcome = "היי! 👋 אני בילי... אני פה כדי לעזור לך לתעד ולהקל על החודשים הראשונים! את אלופה! 😍\n\nאיך קוראים לך?"
            resp.message(welcome)
            cur.execute("INSERT INTO users (phone_number, registration_step) VALUES (%s, 'ASK_BABY_NAME') ON CONFLICT (phone_number) DO UPDATE SET registration_step = 'ASK_BABY_NAME'", (phone_number,))
        elif step == 'ASK_BABY_NAME':
            cur.execute("UPDATE users SET user_name = %s, registration_step = 'ASK_GENDER' WHERE phone_number = %s", (incoming_msg, phone_number))
            resp.message(f"נעים מאוד {incoming_msg}! ❤️ איך קראתם לבייבי?")
        elif step == 'ASK_GENDER':
            cur.execute("UPDATE users SET baby_name = %s, registration_step = 'ASK_BIRTHDAY' WHERE phone_number = %s", (incoming_msg, phone_number))
            resp.message(f"שם מהמם! {incoming_msg} הוא בן או בת?")
        elif step == 'ASK_BIRTHDAY':
            gender = 'בת' if 'בת' in incoming_msg else 'בן'
            cur.execute("UPDATE users SET baby_gender = %s, registration_step = 'CONFIRM_DONE' WHERE phone_number = %s", (gender, phone_number))
            resp.message(f"רשמתי! ומתי {user[1] if user else 'הוא/היא'} נולד/ה? 🎂")
        elif step == 'CONFIRM_DONE':
            cur.execute("UPDATE users SET baby_birthday = %s, registration_step = 'COMPLETED' WHERE phone_number = %s", (incoming_msg, phone_number))
            about_bili = (
                f"איזה כיף! סיימנו את הרישום. 🎊\n\n"
                f"*למה אני פה?*\n"
                f"אני אעזור לך לעקוב אחרי זמני שינה, הנקות ובקבוקים. בכל רגע תוכלי לדעת מתי הייתה ההנקה האחרונה או כמה הבייבי ישן היום.\n\n"
                f"✨ *שינה:* 'נרדם', 'קם', או 'ישן 20 דקות'.\n"
                f"✨ *אוכל:* 'הנקה ימין' או 'בקבוק 60'.\n"
                f"✨ *סטטוס:* כתבי 'סטטוס' לסיכום היום.\n"
                f"✨ *עזרה:* כתבי 'עזרה' לתפריט המידע.\n\nשנתחיל?"
            )
            resp.message(about_bili)
        conn.commit()
        return str(resp)

    user_name, baby_name, baby_gender, _ = user
    suffix = "ה" if baby_gender == 'בת' else ""

    # --- פקודת סטטוס (חדש!) ---
    if incoming_msg in ['סטטוס', 'סיכום', 'מה היה היום']:
        today = datetime.now(Israel_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        cur.execute("SELECT event_type, value, start_time FROM events WHERE phone_number = %s AND start_time >= %s", (phone_number, today))
        events = cur.fetchall()
        
        if not events:
            resp.message(f"עוד לא רשמנו כלום היום עבור {baby_name}. הכל בסדר, אני כאן כשתיצטרכי! ❤️")
        else:
            summary = f"📊 *סיכום היום של {baby_name}:*\n"
            for e_type, val, s_time in events:
                summary += f"- {e_type}: {val} (ב-{s_time.strftime('%H:%M')})\n"
            resp.message(summary)
        return str(resp)

    # --- שאר הפקודות (עזרה, אוכל, שינה) ---
    if 'עזרה' in incoming_msg:
        help_msg = "איך אפשר לעזור? 🌱\n1️⃣ טיפול בחלב אם\n2️⃣ דגשים להנקה\n3️⃣ נורות אזהרה\n4️⃣ המלצות כלליות"
        resp.message(help_msg)
    elif "בקבוק" in incoming_msg:
        cur.execute("INSERT INTO events (phone_number, event_type, start_time, value) VALUES (%s, 'בקבוק', %s, %s)", 
                    (phone_number, 'בקבוק', datetime.now(Israel_TZ), incoming_msg))
        resp.message(f"רשמתי! {baby_name} קיבל/ה בקבוק. את אלופה! ❤️")
    elif "נרדם" in incoming_msg or "ישן" in incoming_msg:
        cur.execute("INSERT INTO events (phone_number, event_type, start_time, value) VALUES (%s, 'שינה', %s, %s)", 
                    (phone_number, 'שינה', datetime.now(Israel_TZ), incoming_msg))
        resp.message(f"לילה/צהריים טובים ל{baby_name}! רשמתי שהיא/הוא ישן. תנוחי גם את! 😴")
    else:
        resp.message(f"היי {user_name}, לא בטוחה שהבנתי... 🤔 כתבי 'עזרה' כדי לראות מה אני יכולה לעשות!")

    conn.commit()
    cur.close()
    conn.close()
    return str(resp)

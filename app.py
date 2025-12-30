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
    # יצירת הטבלאות עם עמודת תאריך הלידה
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

    # --- תהליך רישום (סעיפים א, ב, ג) ---
    if not user or user[3] != 'COMPLETED':
        step = user[3] if user else 'START'
        
        if step == 'START':
            welcome = (
                "היי! 👋\nאני בילי...\nאני פה כדי לעזור לך לשמור, לתעד, להקל ולהנות מכל מה שקשור בחודשים הראשונים עם הבייבי שלך! 🤱\n\n"
                "דבר ראשון, את אלופה! זאת תקופה מהממת ונעבור אותה יחד! 😍\n\n"
                "כדי שאוכל לפנות אלייך אישית - איך קוראים לך? (שם פרטי מספיק)."
            )
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
                f"איזה כיף! סיימנו את ה

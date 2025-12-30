import os
import psycopg2
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timedelta
import pytz
import time

app = Flask(__name__)

# הגדרות זמן ישראל
Israel_TZ = pytz.timezone('Asia/Jerusalem')

def get_db_connection():
    return psycopg2.connect(os.environ['DATABASE_URL'])

# יצירת טבלאות (כולל טבלת משתמשים ומידע על התינוק)
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # טבלת משתמשים לרישום ראשוני
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            phone_number TEXT PRIMARY KEY,
            user_name TEXT,
            baby_name TEXT,
            baby_gender TEXT,
            baby_birthday DATE,
            registration_step TEXT DEFAULT 'START'
        )
    ''')
    # טבלת אירועים
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
    
    # בדיקה אם המשתמש רשום
    cur.execute("SELECT user_name, baby_name, baby_gender, registration_step FROM users WHERE phone_number = %s", (phone_number,))
    user = cur.fetchone()

    # --- לוגיקת רישום (סעיפים א, ב, ג) ---
    if not user or user[3] != 'COMPLETED':
        step = user[3] if user else 'START'
        
        if step == 'START':
            msg = resp.message("היי! 👋\nאני בילי...\nאני פה כדי לעזור לך לשמור, לתעד, להקל ולהנות מכל מה שקשור בחודשים הראשונים עם הבייבי שלך! 🤱\n\nדבר ראשון, את אלופה! זאת תקופה מהממת ונעבור אותה יחד! 😍")
            time.sleep(1)
            resp.message("כדי שאוכל לפנות אלייך אישית - איך קוראים לך? (שם פרטי מספיק).")
            cur.execute("INSERT INTO users (phone_number, registration_step) VALUES (%s, 'ASK_BABY_GENDER') ON CONFLICT (phone_number) DO UPDATE SET registration_step = 'ASK_BABY_GENDER'", (phone_number,))
        
        elif step == 'ASK_BABY_GENDER':
            cur.execute("UPDATE users SET user_name = %s, registration_step = 'ASK_BABY_NAME' WHERE phone_number = %s", (incoming_msg, phone_number))
            resp.message(f"נעים מאוד {incoming_msg}! ❤️\nמה נולד לנו? (בן/בת)")
            
        elif step == 'ASK_BABY_NAME':
            gender = 'בן' if 'בן' in incoming_msg else 'בת'
            cur.execute("UPDATE users SET baby_gender = %s, registration_step = 'ASK_BABY_BIRTHDAY' WHERE phone_number = %s", (gender, phone_number))
            resp.message(f"מזל טוב! ואיך קראתם ל{('קטן' if gender=='בן' else 'קטנה')}?")
            
        elif step == 'ASK_BABY_BIRTHDAY':
            cur.execute("UPDATE users SET baby_name = %s, registration_step = 'COMPLETED' WHERE phone_number = %s", (incoming_msg, phone_number))
            user_data = cur.execute("SELECT user_name, baby_name, baby_gender FROM users WHERE phone_number = %s", (phone_number,)).fetchone()
            
            # הודעת הסבר עדינה (סעיף ד)
            resp.message(f"איזה שם מהמם! 😍\nמעכשיו אני כאן איתך. את יכולה פשוט לכתוב לי מה קורה:\n\n✨ *שינה:* 'נרדם' או 'קם' (או 'ישן 20 דקות').\n✨ *אוכל:* 'הנקה ימין' או 'בקבוק 60'.\n✨ *עזרה:* פשוט כתבי 'עזרה' בכל שלב.\n\nשנתחיל?")
        
        conn.commit()
        return str(resp)

    # --- לוגיקת תפעול שוטף (אחרי רישום) ---
    user_name, baby_name, baby_gender, _ = user
    suffix = "" if baby_gender == 'בן' else 'ה'
    
    # עזרה (סעיפים ז, ח)
    if incoming_msg in ['עזרה', 'help', 'Help']:
        msg = "איך אפשר לעזור? 🌱\n\nבחרי נושא (או כתבי את המספר):\n1️⃣ טיפול בחלב אם\n2️⃣ דברים שחשוב לשים לב בהנקה\n3️⃣ נורות אזהרה\n4️⃣ המלצות כלליות להנקה\n\n💡 *טיפ:* כדי לתעד, פשוט כתבי לי מה קרה (למשל: 'הנקה שמאל' או 'ישן שעה')."
        resp.message(msg)

    # שינה ידנית (סעיף ט)
    elif "ישן" in incoming_msg and any(char.isdigit() for char in incoming_msg):
        # חילוץ דקות (לוגיקה פשוטה)
        minutes = [int(s) for s in incoming_msg.split() if s.isdigit()][0]
        now = datetime.now(Israel_TZ)
        cur.execute("INSERT INTO events (phone_number, event_type, start_time, end_time, value) VALUES (%s, 'sleep', %s, %s, %s)", 
                    (phone_number, 'sleep', now - timedelta(minutes=minutes), now, f"{minutes} דקות"))
        resp.message(f"איזה יופי, נרשם ש{baby_name} ישנ{suffix} {minutes} דקות. כל דקה של מנוחה חשובה! 🌟")

    # טיפול ב'התעורר' ללא טיימר (סעיף ט)
    elif incoming_msg == "קם" or incoming_msg == "התעורר":
        cur.execute("SELECT id, start_time FROM events WHERE phone_number = %s AND event_type = 'sleep' AND end_time IS NULL", (phone_number,))
        active_sleep = cur.fetchone()
        if active_sleep:
            # לוגיקה קיימת לסגירת טיימר
            pass 
        else:
            resp.message(f"שמחה ש{baby_name} התעורר{suffix}! לא הפעלנו טיימר לפני כן... כמה זמן לדעתך הוא/היא ישנ{suffix}? (כתבי לי רק את מספר הדקות)")

    # בקבוק (סעיף י)
    elif "בקבוק" in incoming_msg:
        resp.message(f"כמה {baby_name} שת{('ה' if baby_gender=='בת' else '')}? (כתבי לי כמות ב-מ\"ל)")

    else:
        resp.message("קיבלתי, אני רושמת לי. את עושה עבודה מדהימה! ❤️")

    conn.commit()
    cur.close()
    conn.close()
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

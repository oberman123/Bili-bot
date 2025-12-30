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

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # איפוס טבלאות כדי לוודא שכל העמודות החדשות קיימות
    cur.execute("DROP TABLE IF EXISTS users CASCADE")
    cur.execute("DROP TABLE IF EXISTS events CASCADE")
    
    cur.execute('''
        CREATE TABLE users (
            phone_number TEXT PRIMARY KEY,
            user_name TEXT,
            baby_name TEXT,
            baby_gender TEXT,
            baby_birthday DATE,
            registration_step TEXT DEFAULT 'START'
        )
    ''')
    cur.execute('''
        CREATE TABLE events (
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

# הרצת יצירת הטבלאות בכל פעם שהאפליקציה עולה (כדי לוודא תקינות)
init_db()

@app.route("/sms", methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').strip()
    phone_number = request.values.get('From', '')
    resp = MessagingResponse()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # בדיקת משתמש
    cur.execute("SELECT user_name, baby_name, baby_gender, registration_step FROM users WHERE phone_number = %s", (phone_number,))
    user = cur.fetchone()

    # --- תהליך רישום ---
    if not user or user[3] != 'COMPLETED':
        step = user[3] if user else 'START'
        
        if step == 'START':
            welcome_text = (
                "היי! 👋\n"
                "אני בילי...\n"
                "אני פה כדי לעזור לך לשמור, לתעד, להקל ולהנות מכל מה שקשור בחודשים הראשונים עם הבייבי שלך! 🤱\n\n"
                "דבר ראשון, את אלופה! זאת תקופה מהממת ונעבור אותה יחד! 😍\n\n"
                "כדי שאוכל לפנות אלייך אישית - איך קוראים לך? (שם פרטי מספיק)."
            )
            resp.message(welcome_text)
            cur.execute("INSERT INTO users (phone_number, registration_step) VALUES (%s, 'ASK_BABY_GENDER')", (phone_number,))
        
        elif step == 'ASK_BABY_GENDER':
            cur.execute("UPDATE users SET user_name = %s, registration_step = 'ASK_BABY_NAME' WHERE phone_number = %s", (incoming_msg, phone_number))
            resp.message(f"נעים מאוד {incoming_msg}! ❤️\nמה נולד לנו? (בן/בת)")
            
        elif step == 'ASK_BABY_NAME':
            gender = 'בת' if 'בת' in incoming_msg else 'בן'
            cur.execute("UPDATE users SET baby_gender = %s, registration_step = 'ASK_BABY_BIRTHDAY' WHERE phone_number = %s", (gender, phone_number))
            label = "לקטנה" if gender == 'בת' else "לקטן"
            resp.message(f"מזל טוב! ואיך קראתם {label}?")
            
        elif step == 'ASK_BABY_BIRTHDAY':
            cur.execute("UPDATE users SET baby_name = %s, registration_step = 'COMPLETED' WHERE phone_number = %s", (incoming_msg, phone_number))
            resp.message(
                f"איזה שם מהמם! 😍\n"
                f"מעכשיו אני כאן איתך. את יכולה פשוט לכתוב לי מה קורה:\n\n"
                f"✨ *שינה:* 'נרדם', 'קם', או 'ישן 20 דקות'.\n"
                f"✨ *אוכל:* 'הנקה ימין' או 'בקבוק 60'.\n"
                f"✨ *עזרה:* כתבי 'עזרה' לתפריט המלא.\n\n"
                f"שנתחיל?"
            )
        
        conn.commit()
        cur.close()
        conn.close()
        return str(resp)

    # --- לוגיקה אחרי רישום ---
    user_name, baby_name, baby_gender, _ = user
    suffix = "ה" if baby_gender == 'בת' else ""
    
    # פקודת עזרה (סעיפים ז, ח, ו)
    if incoming_msg in ['עזרה', 'Help', 'סטטוס', 'פירוט']:
        help_msg = (
            "איך אפשר לעזור? 🌱\n\n"
            "בחרי נושא (או כתבי את המספר):\n"
            "1️⃣ טיפול בחלב אם\n"
            "2️⃣ דברים שחשוב לשים לב בהנקה\n"
            "3️⃣ נורות אזהרה\n"
            "4️⃣ המלצות כלליות להנקה\n\n"
            "💡 *איך עובדים מולי?*\n"
            "פשוט כתבי לי מה קרה. למשל: 'נרדם', 'הנקה ימין', 'בקבוק 90' או 'ישנה חצי שעה'."
        )
        resp.message(help_msg)

    # שינה ידנית (סעיף ט)
    elif "ישן" in incoming_msg and any(char.isdigit() for char in incoming_msg):
        try:
            minutes = [int(s) for s in incoming_msg.split() if s.isdigit()][0]
            now = datetime.now(Israel_TZ)
            cur.execute("INSERT INTO events (phone_number, event_type, start_time, end_time, value) VALUES (%s, 'sleep', %s, %s, %s)", 
                        (phone_number, 'sleep', now - timedelta(minutes=minutes), now, f"{minutes} דקות"))
            resp.message(f"איזה יופי, נרשם ש{baby_name} ישנ{suffix} {minutes} דקות. כל דקה של מנוחה חשובה! 🌟")
        except:
            resp.message("לא הצלחתי להבין כמה זמן... נסי לכתוב למשל 'ישן 30 דקות'.")

    # התעוררות ללא טיימר (סעיף ט)
    elif incoming_msg in ["קם", "התעורר", "התעוררה"]:
        cur.execute("SELECT id FROM events WHERE phone_number = %s AND event_type = 'sleep' AND end_time IS NULL", (phone_number,))
        if not cur.fetchone():
            resp.message(f"שמחה ש{baby_name} התעורר{suffix}! לא הפעלנו טיימר לפני כן... כמה זמן לדעתך הוא/היא ישנ{suffix}? (כתבי לי רק את מספר הדקות)")
        else:
            now = datetime.now(Israel_TZ)
            cur.execute("UPDATE events SET end_time = %s WHERE phone_number = %s AND event_type = 'sleep' AND end_time IS NULL", (now, phone_number))
            resp.message(f"בוקר טוב ל{baby_name}! ☀️ רשמתי שהיא התעוררה. את אלופה!")

    # בקבוק (סעיף י)
    elif "בקבוק" in incoming_msg:
        label = "שתתה" if baby_gender == 'בת' else "שתה"
        resp.message(f"כמה {baby_name} {label}? 🍼 (כתבי לי כמות ב-מ\"ל, למשל: 90)")

    # תגובה גנרית תומכת (סעיף יא)
    else:
        resp.message(f"קיבלתי, רשמתי לי! את עושה עבודה מדהימה עם {baby_name}. ❤️")

    conn.commit()
    cur.close()
    conn.close()
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

import os
import datetime as dt
import re
import psycopg2
import psycopg2.extras
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
    # איפוס טבלה כדי לוודא מבנה עמודות תקין
    cur.execute("DROP TABLE IF EXISTS users;") 
    cur.execute('''
        CREATE TABLE users (
            phone_number TEXT PRIMARY KEY,
            data JSONB DEFAULT '{}'::jsonb,
            registration_step TEXT DEFAULT 'START'
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# הרצה בכל עליה של השרת
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

    duration_match = re.search(r'(\d+)\s*(דקות|דק|דקה)', text)
    if duration_match:
        parsed['duration'] = int(duration_match.group(1))
    
    if any(word in text for word in ['הנקה', 'ינק', 'צד', 'ימין', 'שמאל']):
        parsed['event_type'] = 'breastfeeding'
        parsed['side'] = 'ימין' if 'ימין' in text else 'שמאל' if 'שמאל' in text else None
    elif 'בקבוק' in text:
        parsed['event_type'] = 'bottle'
        amount = re.findall(r'\d+', text)
        if amount: parsed['amount'] = amount[0]
    elif any(word in text for word in ['ישן', 'נרדם', 'קם', 'התעורר', 'שינה']):
        parsed['event_type'] = 'sleep'
    elif any(word in text for word in ['סטטוס', 'סיכום']):
        parsed['event_type'] = 'status'
    
    return parsed

# ====================================================
# III. ניהול ה-Webhook וההרשמה
# ====================================================

@app.route("/sms", methods=['POST'])
def whatsapp_webhook():
    incoming_msg = request.values.get('Body', '').strip()
    user_phone = request.values.get('From', '')
    resp = MessagingResponse()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT data, registration_step FROM users WHERE phone_number = %s", (user_phone,))
        row = cur.fetchone()
        
        if not row:
            cur.execute("INSERT INTO users (phone_number, registration_step) VALUES (%s, 'START')", (user_phone,))
            conn.commit()
            user_data, step = {}, 'START'
        else:
            user_data, step = row

        # פקודת איפוס ידנית
        if incoming_msg in ['אפס', 'reset']:
            cur.execute("UPDATE users SET registration_step = 'START', data = '{}' WHERE phone_number = %s", (user_phone,))
            conn.commit()
            resp.message("מערכת אותחלה. שלחי הודעה כלשהי כדי להתחיל מחדש.")
            return str(resp)

        # לוגיקת הרשמה (Onboarding)
        if step != 'COMPLETED':
            if step == 'START':
                welcome_msg = (
                    "היי! 👋 אני בילי... פה כדי לעזור לך לשמור, לתעד, ולהקל עלייך בחודשים הראשונים עם הבייבי! "
                    "דבר ראשון, את אלופה! ❤️ כדי שנתחיל - איך קוראים לך?"
                )
                resp.message(welcome_msg)
                cur.execute("UPDATE users SET registration_step = 'ASK_GENDER' WHERE phone_number = %s", (user_phone,))
            
            elif step == 'ASK_GENDER':
                user_data['mom_name'] = incoming_msg
                resp.message(f"נעים מאוד {incoming_msg}! מה נולד לנו? (בן/בת)")
                cur.execute("UPDATE users SET data = %s, registration_step = 'ASK_BABY_NAME' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
            
            elif step == 'ASK_BABY_NAME':
                user_data['baby_gender'] = 'male' if 'בן' in incoming_msg else 'female'
                prompt = "איך קראתם לקטן?" if user_data['baby_gender'] == 'male' else "איך קראתם לקטנה?"
                resp.message(f"מזל טוב! {prompt}")
                cur.execute("UPDATE users SET data = %s, registration_step = 'ASK_DOB' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
            
            elif step == 'ASK_DOB':
                user_data['baby_name'] = incoming_msg
                resp.message(f"שם מהמם! מתי {incoming_msg} נולד/ה? (למשל: 21.05.2024)")
                cur.execute("UPDATE users SET data = %s, registration_step = 'FINALIZE' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
            
            elif step == 'FINALIZE':
                user_data['dob'] = incoming_msg
                user_data['events'] = []
                resp.message("סיימנו! עכשיו את יכולה לכתוב לי דברים כמו 'הנקה 10 דקות' או 'קם משינה'. אני פה!")
                cur.execute("UPDATE users SET data = %s, registration_step = 'COMPLETED' WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
            
            conn.commit()
            return str(resp)

        # לוגיקה רגילה אחרי הרשמה
        parsed = parse_input(incoming_msg)
        baby_name = user_data.get('baby_name', 'הבייבי')
        now = dt.datetime.now()

        if parsed['event_type'] == 'breastfeeding':
            user_data.setdefault('events', []).append({'type': 'הנקה', 'side': parsed['side'], 'duration': parsed['duration'], 'time': now.isoformat()})
            resp.message(f"רשמתי הנקה ל{baby_name}. את אלופה! ✨")
        
        elif parsed['event_type'] == 'status':
            events = user_data.get('events', [])
            summary = f"סטטוס עבור {baby_name}:\n"
            summary += "\n".join([f"- {e['type']} ({e.get('duration','')} דק') ב-{e['time'][11:16]}" for e in events[-3:]]) if events else "עוד לא רשמנו כלום היום."
            resp.message(summary)
        
        else:
            resp.message(f"קיבלתי! {baby_name} בטיפול ידיים טובות. לסיכום כתבי 'סטטוס'.")

        cur.execute("UPDATE users SET data = %s WHERE phone_number = %s", (psycopg2.extras.Json(user_data), user_phone))
        conn.commit()

    except Exception as e:
        print(f"Error: {e}")
        resp.message("אופס, משהו השתבש. נסי שוב?")
    
    finally:
        cur.close()
        conn.close()
        
    return str(resp)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000)

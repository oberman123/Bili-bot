import os  
import datetime as dt
import re  
import logging
from datetime import timedelta 

from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
# הערה: לאימות חתימת Twilio יש להתקין: pip install twilio flask
from twilio.request_validator import RequestValidator
from tinydb import TinyDB, Query
from flask import Flask, request, abort

# ====================================================
# I. הגדרות, לוגים ו-DB
# ====================================================

# הגדרת לוגים בסיסית
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# בדיקת משתני סביבה קריטיים בהפעלה
account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
if not account_sid or not auth_token:
    logging.error("Missing Twilio Environment Variables!")

client = Client(account_sid, auth_token) 
db = TinyDB('users_data.json')
User = Query()

# מפתחות קונסטנטיים (עקביות בשמירה)
KEY_MOM_NAME = 'mom_name' 
KEY_GENDER = 'baby_gender' 
KEY_NAME = 'baby_name'
KEY_DOB = 'dob'  # יישמר בפורמט ISO: YYYY-MM-DD
KEY_EVENTS = 'events'
KEY_STAGE = 'stage'

# פונקציית עזר לזמן ישראל (למניעת באגים של שרת בענן)
def get_israel_time():
    # פתרון פשוט ללא ספריות חיצוניות: UTC+2 (או +3 בקיץ, כאן לצורך הפשטות UTC+2)
    return dt.datetime.utcnow() + timedelta(hours=2)

def normalize_user_id(user_id: str) -> str:
    if not user_id: return ""
    # חיתוך דינמי למניעת "קסם מספרי"
    prefix = 'whatsapp:'
    if user_id.startswith(prefix):
        return user_id[len(prefix):]
    return user_id

def save_user_data(user_id: str, data: dict):
    # נרמול פעם אחת בלבד בכניסה ל-DB
    data['id'] = user_id 
    db.upsert(data, User.id == user_id)

# ====================================================
# II. לוגיקת זיהוי ובדיקות (תיקון באגים)
# ====================================================

def parse_gender(text: str):
    """זיהוי מגדר עמיד יותר מ-substring פשוט"""
    text = text.strip().lower()
    # שימוש ב-Regex עם גבולות מילה או רשימה סגורה
    if re.search(r'\b(בן|זכר|ילד)\b', text):
        return 'male'
    if re.search(r'\b(בת|נקבה|ילדה)\b', text):
        return 'female'
    return None

def validate_birth_date(date_str: str):
    """בדיקת תאריך: פורמט, עתיד, וגיל מקסימלי"""
    clean_date = date_str.replace('.', '/')
    if not re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', clean_date):
        return False, "נראה שכתבת תאריך לא מדויק. 😓\nשימי לב לפורמט: 01.01.2024"
    
    try:
        day, month, year = map(int, clean_date.split('/'))
        if year < 100: year += 2000
        
        birth_date = dt.date(year, month, day)
        today = get_israel_time().date()
        
        if birth_date > today:
            return False, "בילי עוד לא יודעת לחזות את העתיד... 😬\nאנא הכניסי תאריך מהיום אחורה."
        if birth_date < today - timedelta(days=3*365):
            return False, "בילי מיועדת לתינוקות עד גיל 3. 👶"
            
        return True, birth_date.isoformat() # שמירה ב-ISO
    except ValueError:
        return False, "התאריך לא תקין. נסי שוב."

# ====================================================
# III. Onboarding Logic (לבבית ומתוקנת)
# ====================================================

def onboarding_logic(user_data: dict, message: str) -> list[str]:
    stage = user_data.get(KEY_STAGE, 0)
    user_id = user_data['id']

    if stage == 0:
        # פתיח לבבי
        welcome = (
            "היי! 👋 אני בילי...\n"
            "אני פה כדי לעזור לך לתעד ולהקל עלייך בחודשים הראשונים! 🤱\n\n"
            "את אלופה! ❤️ כדי שנתחיל - איך קוראים לך?"
        )
        user_data[KEY_STAGE] = 1
        save_user_data(user_id, user_data)
        return [welcome]

    if stage == 1:
        user_data[KEY_MOM_NAME] = message.strip() # ללא .title() בעברית
        user_data[KEY_STAGE] = 2
        save_user_data(user_id, user_data)
        return [f"נעים מאוד {user_data[KEY_MOM_NAME]}! ❤️\nמה נולד לנו? (בן/בת)"]

    if stage == 2:
        gender = parse_gender(message)
        if not gender:
            return ["סליחה, לא הבנתי... כתבי לי 'בן' או 'בת'."]
        user_data[KEY_GENDER] = gender
        user_data[KEY_STAGE] = 3
        save_user_data(user_id, user_data)
        prompt = "איך קראתם לקטן?" if gender == 'male' else "איך קראתם לקטנה?"
        return [f"מזל טוב! 🌸\n{prompt}"]

    if stage == 3:
        user_data[KEY_NAME] = message.strip()
        user_data[KEY_STAGE] = 4
        save_user_data(user_id, user_data)
        return [f"{user_data[KEY_NAME]}? שם מהמם! ✨\nמתי הוא/היא נולדו? (למשל: 21.05.2024)"]

    if stage == 4:
        is_valid, result = validate_birth_date(message)
        if not is_valid:
            return [result]
            
        user_data[KEY_DOB] = result
        user_data[KEY_STAGE] = 5 # סיום
        save_user_data(user_id, user_data)
        
        return [f"איזה כיף! סיימנו. ❤️\nמהיום אני פה בשבילכם. כתבי 'סטטוס' בכל זמן לסיכום."]

    return ["משהו השתבש... כתבי 'אפס' כדי להתחיל מחדש."]

# ====================================================
# IV. השרת (Flask)
# ====================================================

app = Flask(__name__)

@app.route("/sms", methods=['POST'])
def whatsapp_webhook():
    # 1. אימות בסיסי (אופציונלי להוסיף X-Twilio-Signature כאן)
    incoming_msg = request.values.get('Body', '').strip()
    user_id = normalize_user_id(request.values.get('From', ''))
    
    if not user_id:
        abort(400)

    # 2. שליפת מידע (נרמול פעם אחת בלבד)
    user_data = db.get(User.id == user_id)
    resp = MessagingResponse()

    # 3. טיפול באיפוס
    if incoming_msg.lower() in ['אפס', 'reset']:
        db.remove(User.id == user_id)
        resp.message("איתחלנו! שלחי הודעה כדי להתחיל מחדש. ❤️")
        return str(resp)

    # 4. ניתוב: הרשמה או לוגיקה רגילה
    if not user_data or user_data.get(KEY_STAGE, 0) < 5:
        if not user_data: 
            user_data = {'id': user_id, KEY_STAGE: 0, KEY_EVENTS: []}
        
        responses = onboarding_logic(user_data, incoming_msg)
        for msg in responses:
            resp.message(msg)
    else:
        # לוגיקה רגילה של הבוט (NLP וכו')
        baby_name = user_data.get(KEY_NAME, "הבייבי")
        resp.message(f"קיבלתי! {baby_name} בידיים טובות. ❤️")

    return str(resp)

if __name__ == "__main__":
    # בפרודקשן (Render/Heroku) מומלץ להריץ עם Gunicorn ו-worker אחד:
    # gunicorn --workers 1 --bind 0.0.0.0:10000 app:app
    app.run(port=10000)

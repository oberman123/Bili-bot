import os  
import datetime as dt
import re  
import json
from datetime import timedelta 

from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from flask import Flask, request, jsonify

# SQLAlchemy לניהול הנתונים בענן (PostgreSQL)
from sqlalchemy import create_engine, Column, Integer, String, JSON, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError

# ====================================================
# I. הגדרות ו-DB (SQLAlchemy)
# ====================================================

account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token) 

# חיבור ל-DB (מותאם ל-Render PostgreSQL)
DB_URL = os.environ.get("DATABASE_URL")
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(DB_URL or 'sqlite:///local_test.db')
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserData(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True) 
    mom_name = Column(String)
    baby_gender = Column(String)
    baby_name = Column(String)
    dob = Column(String)
    feed_method = Column(String)
    stage = Column(Integer, default=0)
    role = Column(String, default='main') # main / partner
    partner_phone = Column(String)
    main_user_id = Column(String)
    events = Column(JSON, default=list) 
    enc_tier = Column(JSON, default=dict)
    # שדות לטיימרים (שינה והנקה)
    pending_timer_start = Column(String)
    pending_timer_type = Column(String) # sleep / feed

Base.metadata.create_all(bind=engine)

# מפתחות קונסטנטיים
KEY_MOM_NAME, KEY_GENDER, KEY_NAME, KEY_DOB = 'mom_name', 'baby_gender', 'baby_name', 'dob'
KEY_FEED_METHOD, KEY_EVENTS, KEY_ROLE, KEY_STAGE = 'feed_method', 'events', 'role', 'stage'
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ====================================================
# II. פונקציות עזר ל-DB וניהול משתמשים
# ====================================================

def normalize_user_id(user_id: str) -> str:
    if user_id.startswith('whatsapp:'): user_id = user_id[9:]
    return user_id.replace('+', '')

def get_db_user(user_id: str):
    norm_id = normalize_user_id(user_id)
    session = SessionLocal()
    user = session.query(UserData).filter(UserData.id == norm_id).first()
    session.close()
    return user

def save_db_user(user_obj):
    session = SessionLocal()
    session.merge(user_obj)
    session.commit()
    session.close()

def get_effective_user_id(user):
    """מחזיר את ה-ID של האמא (גם אם הפונה הוא בן הזוג)"""
    if user.role == 'partner' and user.main_user_id:
        return user.main_user_id
    return user.id

def add_event(user_id: str, event_type: str, details: dict):
    session = SessionLocal()
    user = session.query(UserData).filter(UserData.id == user_id).first()
    if user:
        new_event = {
            'type': event_type,
            'timestamp': dt.datetime.now().strftime(TIME_FORMAT),
            'details': details
        }
        updated_events = list(user.events) if user.events else []
        updated_events.append(new_event)
        user.events = updated_events
        session.commit()
    session.close()

# ====================================================
# III. ניתוח קלט (NLP)
# ====================================================

def parse_input(text: str) -> dict:
    parsed = {'action': None}
    msg = text.lower().strip()

    # טיימרים
    if any(k in msg for k in ['נרדם', 'התחיל לישון']): 
        return {'action': 'timer_start', 'target': 'sleep'}
    if any(k in msg for k in ['התעורר', 'סיים לישון']): 
        return {'action': 'timer_end', 'target': 'sleep'}
    if any(k in msg for k in ['התחל הנקה', 'התחלת הנקה']): 
        return {'action': 'timer_start', 'target': 'feed'}
    if any(k in msg for k in ['סיים הנקה', 'סיום הנקה']): 
        return {'action': 'timer_end', 'target': 'feed'}

    # שינה ידנית
    sleep_match = re.search(r'ישן\s+(\d+)\s+שעות', msg)
    if sleep_match: 
        return {'action': 'log_sleep_manual', 'hours': int(sleep_match.group(1))}

    # פקודות ניהול
    if msg == 'סטטוס': return {'action': 'status'}
    if msg == 'פירוט': return {'action': 'details'}
    if msg == 'עזרה': return {'action': 'help'}
    if 'השוואה' in msg: return {'action': 'comparison'}
    if 'הוסף בן זוג' in msg:
        phone = re.search(r'\d{9,15}', msg)
        return {'action': 'add_partner', 'phone': phone.group() if phone else None}

    # תיעוד רגיל
    if any(k in msg for k in ['ימין', 'שמאל', 'הנקתי', 'ינקה', 'ינק']):
        parsed['action'] = 'log_feed'
        parsed['side'] = 'ימין' if 'ימין' in msg else 'שמאל' if 'שמאל' in msg else 'שני צדדים'
        dur = re.search(r'\d+', msg)
        parsed['duration'] = int(dur.group()) if dur else 0
    elif 'בקבוק' in msg:
        parsed['action'] = 'log_bottle'
        amt = re.search(r'\d+', msg)
        parsed['amount'] = int(amt.group()) if amt else 0
    elif any(k in msg for k in ['פיפי', 'קקי', 'חיתול']):
        parsed['action'] = 'log_diaper'
        parsed['d_type'] = 'קקי ופיפי' if ('קקי' in msg and 'פיפי' in msg) or 'מלא' in msg else 'קקי' if 'קקי' in msg else 'פיפי'
    elif any(k in msg for k in ['שאבתי', 'שאיבה']):
        parsed['action'] = 'log_pump'
        amt = re.search(r'\d+', msg)
        parsed['amount'] = int(amt.group()) if amt else 0

    return parsed

# ====================================================
# IV. לוגיקת סטטיסטיקות ודוחות
# ====================================================

def get_daily_summary(user_id):
    user = get_db_user(user_id)
    if not user or not user.events: return "אין נתונים להיום עדיין."
    
    today = dt.datetime.now().strftime("%Y-%m-%d")
    todays = [e for e in user.events if e['timestamp'].startswith(today)]
    
    if not todays: return "אין תיעודים להיום."

    feeds = [e for e in todays if e['type'] == 'log_feed']
    bottles = [e for e in todays if e['type'] == 'log_bottle']
    diapers = [e for e in todays if e['type'] == 'log_diaper']
    sleeps = [e for e in todays if e['type'] in ['sleep', 'log_sleep_manual']]
    
    summary = f"📊 *סטטוס יומי עבור {user.baby_name}:*\n"
    summary += f"🍼 הנקות: {len(feeds)}\n"
    summary += f"🍼 בקבוקים: {len(bottles)} (סך הכל {sum(e['details'].get('amount', 0) for e in bottles)} מ\"ל)\n"
    summary += f"💩 חיתולים: {len(diapers)}\n"
    
    total_sleep_min = sum(e['details'].get('duration', 0) for e in sleeps)
    if total_sleep_min > 0:
        summary += f"😴 שינה: {total_sleep_min // 60} שעות ו-{total_sleep_min % 60} דקות\n"
    
    return summary

# ====================================================
# V. ניהול הודעות ראשי
# ====================================================

def handle_message(user_id_raw: str, incoming_message: str) -> list:
    norm_id = normalize_user_id(user_id_raw)
    user = get_db_user(norm_id)
    
    # משתמש חדש
    if not user:
        user = UserData(id=norm_id, stage=0, events=[], enc_tier={})
        save_db_user(user)
        return ["מהמם! ❤️ איזה כיף שהגעת. אני בילי, ואני כאן כדי לעזור לך לעקוב אחרי הכל בקלות.\n\nאיך קוראים לך?"]

    # תהליך הרשמה (Onboarding)
    if user.stage < 5:
        return handle_onboarding(user, incoming_message)

    # זיהוי פעולה
    parsed = parse_input(incoming_message)
    eff_id = get_effective_user_id(user)

    # 1. טיימרים
    if parsed.get('action') == 'timer_start':
        user.pending_timer_start = dt.datetime.now().strftime(TIME_FORMAT)
        user.pending_timer_type = parsed['target']
        save_db_user(user)
        return [f"התחלנו טיימר {parsed['target']}! עדכני אותי כשמסתיים."]

    if parsed.get('action') == 'timer_end':
        if not user.pending_timer_start: return ["לא מצאתי טיימר פעיל."]
        start = dt.datetime.strptime(user.pending_timer_start, TIME_FORMAT)
        dur = int((dt.datetime.now() - start).total_seconds() / 60)
        add_event(eff_id, 'sleep' if user.pending_timer_type == 'sleep' else 'log_feed', {'duration': dur, 'method': 'timer'})
        user.pending_timer_start = None
        save_db_user(user)
        return [f"נרשם! משך זמן: {dur} דקות. ✅"]

    # 2. שינה ידנית
    if parsed.get('action') == 'log_sleep_manual':
        add_event(eff_id, 'log_sleep_manual', {'duration': parsed['hours'] * 60})
        return [f"רשמתי {parsed['hours']} שעות שינה. לילה טוב! 😴"]

    # 3. דוחות
    if parsed.get('action') == 'status':
        return [get_daily_summary(eff_id)]
    
    # 4. תיעוד רגיל
    if parsed.get('action') in ['log_feed', 'log_bottle', 'log_diaper', 'log_pump']:
        add_event(eff_id, parsed['action'], parsed)
        return ["נרשם בהצלחה! ✅"]

    # 5. עזרה
    if parsed.get('action') == 'help':
        return ["כתבי לי פעולות כמו:\n'הנקתי 10 דקות'\n'נרדם'\n'פיפי'\n'סטטוס'\n'בקבוק 120'"]

    return ["לא בטוחה שהבנתי... נסי לכתוב 'עזרה' כדי לראות מה אני יודעת לעשות."]

def handle_onboarding(user, msg):
    if user.stage == 0:
        user.mom_name = msg; user.stage = 1; save_db_user(user)
        return [f"נעים מאוד {msg}! ❤️ מה נולד לנו? (בן/בת)"]
    elif user.stage == 1:
        user.baby_gender = msg; user.stage = 2; save_db_user(user)
        return ["ואיך קראתם לקטנ/ה?"]
    elif user.stage == 2:
        user.baby_name = msg; user.stage = 3; save_db_user(user)
        return [f"מזל טוב על {msg}! 🎉 מתי היומולדת? (DD.MM.YY)"]
    elif user.stage == 3:
        user.dob = msg; user.stage = 4; save_db_user(user)
        return ["ומה שיטת ההאכלה העיקרית? (הנקה/בקבוק/משולב)"]
    elif user.stage == 4:
        user.feed_method = msg; user.stage = 5; save_db_user(user)
        
        # טקסט הפתיחה החדש שביקשת
        txt = (f"מהמם! ❤️ איזה כיף שאת נותנת את כל הטוב הזה!\nאת פשוט אלופה...\n\n"
               f"עכשיו אני כאן בשבילך....\nפה כדי לשמור לך על כל המידע החשוב והמדהים הזה!\n\n"
               f"אז ככה זה עובד-\nמעכשיו, כל פעילות של {user.baby_name}, את יכולה לתעד בקלות!\n\n"
               f"הנקת?🤱 פשוט כתבי-\n• הנקתי\n• ימין 10 דק\n• שמאל 10 דק\n"
               f"את יכולה גם פשוט לכתוב - ינק/ הנקתי/ וכו'...\n\n"
               f"החלפת חיתול?💩 פשוט כתבי-\n• פיפי / קקי / חיתול מלא\n\n"
               f"את שואבת? 🥰 פשוט כתבי-\n• *שאבתי* או *שאיבה*, עדיף להוסיף גם כמות.\n\n"
               f"נתת בקבוק? 🍼 פשוט כתבי-\n• *בקבוק* או *אכל בקבוק*, עדיף להוסיף גם כמות.\n\n"
               f"{user.baby_name} {'ישן' if 'בן' in user.baby_gender else 'ישנה'}?...😴 פשוט כתבי-\n"
               f"• ישן\n• נרדם / התעורר (אנחנו כבר נחשב כמה זמן....)\n• ישן 3 שעות\n\n"
               f"אני שומרת הכול באופן מסודר בשבילך.\nבכל רגע שתצטרכי, אפשר לכתוב 'סטטוס' ותקבלי תמונת מצב יומית ברורה.\n\n"
               f"אני פה ללוות, להרגיע ולעזור לך לעקוב בלי מאמץ 🤱❤️")
        return [txt]
    return []

# ====================================================
# VI. Flask App
# ====================================================

app = Flask(__name__)

@app.route("/sms", methods=['POST'])
def whatsapp_webhook():
    incoming_message = request.values.get('Body', '') 
    user_id_raw = request.values.get('From', '')  
    
    try:
        response_texts = handle_message(user_id_raw, incoming_message)
        resp = MessagingResponse()
        for text in response_texts:
            resp.message(text)
        return str(resp)
    except Exception as e:
        print(f"Error: {e}")
        return "Error", 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

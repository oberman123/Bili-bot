import os  
import datetime as dt
import re  
import random 
from datetime import timedelta 

from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from tinydb import TinyDB, Query
from flask import Flask, request, jsonify

# 💡 הערה: הקוד מוגדר להשתמש בזמן המקומי של המכונה שמריצה אותו, 
# ואינו דורש התקנות חיצוניות (כגון pytz או tzdata).

# ====================================================
# I. הגדרות ו-DB
# ====================================================

# הגדרות Twilio (חובה להחליף את [YOUR_...] בפרטים שלך)
account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token) 

# הגדרות DB
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

# ספי עידוד (Encouragement Tiers)
MILESTONE_TIERS = { 
    4: "מדהים! עקביות זה שם המשחק. רק ארבעה אירועים ואת כבר מנצחת את היום! 🏆",
    8: "וואו, תדעי שאת עוקבת ומנהלת את הכל בצורה מושלמת. איזו השקעה 👏",
    12: "את שיאנית! המערכת שלך מסודרת בזכותך. קחי נשימה עמוקה, עשית עבודה מעולה היום. ❤️"
}

# תוכן תפריט עזרה וסעיף משפטי
LEGAL_DISCLAIMER = "\n\n---\n_המידע כאן כללי ולא מחליף ייעוץ מקצועי. אם יש ספק — תמיד כדאי לפנות לאשת מקצוע מוסמכת._"

HELP_TOPICS = {
    'menu': "איך אפשר לעזור? 🌱\n\nבחרי נושא (או כתבי את המספר):\n1️⃣ טיפול בחלב אם\n2️⃣ דברים שחשוב לשים לב בהנקה\n3️⃣ נורות אזהרה\n4️⃣ המלצות כלליות להנקה\n\n(אפשר לבחור במילים או במספר)",
    
    '1': {
        'keywords': ['טיפול בחלב', 'חלב אם', 'טיפול'],
        'text': "כמה דברים חשובים לשמור על חלב אם 🍼\n\n"
                "• לשמור בקירור עד 4 ימים\n"
                "• בהקפאה – עד חצי שנה\n"
                "• להפשיר בעדינות (לא במיקרוגל)\n"
                "• אם יש ריח/צבע חריג – לא להשתמש\n\n"
                "רוצה שאשלח טיפים לאחסון?"
    },
    '2': {
        'keywords': ['דברים לשים לב', 'שים לב', 'הנקה'],
        'text': "בהנקה, שימי לב ל־ 🤱\n\n"
                "• שהתינוק בולע ולא רק מוצץ\n"
                "• שאין כאב מתמשך\n"
                "• שהשד מתרכך בסיום\n"
                "• שהתינוק רגוע אחרי\n\n"
                "כל אמא והתינוק שלה – זה בסדר ללמוד יחד 🌸"
    },
    '3': {
        'keywords': ['אזהרה', 'נורות', 'אדום'],
        'text': "נורות אזהרה 🚨\n\n"
                "במקרים האלו כדאי להתייעץ עם אשת מקצוע:\n\n"
                "• כאב חזק או פצעים שלא משתפרים\n"
                "• חום או אודם בשד\n"
                "• תינוק שלא עולה במשקל\n"
                "• מעט מאוד חיתולים רטובים\n\n"
                "אם משהו מרגיש לך 'לא רגיל' – תקשיבי לעצמך 💙"
    },
    '4': {
        'keywords': ['המלצות', 'כלליות', 'טיפים'],
        'text': "כמה המלצות שעוזרות להרבה אמהות 💛\n\n"
                "• להחליף צדדים בין הנקות\n"
                "• למצוא תנוחה שנוחה לך\n"
                "• לשתות ולאכול כשאפשר\n"
                "• לזכור: לא כל יום נראה אותו דבר\n\n"
                "את עושה הכי טוב שאת יכולה 🤍"
    },
}


# ====================================================
# A. פונקציות עזר ל-Timezone
# ====================================================

def get_now_tz() -> dt.datetime:
    """מחזיר את ה-datetime הנוכחי לפי זמן המערכת המקומי."""
    return dt.datetime.now()


def get_today_tz() -> dt.date:
    """מחזיר את התאריך הנוכחי (date) לפי זמן המערכת המקומי."""
    return dt.datetime.now().date()


# ====================================================
# II. פונקציות עזר לבסיס הנתונים (TinyDB)
# ====================================================

def normalize_user_id(user_id: str) -> str:
    """מנרמל את ה-user_id (מוריד 'whatsapp:' אם קיים)"""
    if user_id.startswith('whatsapp:'):
        user_id = user_id[9:]
    return user_id

def get_user_data_single(user_id: str) -> dict or None:
    """שולף משתמש יחיד לפי ID, או מחזיר None"""
    normalized_id = normalize_user_id(user_id) 
    return db.get(User.id == normalized_id)

def save_user_data(user_id: str, data: dict):
    """מעדכן או מוסיף נתוני משתמש"""
    normalized_id = normalize_user_id(user_id) 
    data['id'] = normalized_id 
    db.upsert(data, User.id == normalized_id)

def add_event(user_id: str, event_type: str, details: dict):
    """מוסיף אירוע חדש ל-KEY_EVENTS"""
    user = get_user_data_single(user_id)
    if not user:
        return

    # שימוש בפורמט ארוך יותר (כולל מילישניות) למניעת דריסת נתונים ב-Batch
    event = {
        'type': event_type,
        'timestamp': get_now_tz().strftime("%Y-%m-%d %H:%M:%S.%f"), 
        'details': details
    }
    
    if KEY_EVENTS not in user:
        user[KEY_EVENTS] = []
    
    user[KEY_EVENTS].append(event)
    save_user_data(user_id, user)
    return user[KEY_EVENTS]

def delete_user_data(user_id: str):
    """מוחק את נתוני המשתמש מה-DB לצורך איפוס מלא."""
    normalized_id = normalize_user_id(user_id)
    db.remove(User.id == normalized_id)


# ====================================================
# B. פונקציות עידוד וחיזוק
# ====================================================

def check_milestone_encouragement(user_id: str, user: dict, today: dt.date) -> str or None:
    """
    בדיקה האם צריך לשלוח עידוד על ציון דרך במספר האירועים היומי.
    מחזיר הודעת עידוד או None.
    """
    events = user.get(KEY_EVENTS, [])
    
    # 1. ספירת אירועי היום
    today_event_count = sum(1 for event in events if event['timestamp'].split(' ')[0] == today.strftime("%Y-%m-%d"))
    
    # 2. קבלת סף העידוד האחרון שנשלח היום
    # הערך שמור כ- { '2025-12-14': 4 }
    enc_data = user.get(KEY_ENCOURAGEMENT_TIER, {})
    
    # מוודאים שאנו בודקים רק סף חדש
    last_tier_sent = enc_data.get(today.strftime("%Y-%m-%d"), 0)
    
    # 3. בדיקת סף
    for tier, message in MILESTONE_TIERS.items():
        if today_event_count >= tier and tier > last_tier_sent:
            # עדכון ה-DB עם הסף החדש שנשלח
            enc_data[today.strftime("%Y-%m-%d")] = tier
            user[KEY_ENCOURAGEMENT_TIER] = enc_data
            save_user_data(user_id, user)
            
            # החזרת הודעת העידוד
            return message

    return None


# ====================================================
# III. פונקציות עזר לטיפול במגדר
# ====================================================

def get_gender_text(user_data: dict, is_male: str, is_female: str, neutral: str = None) -> str:
    """מחזיר את המילה המתאימה לפי המגדר השמור."""
    gender = user_data.get(KEY_GENDER)
    if gender == 'male':
        return is_male
    elif gender == 'female':
        return is_female
    return neutral or is_male 

def get_baby_name_or_default(user_data: dict) -> str:
    """מחזיר את שם התינוק/ת או ברירת מחדל לפי המגדר."""
    name = user_data.get(KEY_NAME)
    if name:
        return name
        
    gender = user_data.get(KEY_GENDER)
    if gender == 'male':
        return 'הנסיך'
    elif gender == 'female':
        return 'הנסיכה'
    return 'הבייבי'

# ====================================================
# IV. פונקציות עזר לזיהוי קלט (NLP קל)
# ====================================================

def _parse_single_breastfeeding(line: str) -> dict or None:
    """מנתח שורה בודדת עבור הנקה, תומך ב-side/duration וב-duration/side."""
    msg = line.lower().strip()
    
    if not any(keyword in msg for keyword in ['ינק', 'יניקה', 'הנקה', 'הנקתי', 'ימין', 'שמאל']) and \
       not re.search(r'\d+.*(ימין|שמאל)', msg):
        return None
    
    side_match = re.search(r'(ימין|שמאל)', msg)
    side = side_match.group(1) if side_match else 'לא צוין'
    
    duration = 0
    duration_match = re.search(r'\d{1,3}\s*(דק|דקות|m)?', msg)
    
    if duration_match:
        duration = int(re.search(r'\d+', duration_match.group(0)).group(0))
        
    return {'type': 'breastfeeding', 'side': side, 'duration': duration, 'message': line}


def parse_input(message: str) -> dict:
    """מנתח קלט נכנס ומנסה לזהות סוג ופרטים"""
    
    if '\n' in message:
        return {'type': 'multi_event', 'message': message}
        
    msg = message.lower().strip()
    
    parsed_bf = _parse_single_breastfeeding(msg)
    if parsed_bf:
        return parsed_bf

    if msg.startswith(('בקבוק', 'בקבוקים')):
        amount_match = re.search(r'(\d+)', msg)
        amount = int(amount_match.group(1)) if amount_match else 0
        return {'type': 'bottle', 'amount': amount, 'message': message}
        
    if msg.startswith(('שאב', 'שאיבה')): 
        amount_match = re.search(r'(\d+)', msg)
        amount = int(amount_match.group(1)) if amount_match else 0
        return {'type': 'pump', 'amount': amount, 'message': message}

    if msg in ['קקי', 'פיפי', 'חיתול קקי', 'חיתול פיפי', 'חיתול', 'חיתול מלא']:
        diaper_type = 'both' if 'חיתול מלא' in msg or (msg == 'חיתול' and 'קקי' not in msg and 'פיפי' not in msg) else 'poo' if 'קקי' in msg else 'pee' if 'פיפי' in msg else 'both'
        return {'type': 'diaper', 'diaper_type': diaper_type, 'message': message}
        
    if msg == 'סטטוס':
        return {'type': 'status'}
    if msg == 'פירוט':
        return {'type': 'details'}
    if msg.startswith('השוואה'):
        return {'type': 'comparison'}
    
    if msg == 'עזרה' or msg == 'help': 
        return {'type': 'help_menu'}
        
    if msg.startswith('הוסף בן זוג'):
        phone_match = re.search(r'05\d-?\d{7}', msg)
        phone = phone_match.group(0).replace('-', '') if phone_match else None
        return {'type': 'add_partner', 'phone': phone}
        
    return {'type': 'unknown', 'message': message}


# ====================================================
# V. פונקציות לוגיקה
# ====================================================

def is_onboarding_complete(user_id: str) -> bool:
    """בדיקה האם ההרשמה הושלמה (שלב 5 ומעלה)"""
    user = get_user_data_single(user_id)
    return user and user.get('stage', 0) >= 5 

def onboarding_logic(user_id: str, message: str) -> list[str]:
    """שלב הצטרפות - 5 שלבים."""
    user = get_user_data_single(user_id)
    stage = user.get('stage', 0) if user else 0
    responses = [] 

    if user is None:
        user_data = {'id': normalize_user_id(user_id), 'stage': 0, KEY_EVENTS: [], KEY_ROLE: KEY_MAIN_USER, KEY_ENCOURAGEMENT_TIER: {}}
        save_user_data(user_id, user_data)
        
        welcome_message = "היי! 👋\nאני בילי...\nאני פה כדי לעזור לך לשמור, לתעד, להקל ולהנות מכל מה שקשור בחודשים הראשונים עם הבייבי שלך! 🤱\n\n" \
                          "דבר ראשון, את אלופה! זאת תקופה מהממת ונעבור אותה יחד!😍\n\n" \
                          "כדי שאוכל לפנות אלייך אישית - איך קוראים לך? (שם פרטי מספיק)."
        return [welcome_message]
        
    if stage == 0:
        if not message.strip():
            return ["אני זקוקה לשם שלך כדי שנוכל להתחיל!"] 
            
        user[KEY_MOM_NAME] = message.title()
        user['stage'] = 1 
        save_user_data(user_id, user)
        
        gender_question = f"איזה כיף, {user[KEY_MOM_NAME]}! ❤️\nמה נולד?\nאנא בחרי:\n1. בן 👶\n2. בת 👧"
        return [gender_question]
    
    if stage == 1:
        msg = message.lower().strip().replace('.', '')
        gender_map = {'1': 'male', 'בן': 'male', '2': 'female', 'בת': 'female'}
        gender = gender_map.get(msg) or gender_map.get(msg.split('.')[0])
        
        if not gender:
            return ["לא זיהיתי. אנא בחרי 1 (בן) או 2 (בת)."]

        user[KEY_GENDER] = gender
        user['stage'] = 2
        save_user_data(user_id, user)
        
        gender_text = get_gender_text(user, 'לו', 'לה')
        confirmation_message = f"תודה על השיתוף! 🌸\nמעולה!\nאיך קראתם {gender_text}?"
        return [confirmation_message]
        
    if stage == 2:
        if not message.strip():
            return ["אני זקוקה לשם התינוק/ת כדי שנוכל להתחיל! 👶"]
            
        user[KEY_NAME] = message.title()
        user['stage'] = 3
        save_user_data(user_id, user)
        
        responses.append("איזה שם מהמם! ✨\nמתי ילדת? (DD/MM/YYYY)")
        return responses
        
    if stage == 3:
        date_pattern = re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}$')
        
        if not date_pattern.match(message):
            return ["וואי, נראה שכתבת תאריך לא מדויק. 😓", 
                    "שימי לב שצריך DD/MM/YYYY (לדוגמה: 01/01/2024)."]
            
        try:
            day, month, year = map(int, message.split('/'))
            
            # טיפול בשנה דו-ספרתית
            if year < 100:
                year += 2000
                
            birth_date = dt.date(year, month, day)
        except ValueError:
            return ["וואי, נראה שכתבת תאריך לא מדויק. 😓", 
                    "שימי לב שצריך DD/MM/YYYY (לדוגמה: 01/01/2024)."]

        # שימוש ב-get_today_tz()
        today = get_today_tz()
        max_dob = today - timedelta(days=3 * 365) 
        
        if birth_date > today:
            return ["וואי, נראה שהתאריך שציינת הוא בעתיד. 😬", 
                    "אנא הכניסי את תאריך הלידה של התינוק/ת (תאריך מהיום אחורה, DD/MM/YYYY)."]
        
        if birth_date < max_dob:
             return [f"הי, בילי מיועדת לתינוקות עד גיל 3. 👶",
                     f"התאריך {message} מחוץ לטווח. אנא שלחי תאריך לידה עד 3 שנים אחורה."]

        user[KEY_DOB] = message
        user['stage'] = 4 
        save_user_data(user_id, user)
        
        baby_name = user.get(KEY_NAME)
        
        full_question = f"איזה כיף.... 🥰\n\nתגידי,\nמה את נותנת ל{baby_name} לאכול?\nאנא בחרי:\n1. הנקה מלאה\n2. הנקה ובקבוקים\n3. רק בקבוקים"
                        
        return [full_question]
        
    if stage == 4:
        
        msg_clean = re.sub(r'[^\dא-תa-z]', '', message.lower().strip())
        
        feed_map = {'1': 'מלאה', '2': 'חלקית', '3': 'בקבוקים', 
                    'הנקהמלאה': 'מלאה', 'הנקהובקבוקים': 'חלקית', 'רקבקבוקים': 'בקבוקים', 'פורמולה': 'בקבוקים'}
        
        feed_method = feed_map.get(msg_clean) 
        
        if not feed_method and len(msg_clean) > 0 and msg_clean[0].isdigit():
            digit_input = msg_clean[0]
            if digit_input in ['1', '2', '3']:
                feed_method = feed_map.get(digit_input)
        
        if not feed_method:
            return ["לא זיהיתי. אנא בחרי: 1. הנקה מלאה, 2. הנקה ובקבוקים, או 3. רק בקבוקים."]

        user[KEY_FEED_METHOD] = feed_method
        user['stage'] = 5 
        save_user_data(user_id, user)
        
        baby_name = user.get(KEY_NAME)
        
        end_message = f"מהמם! ❤️ איזה כיף שאת נותנת את כל הטוב הזה!\nפשוט אלופה...\n\nעכשיו אני כאן בשבילך....\nפה כדי לשמור לך על כל המידע החשוב והמדהים הזה!\n\n" \
                      f"**האכלת?...🍼**\n" \
                      f"• 'ימין 10 דק' \n" \
                      f"• **תמיכה בריבוי: 'ימין 10\\n שמאל 10'**\n"

        if feed_method in ['חלקית', 'בקבוקים']:
            end_message += f"\n**אם נתת בקבוק-** פשוט תכתבי לי **'בקבוק'**\n" \
                           f"אפשר גם להוסיף כמה אכל - **'בקבוק 90'**\n"

        end_message += f"\n**החלפת חיתול?💩**\n" \
                       f"• פיפי / קקי / חיתול מלא\n" \
                       f"**את שואבת?**\n" \
                       f"• **שאבתי** או **שאיבה**, עדיף להוסיף גם כמות.\n\n" \
                       f"אני שומרת הכול באופן מסודר בשבילך. בכל רגע שתצטרכי — אפשר לכתוב **'סטטוס'** ותקבלי תמונת מצב יומית ברורה.\n" \
                       f"**אם את צריכה עזרה נוספת, מוזמנת לכתוב 'עזרה' ואנסה לעזור לך במה שאפשר....**\n" \
                       f"אני פה ללוות, להרגיע ולעזור לך לעקוב בלי מאמץ 🤱🩵"
        
        return [end_message] 
    
    if stage >= 5:
        return [default_response(user)]

def handle_logging_core(user_id: str, parsed_input: dict) -> str:
    """ מבצע את השמירה ב-DB ומחזיר הודעת הצלחה """
    # הפונקציה הזו קוראת ל-get_user_data_single() ושומרת חזרה באמצעות save_user_data()
    user = get_user_data_single(user_id) 
    baby_name = get_baby_name_or_default(user)
    baby_pronoun = get_gender_text(user, 'הוא', 'היא', 'הבייבי')
    event_type = parsed_input['type']
    
    if event_type == 'breastfeeding':
        side = parsed_input.get('side', 'צד לא צוין')
        duration = parsed_input.get('duration', 0)
        details_to_log = {'side': side, 'duration': duration}
        add_event(user_id, 'breastfeeding', details_to_log)
        response = f"נרשמה הנקה מצד {side} ({duration} דק) 🤱" if duration > 0 else "מעולה, נרשמה הנקה 🙂"
        if duration >= 15 and random.randint(1, 2) == 1: 
            response += f"\n\nאיזו אלופה! {baby_pronoun} קיבל/ה את כל הטוב שצריך 👏"
        return response

    if event_type == 'bottle':
        amount = int(parsed_input.get('amount', 0) or 0) 
        
        if amount <= 0:
             return f"לא נרשם בקבוק. אנא שלח/י כמות חיובית."
             
        add_event(user_id, 'bottle', {'amount': amount}) 
        return f"נרשם בקבוק של {amount} מ״ל ל{baby_name} 🍼"
        
    if event_type == 'pump':
        amount = int(parsed_input.get('amount', 0) or 0)
        if amount <= 0:
             return f"לא נרשמה שאיבה. אנא שלח/י כמות חיובית."
             
        add_event(user_id, 'pump', {'amount': amount})
        return f"נרשמו {amount} מ״ל שאיבה 🍼💪"
        
    if event_type == 'diaper':
        diaper_type = parsed_input.get('diaper_type', 'both')
        add_event(user_id, 'diaper', {'type': diaper_type}) 
        if diaper_type == 'pee':
            return "תודה! פיפי נרשם 😊"
        elif diaper_type == 'poo':
            return "נרשם חיתול קקי 💩"
        elif diaper_type == 'both': 
            return "נרשם חיתול מלא. כל הכבוד! ✅"
            
    return default_response(user)


def calculate_status_for_range(events: list, start_date: dt.date, end_date: dt.date) -> dict:
    """Calculates summary stats for events within a date range (inclusive)."""
    status = {
        'breastfeeding': 0, 
        'bf_total_minutes': 0, 
        'bf_left_count': 0,    
        'bf_right_count': 0,   
        'bottle': {'count': 0, 'total_amount': 0}, 
        'diaper': 0, 
        'pump': {'count': 0, 'total_amount': 0}
    }
    
    for event in events:
        if not isinstance(event, dict) or 'timestamp' not in event:
            continue
            
        event_date_str = event['timestamp'].split(' ')[0]
        
        try:
            event_date = dt.datetime.strptime(event_date_str, "%Y-%m-%d").date()
        except ValueError:
            print(f"DEBUG: Failed to parse timestamp date part {event_date_str}")
            continue

        if start_date <= event_date <= end_date:
            event_type = event.get('type')
            details = event.get('details', {}) 
            
            if event_type == 'breastfeeding':
                status['breastfeeding'] = status.get('breastfeeding', 0) + 1
                
                duration = int(details.get('duration', 0))
                side = details.get('side', '').lower()
                
                status['bf_total_minutes'] += duration
                
                if 'שמאל' in side or 'left' in side:
                    status['bf_left_count'] += 1
                elif 'ימין' in side or 'right' in side:
                    status['bf_right_count'] += 1
                
            elif event_type == 'diaper':
                status['diaper'] = status.get('diaper', 0) + 1
            
            elif event_type in ['bottle', 'pump']:
                
                raw_amount = details.get('amount', 0)
                
                amount = 0
                try:
                    amount = int(raw_amount) 
                except (ValueError, TypeError):
                    print(f"DEBUG: Failed to convert amount {raw_amount} to int for event {event_type} at {event.get('timestamp')}")
                    continue
                
                if amount > 0:
                    status[event_type]['count'] += 1
                    status[event_type]['total_amount'] += amount
                
    return status

def calculate_status(events: list) -> dict:
    """מחשב סיכום יומי מאירועים"""
    today = get_today_tz() 
    
    today_stats = calculate_status_for_range(events, today, today)
    
    s = {
        'breastfeeding': today_stats.get('breastfeeding', 0),
        'bf_total_minutes': today_stats.get('bf_total_minutes', 0), 
        'bf_left_count': today_stats.get('bf_left_count', 0),        
        'bf_right_count': today_stats.get('bf_right_count', 0),       
        'bottle_count': today_stats['bottle']['count'],
        'bottle_total': today_stats['bottle']['total_amount'],
        'diaper': today_stats.get('diaper', 0),
        'pump_count': today_stats['pump']['count'],
        'pump_total': today_stats['pump']['total_amount'],
    }
    
    last_update = None
    for event in reversed(events):
        event_date = event['timestamp'].split(' ')[0]
        if event_date == today.strftime("%Y-%m-%d"): 
            # ה-timestamp הוא 'YYYY-MM-DD HH:MM:SS.XXXXXX'
            time_part = event['timestamp'].split(' ')[1] 
            last_update = time_part[:5] 
            break
        
    if s['breastfeeding'] > 5 and s['diaper'] > 4:
        note = "איזה יום פורה! את על זה לגמרי 👏"
    elif s['breastfeeding'] > 0 or s['bottle_count'] > 0:
        note = "היום רק התחיל, בואי נמשיך לתעד 🩵"
    else:
        note = "לא תועדה פעילות היום. רוצה להתחיל? 🌼"
        
    return {'status': s, 'last_update': last_update or 'טרם תועד', 'note': note}

def get_status_response(user_id: str, user: dict) -> list[str]:
    """בניית תגובת סטטוס והצגת תפריט המשך."""
    events = user.get(KEY_EVENTS, [])
    baby_name = get_baby_name_or_default(user)
    
    status_data = calculate_status(events)
    s = status_data['status']
    
    response = f"**סטטוס היום של {baby_name}** 📊\n"
    response += f"• הנקות: {s['breastfeeding']} (סה״כ **{s['bf_total_minutes']} דק'**)\n" 
    
    if s['bf_left_count'] > 0 or s['bf_right_count'] > 0:
        response += f"  (ימין: {s['bf_right_count']}, שמאל: {s['bf_left_count']})\n"
        
    response += f"• בקבוקים: {s['bottle_count']} ({s['bottle_total']} מ״ל סה״כ)\n"
    response += f"• חיתולים: {s['diaper']}\n"
    response += f"• שאיבות: {s['pump_count']} ({s['pump_total']} מ״ל סה״כ)\n"
    response += f"• עדכון אחרון: {status_data['last_update']}\n"
    response += "\nהערה: " + status_data['note']
    
    user['pending_action'] = 'status_followup'
    save_user_data(user_id, user)
    
    response += "\n\nמה תרצי לעשות עכשיו?\n" \
                "1. **פירוט** אירועי היום\n" \
                "2. **השוואה** לאתמול וסיכום שבועי"
                
    return [response]


def get_comparison_response(user_id: str, user: dict) -> str:
    """Buidling the daily and weekly comparison response."""
    events = user.get(KEY_EVENTS, [])
    baby_name = get_baby_name_or_default(user)
    
    today = get_today_tz()
    yesterday = today - timedelta(days=1)
    
    # --- 1. השוואה יומית (היום מול אתמול) ---
    
    today_stats = calculate_status_for_range(events, today, today)
    yesterday_stats = calculate_status_for_range(events, yesterday, yesterday)
    
    comparison_text = f"**השוואה יומית: היום מול אתמול של {baby_name}** ⚖️\n"
    
    keys = {
        'breastfeeding': 'הנקות', 
        'bf_total_minutes': 'סה"כ הנקה (דק\')', 
        'bottle': 'בקבוקים (מ"ל)', 
        'diaper': 'חיתולים', 
        'pump': 'שאיבות (מ"ל)'
    }
    
    def format_daily_comparison(key):
        if key in ['bottle', 'pump']:
            today_val = today_stats[key]['total_amount']
            yesterday_val = yesterday_stats[key]['total_amount']
            label = keys[key]
        elif key == 'bf_total_minutes': 
            today_val = today_stats.get(key, 0)
            yesterday_val = yesterday_stats.get(key, 0)
            label = keys[key]
        else:
            today_val = today_stats.get(key, 0)
            yesterday_val = yesterday_stats.get(key, 0)
            label = keys[key]

        diff_val = today_val - yesterday_val
        
        if diff_val > 0:
            diff = f"(+ {diff_val})"
        elif diff_val < 0:
            diff = f"(- {abs(diff_val)})"
        else:
            diff = "(זהה)"
            
        return f"• {label}: {today_val} {diff}"
        
    comparison_text += "\n".join(format_daily_comparison(key) for key in keys)
    
    # --- 2. השוואה שבועית ---
    
    current_weekday = today.weekday() 
    days_to_sunday = (current_weekday + 1) % 7 

    this_week_start = today - timedelta(days=days_to_sunday)
    this_week_end = today 
    
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1) 
    
    this_week_stats = calculate_status_for_range(events, this_week_start, this_week_end)
    last_week_stats = calculate_status_for_range(events, last_week_start, last_week_end)

    weekly_text = f"\n\n**סיכום שבועי (השבוע מול שבוע קודם):** 🗓️"
    
    def format_weekly_comparison(key):
        if key in ['bottle', 'pump']:
            current_val = this_week_stats[key]['total_amount']
            last_val = last_week_stats[key]['total_amount']
            label = keys[key]
        elif key == 'bf_total_minutes': 
             current_val = this_week_stats.get(key, 0)
             last_val = last_week_stats.get(key, 0)
             label = keys[key]
        else:
            current_val = this_week_stats.get(key, 0)
            last_val = last_week_stats.get(key, 0)
            label = keys[key]
        
        diff = current_val - last_val
        
        if diff > 0:
            diff_label = f"גבוה ב-{diff}"
        elif diff < 0:
            diff_label = f"נמוך ב-{abs(diff)}"
        else:
            diff_label = "זהה"
            
        if key in ['bottle', 'pump']:
             return f"• {label}: {current_val} מ״ל. ({diff_label} משבוע שעבר)"
        elif key == 'bf_total_minutes': 
             return f"• {label}: {current_val} דקות. ({diff_label} משבוע שעבר)"
        else:
             return f"• {label}: {current_val} פעולות. ({diff_label} משבוע שעבר)"

        
    weekly_text += "\n".join(format_weekly_comparison(key) for key in keys)
    
    return comparison_text + weekly_text


def get_details_response(user_id: str) -> str:
    """בניית תגובת פירוט"""
    user = get_user_data_single(user_id)
    events = user.get(KEY_EVENTS, [])
    today = get_today_tz().strftime("%Y-%m-%d")
    
    today_events = [e for e in events if e['timestamp'].split(' ')[0] == today]
    
    if not today_events:
        return "לא תועדו אירועים היום. נסי לתעד הנקה/בקבוק/חיתול."
        
    response = "פירוט אירועי היום:\n"
    
    for event in reversed(today_events):
        time_part = event['timestamp'].split(' ')[1] 
        time = time_part[:5] 
        
        if event['type'] == 'breastfeeding':
            side = event['details'].get('side', 'צד לא ידוע')
            duration = event['details'].get('duration', 0)
            duration_text = f" ({duration} דקות)" if duration > 0 else ""
            response += f"- {time}: הנקה {side}{duration_text}\n"
        elif event['type'] == 'bottle':
            amount = event['details'].get('amount', 0)
            response += f"- {time}: בקבוק {amount} מ״ל\n"
        elif event['type'] == 'pump':
            amount = event['details'].get('amount', 0)
            response += f"- {time}: שאיבה {amount} מ״ל\n"
        elif event['type'] == 'diaper':
            d_type = event['details'].get('type', '')
            diaper_type_map = {'pee': 'פיפי', 'poo': 'קקי', 'both': 'מלא'}.get(d_type, 'לא ידוע')
            response += f"- {time}: {diaper_type_map}\n"
            
    return response


def handle_help_menu(user_id: str, message: str) -> list[str]:
    """ מטפל בבחירה בתפריט העזרה. """
    user = get_user_data_single(user_id)
    msg = message.lower().strip()
    
    # ניקוי מצב ממתין
    user['pending_action'] = None
    save_user_data(user_id, user)
    
    # 1. בדיקה לפי מספר
    topic_key = msg
    if topic_key not in HELP_TOPICS:
        # 2. בדיקה לפי מילות מפתח
        found = False
        for key, value in HELP_TOPICS.items():
            if key != 'menu' and any(k in msg for k in value['keywords']):
                topic_key = key
                found = True
                break
        
        if not found:
            return [f"לא זיהיתי את הבחירה '{message}'. אנא נסי שוב עם 1, 2, 3, 4 או 'עזרה' כדי לחזור לתפריט."]

    
    if topic_key in ['1', '2', '3', '4']:
        full_text = HELP_TOPICS[topic_key]['text'] + LEGAL_DISCLAIMER
        return [full_text]
        
    # אם הגיע לכאן בלי בחירה חוקית, מחזיר את תפריט העזרה
    return [HELP_TOPICS['menu']]


def handle_add_partner(user_id: str, partner_phone: str) -> str:
    """מוסיף טלפון של בן/בת זוג ושולח לו הודעה (פיצ'ר 9)"""
    if not partner_phone or len(partner_phone) not in [9, 10]:
        return "אנא שלחי את המספר של בן/בת הזוג בצורה תקינה (לדוגמה: הוסף בן זוג: 0541234567)."

    user = get_user_data_single(user_id)
    baby_name = get_baby_name_or_default(user)
    
    user[KEY_PARTNER_PHONE] = normalize_user_id(partner_phone) # נרמול מספר השותף
    save_user_data(user_id, user)
    
    partner_id_normalized = normalize_user_id(partner_phone)
    partner_data = {'id': partner_id_normalized, 'stage': 5, KEY_ROLE: KEY_PARTNER_USER, 'main_user_id': normalize_user_id(user_id), KEY_NAME: baby_name, KEY_GENDER: user.get(KEY_GENDER)}
    save_user_data(partner_phone, partner_data)
    
    return f"מצויין! נרשם בן/בת זוג עם המספר {partner_phone}.\n" \
           f"שימי לב, הוא/היא יכול/ה לתעד רק בקבוקים וחיתולים עבור {baby_name}."

def default_response(user_data: dict) -> str:
    """תגובת ברירת מחדל"""
    baby_name = get_baby_name_or_default(user_data)
    mom_name = user_data.get(KEY_MOM_NAME, 'יקירה') 
    
    return f"היי {mom_name} 🌼\n\nלא זיהיתי את הפעולה הזו.\nכדי שאוכל לעזור ל{baby_name}, נסי:\n" \
           f"• הנקה: 'ימין 10 דק' \n" \
           f"• בקבוק: 'בקבוק 90' או **'בקבוק'** (כדי שאשאל אותך)\n" \
           f"• חיתולים: 'קקי' או 'פיפי'\n" \
           f"• שאיבות: 'שאבתי' או 'שאיבה', עדיף להוסיף גם כמות.\n" \
           f"• סטטוס יומי: 'סטטוס'\n" \
           f"• עזרה/טיפים: **'עזרה'**"

def handle_logging_action(user_id: str, parsed_input: dict, user: dict) -> list[str]:
    """ פונקציה המרכזת את הלוגיקה של תיעוד יומן."""
    event_type = parsed_input['type']
    baby_name = get_baby_name_or_default(user)
    ate_pronoun = get_gender_text(user, 'אכל', 'אכלה', 'אכל/ה')
    
    if event_type in ['breastfeeding', 'bottle', 'pump', 'diaper']:
        
        role = user.get(KEY_ROLE, KEY_MAIN_USER) 
        
        if role == KEY_PARTNER_USER and event_type not in ['bottle', 'diaper']:
            return ["כבן/בת זוג, אתה יכול/ה לתעד רק בקבוקים ('בקבוק 90') וחיתולים ('קקי'/'פיפי')."]

        if event_type == 'pump' and parsed_input.get('amount', 0) == 0:
            user['pending_action'] = 'pump_amount'
            save_user_data(user_id, user)
            return ["מצוין! כמה שאבת?"]
            
        if event_type == 'bottle' and parsed_input.get('amount', 0) == 0:
            user['pending_action'] = 'bottle_amount'
            save_user_data(user_id, user)
            return [f"כמה {baby_name} {ate_pronoun}?"]
            
        if (event_type == 'bottle' or event_type == 'pump') and parsed_input.get('amount', 0) == 0:
             return ["אנא צייני כמות (לדוגמה: 'בקבוק 90' או 'שאיבה 60')."]
            
        # 1. ביצוע הלוג
        log_response = handle_logging_core(user_id, parsed_input)
        
        # 2. בדיקת עידוד לאחר הלוג
        # חשוב: הפונקציה check_milestone_encouragement קוראת את הנתונים העדכניים ישירות מה-DB (דרך get_user_data_single)
        # ולכן היא לא תדרוס את האירוע החדש.
        today = get_today_tz()
        user_after_log = get_user_data_single(user_id) 
        encouragement_message = check_milestone_encouragement(user_id, user_after_log, today)

        responses = [log_response]
        if encouragement_message:
            responses.append(encouragement_message) # הוספת העידוד כהודעה נפרדת
            
        return responses
        
    return [default_response(user)]


def handle_message(user_id: str, message: str) -> list[str]:
    """פונקציית הליבה לטיפול בהודעה נכנסת - מחזירה רשימת תגובות"""
    
    user_id_normalized = normalize_user_id(user_id) 
    
    user = get_user_data_single(user_id_normalized)
    msg_stripped = message.strip().lower() 
    
    if msg_stripped in ['אפס', 'התחל מחדש', 'reset']:
        delete_user_data(user_id_normalized)
        return ["נתוני המשתמש נמחקו לחלוטין. אנא התחילי שיחה חדשה (שלחי כל הודעה) כדי להתחיל את תהליך ההרשמה מחדש."]
        
    if user is None:
        return onboarding_logic(user_id_normalized, message)
    
    if not is_onboarding_complete(user_id_normalized):
        onboarding_responses = onboarding_logic(user_id_normalized, message)
        if onboarding_responses and onboarding_responses[0] != default_response(user):
             return onboarding_responses

    pending_action = user.get('pending_action')
    parsed_input = parse_input(message)
    event_type = parsed_input['type'] 
    is_logging_action = event_type in ['breastfeeding', 'bottle', 'pump', 'diaper', 'multi_event']
    
    # A. טיפול בפעולות ספציפיות לכמות (התיקון נמצא כאן)
    if pending_action in ['pump_amount', 'bottle_amount']:
        if msg_stripped.isdigit():
            amount = int(msg_stripped)
            if amount > 0:
                event_type_short = pending_action.split('_')[0]
                
                # 1) 💡 תיקון באג דריסת נתונים: ניקוי ה-pending_action ושמירה קודם.
                # הפעולה הזו מבצעת שמירה של האובייקט הקיים (שאין בו עדיין את האירוע) רק כדי לנקות את ה-pending_action.
                user['pending_action'] = None 
                save_user_data(user_id_normalized, user) # שמירה של הניקוי בלבד

                # 2) עכשיו לתעד (handle_logging_core קורא מחדש מה-DB, מוסיף event ושומר).
                parsed_data_final = {
                    'type': event_type_short, 
                    'amount': amount, 
                    'message': f"Recorded {event_type_short} amount {amount}" 
                } 
                log_response = handle_logging_core(user_id_normalized, parsed_data_final)
                
                # 3) בדיקת עידוד 
                today = get_today_tz()
                # חייבים לרענן את user כי הוא הכיל את האירוע החדש אחרי handle_logging_core, אבל אנחנו כבר יודעים שהוא תקין.
                user_after_log = get_user_data_single(user_id_normalized) 
                encouragement_message = check_milestone_encouragement(user_id_normalized, user_after_log, today)

                responses = [log_response]
                if encouragement_message:
                    responses.append(encouragement_message)
                    
                return responses
            else:
                return ["הכמות שצוינה אינה חוקית. אנא שלחי רק מספר חיובי (לדוגמה: 60)."]
        else:
            user['pending_action'] = None 
            save_user_data(user_id_normalized, user)
            return ["לא זיהיתי מספר. ניקיתי את מצב השאילתה הממתינה. אנא נסי שוב עם מספר (לדוגמה: 60) או התחילי פעולה חדשה."]
            
    # B. טיפול ב-Status Followup 
    if pending_action == 'status_followup':
        
        if is_logging_action:
            user['pending_action'] = None
            save_user_data(user_id_normalized, user)
            return handle_logging_action(user_id_normalized, parsed_input, user)
            
        user['pending_action'] = None 
        save_user_data(user_id_normalized, user)
        
        if 'פירוט' in msg_stripped or '1' == msg_stripped:
            return [get_details_response(user_id_normalized)]
        elif 'השוואה' in msg_stripped or '2' == msg_stripped:
            return [get_comparison_response(user_id_normalized, user)]
        else:
            return [default_response(user)]
            
    # C. טיפול בתפריט עזרה ממתין
    if pending_action == 'help_menu':
        # הפונקציה handle_help_menu מטפלת בניקוי ה-pending_action ושליחת התוכן
        return handle_help_menu(user_id_normalized, message) 
        

    # 3. זיהוי פקודות מערכת ואירועים רגילים
    
    if event_type == 'multi_event':
        lines = parsed_input['message'].split('\n')
        batch_responses = []
        
        LOGGABLE_EVENTS = ['breastfeeding', 'bottle', 'pump', 'diaper']
        
        for line in lines:
            line = line.strip()
            if not line:
                continue

            parsed_line = parse_input(line)
            line_event_type = parsed_line['type']
            
            if line_event_type in LOGGABLE_EVENTS:
                # שימו לב: כאן אנחנו קוראים ל-handle_logging_core ישירות (שמחזירה רק את תגובת הלוג)
                log_response = handle_logging_core(user_id_normalized, parsed_line)
                batch_responses.append(f"• {log_response}")
            else:
                batch_responses.append(f"• ⚠️ לא זוהה אירוע לתיעוד בשורה: '{line}'")
                
        if batch_responses:
            # לאחר הוספת כל האירועים בבת אחת, נבדוק אם יש עידוד חדש
            today = get_today_tz()
            user_after_batch = get_user_data_single(user_id_normalized) # שליפה מחדש של הנתונים המעודכנים
            encouragement_message = check_milestone_encouragement(user_id_normalized, user_after_batch, today)

            final_response = [f"✅ נרשמו אירועים:\n" + "\n".join(batch_responses)]
            if encouragement_message:
                final_response.append(encouragement_message)
                
            return final_response
            
        else:
            return [default_response(user)]

            
    if event_type == 'status': 
        return get_status_response(user_id_normalized, user) 
    
    # טיפול בפקודת "עזרה"
    if event_type == 'help_menu':
        user['pending_action'] = 'help_menu'
        save_user_data(user_id_normalized, user)
        return [HELP_TOPICS['menu']] # הצגת התפריט
    
    if event_type == 'details': 
        return [get_details_response(user_id_normalized)]
        
    if event_type == 'comparison':
        return [get_comparison_response(user_id_normalized, user)]
        
    if event_type == 'add_partner': 
        return [handle_add_partner(user_id_normalized, parsed_input.get('phone'))]
    
    # 4. טפל בתיעוד (Logging)
    if is_logging_action:
        # handle_logging_action כוללת את בדיקת ה-24.0 (עידוד)
        return handle_logging_action(user_id_normalized, parsed_input, user)


    # 5. ברירת מחדל
    return [default_response(user)]


# ====================================================
# VII. הגדרת ה-Webhook והשרת
# ====================================================

app = Flask(__name__) # ⬅️ וודא/י ששורה זו מופיעה רק כאן או בראש הקובץ!

@app.route("/sms", methods=['POST']) # ⬅️ תיקון קריטי: שינוי מ- "/whatsapp" ל- "/sms"
def whatsapp_webhook():
    incoming_message = request.values.get('Body', '') 
    user_id_raw = request.values.get('From', '')  
    
    print(f"\n--- DEBUG RAW TWILIO INPUT ---")
    print(f"RAW INPUT: '{incoming_message}'")
    print(f"RAW USER ID: {user_id_raw}")
    print(f"------------------------------\n")
    
    resp = MessagingResponse()
    
    response_list = handle_message(user_id_raw, incoming_message) 
        
    for response_text in response_list:
        resp.message(response_text)

    return str(resp)


if __name__ == "__main__":
    app.run(debug=True, port=5000)

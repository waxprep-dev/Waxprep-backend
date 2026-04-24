"""
Student Onboarding Flow
ADDED: Terms and conditions acceptance step (Step 0 before name)
All imports are lazy to prevent startup errors.
"""
import re
EXAM_SUBJECTS = {
'JAMB': [
'English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology',
'Economics', 'Government', 'Literature in English', 'Geography',
'Commerce', 'Agricultural Science', 'Christian Religious Studies',
'Islamic Religious Studies', 'History', 'Yoruba', 'Igbo', 'Hausa'
],
'WAEC': [
'English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology',
'Economics', 'Government', 'Literature in English', 'Geography',
'Commerce', 'Agricultural Science', 'Further Mathematics',
'Food and Nutrition', 'Computer Studies', 'Technical Drawing'
],
'NECO': [
'English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology',
'Economics', 'Government', 'Literature in English', 'Geography',
'Commerce', 'Agricultural Science'
],
'COMMON_ENTRANCE': [
'English Language', 'Mathematics', 'Basic Science',
'Social Studies', 'Verbal Reasoning', 'Quantitative Reasoning'
],
'POST_UTME': [
'English Language', 'Mathematics', 'Physics', 'Chemistry',
'Biology', 'Economics', 'Government'
],
}
CLASS_LEVELS = ['JSS1', 'JSS2', 'JSS3', 'SS1', 'SS2', 'SS3']
NIGERIAN_STATES = [
'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue',
'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'FCT',
'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi',
'Kwara', 'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo',
'Plateau', 'Rivers', 'Sokoto', 'Taraba', 'Yobe', 'Zamfara'
]
async def handle_new_or_existing(phone: str, conversation: dict, message: str):
"""Handles the very first message from any user."""
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from config.settings import settings
welcome = (
    "Welcome to WaxPrep!\n\n"
    "Nigeria's most advanced study companion. I'm Wax, your personal tutor "
    "for JAMB, WAEC, NECO, and more.\n\n"
    "Are you new to WaxPrep, or do you have a WAX ID already?\n\n"
    "1 — I'm new, create my account\n"
    "2 — I have a WAX ID, log me in"
)

await send_whatsapp_message(phone, welcome)
await update_conversation_state(
    conversation['id'], 'whatsapp', phone,
    {'conversation_state': {'awaiting_response_for': 'new_or_existing'}}
)
async def handle_onboarding_response(phone: str, conversation: dict, message: str):
"""Routes onboarding responses to the correct step handler."""
import json
raw_state = conversation.get('conversation_state', {})
if isinstance(raw_state, str):
    try:
        state = json.loads(raw_state)
    except Exception:
        state = {}
else:
    state = raw_state or {}

awaiting = state.get('awaiting_response_for', '')

handlers = {
    'new_or_existing': _step_new_or_existing,
    'terms_acceptance': _step_terms_acceptance,
    'wax_id_entry': _step_wax_id_entry,
    'pin_entry': _step_pin_entry,
    'name': _step_name,
    'class_level': _step_class_level,
    'target_exam': _step_target_exam,
    'subjects': _step_subjects,
    'exam_date': _step_exam_date,
    'state': _step_state,
    'language_pref': _step_language_pref,
    'pin_setup': _step_pin_setup,
    'pin_confirm': _step_pin_confirm,
}

handler = handlers.get(awaiting)
if handler:
    await handler(phone, conversation, message, state)
else:
    await handle_new_or_existing(phone, conversation, message)
async def _step_new_or_existing(phone: str, conversation: dict, message: str, state: dict):
"""Handles 1 = new student, 2 = existing student."""
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from config.settings import settings
msg = message.strip().lower()
new_keywords = ['1', 'new', "i'm new", 'create', 'register', 'signup', 'sign up']
existing_keywords = ['2', 'existing', 'login', 'log in', 'wax', 'i have']

if any(k in msg for k in new_keywords):
    await send_whatsapp_message(
        phone,
        "Before we set up your account, please read and accept our Terms of Service.\n\n"
        "By using WaxPrep, you agree to:\n\n"
        "1. Use the platform only for educational purposes\n"
        "2. Not share your account with others\n"
        "3. Not attempt to cheat or manipulate the system\n"
        "4. Allow WaxPrep to collect your study data to improve your experience\n"
        "5. Keep your PIN and WAX ID private\n\n"
        f"Full Terms: {settings.TERMS_URL}\n"
        f"Privacy Policy: {settings.PRIVACY_URL}\n\n"
        "Type YES to accept and continue, or NO to decline.\n\n"
        "You must accept to use WaxPrep."
    )
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            'awaiting_response_for': 'terms_acceptance',
            'is_new_student': True
        }
    })

elif any(k in msg for k in existing_keywords):
    await send_whatsapp_message(
        phone,
        "Welcome back!\n\n"
        "Please send your WAX ID to log in.\n\n"
        "It looks like this: WAX-A74892"
    )
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {'awaiting_response_for': 'wax_id_entry'}
    })

else:
    await send_whatsapp_message(
        phone,
        "Please reply with:\n"
        "1 if you are new to WaxPrep\n"
        "2 if you already have a WAX ID"
    )
async def _step_terms_acceptance(phone: str, conversation: dict, message: str, state: dict):
"""Handles terms and conditions acceptance."""
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from config.settings import settings
msg = message.strip().lower()

if msg in ['yes', 'y', 'i agree', 'agree', 'accept', 'i accept', 'ok', 'okay', '1']:
    await send_whatsapp_message(
        phone,
        "Thank you for accepting!\n\n"
        "Let's get you set up. First, what is your full name?\n\n"
        "(Type your name and send)"
    )
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **state,
            'terms_accepted': True,
            'awaiting_response_for': 'name',
            'onboarding_step': 1
        }
    })

elif msg in ['no', 'n', 'decline', 'reject', 'i decline', '2']:
    await send_whatsapp_message(
        phone,
        "No problem. You can come back and accept whenever you are ready.\n\n"
        "WaxPrep is here when you need it.\n\n"
        "Type HI anytime to start again."
    )

else:
    await send_whatsapp_message(
        phone,
        "Please reply with YES to accept the terms and create your account,\n"
        "or NO to decline.\n\n"
        f"Read the full terms here: {settings.TERMS_URL}"
    )
async def _step_wax_id_entry(phone: str, conversation: dict, message: str, state: dict):
"""Handles WAX ID entry for login."""
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from features.wax_id import get_student_by_wax_id
from features.pin import is_account_locked
from helpers import extract_wax_id
wax_id = extract_wax_id(message)

if not wax_id:
    clean = message.strip().upper().replace(' ', '')
    if re.match(r'^WAX[A-Z][A-Z0-9]{5}$', clean):
        wax_id = f"WAX-{clean[3:]}"
    else:
        await send_whatsapp_message(
            phone,
            "That does not look like a valid WAX ID.\n\n"
            "Your WAX ID looks like: WAX-A74892\n\n"
            "Please check and try again, or type NEW to create a new account."
        )
        return

student = await get_student_by_wax_id(wax_id)

if not student:
    await send_whatsapp_message(
        phone,
        f"No account found with WAX ID {wax_id}.\n\n"
        "Please double-check your WAX ID.\n\n"
        "Or type NEW to create a fresh account."
    )
    return

if student.get('is_banned'):
    await send_whatsapp_message(phone, "This account has been suspended. Contact support for help.")
    return

if await is_account_locked(student['id']):
    await send_whatsapp_message(
        phone,
        "Account Temporarily Locked\n\n"
        "Too many wrong PIN attempts. Locked for 30 minutes.\n\n"
        "Please try again later or type RECOVER if you forgot your PIN."
    )
    return

name = student['name'].split()[0]
await send_whatsapp_message(
    phone,
    f"Found it! Welcome back, {name}!\n\n"
    "Please enter your 4-digit PIN to log in."
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {
        'awaiting_response_for': 'pin_entry',
        'pending_wax_id': wax_id,
    }
})
async def _step_pin_entry(phone: str, conversation: dict, message: str, state: dict):
"""Handles PIN entry for existing user login."""
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from features.wax_id import get_student_by_wax_id, link_platform_to_student
from features.pin import record_failed_pin_attempt, clear_failed_attempts
from helpers import verify_pin
pending_wax_id = state.get('pending_wax_id', '')
if not pending_wax_id:
    await handle_new_or_existing(phone, conversation, message)
    return

student = await get_student_by_wax_id(pending_wax_id)
if not student:
    await handle_new_or_existing(phone, conversation, message)
    return

pin = message.strip()
if not verify_pin(pin, student['pin_hash']):
    failed = await record_failed_pin_attempt(student['id'])
    remaining = max(0, 5 - failed)

    if remaining == 0:
        await send_whatsapp_message(
            phone,
            "Account Locked — Too many wrong attempts.\n\n"
            "Locked for 30 minutes. Type RECOVER if you forgot your PIN."
        )
    else:
        await send_whatsapp_message(
            phone,
            f"Wrong PIN. {remaining} attempt{'s' if remaining != 1 else ''} left.\n\n"
            "Type RECOVER if you have forgotten your PIN."
        )
    return

await clear_failed_attempts(student['id'])
await link_platform_to_student(student['id'], 'whatsapp', phone)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'student_id': student['id'],
    'current_mode': 'default',
    'conversation_state': {},
})

from database.students import get_student_subscription_status
status = await get_student_subscription_status(student)
streak = student.get('current_streak', 0)
answered = student.get('total_questions_answered', 0)
name = student['name'].split()[0]

welcome_back = (
    f"Welcome back, {name}!\n\n"
    f"WAX ID: {pending_wax_id}\n"
    f"Plan: {status['display_tier']}\n"
    f"Streak: {streak} day{'s' if streak != 1 else ''}\n"
    f"Total Questions: {answered:,}\n\n"
)

if streak > 0:
    welcome_back += f"Your {streak}-day streak is waiting. Keep it alive today!\n\n"

welcome_back += "What would you like to study?\n\nJust ask me anything, or type HELP for all commands."

await send_whatsapp_message(phone, welcome_back)
async def _step_name(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from helpers import clean_name
name = clean_name(message)

if len(name) < 2:
    await send_whatsapp_message(phone, "That name seems too short. Please enter your full name.")
    return

if len(name) > 100:
    await send_whatsapp_message(phone, "Please enter just your first and last name.")
    return

first = name.split()[0]
options = '\n'.join([f"{i+1}. {lvl}" for i, lvl in enumerate(CLASS_LEVELS)])

await send_whatsapp_message(
    phone,
    f"Nice to meet you, {first}!\n\n"
    f"What class are you in?\n\n{options}\n\n"
    "(Reply with the number or class name)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {**state, 'name': name, 'awaiting_response_for': 'class_level'}
})
async def _step_class_level(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
msg = message.strip().upper()
number_map = {str(i + 1): lvl for i, lvl in enumerate(CLASS_LEVELS)}

class_level = number_map.get(msg) or (msg if msg in CLASS_LEVELS else None)
if not class_level:
    for lvl in CLASS_LEVELS:
        if msg in lvl or lvl in msg:
            class_level = lvl
            break

if not class_level:
    await send_whatsapp_message(
        phone,
        f"Please choose from: {', '.join(CLASS_LEVELS)}\n\n(Reply with the number 1-6)"
    )
    return

await send_whatsapp_message(
    phone,
    f"{class_level}!\n\n"
    "Which exam are you preparing for?\n\n"
    "1 — JAMB (UTME)\n"
    "2 — WAEC (SSCE)\n"
    "3 — NECO\n"
    "4 — Common Entrance\n"
    "5 — Post-UTME\n\n"
    "(Reply with the number)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'}
})
async def _step_target_exam(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
msg = message.strip().upper()
exam_map = {
    '1': 'JAMB', 'JAMB': 'JAMB', 'UTME': 'JAMB',
    '2': 'WAEC', 'WAEC': 'WAEC', 'SSCE': 'WAEC', 'GCE': 'WAEC',
    '3': 'NECO', 'NECO': 'NECO',
    '4': 'COMMON_ENTRANCE', 'COMMON': 'COMMON_ENTRANCE',
    '5': 'POST_UTME', 'POST': 'POST_UTME', 'POSTUTME': 'POST_UTME',
}

target_exam = None
for key, value in exam_map.items():
    if key in msg:
        target_exam = value
        break

if not target_exam:
    await send_whatsapp_message(phone, "Please reply with 1, 2, 3, 4, or 5 to choose your exam.")
    return

available_subjects = EXAM_SUBJECTS.get(target_exam, EXAM_SUBJECTS['JAMB'])
subject_list = '\n'.join([f"{i+1}. {sub}" for i, sub in enumerate(available_subjects[:15])])

note = "JAMB requires 4 subjects (English + 3 others)." if target_exam == 'JAMB' else "Which subjects are you sitting for?"

await send_whatsapp_message(
    phone,
    f"{target_exam}!\n\n"
    f"{note}\n\n"
    f"{subject_list}\n\n"
    "(Reply with numbers separated by commas: e.g., 1,2,4,6)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {
        **state,
        'target_exam': target_exam,
        'available_subjects': available_subjects,
        'awaiting_response_for': 'subjects'
    }
})
async def _step_subjects(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
available = state.get('available_subjects', EXAM_SUBJECTS['JAMB'])
target_exam = state.get('target_exam', 'JAMB')

numbers = re.findall(r'\d+', message)
selected = []

for num_str in numbers:
    num = int(num_str)
    if 1 <= num <= len(available):
        sub = available[num - 1]
        if sub not in selected:
            selected.append(sub)

if not selected:
    msg_upper = message.upper()
    for sub in available:
        if sub.upper() in msg_upper and sub not in selected:
            selected.append(sub)

if 'English Language' not in selected and target_exam in ['JAMB', 'WAEC', 'NECO']:
    selected.insert(0, 'English Language')

if len(selected) < 2:
    await send_whatsapp_message(
        phone,
        "Please select at least 2 subjects.\n\nReply with numbers: e.g., 1,2,4,6"
    )
    return

subjects_display = '\n'.join([f"- {s}" for s in selected])

await send_whatsapp_message(
    phone,
    f"Your subjects:\n{subjects_display}\n\n"
    "When is your exam?\n\n"
    "(e.g., May 2025 or June 2025 or Not sure)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {**state, 'subjects': selected, 'awaiting_response_for': 'exam_date'}
})
async def _step_exam_date(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from datetime import datetime, timedelta
from helpers import nigeria_now
msg = message.strip().lower()
exam_date = None
days_left = 180

months = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6,
    'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12
}

year_match = re.search(r'20(2[4-9]|[3-9]\d)', msg)
year = int(year_match.group(0)) if year_match else None

month = None
for m_name, m_num in months.items():
    if m_name in msg:
        month = m_num
        break

if month and year:
    exam_date = f"{year}-{month:02d}-15"
    exam_dt = datetime(year, month, 15)
    days_left = max(1, (exam_dt - datetime.now()).days)
elif msg in ['not sure', 'soon', 'this year', 'idk', "don't know", 'unsure', 'no']:
    future = nigeria_now() + timedelta(days=180)
    exam_date = future.strftime('%Y-%m-%d')
    days_left = 180

if not exam_date:
    await send_whatsapp_message(
        phone,
        "When is your exam?\n\n"
        "Try:\n- May 2025\n- June 2025\n- Not sure"
    )
    return

if days_left < 30:
    urgency = f"\n\nOnly {days_left} days left! We need to focus hard right away."
elif days_left < 90:
    urgency = f"\n\n{days_left} days to go. Let's build a strong foundation."
else:
    urgency = f"\n\n{days_left} days — plenty of time if we start now and stay consistent."

await send_whatsapp_message(
    phone,
    f"Got it!{urgency}\n\n"
    "Which state are you in?\n\n"
    "(e.g., Lagos, Abuja, Kano, Rivers)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {
        **state,
        'exam_date': exam_date,
        'days_until_exam': days_left,
        'awaiting_response_for': 'state'
    }
})
async def _step_state(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
msg = message.strip().title()
matched = msg

for s in NIGERIAN_STATES:
    if msg.lower() in s.lower() or s.lower() in msg.lower():
        matched = s
        break

await send_whatsapp_message(
    phone,
    f"{matched}!\n\n"
    "How would you like me to explain things?\n\n"
    "1 — Standard English\n"
    "2 — Naija Pidgin mixed with English\n\n"
    "(You can always switch this later)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {**state, 'student_state': matched, 'awaiting_response_for': 'language_pref'}
})
async def _step_language_pref(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
msg = message.strip().lower()
if any(k in msg for k in ['2', 'pidgin', 'naija']):
    language = 'pidgin'
else:
    language = 'english'

await send_whatsapp_message(
    phone,
    "Almost done!\n\n"
    "Let's set your security PIN.\n\n"
    "Your PIN is a 4-digit number you will use to log in on any device.\n"
    "Keep it private — do not share it with anyone.\n\n"
    "What 4-digit PIN would you like? (e.g., 5823)"
)

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {**state, 'language_pref': language, 'awaiting_response_for': 'pin_setup'}
})
async def _step_pin_setup(phone: str, conversation: dict, message: str, state: dict):
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from helpers import is_valid_pin
pin = message.strip()
weak_pins = {'1234', '0000', '1111', '2222', '3333', '4444',
             '5555', '6666', '7777', '8888', '9999', '1212', '0123'}

if not is_valid_pin(pin):
    await send_whatsapp_message(phone, "Your PIN must be exactly 4 digits. Please try again.")
    return

if pin in weak_pins:
    await send_whatsapp_message(phone, "That PIN is too easy to guess. Please choose a more unique one.")
    return

await send_whatsapp_message(phone, "Got it! Please confirm your PIN by typing it again.")

await update_conversation_state(conversation['id'], 'whatsapp', phone, {
    'conversation_state': {**state, 'pending_pin': pin, 'awaiting_response_for': 'pin_confirm'}
})
async def _step_pin_confirm(phone: str, conversation: dict, message: str, state: dict):
"""Final onboarding step — creates the account."""
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from database.students import create_student
from features.wax_id import link_platform_to_student
from config.settings import settings
pin_confirm = message.strip()
pending_pin = state.get('pending_pin', '')

if pin_confirm != pending_pin:
    await send_whatsapp_message(
        phone,
        "Those PINs do not match.\n\nPlease enter your desired PIN again:"
    )
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {**state, 'pending_pin': None, 'awaiting_response_for': 'pin_setup'}
    })
    return

try:
    student = await create_student(
        phone=phone,
        name=state.get('name', 'Student'),
        pin=pending_pin,
        class_level=state.get('class_level'),
        target_exam=state.get('target_exam'),
        subjects=state.get('subjects', []),
        exam_date=state.get('exam_date'),
        state=state.get('student_state'),
        referred_by_wax_id=state.get('referred_by_wax_id'),
    )

    await link_platform_to_student(student['id'], 'whatsapp', phone)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'student_id': student['id'],
        'current_mode': 'default',
        'conversation_state': {},
    })

    wax_id = student['wax_id']
    recovery_code = student['recovery_code']
    name_first = student['name'].split()[0]
    days_left = state.get('days_until_exam', 180)
    trial_days = settings.TRIAL_DURATION_DAYS

    welcome = (
        f"Welcome to WaxPrep, {name_first}!\n\n"
        f"Your account is ready. Save these now:\n\n"
        f"WAX ID: {wax_id}\n"
        f"Recovery Code: {recovery_code}\n\n"
        f"Write these down somewhere safe.\n"
        f"They are how you get back in if you lose your phone.\n\n"
        f"{trial_days}-Day Full Access Trial is now ACTIVE!\n"
        f"You have everything unlocked for {trial_days} days, free.\n\n"
    )

    if days_left < 180:
        welcome += f"Your exam is in {days_left} days. Let's make every day count.\n\n"

    welcome += (
        "What would you like to do?\n\n"
        "LEARN [topic] — Teach me something\n"
        "QUIZ [subject] — Test my knowledge\n"
        "EXAM — Mock exam mode\n"
        "HELP — All commands\n\n"
        "Or just ask me any question right now!"
    )

    await send_whatsapp_message(phone, welcome)

except Exception as e:
    print(f"Account creation error: {e}")
    import traceback
    traceback.print_exc()
    await send_whatsapp_message(
        phone,
        "There was an error creating your account.\n\n"
        "Please try again by sending HI.\n\n"
        f"Reference: {str(e)[:50]}"
    )

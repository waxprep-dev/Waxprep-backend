"""
Telegram-specific onboarding flow.
Uses send_telegram_message instead of WhatsApp sender.
All steps are identical to the WhatsApp onboarding, just adapted for Telegram.
"""

import re
from telegram.sender import send_telegram_message
from database.conversations import update_conversation_state
from config.settings import settings

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


async def handle_new_or_existing(chat_id: int, conversation: dict, message: str):
    welcome = (
        "Welcome to WaxPrep!\n\n"
        "Nigeria's smartest AI study companion. I'm Wax, your personal tutor "
        "for JAMB, WAEC, NECO, Post-UTME, and more.\n\n"
        "Are you new here, or do you already have a WAX ID?\n\n"
        "*1* — I'm new, create my account\n"
        "*2* — I have a WAX ID, log me in"
    )

    await send_telegram_message(chat_id, welcome)
    await update_conversation_state(
        conversation['id'], 'telegram', str(chat_id),
        {'conversation_state': {'awaiting_response_for': 'new_or_existing'}}
    )


async def handle_onboarding_response(chat_id: int, conversation: dict, message: str):
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
        await handler(chat_id, conversation, message, state)
    else:
        await handle_new_or_existing(chat_id, conversation, message)


async def _step_new_or_existing(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    new_keywords = ['1', 'new', "i'm new", 'create', 'register', 'signup']
    existing_keywords = ['2', 'existing', 'login', 'log in', 'have', 'wax']

    if any(k in msg for k in new_keywords):
        await send_telegram_message(
            chat_id,
            "Before we set up your account, please accept our Terms of Service.\n\n"
            "By using WaxPrep, you agree to:\n\n"
            "Use the platform only for your own study\n"
            "Keep your WAX ID and PIN private\n"
            "Not attempt to manipulate the system or share answers\n"
            "Allow WaxPrep to use your study data to personalize your experience\n\n"
            f"Full Terms: {settings.TERMS_URL}\n\n"
            "Type *YES* to accept and create your account.\n"
            "Type *NO* to decline."
        )
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': {
                'awaiting_response_for': 'terms_acceptance',
                'is_new_student': True
            }
        })

    elif any(k in msg for k in existing_keywords):
        await send_telegram_message(
            chat_id,
            "Welcome back!\n\n"
            "Send your WAX ID to log in.\n\n"
            "It looks like: *WAX-A74892*"
        )
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': {'awaiting_response_for': 'wax_id_entry'}
        })

    else:
        await send_telegram_message(
            chat_id,
            "Please reply with:\n"
            "*1* — New to WaxPrep\n"
            "*2* — Already have a WAX ID"
        )


async def _step_terms_acceptance(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    if msg in ['yes', 'y', 'agree', 'accept', 'i agree', 'i accept', 'ok', 'okay', '1']:
        await send_telegram_message(
            chat_id,
            "Thank you! Let's set up your account.\n\n"
            "First, what is your full name?\n\n"
            "_(Type your name and send)_"
        )
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': {**state, 'terms_accepted': True, 'awaiting_response_for': 'name'}
        })
    elif msg in ['no', 'n', 'decline', 'reject', '2']:
        await send_telegram_message(
            chat_id,
            "No problem. Come back anytime.\n\n"
            "WaxPrep is here whenever you're ready.\n\n"
            "Type *HI* to start again."
        )
    else:
        await send_telegram_message(
            chat_id,
            "Please reply *YES* to accept and continue, or *NO* to decline.\n\n"
            f"Read the full terms: {settings.TERMS_URL}"
        )


async def _step_wax_id_entry(chat_id: int, conversation: dict, message: str, state: dict):
    from helpers import extract_wax_id
    from features.wax_id import get_student_by_wax_id
    from database.cache import get_failed_pin_count

    wax_id = extract_wax_id(message)
    if not wax_id:
        clean = message.strip().upper().replace(' ', '')
        if re.match(r'^WAX[A-Z][A-Z0-9]{5}$', clean):
            wax_id = f"WAX-{clean[3:]}"
        else:
            await send_telegram_message(
                chat_id,
                "That does not look like a valid WAX ID.\n\n"
                "Your WAX ID looks like: *WAX-A74892*\n\n"
                "Check and try again, or type *NEW* to create a fresh account."
            )
            return

    student = await get_student_by_wax_id(wax_id)
    if not student:
        await send_telegram_message(
            chat_id,
            f"No account found with WAX ID *{wax_id}*.\n\n"
            "Double-check your WAX ID.\n\n"
            "Or type *NEW* to create a fresh account."
        )
        return

    if student.get('is_banned'):
        await send_telegram_message(chat_id, "This account has been suspended. Contact support.")
        return

    if get_failed_pin_count(student['id']) >= 5:
        await send_telegram_message(
            chat_id,
            "Account Temporarily Locked\n\n"
            "Too many wrong PIN attempts. Locked for 30 minutes.\n\n"
            "Please try again later."
        )
        return

    name = student['name'].split()[0]
    await send_telegram_message(
        chat_id,
        f"Found it! Welcome back, *{name}*!\n\n"
        "Please enter your 4-digit PIN to log in."
    )

    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {
            'awaiting_response_for': 'pin_entry',
            'pending_wax_id': wax_id,
        }
    })


async def _step_pin_entry(chat_id: int, conversation: dict, message: str, state: dict):
    from features.wax_id import get_student_by_wax_id, link_platform_to_student
    from database.cache import record_failed_pin, clear_failed_pins
    from helpers import verify_pin

    pending_wax_id = state.get('pending_wax_id', '')
    if not pending_wax_id:
        await handle_new_or_existing(chat_id, conversation, message)
        return

    student = await get_student_by_wax_id(pending_wax_id)
    if not student:
        await handle_new_or_existing(chat_id, conversation, message)
        return

    pin = message.strip()
    if not verify_pin(pin, student['pin_hash']):
        failed = record_failed_pin(student['id'])
        remaining = max(0, 5 - failed)
        if remaining == 0:
            await send_telegram_message(
                chat_id,
                "Account Locked — Too many wrong attempts.\n\nLocked for 30 minutes."
            )
        else:
            await send_telegram_message(
                chat_id,
                f"Wrong PIN. {remaining} attempt{'s' if remaining != 1 else ''} left."
            )
        return

    clear_failed_pins(student['id'])
    await link_platform_to_student(student['id'], 'telegram', str(chat_id))

    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
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
        f"Welcome back, *{name}*!\n\n"
        f"WAX ID: {pending_wax_id}\n"
        f"Plan: {status['display_tier']}\n"
        f"Streak: {streak} day{'s' if streak != 1 else ''}\n"
        f"Total Questions: {answered:,}\n\n"
    )
    if streak > 0:
        welcome_back += f"Your {streak}-day streak is waiting. Keep it alive today!\n\n"
    welcome_back += "What would you like to study? Just ask me anything."

    await send_telegram_message(chat_id, welcome_back)


async def _step_name(chat_id: int, conversation: dict, message: str, state: dict):
    from helpers import clean_name
    name = clean_name(message)
    if len(name) < 2:
        await send_telegram_message(chat_id, "That name seems too short. Please enter your full name.")
        return
    if len(name) > 100:
        await send_telegram_message(chat_id, "Please enter just your first and last name.")
        return

    first = name.split()[0]
    options = '\n'.join([f"{i+1}. {lvl}" for i, lvl in enumerate(CLASS_LEVELS)])
    await send_telegram_message(
        chat_id,
        f"Nice to meet you, *{first}*!\n\n"
        f"What class are you in?\n\n{options}\n\n"
        "_(Reply with the number or class name)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'name': name, 'awaiting_response_for': 'class_level'}
    })


async def _step_class_level(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().upper()
    number_map = {str(i + 1): lvl for i, lvl in enumerate(CLASS_LEVELS)}
    class_level = number_map.get(msg) or (msg if msg in CLASS_LEVELS else None)
    if not class_level:
        for lvl in CLASS_LEVELS:
            if msg in lvl or lvl in msg:
                class_level = lvl
                break
    if not class_level:
        await send_telegram_message(
            chat_id,
            f"Please choose from: {', '.join(CLASS_LEVELS)}\n\n(Reply with the number 1-6)"
        )
        return

    await send_telegram_message(
        chat_id,
        f"{class_level}!\n\n"
        "Which exam are you preparing for?\n\n"
        "1 — JAMB (UTME)\n"
        "2 — WAEC (SSCE)\n"
        "3 — NECO\n"
        "4 — Common Entrance\n"
        "5 — Post-UTME\n\n"
        "_(Reply with the number)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'}
    })


async def _step_target_exam(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().upper()
    exam_map = {
        '1': 'JAMB', 'JAMB': 'JAMB', 'UTME': 'JAMB',
        '2': 'WAEC', 'WAEC': 'WAEC', 'SSCE': 'WAEC', 'GCE': 'WAEC',
        '3': 'NECO', 'NECO': 'NECO',
        '4': 'COMMON_ENTRANCE', 'COMMON': 'COMMON_ENTRANCE',
        '5': 'POST_UTME', 'POST': 'POST_UTME', 'POSTUTME': 'POST_UTME',
    }
    
    target_exams = []
    for key, value in exam_map.items():
        if key in msg:
            target_exams.append(value)
    target_exam = target_exams[0] if target_exams else None
    is_multi_exam = len(target_exams) > 1

    if not target_exam:
        await send_telegram_message(chat_id, "Please reply with 1, 2, 3, 4, or 5 to choose your exam.")
        return

    if is_multi_exam:
        # Combine subjects from all selected exams
        available_subjects = []
        for exam in target_exams:
            for sub in EXAM_SUBJECTS.get(exam, []):
                if sub not in available_subjects:
                    available_subjects.append(sub)
        exam_display = " + ".join(target_exams)
        note = f"{exam_display} — pick all the subjects you're sitting for."
    else:
        available_subjects = EXAM_SUBJECTS.get(target_exam, EXAM_SUBJECTS['JAMB'])
        note = "JAMB requires 4 subjects (English + 3 others)." if target_exam == 'JAMB' else "Which subjects are you sitting for?"

    subject_list = '\n'.join([f"{i+1}. {sub}" for i, sub in enumerate(available_subjects[:15])])

    await send_telegram_message(
        chat_id,
        f"{' + '.join(target_exams) if is_multi_exam else target_exam}!\n\n"
        f"{note}\n\n"
        f"{subject_list}\n\n"
        "_(Reply with numbers separated by commas: e.g. 1,2,4,6)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {
            **state, 
            'target_exam': 'Multiple' if is_multi_exam else target_exam, 
            'target_exams': target_exams,
            'available_subjects': available_subjects, 
            'awaiting_response_for': 'subjects'
        }
    })


async def _step_subjects(chat_id: int, conversation: dict, message: str, state: dict):
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
        await send_telegram_message(chat_id, "Please select at least 2 subjects.\n\nReply with numbers: e.g. 1,2,4,6")
        return

    subjects_display = '\n'.join([f"- {s}" for s in selected])
    await send_telegram_message(
        chat_id,
        f"Your subjects:\n{subjects_display}\n\n"
        "When is your exam?\n\n"
        "_(e.g. May 2026 or June 2026 or Not sure)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'subjects': selected, 'awaiting_response_for': 'exam_date'}
    })


async def _step_exam_date(chat_id: int, conversation: dict, message: str, state: dict):
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
    elif msg in ['not sure', 'soon', 'this year', 'idk', "don't know", 'unsure', 'no', 'skip']:
        class_level = state.get('class_level', 'SS3')
        if 'SS1' in class_level:
            years_ahead = 2
        elif 'SS2' in class_level:
            years_ahead = 1
        else:
            years_ahead = 0
        future_year = nigeria_now().year + years_ahead
        exam_date = f"{future_year}-06-15"
        days_left = max(1, (datetime(future_year, 6, 15) - datetime.now()).days)

    if not exam_date:
        await send_telegram_message(chat_id, "When is your exam?\n\nTry:\n- May 2026\n- June 2026\n- Not sure")
        return

    if days_left < 30:
        urgency = f"\n\nOnly {days_left} days left! We need to move fast."
    elif days_left < 90:
        urgency = f"\n\n{days_left} days. Enough time if we stay focused."
    else:
        urgency = f"\n\n{days_left} days — plenty of time if we start now and stay consistent."

    await send_telegram_message(
        chat_id,
        f"Got it!{urgency}\n\nWhich state are you in?\n\n_(e.g. Lagos, Abuja, Kano, Rivers)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'exam_date': exam_date, 'days_until_exam': days_left, 'awaiting_response_for': 'state'}
    })


async def _step_state(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().title()
    matched = msg
    for s in NIGERIAN_STATES:
        if msg.lower() in s.lower() or s.lower() in msg.lower():
            matched = s
            break
    await send_telegram_message(
        chat_id,
        f"{matched}!\n\n"
        "How should I explain things to you?\n\n"
        "*1* — Standard English\n"
        "*2* — Nigerian Pidgin mixed with English\n\n"
        "_(You can change this anytime)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'student_state': matched, 'awaiting_response_for': 'language_pref'}
    })


async def _step_language_pref(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    language = 'pidgin' if any(k in msg for k in ['2', 'pidgin', 'naija']) else 'english'
    await send_telegram_message(
        chat_id,
        "Almost done!\n\n"
        "Set a 4-digit security PIN.\n\n"
        "Your PIN is how you log in on any device. Keep it private.\n\n"
        "_(Enter any 4 digits, e.g. 5823)_"
    )
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'language_pref': language, 'awaiting_response_for': 'pin_setup'}
    })


async def _step_pin_setup(chat_id: int, conversation: dict, message: str, state: dict):
    from helpers import is_valid_pin
    pin = message.strip()
    weak_pins = {'1234', '0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999', '1212', '0123'}
    if not is_valid_pin(pin):
        await send_telegram_message(chat_id, "Your PIN must be exactly 4 digits. Please try again.")
        return
    if pin in weak_pins:
        await send_telegram_message(chat_id, "That PIN is too easy to guess. Please choose a more unique one.")
        return
    await send_telegram_message(chat_id, "Got it! Confirm your PIN by typing it again.")
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
        'conversation_state': {**state, 'pending_pin': pin, 'awaiting_response_for': 'pin_confirm'}
    })


async def _step_pin_confirm(chat_id: int, conversation: dict, message: str, state: dict):
    from database.students import create_student
    from features.wax_id import link_platform_to_student
    from features.notifications import notify_admin_new_student, fire_and_forget
    from helpers import clean_name

    pin_confirm = message.strip()
    pending_pin = state.get('pending_pin', '')
    if pin_confirm != pending_pin:
        await send_telegram_message(chat_id, "Those PINs do not match.\n\nPlease enter your desired PIN again:")
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': {**state, 'pending_pin': None, 'awaiting_response_for': 'pin_setup'}
        })
        return

    try:
        student = await create_student(
            phone=f"telegram:{chat_id}",
            name=state.get('name', 'Student'),
            pin=pending_pin,
            class_level=state.get('class_level'),
            target_exam=state.get('target_exam'),
            subjects=state.get('subjects', []),
            exam_date=state.get('exam_date'),
            state=state.get('student_state'),
            referred_by_wax_id=state.get('referred_by_wax_id'),
            language_preference=state.get('language_pref', 'english'),
        )

        await link_platform_to_student(student['id'], 'telegram', str(chat_id))

        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'student_id': student['id'],
            'current_mode': 'default',
            'conversation_state': {},
        })

        fire_and_forget(notify_admin_new_student(student, f"telegram:{chat_id}"))

        wax_id = student['wax_id']
        recovery_code = student['recovery_code']
        name_first = student['name'].split()[0]
        days_left = state.get('days_until_exam', 180)
        trial_days = settings.TRIAL_DURATION_DAYS

        welcome = (
            f"Welcome to WaxPrep, *{name_first}*!\n\n"
            f"Your account is ready. *Save these now:*\n\n"
            f"WAX ID: *{wax_id}*\n"
            f"Recovery Code: *{recovery_code}*\n\n"
            f"Write these somewhere safe. They are how you get back in if you lose your phone.\n\n"
            f"*{trial_days}-Day Full Access Trial is now ACTIVE!*\n"
            f"Everything is unlocked for {trial_days} days — completely free.\n\n"
        )
        if days_left < 180:
            welcome += f"Your exam is in {days_left} days. Let's make every day count.\n\n"
        welcome += (
            "What do you want to do?\n\n"
            "Just ask me any question\n"
            "Or type *QUIZ [subject]* to get tested\n"
            "Or type *HELP* to see all commands"
        )

        await send_telegram_message(chat_id, welcome)

    except Exception as e:
        print(f"Account creation error: {e}")
        await send_telegram_message(
            chat_id,
            "There was an error creating your account.\n\n"
            "Please try again by sending *HI*.\n\n"
            f"Reference: {str(e)[:50]}"
        )

import re
import asyncio
import json
import random
from datetime import datetime
from telegram.sender import send_telegram_message
from database.conversations import update_conversation_state
from config.settings import settings
from constants import EXAM_SUBJECTS, CLASS_LEVELS, NIGERIAN_STATES, SUBJECT_INTROS, get_welcome_intro, WELCOME_VARIANTS

# Helper: save onboarding state to Redis for unregistered users
async def _save_onboarding_state(chat_id, state_dict):
    """Saves the current onboarding step to Redis so it survives between messages."""
    from database.conversations import save_onboarding_state
    await save_onboarding_state('telegram', str(chat_id), state_dict)


async def handle_new_or_existing(chat_id: int, conversation: dict, message: str):
    welcome = random.choice(WELCOME_VARIANTS)
    await send_telegram_message(chat_id, welcome)
    # Save state in Redis for anonymous users
    await _save_onboarding_state(chat_id, {'awaiting_response_for': 'new_or_existing'})


async def handle_onboarding_response(chat_id: int, conversation: dict, message: str, onboarding_state_override: dict = None):
    # Use the override state (from handler.py's Redis store) if provided,
    # otherwise fall back to reading from the conversation object.
    if onboarding_state_override is not None:
        state = onboarding_state_override
    else:
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
        'student_goal': _step_student_goal,
        'terms_acceptance': _step_terms_acceptance,
        'wax_id_entry': _step_wax_id_entry, 'pin_entry': _step_pin_entry,
        'name': _step_name, 'difficult_subject': _step_difficult_subject,
        'class_level': _step_class_level, 'target_exam': _step_target_exam,
        'subjects': _step_subjects, 'exam_date': _step_exam_date, 'exam_year_confirm': _step_exam_year_confirm,
        'state': _step_state, 'language_pref': _step_language_pref,
        'pin_setup': _step_pin_setup, 'pin_confirm': _step_pin_confirm,
    }
    handler = handlers.get(awaiting)
    if handler:
        await handler(chat_id, conversation, message, state)
    else:
        await handle_new_or_existing(chat_id, conversation, message)


async def _step_new_or_existing(chat_id, conversation, message, state):
    msg = message.strip().lower()

    if any(k in msg for k in ['2', 'existing', 'login', 'log in', 'have', 'wax']):
        await send_telegram_message(chat_id,
            "Before we log you in, please accept our Terms of Service.\n\n"
            "By using WaxPrep, you agree to use it for your own study, keep your PIN private, "
            f"and not misuse the platform.\n\nFull Terms: {settings.TERMS_URL}\n\n"
            "Type *YES* to accept and log in."
        )
        await _save_onboarding_state(chat_id, {'awaiting_response_for': 'terms_acceptance', 'is_new_student': False})
        return

    if any(k in msg for k in ['1', 'new', "i'm new", 'create', 'register', 'signup']) or 'new' in msg:
        await send_telegram_message(chat_id,
            "Great! Let's get you set up. First — what do you need help with?\n\n"
            "*1* — My schoolwork\n"
            "*2* — Preparing for a test or exam\n"
            "*3* — I just want to learn something new\n\n"
            "_(Reply with the number, or just tell me in your own words)_"
        )
        await _save_onboarding_state(chat_id, {'awaiting_response_for': 'student_goal', 'is_new_student': True})
        return

    await send_telegram_message(chat_id,
        "Are you new to WaxPrep, or do you already have an account?\n\n"
        "*1* — I'm new\n"
        "*2* — I have a WAX ID"
    )


async def _step_student_goal(chat_id, conversation, message, state):
    msg = message.strip().lower()

    goal_map = {
        '1': 'schoolwork', '2': 'exam prep', '3': 'learning',
        'school': 'schoolwork', 'exam': 'exam prep', 'learn': 'learning',
    }

    goal = None
    for key, value in goal_map.items():
        if key in msg:
            goal = value
            break

    if not goal:
        await send_telegram_message(chat_id,
            "Just pick one that's closest:\n\n"
            "*1* — My schoolwork\n"
            "*2* — Preparing for a test or exam\n"
            "*3* — I just want to learn something new"
        )
        return

    await send_telegram_message(chat_id,
        f"Got it — {goal}. Before we continue, please accept our Terms of Service.\n\n"
        "By using WaxPrep, you agree to use it for your own study, keep your PIN private, "
        f"and not misuse the platform.\n\nFull Terms: {settings.TERMS_URL}\n\n"
        "Type *YES* to accept and create your account."
    )
    await _save_onboarding_state(chat_id, {**state, 'student_goal': goal, 'awaiting_response_for': 'terms_acceptance'})


async def _step_terms_acceptance(chat_id, conversation, message, state):
    msg = message.strip().lower()
    is_new = state.get('is_new_student', True)

    if msg in ['yes', 'y', 'agree', 'accept', 'i agree', 'i accept', 'ok', 'okay', '1']:
        if is_new:
            await send_telegram_message(chat_id, "Thank you! Let's set up your account.\n\nFirst, what is your full name?\n\n_(Type your name and send)_")
            await _save_onboarding_state(chat_id, {**state, 'terms_accepted': True, 'awaiting_response_for': 'name'})
        else:
            await send_telegram_message(chat_id, "Welcome back!\n\nSend your WAX ID to log in.\n\nIt looks like: *WAX-A74892*")
            await _save_onboarding_state(chat_id, {'awaiting_response_for': 'wax_id_entry'})
    elif msg in ['no', 'n', 'decline', 'reject', '2']:
        await send_telegram_message(chat_id, "No problem. Come back anytime.\n\nWaxPrep is here whenever you're ready.\n\nType *HI* to start again.")
    else:
        await send_telegram_message(chat_id, "Please reply *YES* to accept and continue, or *NO* to decline.\n\nRead the full terms: {}".format(settings.TERMS_URL))


async def _step_wax_id_entry(chat_id, conversation, message, state):
    from helpers import extract_wax_id
    from features.wax_id import get_student_by_wax_id
    from database.cache import get_failed_pin_count

    msg = message.strip()

    # FIRST: Check if student wants to escape to new account
    escape_keywords = ['new', 'create', 'register', 'signup', 'fresh', "i don't have", 'i dont have', 'no id', 'no account', 'start over', 'reset', 'none', 'i am new', "i'm new"]
    if any(k in msg.lower() for k in escape_keywords):
        await send_telegram_message(chat_id,
            "No problem! Let's create a fresh account for you. First — what do you need help with?\n\n"
            "*1* — My schoolwork\n"
            "*2* — Preparing for a test or exam\n"
            "*3* — I just want to learn something new\n\n"
            "_(Reply with the number, or just tell me in your own words)_"
        )
        await _save_onboarding_state(chat_id, {'awaiting_response_for': 'student_goal', 'is_new_student': True})
        return

    wax_id = extract_wax_id(message)
    if not wax_id:
        clean = message.strip().upper().replace(' ', '')
        if re.match(r'^WAX[A-Z][A-Z0-9]{5}$', clean):
            wax_id = f"WAX-{clean[3:]}"
        else:
            await send_telegram_message(chat_id,
                "That does not look like a valid WAX ID.\n\n"
                "Your WAX ID looks like: *WAX-A74892*\n\n"
                "Check and try again, or type *NEW* to create a fresh account."
            )
            return

    student = await get_student_by_wax_id(wax_id)
    if not student:
        await send_telegram_message(chat_id,
            f"No account found with WAX ID *{wax_id}*.\n\n"
            "Double-check your WAX ID, or type *NEW* to create a fresh account."
        )
        return
    if student.get('is_banned'):
        await send_telegram_message(chat_id, "This account has been suspended. Contact support.")
        return
    if get_failed_pin_count(student['id']) >= 5:
        await send_telegram_message(chat_id,
            "Account Temporarily Locked\n\n"
            "Too many wrong PIN attempts. Locked for 30 minutes.\n\n"
            "Please try again later."
        )
        return

    name = student['name'].split()[0]
    await send_telegram_message(chat_id,
        f"Found it! Welcome back, *{name}*!\n\n"
        "Please enter your 4-digit PIN to log in."
    )
    await _save_onboarding_state(chat_id, {'awaiting_response_for': 'pin_entry', 'pending_wax_id': wax_id})


async def _step_pin_entry(chat_id, conversation, message, state):
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
            await send_telegram_message(chat_id, "Account Locked — Too many wrong attempts.\n\nLocked for 30 minutes.")
        else:
            await send_telegram_message(chat_id, f"Wrong PIN. {remaining} attempt{'s' if remaining != 1 else ''} left.")
        return
    clear_failed_pins(student['id'])
    await link_platform_to_student(student['id'], 'telegram', str(chat_id))
    # Clear onboarding state since the student is now logged in
    from database.conversations import clear_onboarding_state
    await clear_onboarding_state('telegram', str(chat_id))
    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {'student_id': student['id'], 'current_mode': 'default', 'conversation_state': {}})
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    name = student['name'].split()[0]
    welcome_back = f"Welcome back, *{name}*!\n\nWAX ID: {pending_wax_id}\nPlan: {status['display_tier']}\nStreak: {student.get('current_streak', 0)} day{'s' if student.get('current_streak', 0) != 1 else ''}\nTotal Questions: {student.get('total_questions_answered', 0):,}\n\n"
    if student.get('current_streak', 0) > 0:
        welcome_back += f"Your {student.get('current_streak')}-day streak is waiting. Keep it alive today!\n\n"
    welcome_back += "What would you like to study? Just ask me anything."
    await send_telegram_message(chat_id, welcome_back)


async def _step_name(chat_id, conversation, message, state):
    from helpers import clean_name
    name = clean_name(message)

    if len(name) < 3:
        await send_telegram_message(chat_id, "That name seems too short. Please enter your full name.")
        return

    invalid_names = {'wa', 'ok', 'hi', 'no', 'yes', 'test', 'ab', 'cd', 'name', 'student', 'user'}
    if name.lower() in invalid_names or len(name.split()) < 2:
        await send_telegram_message(
            chat_id,
            "Please enter your first and last name, like *Chidera Emeka* or *Amina Bello*."
        )
        return

    if len(name) > 100:
        await send_telegram_message(chat_id, "Please enter just your first and last name.")
        return

    first = name.split()[0]
    subjects_list = EXAM_SUBJECTS.get('WAEC', EXAM_SUBJECTS['JAMB'])
    subjects_preview = '\n'.join([f"{s}" for s in subjects_list[:8]])

    await send_telegram_message(
        chat_id,
        f"Nice to meet you, *{first}*!\n\n"
        f"Before we go further — which subject gives you the most trouble right now?\n\n"
        f"For example:\n{subjects_preview}\n... or anything else.\n\n"
        f"_(Just type the subject name)_"
    )
    await _save_onboarding_state(chat_id, {**state, 'name': name, 'awaiting_response_for': 'difficult_subject'})


async def _step_difficult_subject(chat_id, conversation, message, state):
    difficult_subject = message.strip()
    first = state.get('name', 'Student').split()[0]
    class_level = state.get('class_level', 'SS3')

    # Step 1: Immediate acknowledgment
    await send_telegram_message(
        chat_id,
        f"*{difficult_subject}* — excellent choice. Let me show you something real quick..."
    )

    # Step 2: Call the AI to generate the Magic Trick lesson
    magic_lesson = await _generate_magic_trick(chat_id, difficult_subject, first, class_level)

    # Step 3: Deliver the Magic Trick lesson
    await send_telegram_message(chat_id, magic_lesson)

    # Step 4: Transition to class level
    await send_telegram_message(
        chat_id,
        f"That was just a warmup, *{first}*. Now let me learn a bit more about you so I can personalise everything.\n\n"
        f"What class are you in?\n\n"
        f"{chr(10).join([f'{i+1}. {lvl}' for i, lvl in enumerate(CLASS_LEVELS)])}\n\n"
        f"_(Reply with the number or class name)_"
    )
    await _save_onboarding_state(chat_id, {**state, 'difficult_subject': difficult_subject, 'awaiting_response_for': 'class_level'})


async def _generate_magic_trick(chat_id: int, subject: str, student_name: str, class_level: str) -> str:
    """Calls the AI for the Magic Trick lesson, with fallback."""
    import asyncio
    from ai.brain import magic_trick_lesson

    try:
        lesson = await asyncio.wait_for(
            magic_trick_lesson(subject, student_name, class_level),
            timeout=12.0
        )
        if lesson and len(lesson.strip()) > 20:
            return lesson.strip()
    except asyncio.TimeoutError:
        print(f"Magic Trick timed out for subject: {subject}")
    except Exception as e:
        print(f"Magic Trick error for {subject}: {e[:100]}")

    fallback_messages = {
        'physics': f"Ah, Physics. Most people fear it until they realise it's just the rules of how things move and work around us. Think of a danfo bus — when it suddenly brakes and you jerk forward, that's Physics in action. You already understand it more than you think, {student_name}.",
        'chemistry': f"Chemistry! It sounds intimidating but it's honestly just cooking with extra steps. When you soak garri and it swells, or when your puff-puff rises because of baking soda — that's Chemistry. You've been doing it since you were small, {student_name}.",
        'biology': f"Biology — the study of life itself. You live inside a Biology classroom every day. Your own body breathing, digesting, fighting off mosquitoes — that's Biology. You already know more than you give yourself credit for, {student_name}.",
        'mathematics': f"Maths! A lot of students run from it, but at its heart, Maths is just patterns. When a suya seller calculates your change, or you split money with friends — you're doing Maths. It's not a foreign language, {student_name}, it's just a skill you haven't fully trusted yourself with yet.",
        'economics': f"Economics — you're already living it. Every time you go to the market and see prices change, or hear about the naira on the news, you're watching Economics happen. The trick is just learning the names for things you already notice, {student_name}.",
        'government': f"Government! It's really just the story of how people organise power. You see it during elections, with INEC, in local government debates. Once you connect it to things happening around you, it stops feeling abstract, {student_name}.",
        'english': f"English! Here's a secret — you don't need to sound like a textbook to be good at English. Chinua Achebe wrote some of the world's greatest novels in simple, clear English. Focus on clarity, not big words. You've got this, {student_name}.",
    }

    subject_lower = subject.lower().strip()
    for key, msg in fallback_messages.items():
        if key in subject_lower:
            return msg

    return f"Ah, {subject}. I see you, {student_name}. A lot of students find {subject} tricky — not because it's impossible, but because most teachers rush through it. We'll take it step by step, at your pace."


async def _step_class_level(chat_id, conversation, message, state):
    msg = message.strip().upper()
    number_map = {str(i + 1): lvl for i, lvl in enumerate(CLASS_LEVELS)}
    class_level = number_map.get(msg) or (msg if msg in CLASS_LEVELS else None)
    if not class_level:
        for lvl in CLASS_LEVELS:
            if msg in lvl or lvl in msg:
                class_level = lvl
                break
    if not class_level:
        await send_telegram_message(chat_id, f"Please choose from: {', '.join(CLASS_LEVELS)}\n\n(Reply with the number 1-6)")
        return

    from constants import JUNIOR_EXAMS, SENIOR_EXAMS
    is_junior = any(level in class_level.upper() for level in ['JSS'])

    if is_junior:
        await send_telegram_message(
            chat_id,
            f"{class_level}!\n\n"
            "Which exam are you preparing for?\n\n"
            "1 — Common Entrance\n"
            "2 — BECE (Junior WAEC)\n\n"
            "_(Reply with the number)_"
        )
        await _save_onboarding_state(chat_id, {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'})
        return

    await send_telegram_message(chat_id, f"{class_level}!\n\nWhich exam are you preparing for?\n\n1 — JAMB (UTME)\n2 — WAEC (SSCE)\n3 — NECO\n4 — Common Entrance\n5 — Post-UTME\n\n_(Reply with the number)_")
    await _save_onboarding_state(chat_id, {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'})


async def _step_target_exam(chat_id, conversation, message, state):
    msg = message.strip().upper()
    class_level = state.get('class_level', 'SS3')
    is_junior = any(level in class_level.upper() for level in ['JSS'])

    if is_junior:
        exam_map = {'1': 'COMMON_ENTRANCE', '2': 'BECE'}
    else:
        exam_map = {
            '1': 'JAMB', 'JAMB': 'JAMB', 'UTME': 'JAMB',
            '2': 'WAEC', 'WAEC': 'WAEC', 'SSCE': 'WAEC', 'GCE': 'WAEC',
            '3': 'NECO', 'NECO': 'NECO',
            '4': 'COMMON_ENTRANCE', 'COMMON': 'COMMON_ENTRANCE',
            '5': 'POST_UTME', 'POST': 'POST_UTME', 'POSTUTME': 'POST_UTME'
        }

    target_exams = [v for k, v in exam_map.items() if k in msg]
    target_exam = target_exams[0] if target_exams else None
    is_multi_exam = len(target_exams) > 1
    if not target_exam:
        await send_telegram_message(chat_id, "Please reply with a valid number to choose your exam.")
        return
    if is_multi_exam:
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
    await send_telegram_message(chat_id, f"{' + '.join(target_exams) if is_multi_exam else target_exam}!\n\n{note}\n\n{subject_list}\n\n_(Reply with numbers separated by commas: e.g. 1,2,4,6)_")
    await _save_onboarding_state(chat_id, {**state, 'target_exam': 'Multiple' if is_multi_exam else target_exam, 'target_exams': target_exams, 'available_subjects': available_subjects, 'awaiting_response_for': 'subjects'})


async def _step_subjects(chat_id, conversation, message, state):
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
    if 'English Language' not in selected and target_exam in ['JAMB', 'WAEC', 'NECO', 'BECE']:
        selected.insert(0, 'English Language')
    if len(selected) < 2:
        await send_telegram_message(chat_id, "Please select at least 2 subjects.\n\nReply with numbers: e.g. 1,2,4,6")
        return
    subjects_display = '\n'.join([f"- {s}" for s in selected])
    await send_telegram_message(chat_id, f"Your subjects:\n{subjects_display}\n\nWhen is your exam?\n\n_(e.g. May 2026 or June 2026 or Not sure)_")
    await _save_onboarding_state(chat_id, {**state, 'subjects': selected, 'awaiting_response_for': 'exam_date'})


async def _step_exam_date(chat_id, conversation, message, state):
    from helpers import nigeria_now
    msg = message.strip().lower()
    exam_date = None
    days_left = 180

    if any(k in msg for k in ['not sure', 'soon', 'this year', 'idk', "don't know", 'unsure', 'no', 'skip']):
        class_level = state.get('class_level', 'SS3')
        years_ahead = 2 if 'SS1' in class_level else (1 if 'SS2' in class_level else 0)
        future_year = nigeria_now().year + years_ahead
        exam_date = f"{future_year}-06-15"
        days_left = max(1, (datetime(future_year, 6, 15) - datetime.now()).days)

        await send_telegram_message(
            chat_id,
            f"I have pencilled {exam_date[:7]} for your exam — about {days_left} days from now.\n\n"
            "Is that correct, or are you planning to write next year instead?\n\n"
            "*1* — This year\n"
            "*2* — Next year"
        )
        await _save_onboarding_state(chat_id, {
            **state,
            'pending_exam_date': exam_date,
            'pending_days_left': days_left,
            'pending_future_year': future_year,
            'awaiting_response_for': 'exam_year_confirm'
        })
        return

    months = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12, 'january': 1, 'february': 2, 'march': 3, 'april': 4, 'june': 6, 'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}
    year_match = re.search(r'20(2[4-9]|[3-9]\d)', msg)
    year = int(year_match.group(0)) if year_match else None
    month = next((m_num for m_name, m_num in months.items() if m_name in msg), None)

    if month and year:
        exam_dt = datetime(year, month, 15)
        now_dt = datetime.now()
        if exam_dt < now_dt:
            await send_telegram_message(chat_id, "That date is already in the past! Please enter a future exam date.\n\nTry: May 2026, June 2026, or type *Not sure*")
            return
        exam_date = f"{year}-{month:02d}-15"
        days_left = max(1, (exam_dt - now_dt).days)

    if not exam_date:
        await send_telegram_message(chat_id, "When is your exam?\n\nTry:\n- May 2026\n- June 2026\n- Not sure")
        return

    urgency = f"\n\nOnly {days_left} days left! We need to move fast." if days_left < 30 else f"\n\n{days_left} days. Enough time if we stay focused." if days_left < 90 else f"\n\n{days_left} days — plenty of time if we start now and stay consistent."
    await send_telegram_message(chat_id, f"Got it!{urgency}\n\nWhich state are you in?\n\n_(e.g. Lagos, Abuja, Kano, Rivers)_")
    await _save_onboarding_state(chat_id, {**state, 'exam_date': exam_date, 'days_until_exam': days_left, 'awaiting_response_for': 'state'})


async def _step_exam_year_confirm(chat_id: int, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    exam_date = state.get('pending_exam_date', '')
    days_left = state.get('pending_days_left', 180)
    future_year = state.get('pending_future_year', 2026)

    if msg in ['2', 'next', 'next year', 'defer'] or 'next year' in msg:
        future_year += 1
        exam_date = f"{future_year}-06-15"
        days_left = max(1, (datetime(future_year, 6, 15) - datetime.now()).days)

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
    await _save_onboarding_state(chat_id, {**state, 'exam_date': exam_date, 'days_until_exam': days_left, 'awaiting_response_for': 'state'})


async def _step_state(chat_id, conversation, message, state):
    msg = message.strip().title()
    matched = next((s for s in NIGERIAN_STATES if msg.lower() in s.lower() or s.lower() in msg.lower()), msg)
    await send_telegram_message(chat_id, f"{matched}!\n\nHow should I explain things to you?\n\n*1* — Standard English\n*2* — Nigerian Pidgin mixed with English\n\n_(You can change this anytime)_")
    await _save_onboarding_state(chat_id, {**state, 'student_state': matched, 'awaiting_response_for': 'language_pref'})


async def _step_language_pref(chat_id, conversation, message, state):
    msg = message.strip().lower()
    language = 'pidgin' if any(k in msg for k in ['2', 'pidgin', 'naija']) else 'english'
    await send_telegram_message(chat_id, "Almost done!\n\nSet a 4-digit security PIN.\n\nYour PIN is how you log in on any device. Keep it private.\n\n_(Enter any 4 digits, e.g. 5823)_")
    await _save_onboarding_state(chat_id, {**state, 'language_pref': language, 'awaiting_response_for': 'pin_setup'})


async def _step_pin_setup(chat_id, conversation, message, state):
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
    await _save_onboarding_state(chat_id, {**state, 'pending_pin': pin, 'awaiting_response_for': 'pin_confirm'})


async def _step_pin_confirm(chat_id, conversation, message, state):
    from database.students import create_student
    from features.wax_id import link_platform_to_student
    from features.notifications import notify_admin_new_student, fire_and_forget
    pin_confirm = message.strip()
    pending_pin = state.get('pending_pin', '')
    if pin_confirm != pending_pin:
        await send_telegram_message(chat_id, "Those PINs do not match.\n\nPlease enter your desired PIN again:")
        await _save_onboarding_state(chat_id, {**state, 'pending_pin': None, 'awaiting_response_for': 'pin_setup'})
        return
    try:
        student = await create_student(phone=f"telegram:{chat_id}", name=state.get('name', 'Student'), pin=pending_pin, class_level=state.get('class_level'), target_exam=state.get('target_exam'), subjects=state.get('subjects', []), exam_date=state.get('exam_date'), state=state.get('student_state'), language_preference=state.get('language_pref', 'english'))
        await link_platform_to_student(student['id'], 'telegram', str(chat_id))

        from database.conversations import get_or_create_conversation, migrate_temp_to_real, clear_onboarding_state
        from database.cache import invalidate_conversation

        # Clear onboarding state from Redis — onboarding is complete
        await clear_onboarding_state('telegram', str(chat_id))
        # Invalidate any stale conversation cache so the next message creates a fresh real conversation
        invalidate_conversation('telegram', str(chat_id))

        await migrate_temp_to_real('telegram', str(chat_id), student['id'])
        conversation = await get_or_create_conversation(
            student_id=student['id'],
            platform='telegram',
            platform_user_id=str(chat_id)
        )

        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'student_id': student['id'],
            'current_mode': 'default',
            'conversation_state': {}
        })

        fire_and_forget(notify_admin_new_student(student, f"telegram:{chat_id}"))
        name_first = student['name'].split()[0]
        days_left = state.get('days_until_exam', 180)
        intro = get_welcome_intro(state.get('subjects', []))
        class_level = state.get('class_level', 'your class')
        exam_name = state.get('target_exam', 'your exams')
        target_exams = state.get('target_exams', [exam_name])
        exam_count = len(target_exams)
        exam_display = f"{exam_count} exams — {exam_name}" if exam_count > 1 else exam_name
        welcome = (
            f"Welcome to WaxPrep, *{name_first}*!\n\n"
            f"{class_level}, {exam_display} — and {days_left} days. "
            f"That sounds like a lot until you realise other students are already "
            f"grinding past questions while some are still making up their minds.\n\n"
            f"No need to worry about what to ask. A student doesn't tell the "
            f"teacher where the lesson starts — I'll lead, you follow.\n\n"
            f"Let's get your first quick win.\n\n"
            f"{intro}\n\n"
            f"*Your account details — save these:*\n"
            f"WAX ID: *{student['wax_id']}*\n"
            f"Recovery Code: *{student['recovery_code']}*\n\n"
            f"*Full Access is now ACTIVE!*")
        await send_telegram_message(chat_id, welcome)
    except Exception as e:
        await send_telegram_message(chat_id, f"Error creating account. Send *HI* to retry. Ref: {str(e)[:50]}")

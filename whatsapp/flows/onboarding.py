import re
import json
import random
from datetime import datetime
from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from config.settings import settings
from constants import EXAM_SUBJECTS, CLASS_LEVELS, NIGERIAN_STATES, SUBJECT_INTROS, get_welcome_intro, WELCOME_VARIANTS

async def handle_new_or_existing(phone: str, conversation: dict, message: str):
    welcome = random.choice(WELCOME_VARIANTS)
    await send_whatsapp_message(phone, welcome)
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {'awaiting_response_for': 'new_or_existing'}})

async def handle_onboarding_response(phone: str, conversation: dict, message: str):
    raw_state = conversation.get('conversation_state', {})
    if isinstance(raw_state, str):
        try: state = json.loads(raw_state)
        except: state = {}
    else: state = raw_state or {}
    awaiting = state.get('awaiting_response_for', '')
    handlers = {
        'new_or_existing': _step_new_or_existing,
        'student_goal': _step_student_goal,
        'terms_acceptance': _step_terms_acceptance,
        'wax_id_entry': _step_wax_id_entry,
        'pin_entry': _step_pin_entry,
        'name': _step_name,
        'class_level': _step_class_level,
        'target_exam': _step_target_exam,
        'subjects': _step_subjects,
        'exam_date': _step_exam_date,
        'exam_year_confirm': _step_exam_year_confirm,
        'state': _step_state,
        'language_pref': _step_language_pref,
        'pin_setup': _step_pin_setup,
        'pin_confirm': _step_pin_confirm,
    }
    handler = handlers.get(awaiting)
    if handler: await handler(phone, conversation, message, state)
    else: await handle_new_or_existing(phone, conversation, message)

async def _step_new_or_existing(phone: str, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    
    # Returning student
    if any(k in msg for k in ['2', 'existing', 'login', 'have']):
        await send_whatsapp_message(phone,
            "Before we log you in, please accept our Terms of Service.\n\n"
            "By using WaxPrep, you agree to use it for your own study, keep your PIN private, "
            f"and not misuse the platform.\n\nFull Terms: {settings.TERMS_URL}\n\n"
            "Type *YES* to accept and log in."
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone,
            {'conversation_state': {'awaiting_response_for': 'terms_acceptance', 'is_new_student': False}}
        )
        return

    # New student
    if any(k in msg for k in ['1', 'new', 'create', 'register']) or 'new' in msg:
        await send_whatsapp_message(phone,
            "Great! Let's get you set up. First — what do you need help with?\n\n"
            "*1* — My schoolwork\n"
            "*2* — Preparing for a test or exam\n"
            "*3* — I just want to learn something new\n\n"
            "_(Reply with the number)_"
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone,
            {'conversation_state': {'awaiting_response_for': 'student_goal', 'is_new_student': True}}
        )
        return
    
    await send_whatsapp_message(phone, "Please reply with *1* (New) or *2* (Existing).")

async def _step_student_goal(phone: str, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    goal_map = {'1': 'schoolwork', '2': 'exam prep', '3': 'learning', 'school': 'schoolwork', 'exam': 'exam prep', 'learn': 'learning'}
    goal = next((v for k, v in goal_map.items() if k in msg), None)
    
    if not goal:
        await send_whatsapp_message(phone, "Pick one:\n1—Schoolwork\n2—Exam Prep\n3—Learning")
        return
    
    await send_whatsapp_message(phone,
        f"Got it — {goal}. Before we continue, please accept our Terms of Service.\n\n"
        "By using WaxPrep, you agree to use it for your own study and keep your PIN private.\n\n"
        f"Full Terms: {settings.TERMS_URL}\n\nType *YES* to accept."
    )
    await update_conversation_state(conversation['id'], 'whatsapp', phone,
        {'conversation_state': {**state, 'student_goal': goal, 'awaiting_response_for': 'terms_acceptance'}}
    )

async def _step_terms_acceptance(phone: str, conversation: dict, message: str, state: dict):
    msg = message.strip().lower()
    is_new = state.get('is_new_student', True)
    if msg in ['yes', 'y', 'agree', 'accept', 'ok', '1']:
        if is_new:
            await send_whatsapp_message(phone, "Thank you! What is your full name?")
            await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'terms_accepted': True, 'awaiting_response_for': 'name'}})
        else:
            await send_whatsapp_message(phone, "Welcome back!\n\nSend your WAX ID to log in.")
            await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {'awaiting_response_for': 'wax_id_entry'}})
    else:
        await send_whatsapp_message(phone, "Type *YES* to accept and continue.")

async def _step_wax_id_entry(phone: str, conversation: dict, message: str, state: dict):
    from features.wax_id import get_student_by_wax_id
    from helpers import extract_wax_id
    wax_id = extract_wax_id(message)
    student = await get_student_by_wax_id(wax_id) if wax_id else None
    if not student:
        await send_whatsapp_message(phone, "No account found. Double-check your WAX ID or type *NEW*.")
        return
    await send_whatsapp_message(phone, f"Found it! Welcome back, *{student['name'].split()[0]}*!\nEnter your 4-digit PIN.")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {'awaiting_response_for': 'pin_entry', 'pending_wax_id': wax_id}})

async def _step_pin_entry(phone: str, conversation: dict, message: str, state: dict):
    from features.wax_id import get_student_by_wax_id, link_platform_to_student
    from helpers import verify_pin
    student = await get_student_by_wax_id(state.get('pending_wax_id'))
    if not student or not verify_pin(message.strip(), student['pin_hash']):
        await send_whatsapp_message(phone, "Wrong PIN. Try again.")
        return
    await link_platform_to_student(student['id'], 'whatsapp', phone)
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'student_id': student['id'], 'current_mode': 'default', 'conversation_state': {}})
    await send_whatsapp_message(phone, f"Welcome back, *{student['name'].split()[0]}*! What would you like to study?")

async def _step_name(phone: str, conversation: dict, message: str, state: dict):
    from helpers import clean_name
    name = clean_name(message)
    
    if len(name) < 3:
        await send_whatsapp_message(phone, "That name seems too short. Please enter your full name.")
        return

    invalid_names = {'wa', 'ok', 'hi', 'no', 'yes', 'test', 'ab', 'cd', 'name', 'student', 'user'}
    if name.lower() in invalid_names or len(name.split()) < 2:
        await send_whatsapp_message(
            phone,
            "Please enter your first and last name, like *Chidera Emeka* or *Amina Bello*."
        )
        return

    options = '\n'.join([f"{i+1}. {lvl}" for i, lvl in enumerate(CLASS_LEVELS)])
    await send_whatsapp_message(phone, f"Nice to meet you, *{name.split()[0]}*!\n\nWhat class are you in?\n\n{options}")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'name': name, 'awaiting_response_for': 'class_level'}})

async def _step_class_level(phone: str, conversation: dict, message: str, state: dict):
    msg = message.strip().upper()
    number_map = {str(i + 1): lvl for i, lvl in enumerate(CLASS_LEVELS)}
    class_level = number_map.get(msg) or (msg if msg in CLASS_LEVELS else None)
    if not class_level:
        await send_whatsapp_message(phone, f"Choose from: {', '.join(CLASS_LEVELS)}")
        return
    
    from constants import JUNIOR_EXAMS, SENIOR_EXAMS
    is_junior = any(level in class_level.upper() for level in ['JSS'])
    
    if is_junior:
        await send_whatsapp_message(
            phone,
            f"{class_level}!\n\n"
            "Which exam are you preparing for?\n\n"
            "1 — Common Entrance\n"
            "2 — BECE (Junior WAEC)\n\n"
            "_(Reply with the number)_"
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'}
        })
        return

    await send_whatsapp_message(phone, f"{class_level}!\n\nWhich exam?\n1—JAMB\n2—WAEC\n3—NECO\n4—Common Entrance\n5—Post-UTME")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'}})

async def _step_target_exam(phone: str, conversation: dict, message: str, state: dict):
    msg = message.strip().upper()
    class_level = state.get('class_level', 'SS3')
    is_junior = any(level in class_level.upper() for level in ['JSS'])

    if is_junior:
        exam_map = {'1': 'COMMON_ENTRANCE', '2': 'BECE'}
    else:
        exam_map = {'1':'JAMB','2':'WAEC','3':'NECO','4':'COMMON_ENTRANCE','5':'POST_UTME'}
        
    target_exams = [exam_map[k] for k in exam_map if k in msg]
    if not target_exams:
        await send_whatsapp_message(phone, "Choose a valid number.")
        return
    is_multi = len(target_exams) > 1
    available = []
    for ex in target_exams:
        for s in EXAM_SUBJECTS.get(ex, []):
            if s not in available: available.append(s)
    subject_list = '\n'.join([f"{i+1}. {sub}" for i, sub in enumerate(available[:15])])
    await send_whatsapp_message(phone, f"{' + '.join(target_exams)}!\n\nPick subjects (e.g. 1,2,4,6):\n\n{subject_list}")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'target_exam': 'Multiple' if is_multi else target_exams[0], 'target_exams': target_exams, 'available_subjects': available, 'awaiting_response_for': 'subjects'}})

async def _step_subjects(phone: str, conversation: dict, message: str, state: dict):
    available = state.get('available_subjects', [])
    numbers = re.findall(r'\d+', message)
    selected = [available[int(n)-1] for n in numbers if 1 <= int(n) <= len(available)]
    if not selected:
        await send_whatsapp_message(phone, "Select subjects using numbers.")
        return
    if 'English Language' not in selected: selected.insert(0, 'English Language')
    await send_whatsapp_message(phone, f"Your subjects:\n" + '\n'.join([f"- {s}" for s in selected]) + "\n\nWhen is your exam? (e.g. June 2026)")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'subjects': selected, 'awaiting_response_for': 'exam_date'}})

async def _step_exam_date(phone: str, conversation: dict, message: str, state: dict):
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

        await send_whatsapp_message(
            phone,
            f"I have pencilled {exam_date[:7]} for your exam — about {days_left} days from now.\n\n"
            "Is that correct, or are you planning to write next year instead?\n\n"
            "*1* — This year\n"
            "*2* — Next year"
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {
                **state,
                'pending_exam_date': exam_date,
                'pending_days_left': days_left,
                'pending_future_year': future_year,
                'awaiting_response_for': 'exam_year_confirm'
            }
        })
        return

    else:
        yr_m = re.search(r'20(2[4-9]|[3-9]\d)', msg)
        if yr_m:
            year = int(yr_m.group(0))
            month = 5 if 'may' in msg else (6 if 'jun' in msg else 6)
            exam_dt = datetime(year, month, 15)
            now_dt = datetime.now()
            
            if exam_dt < now_dt:
                await send_whatsapp_message(phone, "That date is already in the past! Please enter a future exam date.\n\nTry: May 2026, June 2026, or type *Not sure*")
                return
                
            exam_date = f"{year}-{month:02d}-15"
            days_left = (exam_dt - now_dt).days
            
    if not exam_date:
        await send_whatsapp_message(phone, "Tell me the month and year (e.g. May 2026).")
        return
        
    await send_whatsapp_message(phone, f"Got it! {days_left} days left. Which state are you in?")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'exam_date': exam_date, 'days_until_exam': days_left, 'awaiting_response_for': 'state'}})

async def _step_exam_year_confirm(phone: str, conversation: dict, message: str, state: dict):
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

    await send_whatsapp_message(phone, f"Got it!{urgency}\n\nWhich state are you in?")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **state,
            'exam_date': exam_date,
            'days_until_exam': days_left,
            'awaiting_response_for': 'state',
            'pending_exam_date': None, 'pending_days_left': None, 'pending_future_year': None
        }
    })

async def _step_state(phone: str, conversation: dict, message: str, state: dict):
    st = message.strip().title()
    await send_whatsapp_message(phone, f"{st}!\nHow should I explain?\n1—Standard English\n2—Pidgin")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'student_state': st, 'awaiting_response_for': 'language_pref'}})

async def _step_language_pref(phone: str, conversation: dict, message: str, state: dict):
    pref = 'pidgin' if '2' in message or 'pidgin' in message.lower() else 'english'
    await send_whatsapp_message(phone, "Set a 4-digit PIN.")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'language_pref': pref, 'awaiting_response_for': 'pin_setup'}})

async def _step_pin_setup(phone: str, conversation: dict, message: str, state: dict):
    pin = message.strip()
    if not pin.isdigit() or len(pin) != 4:
        await send_whatsapp_message(phone, "PIN must be 4 digits.")
        return
    await send_whatsapp_message(phone, "Confirm your PIN.")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'pending_pin': pin, 'awaiting_response_for': 'pin_confirm'}})

async def _step_pin_confirm(phone: str, conversation: dict, message: str, state: dict):
    from database.students import create_student
    from features.wax_id import link_platform_to_student
    from features.notifications import notify_admin_new_student, fire_and_forget
    if message.strip() != state.get('pending_pin'):
        await send_whatsapp_message(phone, "Pins don't match. Start PIN setup again.")
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'awaiting_response_for': 'pin_setup'}})
        return
    try:
        student = await create_student(phone=phone, name=state.get('name'), pin=state.get('pending_pin'), class_level=state.get('class_level'), target_exam=state.get('target_exam'), subjects=state.get('subjects', []), exam_date=state.get('exam_date'), state=state.get('student_state'), language_preference=state.get('language_pref'))
        await link_platform_to_student(student['id'], 'whatsapp', phone)

        from database.conversations import get_or_create_conversation, migrate_temp_to_real
        await migrate_temp_to_real('whatsapp', phone, student['id'])
        conversation = await get_or_create_conversation(
            student_id=student['id'],
            platform='whatsapp',
            platform_user_id=phone
        )

        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'student_id': student['id'], 
            'current_mode': 'default', 
            'conversation_state': {}
        })
        
        fire_and_forget(notify_admin_new_student(student, phone))
        
        subjects = state.get('subjects', [])
        intro = get_welcome_intro(subjects)
        class_lvl = state.get('class_level', 'your class')
        exam_name = state.get('target_exam', 'your exams')
        exam_count = len(state.get('target_exams', [exam_name]))
        exam_display = f"{exam_count} exams — {exam_name}" if exam_count > 1 else exam_name
        days_left = state.get('days_until_exam', 180)

        welcome = (
            f"Welcome to WaxPrep, *{student['name'].split()[0]}*!\n\n"
            f"{class_lvl}, {exam_display} — and {days_left} days. "
            "That sounds like a lot until you realise other students are already grinding.\n\n"
            "I'll lead, you follow.\n\n"
            f"{intro}\n\n"
            f"*Account details:*\nWAX ID: *{student['wax_id']}*\nRecovery: *{student['recovery_code']}*\n\n"
            "*Full Access ACTIVE!*"
        )
        await send_whatsapp_message(phone, welcome)
    except Exception as e:
        await send_whatsapp_message(phone, f"Error: {str(e)[:50]}")

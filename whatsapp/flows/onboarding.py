import re
from datetime import datetime

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

SUBJECT_INTROS = {
    ('physics', 'chemistry', 'biology'): (
        "There's one concept that controls all three sciences: **Energy.** "
        "It's the same energy that powers a generator (Physics), makes bread "
        "rise with yeast (Biology), and burns kerosene in a lamp (Chemistry). "
        "Understand this one thing, and you've already gained ground in three "
        "subjects at once. It'll take 2 minutes. Ready?"
    ),
    ('physics', 'chemistry'): (
        "There's one idea that connects both your science subjects: **Matter.** "
        "Everything around you — the air, the water, your phone — is made of "
        "atoms. Physics tells you how they move. Chemistry tells you how they "
        "react. Master this link and both subjects become easier. 2 minutes. Ready?"
    ),
    ('physics', 'biology'): (
        "Here's a connection most students miss: **Force and Motion** appear "
        "in both Physics and Biology. Blood flowing through your body follows "
        "the same principles as water through a pipe. An okada turning a corner "
        "is the same physics as your heartbeat. See the link? 2 minutes. Ready?"
    ),
    ('chemistry', 'biology'): (
        "Both your sciences meet at **Chemical Reactions.** Digestion is chemistry "
        "inside your body. Fermentation is chemistry inside a palm wine gourd. "
        "Rust on a roof is chemistry in the open air. Same principles, different "
        "scenes. 2 minutes to connect them. Ready?"
    ),
    ('government', 'economics', 'commerce'): (
        "Your three subjects share one big idea: **Systems.** Government sets "
        "the rules. Economics tracks the money. Commerce moves the goods. "
        "Understand how they feed each other, and you understand how Nigeria "
        "works. 2 minutes. Ready?"
    ),
    ('government', 'literature', 'economics'): (
        "Your three subjects tell one big story: **Power, Money, and Meaning.** "
        "Government shows who makes the rules. Economics shows who pays for them. "
        "Literature shows who tells the story. Understand how these three connect, "
        "and you understand how societies rise and fall. 2 minutes. Ready?"
    ),
    ('government', 'literature'): (
        "Both your subjects explore **Power.** Who holds it in a government? "
        "Who holds it in a story? From the Constitution to Chinua Achebe, the "
        "same struggle plays out: who gets to decide, and who pays the price. "
        "2 minutes. Ready?"
    ),
    ('economics', 'commerce', 'geography'): (
        "Your subjects revolve around **Resources.** Where they come from "
        "(Geography), how they're traded (Commerce), and who profits (Economics). "
        "Oil from the Delta, cocoa from Ondo, markets from Onitsha — it's all "
        "connected. 2 minutes. Ready?"
    ),
    ('english', 'literature', 'christian religious studies'): (
        "Your subjects share one thread: **Narrative.** The Bible tells stories "
        "of faith. Achebe tells stories of change. Your English exam tests how "
        "well you understand both. Stories shape beliefs — let me show you how. "
        "2 minutes. Ready?"
    ),
    ('mathematics', 'physics', 'chemistry'): (
        "Your three subjects speak one language: **Equations.** Maths gives you "
        "the grammar. Physics and Chemistry give you the sentences. Once you "
        "see equations as a language instead of a punishment, everything shifts. "
        "2 minutes. Ready?"
    ),
}

def get_welcome_intro(subjects: list) -> str:
    if not subjects:
        return "Let's start with the basics and build from there. Ready?"
    subject_lower = [s.lower().strip() for s in subjects]
    for combo, intro in SUBJECT_INTROS.items():
        if all(c in subject_lower for c in combo):
            return intro
    first = subjects[0] if subjects else 'your subject'
    return f"Let's start with {first} — that's a strong choice. We'll build your foundation step by step. Ready?"

async def handle_new_or_existing(phone: str, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    welcome = (
        "Welcome to WaxPrep!\n\n"
        "Nigeria's smartest AI study companion. I'm Wax, your personal tutor "
        "for JAMB, WAEC, NECO, Post-UTME, and more.\n\n"
        "Are you new here, or do you already have a WAX ID?\n\n"
        "*1* — I'm new, create my account\n"
        "*2* — I have a WAX ID, log me in"
    )
    await send_whatsapp_message(phone, welcome)
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {'awaiting_response_for': 'new_or_existing'}})

async def handle_onboarding_response(phone: str, conversation: dict, message: str):
    import json
    raw_state = conversation.get('conversation_state', {})
    if isinstance(raw_state, str):
        try: state = json.loads(raw_state)
        except: state = {}
    else: state = raw_state or {}
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    from config.settings import settings
    msg = message.strip().lower()
    if any(k in msg for k in ['1', 'new', 'create', 'register']):
        await send_whatsapp_message(phone, f"Before we set up your account, please accept our Terms of Service.\n\nBy using WaxPrep, you agree to:\n\nUse the platform only for your own study\nKeep your WAX ID and PIN private\nAllow WaxPrep to use your study data to personalize your experience\n\nFull Terms: {settings.TERMS_URL}\n\nType *YES* to accept.")
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {'awaiting_response_for': 'terms_acceptance', 'is_new_student': True}})
    elif any(k in msg for k in ['2', 'existing', 'login', 'have']):
        await send_whatsapp_message(phone, "Welcome back!\n\nSend your WAX ID to log in.")
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {'awaiting_response_for': 'wax_id_entry'}})
    else:
        await send_whatsapp_message(phone, "Please reply with *1* (New) or *2* (Existing).")

async def _step_terms_acceptance(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    msg = message.strip().lower()
    if msg in ['yes', 'y', 'agree', 'accept', 'ok', '1']:
        await send_whatsapp_message(phone, "Thank you! What is your full name?")
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'terms_accepted': True, 'awaiting_response_for': 'name'}})
    else:
        await send_whatsapp_message(phone, "Type *YES* to accept and continue.")

async def _step_wax_id_entry(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    from helpers import clean_name
    name = clean_name(message)
    if len(name) < 2:
        await send_whatsapp_message(phone, "Name too short. Enter your full name.")
        return
    options = '\n'.join([f"{i+1}. {lvl}" for i, lvl in enumerate(CLASS_LEVELS)])
    await send_whatsapp_message(phone, f"Nice to meet you, *{name.split()[0]}*!\n\nWhat class are you in?\n\n{options}")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'name': name, 'awaiting_response_for': 'class_level'}})

async def _step_class_level(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    msg = message.strip().upper()
    number_map = {str(i + 1): lvl for i, lvl in enumerate(CLASS_LEVELS)}
    class_level = number_map.get(msg) or (msg if msg in CLASS_LEVELS else None)
    if not class_level:
        await send_whatsapp_message(phone, f"Choose from: {', '.join(CLASS_LEVELS)}")
        return
    await send_whatsapp_message(phone, f"{class_level}!\n\nWhich exam?\n1—JAMB\n2—WAEC\n3—NECO\n4—Common Entrance\n5—Post-UTME")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'class_level': class_level, 'awaiting_response_for': 'target_exam'}})

async def _step_target_exam(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    msg = message.strip().upper()
    exam_map = {'1':'JAMB','2':'WAEC','3':'NECO','4':'COMMON_ENTRANCE','5':'POST_UTME'}
    target_exams = [exam_map[k] for k in exam_map if k in msg]
    if not target_exams:
        await send_whatsapp_message(phone, "Choose 1-5.")
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    msg = message.strip()
    
    if '2' in msg or 'next' in msg.lower():
        year = state.get('pending_future_year') + 1
        exam_date = f"{year}-06-15"
        days_left = (datetime(year, 6, 15) - datetime.now()).days
    else:
        exam_date = state.get('pending_exam_date')
        days_left = state.get('pending_days_left')
        
    await send_whatsapp_message(phone, f"Got it! {days_left} days left. Which state are you in?")
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
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    st = message.strip().title()
    await send_whatsapp_message(phone, f"{st}!\nHow should I explain?\n1—Standard English\n2—Pidgin")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'student_state': st, 'awaiting_response_for': 'language_pref'}})

async def _step_language_pref(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    pref = 'pidgin' if '2' in message or 'pidgin' in message.lower() else 'english'
    await send_whatsapp_message(phone, "Set a 4-digit PIN.")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'language_pref': pref, 'awaiting_response_for': 'pin_setup'}})

async def _step_pin_setup(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    pin = message.strip()
    if not pin.isdigit() or len(pin) != 4:
        await send_whatsapp_message(phone, "PIN must be 4 digits.")
        return
    await send_whatsapp_message(phone, "Confirm your PIN.")
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': {**state, 'pending_pin': pin, 'awaiting_response_for': 'pin_confirm'}})

async def _step_pin_confirm(phone: str, conversation: dict, message: str, state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
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
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {'student_id': student['id'], 'current_mode': 'default', 'conversation_state': {}})
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

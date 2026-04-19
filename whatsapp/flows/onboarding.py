"""
The Onboarding Flow

This handles the complete process of signing up a new student.
The flow has these steps:

Step 0: New or existing?
Step 1: Name
Step 2: Class level
Step 3: Target exam
Step 4: Subjects  
Step 5: Exam date
Step 6: State (for leaderboards and context)
Step 7: Language preference
Step 8: Set PIN
Step 9: Confirm PIN
Step 10: Show WAX ID and recovery code
Step 11: Generate study plan

At each step, the student's response is validated before moving to the next.
Invalid responses get a helpful re-prompt, not an error.

After onboarding, the student gets their WAX ID, recovery code, and immediately 
starts with their first study session.
"""

from whatsapp.sender import send_whatsapp_message
from database.conversations import (
    update_conversation_state, set_awaiting_response, get_or_create_conversation
)
from database.students import create_student
from features.wax_id import (
    get_student_by_wax_id, link_platform_to_student
)
from features.pin import verify_pin, is_account_locked
from utils.helpers import clean_name, is_valid_pin, is_valid_wax_id, extract_wax_id, nigeria_now
from config.settings import settings
from datetime import timedelta

# ============================================================
# EXAM SUBJECTS DATABASE
# ============================================================

EXAM_SUBJECTS = {
    'JAMB': ['Mathematics', 'English Language', 'Physics', 'Chemistry', 'Biology', 
              'Economics', 'Government', 'Literature in English', 'Geography', 
              'Commerce', 'Agricultural Science', 'Christian Religious Studies',
              'Islamic Religious Studies', 'History', 'Yoruba', 'Igbo', 'Hausa'],
    'WAEC': ['Mathematics', 'English Language', 'Physics', 'Chemistry', 'Biology',
              'Economics', 'Government', 'Literature in English', 'Geography',
              'Commerce', 'Agricultural Science', 'Further Mathematics', 
              'Technical Drawing', 'Food and Nutrition', 'Computer Studies'],
    'NECO': ['Mathematics', 'English Language', 'Physics', 'Chemistry', 'Biology',
              'Economics', 'Government', 'Literature in English', 'Geography',
              'Commerce', 'Agricultural Science'],
    'COMMON_ENTRANCE': ['English Language', 'Mathematics', 'Basic Science', 
                         'Social Studies', 'Verbal Reasoning', 'Quantitative Reasoning'],
}

CLASS_LEVELS = ['JSS1', 'JSS2', 'JSS3', 'SS1', 'SS2', 'SS3']

NIGERIAN_STATES = [
    'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue',
    'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'FCT',
    'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi',
    'Kwara', 'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo',
    'Plateau', 'Rivers', 'Sokoto', 'Taraba', 'Yobe', 'Zamfara'
]

# ============================================================
# MAIN ONBOARDING HANDLER
# ============================================================

async def handle_new_or_existing(phone: str, conversation: dict, message: str):
    """
    Handles the very first message from any user.
    Determines if they're new or have an existing account.
    """
    
    # Send the welcome message
    welcome = (
        "🎓 *Welcome to WaxPrep!*\n\n"
        "Nigeria's most advanced AI study companion. I'm Wax — your personal tutor "
        "for JAMB, WAEC, NECO, and more.\n\n"
        "Are you *new* to WaxPrep, or do you already have a *WAX ID*?\n\n"
        "1️⃣ I'm new — sign me up!\n"
        "2️⃣ I have a WAX ID — log me in"
    )
    
    await send_whatsapp_message(phone, welcome)
    await set_awaiting_response(
        conversation['id'], 'whatsapp', phone, 'new_or_existing'
    )

async def handle_onboarding_response(
    phone: str, 
    conversation: dict, 
    message: str
):
    """
    Routes onboarding responses to the correct step handler.
    """
    state = conversation.get('conversation_state', {})
    awaiting = state.get('awaiting_response_for') or conversation.get('awaiting_response_for')
    
    # Route to the right step
    handlers = {
        'new_or_existing': _handle_new_or_existing_choice,
        'wax_id_entry': _handle_wax_id_entry,
        'pin_entry': _handle_pin_entry,
        'name': _handle_name,
        'class_level': _handle_class_level,
        'target_exam': _handle_target_exam,
        'subjects': _handle_subjects,
        'exam_date': _handle_exam_date,
        'state': _handle_state,
        'language_pref': _handle_language_pref,
        'pin_setup': _handle_pin_setup,
        'pin_confirm': _handle_pin_confirm,
        'referral_code': _handle_referral_code_entry,
    }
    
    handler = handlers.get(awaiting)
    if handler:
        await handler(phone, conversation, message, state)
    else:
        # Unknown state — restart
        await handle_new_or_existing(phone, conversation, message)

async def _handle_new_or_existing_choice(phone: str, conversation: dict, message: str, state: dict):
    """Step 0: Handle 'new or existing' choice."""
    
    msg = message.strip().lower()
    
    if msg in ['1', 'new', "i'm new", 'sign me up', 'new student', 'register']:
        # New student — start onboarding
        new_state = {'onboarding_step': 1, 'awaiting_response_for': 'name'}
        
        await send_whatsapp_message(
            phone,
            "Awesome! Let's get you set up 🚀\n\n"
            "First, what's your full name?\n\n"
            "_(Type your name and send)_"
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': new_state
        })
    
    elif msg in ['2', 'existing', 'i have a wax id', 'log me in', 'login', 'log in']:
        # Existing student — ask for WAX ID
        new_state = {'onboarding_step': 0, 'awaiting_response_for': 'wax_id_entry'}
        
        await send_whatsapp_message(
            phone,
            "Welcome back! 👋\n\n"
            "Please send your *WAX ID* to log in.\n\n"
            "It looks like this: *WAX-A74892*\n\n"
            "_(Type your WAX ID and send)_"
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': new_state
        })
    
    else:
        # Didn't understand — ask again
        await send_whatsapp_message(
            phone,
            "I didn't quite get that 😅\n\n"
            "Please reply with:\n"
            "*1* — if you're new to WaxPrep\n"
            "*2* — if you already have a WAX ID"
        )

async def _handle_wax_id_entry(phone: str, conversation: dict, message: str, state: dict):
    """Handles WAX ID entry for existing user login."""
    
    # Extract WAX ID from message
    wax_id = extract_wax_id(message)
    
    if not wax_id:
        # Try to format what they sent
        clean = message.strip().upper().replace(' ', '')
        if not clean.startswith('WAX-') and clean.startswith('WAX'):
            clean = 'WAX-' + clean[3:]
        
        if is_valid_wax_id(clean):
            wax_id = clean
        else:
            await send_whatsapp_message(
                phone,
                "That doesn't look like a valid WAX ID 🤔\n\n"
                "Your WAX ID should look like: *WAX-A74892*\n\n"
                "Please check and try again. Or type *NEW* to create a new account."
            )
            return
    
    # Look up the student
    student = await get_student_by_wax_id(wax_id)
    
    if not student:
        await send_whatsapp_message(
            phone,
            f"Hmm, I couldn't find an account with WAX ID *{wax_id}* 😕\n\n"
            "Please double-check your WAX ID.\n\n"
            "Or type *NEW* to create a fresh account."
        )
        return
    
    if student.get('is_banned'):
        await send_whatsapp_message(
            phone,
            "This account has been suspended. Please contact support for help."
        )
        return
    
    # Check if account is locked
    if await is_account_locked(student['id']):
        await send_whatsapp_message(
            phone,
            "⚠️ *Account Temporarily Locked*\n\n"
            "Too many incorrect PIN attempts. Your account is locked for 30 minutes for security.\n\n"
            "Please try again later or type *RECOVER* if you've forgotten your PIN."
        )
        return
    
    # Found student — ask for PIN
    new_state = {
        'awaiting_response_for': 'pin_entry',
        'pending_wax_id': wax_id,
        'pending_student_name': student['name'].split()[0]
    }
    
    await send_whatsapp_message(
        phone,
        f"Found your account! 🎯\n\n"
        f"Hi *{student['name'].split()[0]}*! Please enter your *4-digit PIN* to log in.\n\n"
        "_(Type your PIN and send — it's private and secure)_"
    )
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_pin_entry(phone: str, conversation: dict, message: str, state: dict):
    """Handles PIN entry for existing user login."""
    
    pin = message.strip()
    pending_wax_id = state.get('pending_wax_id')
    
    if not pending_wax_id:
        await handle_new_or_existing(phone, conversation, message)
        return
    
    student = await get_student_by_wax_id(pending_wax_id)
    if not student:
        await handle_new_or_existing(phone, conversation, message)
        return
    
    from features.pin import record_failed_pin_attempt, clear_failed_attempts
    
    if not verify_pin(pin, student['pin_hash']):
        # Wrong PIN
        failed_count = await record_failed_pin_attempt(student['id'])
        remaining = 5 - failed_count
        
        if remaining <= 0:
            await send_whatsapp_message(
                phone,
                "⚠️ *Account Locked*\n\n"
                "Too many incorrect PIN attempts. Your account is locked for 30 minutes.\n\n"
                "Type *RECOVER* if you've forgotten your PIN."
            )
        else:
            await send_whatsapp_message(
                phone,
                f"❌ Incorrect PIN. You have *{remaining}* attempt{'s' if remaining != 1 else ''} left.\n\n"
                "Type *RECOVER* if you've forgotten your PIN."
            )
        return
    
    # Correct PIN! Log them in
    await clear_failed_attempts(student['id'])
    
    # Link this WhatsApp number to their WAX ID
    await link_platform_to_student(student['id'], 'whatsapp', phone)
    
    # Clear conversation state and set up for studying
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'student_id': student['id'],
        'current_mode': 'default',
        'conversation_state': {},
        'awaiting_response_for': None,
    })
    
    # Welcome them back with their stats
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    
    streak = student.get('current_streak', 0)
    total_answered = student.get('total_questions_answered', 0)
    name = student['name'].split()[0]
    
    welcome_back = (
        f"✅ *Welcome back, {name}!* 🎉\n\n"
        f"WAX ID: {pending_wax_id}\n"
        f"Plan: {status['display_tier']}\n"
        f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}\n"
        f"📊 Total Questions: {total_answered:,}\n\n"
    )
    
    if streak > 0:
        welcome_back += f"Your {streak}-day streak is waiting — don't break it today! 💪\n\n"
    
    welcome_back += (
        "What would you like to study?\n\n"
        "Just ask me anything, or type *HELP* to see all commands."
    )
    
    await send_whatsapp_message(phone, welcome_back)

async def _handle_name(phone: str, conversation: dict, message: str, state: dict):
    """Step 1: Collect student name."""
    
    name = clean_name(message)
    
    # Validation
    if len(name) < 2:
        await send_whatsapp_message(
            phone,
            "That name seems too short 🤔 Please enter your full name."
        )
        return
    
    if len(name) > 100:
        await send_whatsapp_message(
            phone,
            "That name seems too long. Please enter just your first and last name."
        )
        return
    
    # Save name to state and move to next step
    new_state = {
        **state,
        'name': name,
        'onboarding_step': 2,
        'awaiting_response_for': 'class_level'
    }
    
    first_name = name.split()[0]
    
    class_options = "\n".join([f"{i+1}️⃣ {level}" for i, level in enumerate(CLASS_LEVELS)])
    
    await send_whatsapp_message(
        phone,
        f"Nice to meet you, *{first_name}!* 😊\n\n"
        f"What class are you in?\n\n"
        f"{class_options}\n\n"
        f"_(Reply with the number or the class name)_"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_class_level(phone: str, conversation: dict, message: str, state: dict):
    """Step 2: Collect class level."""
    
    msg = message.strip().upper()
    
    # Map number responses to class levels
    number_map = {str(i+1): level for i, level in enumerate(CLASS_LEVELS)}
    
    class_level = None
    if msg in number_map:
        class_level = number_map[msg]
    elif msg in CLASS_LEVELS:
        class_level = msg
    else:
        # Try fuzzy match
        for level in CLASS_LEVELS:
            if msg in level or level in msg:
                class_level = level
                break
    
    if not class_level:
        options = ", ".join(CLASS_LEVELS)
        await send_whatsapp_message(
            phone,
            f"I didn't recognize that class level 🤔\n\n"
            f"Please choose from: {options}\n\n"
            f"_(Reply with the number 1-6 or the class name)_"
        )
        return
    
    new_state = {
        **state,
        'class_level': class_level,
        'onboarding_step': 3,
        'awaiting_response_for': 'target_exam'
    }
    
    exam_options = (
        "1️⃣ JAMB (UTME)\n"
        "2️⃣ WAEC (SSCE)\n"
        "3️⃣ NECO\n"
        "4️⃣ Common Entrance\n"
        "5️⃣ Post-UTME"
    )
    
    await send_whatsapp_message(
        phone,
        f"{class_level}! Great 📚\n\n"
        f"Which exam are you preparing for?\n\n"
        f"{exam_options}\n\n"
        f"_(You can pick multiple: e.g., '1 and 2' for JAMB and WAEC)_"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_target_exam(phone: str, conversation: dict, message: str, state: dict):
    """Step 3: Collect target exam."""
    
    msg = message.strip().upper()
    
    exam_map = {
        '1': 'JAMB', 'JAMB': 'JAMB', 'UTME': 'JAMB',
        '2': 'WAEC', 'WAEC': 'WAEC', 'SSCE': 'WAEC', 'GCE': 'WAEC',
        '3': 'NECO', 'NECO': 'NECO',
        '4': 'COMMON_ENTRANCE', 'COMMON ENTRANCE': 'COMMON_ENTRANCE', 'ENTRANCE': 'COMMON_ENTRANCE',
        '5': 'POST_UTME', 'POST UTME': 'POST_UTME', 'POST-UTME': 'POST_UTME',
    }
    
    # Find exam
    target_exam = None
    for key, value in exam_map.items():
        if key in msg:
            target_exam = value
            break
    
    if not target_exam:
        await send_whatsapp_message(
            phone,
            "Please choose one of the options:\n"
            "1 - JAMB\n2 - WAEC\n3 - NECO\n4 - Common Entrance\n5 - Post-UTME"
        )
        return
    
    # Get available subjects for this exam
    available_subjects = EXAM_SUBJECTS.get(target_exam, EXAM_SUBJECTS['JAMB'])
    
    # Create numbered subject list
    subject_list = "\n".join([f"{i+1}. {sub}" for i, sub in enumerate(available_subjects[:15])])
    
    new_state = {
        **state,
        'target_exam': target_exam,
        'available_subjects': available_subjects,
        'onboarding_step': 4,
        'awaiting_response_for': 'subjects'
    }
    
    if target_exam == 'JAMB':
        subject_instruction = "JAMB requires 4 subjects (English + 3 others). Which subjects are you taking?"
    elif target_exam in ['WAEC', 'NECO']:
        subject_instruction = "Which subjects are you sitting for?"
    else:
        subject_instruction = "Which subjects will you be writing?"
    
    await send_whatsapp_message(
        phone,
        f"*{target_exam}* it is! 💪\n\n"
        f"{subject_instruction}\n\n"
        f"{subject_list}\n\n"
        f"_(Reply with the numbers separated by commas: e.g., 1,2,4,6)_"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_subjects(phone: str, conversation: dict, message: str, state: dict):
    """Step 4: Collect subjects."""
    
    available_subjects = state.get('available_subjects', [])
    target_exam = state.get('target_exam', 'JAMB')
    
    # Parse the response — could be numbers like "1,2,4" or names like "Physics, Chemistry"
    msg = message.strip()
    selected_subjects = []
    
    # Try number parsing first
    import re
    numbers = re.findall(r'\d+', msg)
    
    if numbers:
        for num_str in numbers:
            num = int(num_str)
            if 1 <= num <= len(available_subjects):
                subject = available_subjects[num - 1]
                if subject not in selected_subjects:
                    selected_subjects.append(subject)
    
    # Also try text matching
    if not selected_subjects or len(selected_subjects) < 2:
        msg_upper = msg.upper()
        for subject in available_subjects:
            if subject.upper() in msg_upper and subject not in selected_subjects:
                selected_subjects.append(subject)
    
    # Ensure English is always included for JAMB and WAEC
    if target_exam in ['JAMB', 'WAEC', 'NECO']:
        if 'English Language' not in selected_subjects:
            selected_subjects.insert(0, 'English Language')
    
    if len(selected_subjects) < 2:
        await send_whatsapp_message(
            phone,
            "Please select at least 2 subjects 📚\n\n"
            "Reply with the numbers from the list above, separated by commas.\n"
            "Example: *1,2,4,6*"
        )
        return
    
    subjects_display = "\n".join([f"✅ {sub}" for sub in selected_subjects])
    
    new_state = {
        **state,
        'subjects': selected_subjects,
        'onboarding_step': 5,
        'awaiting_response_for': 'exam_date'
    }
    
    await send_whatsapp_message(
        phone,
        f"Your subjects:\n{subjects_display}\n\n"
        f"When is your exam? 📅\n\n"
        f"_(Send the month and year, like: *May 2025* or *June 2025*)_"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_exam_date(phone: str, conversation: dict, message: str, state: dict):
    """Step 5: Collect exam date."""
    
    from datetime import datetime
    import re
    
    msg = message.strip()
    exam_date = None
    
    # Try to parse various date formats
    # "May 2025", "2025", "June", next year assumption, etc.
    
    months = {
        'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
        'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
        'aug': 8, 'august': 8, 'sep': 9, 'september': 9, 'oct': 10, 'october': 10,
        'nov': 11, 'november': 11, 'dec': 12, 'december': 12
    }
    
    msg_lower = msg.lower()
    year = None
    month = None
    
    # Find year
    year_match = re.search(r'20(2[3-9]|[3-9]\d)', msg)
    if year_match:
        year = int(year_match.group(0))
    
    # Find month
    for month_name, month_num in months.items():
        if month_name in msg_lower:
            month = month_num
            break
    
    if month and year:
        # Approximate exam date as the 15th of that month
        exam_date = f"{year}-{month:02d}-15"
    elif year:
        # Just year — assume May (JAMB/WAEC typical month)
        exam_date = f"{year}-05-15"
    elif msg_lower in ['not sure', 'soon', 'this year', 'idk']:
        # Give them a default of 6 months from now
        future = nigeria_now() + timedelta(days=180)
        exam_date = future.strftime('%Y-%m-%d')
    
    if not exam_date:
        await send_whatsapp_message(
            phone,
            "I didn't quite catch that 🤔\n\n"
            "When is your exam?\n\n"
            "You can say something like:\n"
            "• *May 2025*\n"
            "• *June 2025*\n"
            "• *Not sure* (I'll make a plan anyway!)"
        )
        return
    
    # Calculate days until exam
    exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
    now_dt = nigeria_now()
    days_left = (exam_dt.replace(tzinfo=None) - now_dt.replace(tzinfo=None)).days
    
    new_state = {
        **state,
        'exam_date': exam_date,
        'days_until_exam': days_left,
        'onboarding_step': 6,
        'awaiting_response_for': 'state'
    }
    
    urgency = ""
    if days_left < 30:
        urgency = f"\n\n⚠️ Only {days_left} days left! We need to focus hard."
    elif days_left < 90:
        urgency = f"\n\n📅 {days_left} days to go. Good time to build a strong foundation."
    else:
        urgency = f"\n\n✅ {days_left} days — plenty of time if we start now and stay consistent."
    
    states_sample = "Lagos, Abuja, Kano, Ogun, Rivers, Oyo..."
    
    await send_whatsapp_message(
        phone,
        f"Got it!{urgency}\n\n"
        f"Which state are you in? 📍\n\n"
        f"_(e.g., {states_sample})_\n\n"
        f"This helps me connect you with students near you."
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_state(phone: str, conversation: dict, message: str, state: dict):
    """Step 6: Collect state."""
    
    msg = message.strip().title()
    
    # Find matching state
    matched_state = None
    for nigerian_state in NIGERIAN_STATES:
        if msg.lower() in nigerian_state.lower() or nigerian_state.lower() in msg.lower():
            matched_state = nigerian_state
            break
    
    if not matched_state:
        matched_state = msg  # Accept whatever they say even if unrecognized
    
    new_state = {
        **state,
        'student_state': matched_state,
        'onboarding_step': 7,
        'awaiting_response_for': 'language_pref'
    }
    
    await send_whatsapp_message(
        phone,
        f"{matched_state}! 🇳🇬\n\n"
        f"How do you want me to explain things to you?\n\n"
        f"1️⃣ *Standard English* — clear, formal\n"
        f"2️⃣ *Naija Pidgin* — more casual and relatable\n\n"
        f"_(You can always switch this later)_"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_language_pref(phone: str, conversation: dict, message: str, state: dict):
    """Step 7: Language preference."""
    
    msg = message.strip().lower()
    
    if msg in ['1', 'english', 'standard', 'formal', 'standard english']:
        language = 'english'
        lang_display = "Standard English"
    elif msg in ['2', 'pidgin', 'naija', 'naija pidgin', 'pidgin english']:
        language = 'pidgin'
        lang_display = "Nigerian Pidgin"
    else:
        language = 'english'
        lang_display = "Standard English"
    
    new_state = {
        **state,
        'language_pref': language,
        'onboarding_step': 8,
        'awaiting_response_for': 'pin_setup'
    }
    
    await send_whatsapp_message(
        phone,
        f"*{lang_display}* it is! 👍\n\n"
        f"Almost done! Let's set up your *security PIN*.\n\n"
        f"Your PIN is a 4-digit number you'll use to log in on any device.\n"
        f"Keep it secret — don't share it with anyone.\n\n"
        f"What 4-digit PIN would you like?\n\n"
        f"_(Type exactly 4 digits, e.g., 1234 — but choose something you'll remember!)_"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_pin_setup(phone: str, conversation: dict, message: str, state: dict):
    """Step 8: PIN setup."""
    
    pin = message.strip()
    
    if not is_valid_pin(pin):
        await send_whatsapp_message(
            phone,
            "Your PIN must be *exactly 4 digits* (like 2580) 🔐\n\n"
            "Please try again with a 4-digit number."
        )
        return
    
    # Check for weak PINs
    weak_pins = ['1234', '0000', '1111', '2222', '3333', '4444', '5555', '6666', '7777', '8888', '9999', '1212', '0123']
    if pin in weak_pins:
        await send_whatsapp_message(
            phone,
            "That PIN is too easy to guess 😅\n\n"
            "Please choose a more unique 4-digit PIN."
        )
        return
    
    new_state = {
        **state,
        'pending_pin': pin,
        'onboarding_step': 9,
        'awaiting_response_for': 'pin_confirm'
    }
    
    await send_whatsapp_message(
        phone,
        "Got it! Please confirm your PIN by typing it again 🔐"
    )
    
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': new_state
    })

async def _handle_pin_confirm(phone: str, conversation: dict, message: str, state: dict):
    """Step 9: PIN confirmation — final step, creates the account."""
    
    pin_confirm = message.strip()
    pending_pin = state.get('pending_pin')
    
    if pin_confirm != pending_pin:
        # PINs don't match
        new_state = {**state, 'awaiting_response_for': 'pin_setup', 'pending_pin': None}
        
        await send_whatsapp_message(
            phone,
            "Those PINs don't match 🤔\n\n"
            "Please enter your desired PIN again:"
        )
        
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': new_state
        })
        return
    
    # Everything is collected! Create the account.
    try:
        from utils.helpers import generate_referral_code
        
        student = await create_student(
            phone=phone,
            name=state['name'],
            pin=pending_pin,
            class_level=state.get('class_level'),
            target_exam=state.get('target_exam'),
            subjects=state.get('subjects', []),
            exam_date=state.get('exam_date'),
            school_name=state.get('school_name'),
            state=state.get('student_state'),
            referred_by_wax_id=state.get('referred_by_wax_id')
        )
        
        # Link this WhatsApp to the new account
        await link_platform_to_student(student['id'], 'whatsapp', phone)
        
        # Update conversation state
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'student_id': student['id'],
            'current_mode': 'default',
            'conversation_state': {},
            'awaiting_response_for': None,
        })
        
        # Calculate days until exam for the welcome message
        days_left = state.get('days_until_exam', 0)
        name_first = student['name'].split()[0]
        wax_id = student['wax_id']
        recovery_code = student['recovery_code']
        trial_days = settings.TRIAL_DURATION_DAYS
        
        # Send the big welcome message
        welcome = (
            f"🎉 *Welcome to WaxPrep, {name_first}!*\n\n"
            f"Your account is ready. Here are your important details:\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 *Your WAX ID:* {wax_id}\n"
            f"🔑 *Recovery Code:* {recovery_code}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"⚠️ *IMPORTANT: Save both of these somewhere safe.*\n"
            f"Your WAX ID and Recovery Code are how you get back in if you ever lose access to your phone.\n"
            f"WaxPrep cannot recover these for you if you lose them.\n\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎁 *{trial_days}-Day Full Access Trial — ACTIVE!*\n"
            f"You have full access to everything on WaxPrep for {trial_days} days. No payment needed yet.\n\n"
        )
        
        if days_left > 0:
            welcome += f"📅 Your exam is in *{days_left} days*. Let's make every day count.\n\n"
        
        welcome += (
            f"What would you like to do first?\n\n"
            f"📚 *LEARN* — teach me a topic\n"
            f"❓ *QUIZ* — test my knowledge\n"
            f"📝 *EXAM* — mock exam mode\n"
            f"📊 *PROGRESS* — see my stats\n"
            f"❓ *HELP* — all commands\n\n"
            f"Or just ask me anything! Type your question and I'll answer it right now. 🚀"
        )
        
        await send_whatsapp_message(phone, welcome)
        
        # Update active student count
        from database.client import redis_client
        redis_client.incr('active_students_total')
        
    except Exception as e:
        print(f"Account creation error: {e}")
        await send_whatsapp_message(
            phone,
            "There was an error creating your account 😔\n\n"
            "Please try again or contact support if the problem continues."
        )

async def _handle_referral_code_entry(phone: str, conversation: dict, message: str, state: dict):
    """Handles referral code entry during onboarding."""
    # This is handled during step processing
    pass

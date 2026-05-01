import re
from telegram.sender import send_telegram_message
from database.conversations import update_conversation_state
from config.settings import settings

EXAM_SUBJECTS = {
    'JAMB': ['English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology', 'Economics', 'Government', 'Literature in English', 'Geography', 'Commerce', 'Agricultural Science', 'Christian Religious Studies', 'Islamic Religious Studies', 'History', 'Yoruba', 'Igbo', 'Hausa'],
    'WAEC': ['English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology', 'Economics', 'Government', 'Literature in English', 'Geography', 'Commerce', 'Agricultural Science', 'Further Mathematics', 'Food and Nutrition', 'Computer Studies', 'Technical Drawing'],
    'NECO': ['English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology', 'Economics', 'Government', 'Literature in English', 'Geography', 'Commerce', 'Agricultural Science'],
    'COMMON_ENTRANCE': ['English Language', 'Mathematics', 'Basic Science', 'Social Studies', 'Verbal Reasoning', 'Quantitative Reasoning'],
    'POST_UTME': ['English Language', 'Mathematics', 'Physics', 'Chemistry', 'Biology', 'Economics', 'Government'],
}

CLASS_LEVELS = ['JSS1', 'JSS2', 'JSS3', 'SS1', 'SS2', 'SS3']
NIGERIAN_STATES = ['Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue', 'Borno', 'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'FCT', 'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi', 'Kwara', 'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo', 'Plateau', 'Rivers', 'Sokoto', 'Taraba', 'Yobe', 'Zamfara']

SUBJECT_INTROS = {
    ('physics', 'chemistry', 'biology'): "There's one concept that controls all three sciences: **Energy.** It's the same energy that powers a generator (Physics), makes bread rise with yeast (Biology), and burns kerosene in a lamp (Chemistry). Understand this one thing, and you've already gained ground in three subjects at once. It'll take 2 minutes. Ready?",
    ('physics', 'chemistry'): "There's one idea that connects both your science subjects: **Matter.** Everything around you — the air, the water, your phone — is made of atoms. Physics tells you how they move. Chemistry tells you how they react. Master this link and both subjects become easier. 2 minutes. Ready?",
    ('physics', 'biology'): "Here's a connection most students miss: **Force and Motion** appear in both Physics and Biology. Blood flowing through your body follows the same principles as water through a pipe. An okada turning a corner is the same physics as your heartbeat. See the link? 2 minutes. Ready?",
    ('chemistry', 'biology'): "Both your sciences meet at **Chemical Reactions.** Digestion is chemistry inside your body. Fermentation is chemistry inside a palm wine gourd. Rust on a roof is chemistry in the open air. Same principles, different scenes. 2 minutes to connect them. Ready?",
    ('government', 'literature', 'economics'): "Your three subjects tell one big story: **Power, Money, and Meaning.** Government shows who makes the rules. Economics shows who pays for them. Literature shows who tells the story. Understand how these three connect, and you understand how societies rise and fall. 2 minutes. Ready?",
    ('government', 'economics', 'commerce'): "Your three subjects share one big idea: **Systems.** Government sets the rules. Economics tracks the money. Commerce moves the goods. Understand how they feed each other, and you understand how Nigeria works. 2 minutes. Ready?",
    ('government', 'literature'): "Both your subjects explore **Power.** Who holds it in a government? Who holds it in a story? From the Constitution to Chinua Achebe, the same struggle plays out: who gets to decide, and who pays the price. 2 minutes. Ready?",
    ('economics', 'commerce', 'geography'): "Your subjects revolve around **Resources.** Where they come from (Geography), how they're traded (Commerce), and who profits (Economics). Oil from the Delta, cocoa from Ondo, markets from Onitsha — it's all connected. 2 minutes. Ready?",
    ('english', 'literature', 'christian religious studies'): "Your subjects share one thread: **Narrative.** The Bible tells stories of faith. Achebe tells stories of change. Your English exam tests how well you understand both. Stories shape beliefs — let me show you how. 2 minutes. Ready?",
    ('mathematics', 'physics', 'chemistry'): "Your three subjects speak one language: **Equations.** Maths gives you the grammar. Physics and Chemistry give you the sentences. Once you see equations as a language instead of a punishment, everything shifts. 2 minutes. Ready?",
}

def get_welcome_intro(subjects: list) -> str:
    if not subjects: return "Let's start with the basics and build from there. Ready?"
    subject_lower = [s.lower().strip() for s in subjects]
    for combo, intro in SUBJECT_INTROS.items():
        if all(c in subject_lower for c in combo): return intro
    first = subjects[0] if subjects else 'your subject'
    return f"Let's start with {first} — that's a strong choice. We'll build your foundation step by step. Ready?"

# ... [Include existing helper functions like handle_new_or_existing, _step_name, etc., up to _step_pin_confirm] ...

async def _step_pin_confirm(chat_id: int, conversation: dict, message: str, state: dict):
    from database.students import create_student
    from features.wax_id import link_platform_to_student
    from features.notifications import notify_admin_new_student, fire_and_forget
    
    pin_confirm = message.strip()
    pending_pin = state.get('pending_pin', '')
    if pin_confirm != pending_pin:
        await send_telegram_message(chat_id, "Those PINs do not match.\n\nPlease enter your desired PIN again:")
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {'conversation_state': {**state, 'pending_pin': None, 'awaiting_response_for': 'pin_setup'}})
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
            language_preference=state.get('language_pref', 'english'),
        )
        await link_platform_to_student(student['id'], 'telegram', str(chat_id))
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {'student_id': student['id'], 'current_mode': 'default', 'conversation_state': {}})
        fire_and_forget(notify_admin_new_student(student, f"telegram:{chat_id}"))

        name_first = student['name'].split()[0]
        days_left = state.get('days_until_exam', 180)
        intro = get_welcome_intro(state.get('subjects', []))
        
        # CORRECTED DYNAMIC LOGIC
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
            f"*Full Access is now ACTIVE!*"
        )
        await send_telegram_message(chat_id, welcome)
    except Exception as e:
        await send_telegram_message(chat_id, f"Error creating account. Send *HI* to retry. Ref: {str(e)[:50]}")

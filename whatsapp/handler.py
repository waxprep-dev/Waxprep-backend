"""
WhatsApp Message Handler

This is the most important file in the entire system.
Every single message from every single student comes through here.

The handler:
1. Extracts the message and phone number from the incoming webhook data
2. Checks if the student is registered
3. Routes them to onboarding if new
4. Routes them to the appropriate handler if existing
5. Ensures every message gets a response

This file is kept clean and simple — it delegates to specific handlers
rather than doing work itself.
"""

from fastapi import Request, HTTPException
import json

from whatsapp.sender import send_whatsapp_message, mark_as_read
from whatsapp.flows.onboarding import (
    handle_new_or_existing, handle_onboarding_response
)
from whatsapp.flows.commands import handle_command
from database.conversations import (
    get_or_create_conversation, save_message, get_conversation_history,
    update_conversation_state
)
from features.wax_id import student_exists_in_platform
from database.students import (
    can_student_ask_question, update_student_stats, increment_questions_today
)
from ai.classifier import classify_message_fast
from ai.router import route_and_respond
from ai.prompts import get_main_tutor_prompt
from utils.helpers import sanitize_input, hash_phone
from config.settings import settings

async def handle_whatsapp_webhook(request: Request):
    """
    Entry point for all incoming WhatsApp messages.
    Called by the FastAPI route in main.py.
    """
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Process each entry in the webhook payload
    entries = body.get('entry', [])
    
    for entry in entries:
        changes = entry.get('changes', [])
        for change in changes:
            value = change.get('value', {})
            messages = value.get('messages', [])
            
            for message_data in messages:
                await process_single_message(message_data, value)
    
    return {"status": "ok"}

async def process_single_message(message_data: dict, context: dict):
    """
    Processes a single incoming WhatsApp message.
    This is where the actual logic lives.
    """
    
    # Extract basic information
    message_id = message_data.get('id')
    phone = message_data.get('from')
    message_type = message_data.get('type', 'text')
    timestamp = message_data.get('timestamp')
    
    if not phone:
        return
    
    # Format phone consistently
    if not phone.startswith('+'):
        phone = '+' + phone
    
    # Mark message as read immediately (shows double blue tick)
    if message_id:
        await mark_as_read(message_id)
    
    # Extract message content
    message_text = ""
    if message_type == 'text':
        message_text = message_data.get('text', {}).get('body', '').strip()
    elif message_type == 'voice' or message_type == 'audio':
        message_text = '[VOICE_NOTE]'  # Will be transcribed in V2
        await send_whatsapp_message(
            phone,
            "Voice notes will be supported soon! 🎙️\n\n"
            "For now, please type your question as text."
        )
        return
    elif message_type == 'image':
        message_text = '[IMAGE]'  # Will use GPT-4o for image analysis in Scholar tier
        await handle_image_message(phone, message_data)
        return
    elif message_type == 'document':
        await send_whatsapp_message(
            phone,
            "Document analysis is coming soon! 📄\n\n"
            "For now, please type your question."
        )
        return
    
    if not message_text:
        return
    
    # Sanitize input
    message_text = sanitize_input(message_text)
    
    # Check if this phone is linked to an existing student account
    student = await student_exists_in_platform('whatsapp', phone)
    
    # Get or create conversation state
    conversation_id_temp = f"temp_{phone}"
    if student:
        conversation = await get_or_create_conversation(
            student['id'], 'whatsapp', phone
        )
    else:
        # Create a temporary conversation for the onboarding flow
        # We'll link it to a student ID once they complete registration
        conversation = await get_or_create_conversation_for_phone(phone)
    
    # Save the incoming message to history
    if student:
        await save_message(
            conversation_id=conversation['id'],
            student_id=student['id'],
            platform='whatsapp',
            role='user',
            content=message_text,
            message_type=message_type
        )
    
    # ============================================================
    # ROUTING LOGIC
    # ============================================================
    
    state = conversation.get('conversation_state', {})
    awaiting = state.get('awaiting_response_for') or conversation.get('awaiting_response_for')
    
    # Check if this is an onboarding response
    if awaiting in ['new_or_existing', 'wax_id_entry', 'pin_entry', 'name', 
                     'class_level', 'target_exam', 'subjects', 'exam_date', 
                     'state', 'language_pref', 'pin_setup', 'pin_confirm']:
        await handle_onboarding_response(phone, conversation, message_text)
        return
    
    # If no student found and no onboarding in progress, start onboarding
    if not student:
        await handle_new_or_existing(phone, conversation, message_text)
        return
    
    # Student exists — route their message
    
    # First, check if session needs resumption offer
    await check_session_resumption(phone, student, conversation)
    
    # Classify the message
    intent = classify_message_fast(message_text, state)
    
    # Handle commands (these don't need AI)
    if intent == 'COMMAND':
        command = message_text.strip().upper().split()[0]
        await handle_command(phone, student, conversation, message_text, command)
        return
    
    # Handle promo codes
    if intent == 'PROMO_CODE':
        await handle_command(phone, student, conversation, message_text, 'PROMO')
        return
    
    # For all other messages, check if student can ask questions
    can_ask, limit_message = await can_student_ask_question(student)
    
    if not can_ask:
        await send_whatsapp_message(phone, limit_message)
        return
    
    # Build the AI system prompt with this student's data
    current_mode = conversation.get('current_mode', 'default')
    system_prompt = get_main_tutor_prompt(student, current_mode)
    
    # Get conversation history for context
    history = await get_conversation_history(conversation['id'])
    
    # Route to the appropriate AI and get response
    response = await route_and_respond(
        message=message_text,
        intent=intent,
        student=student,
        conversation_history=history,
        conversation_state=state,
        system_prompt=system_prompt
    )
    
    # Send the response
    await send_whatsapp_message(phone, response)
    
    # Update question count and stats
    await increment_questions_today(student['id'])
    
    # Save the AI response to history
    await save_message(
        conversation_id=conversation['id'],
        student_id=student['id'],
        platform='whatsapp',
        role='assistant',
        content=response
    )
    
    # Update streak and check for badges
    await update_streak_and_badges(student)

async def handle_image_message(phone: str, message_data: dict):
    """
    Handles image messages from Scholar+ students.
    Free students get a message explaining image analysis is a paid feature.
    """
    student = await student_exists_in_platform('whatsapp', phone)
    
    if not student:
        await send_whatsapp_message(
            phone,
            "Please sign up first to use WaxPrep! Type *HI* to get started."
        )
        return
    
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    
    # Image analysis is for Scholar and above only
    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "📸 Image analysis is available for Scholar Plan subscribers!\n\n"
            "With Scholar Plan, you can send photos of:\n"
            "• Textbook pages\n"
            "• Handwritten notes\n"
            "• Past question papers\n"
            "• Diagrams and graphs\n\n"
            f"Upgrade for just {format_naira(settings.SCHOLAR_MONTHLY)}/month.\n"
            "Type *SUBSCRIBE* to upgrade."
        )
        return
    
    # TODO: Download image and send to GPT-4o for analysis
    # This requires downloading the image from WhatsApp and sending to OpenAI
    # Implementation in full build
    await send_whatsapp_message(
        phone,
        "Got your image! Let me analyze it... 🔍\n\n"
        "_(Image analysis is being set up — check back soon!)_"
    )

async def check_session_resumption(phone: str, student: dict, conversation: dict):
    """
    Checks if the student was in the middle of something and offers to resume.
    Only offers if they were studying within the last 6 hours.
    """
    from utils.helpers import nigeria_now
    from datetime import datetime
    
    last_message = conversation.get('last_message_at')
    mode = conversation.get('current_mode', 'default')
    topic = conversation.get('current_topic')
    
    if not last_message or mode == 'default' or not topic:
        return
    
    if isinstance(last_message, str):
        last_message = datetime.fromisoformat(last_message.replace('Z', '+00:00'))
    
    hours_since = (nigeria_now() - last_message).total_seconds() / 3600
    
    if 0.5 < hours_since < settings.SESSION_RESUME_WINDOW_HOURS:
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Welcome back, {name}! 👋\n\n"
            f"You were learning about *{topic}* earlier.\n\n"
            f"Want to *CONTINUE* where you left off, or start something *NEW*?"
        )

async def get_or_create_conversation_for_phone(phone: str) -> dict:
    """
    Creates a temporary conversation for an unregistered user.
    Used during the onboarding process before a student ID exists.
    """
    from database.client import supabase, redis_client
    import json
    
    cache_key = f"conv:whatsapp:{phone}"
    cached = redis_client.get(cache_key)
    
    if cached:
        return json.loads(cached)
    
    # Create a temporary conversation without a student ID
    result = supabase.table('conversations').insert({
        'platform': 'whatsapp',
        'platform_user_id': phone,
        'current_mode': 'onboarding',
        'conversation_state': {'awaiting_response_for': 'new_or_existing'},
    }).execute()
    
    if result.data:
        conv = result.data[0]
        redis_client.setex(cache_key, 7200, json.dumps(conv, default=str))
        return conv
    
    return {'id': f'temp_{phone}', 'conversation_state': {}}

async def update_streak_and_badges(student: dict):
    """
    Updates the student's streak after they study.
    Also checks if any badges should be awarded.
    """
    from database.students import update_student
    from utils.helpers import nigeria_today
    from datetime import datetime, timedelta
    
    today = nigeria_today()
    last_study = student.get('last_study_date')
    current_streak = student.get('current_streak', 0)
    
    if last_study == today:
        # Already studied today — streak unchanged
        return
    
    # Check if yesterday
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    
    if last_study == yesterday:
        # Consecutive day — increment streak
        new_streak = current_streak + 1
    elif last_study is None:
        # First time studying — start streak
        new_streak = 1
    else:
        # Gap in studying — reset streak
        new_streak = 1
    
    longest_streak = max(student.get('longest_streak', 0), new_streak)
    
    await update_student(student['id'], {
        'current_streak': new_streak,
        'longest_streak': longest_streak,
        'last_study_date': today,
    })
    
    # Check for streak badges
    streak_badge_thresholds = {7: 'STREAK_7', 14: 'STREAK_14', 30: 'STREAK_30', 
                               60: 'STREAK_60', 100: 'STREAK_100'}
    
    for threshold, badge_code in streak_badge_thresholds.items():
        if new_streak == threshold:
            await award_badge(student['id'], badge_code)
            break

async def award_badge(student_id: str, badge_code: str):
    """Awards a badge to a student if they don't already have it."""
    from database.client import supabase
    
    # Get badge
    badge_result = supabase.table('badges').select('*').eq('badge_code', badge_code).execute()
    if not badge_result.data:
        return
    
    badge = badge_result.data[0]
    
    # Check if already earned
    existing = supabase.table('student_badges')\
        .select('id')\
        .eq('student_id', student_id)\
        .eq('badge_id', badge['id'])\
        .execute()
    if existing.data:
        return  # Already has this badge
    
    # Award the badge
    supabase.table('student_badges').insert({
        'student_id': student_id,
        'badge_id': badge['id'],
    }).execute()
    
    # Give the points
    points = badge.get('points_awarded', 50)
    supabase.rpc('add_points_to_student', {
        'student_id_param': student_id,
        'points_to_add': points
    }).execute()
async def handle_quiz_session(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    intent: str
):
    """
    Manages an active quiz session.
    
    When in quiz mode, the conversation flows like:
    1. Student says "quiz me on Physics"
    2. We send them a question
    3. They answer A, B, C, or D
    4. We tell them if they're right and why
    5. We ask if they want another question
    6. Repeat
    """
    from features.quiz_engine import (
        get_question_for_student, format_question_for_whatsapp,
        evaluate_quiz_answer, update_mastery_after_answer,
        calculate_and_award_points
    )
    
    state = conversation.get('conversation_state', {})
    awaiting = state.get('awaiting_response_for')
    
    # If awaiting a quiz answer
    if awaiting == 'quiz_answer':
        current_question = state.get('current_question')
        
        if not current_question:
            # Something went wrong, restart
            await send_whatsapp_message(
                phone,
                "Let me restart your quiz session. What subject would you like to practice?"
            )
            return
        
        # Evaluate the answer
        is_correct, feedback = evaluate_quiz_answer(
            message.strip(),
            current_question.get('correct_answer', 'A'),
            current_question
        )
        
        if is_correct is None:
            # Couldn't parse the answer
            await send_whatsapp_message(phone, feedback)
            return
        
        # Update mastery
        await update_mastery_after_answer(
            student_id=student['id'],
            subject=current_question.get('subject', ''),
            topic=current_question.get('topic', ''),
            question_difficulty=current_question.get('difficulty_level', 5),
            is_correct=is_correct
        )
        
        # Calculate and award points
        points, badge = await calculate_and_award_points(
            student_id=student['id'],
            is_correct=is_correct,
            question_difficulty=current_question.get('difficulty_level', 5)
        )
        
        # Add points info to feedback
        points_msg = f"\n\n+{points} points! 💰" if is_correct else f"\n\n+{points} points for trying."
        
        badge_msg = ""
        if badge:
            badge_msg = f"\n\n🏅 *New Badge: {badge['name']}!*\n{badge['description']}"
        
        full_feedback = feedback + points_msg + badge_msg
        
        # Increment question count
        session_q = state.get('session_questions', 0) + 1
        session_correct = state.get('session_correct', 0) + (1 if is_correct else 0)
        
        # After every 5 questions, show a mini progress update
        if session_q % 5 == 0:
            accuracy = round(session_correct / session_q * 100)
            full_feedback += (
                f"\n\n📊 *Session Update:*\n"
                f"{session_q} questions | {session_correct} correct | {accuracy}% accuracy"
            )
        
        full_feedback += "\n\n_Next question? Type *YES* or *NEXT*, or say what subject to switch to._"
        
        await send_whatsapp_message(phone, full_feedback)
        
        # Update conversation state
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'current_mode': 'quiz',
            'conversation_state': {
                **state,
                'awaiting_response_for': 'quiz_continue',
                'session_questions': session_q,
                'session_correct': session_correct,
                'last_question': current_question,
            }
        })
        
        return
    
    # Starting a new quiz or continuing
    subject = conversation.get('current_subject') or extract_subject_from_message(message)
    
    if not subject:
        await send_whatsapp_message(
            phone,
            "Which subject would you like to be quizzed on? 📚\n\n"
            "You can say:\n"
            "• *Quiz Physics*\n"
            "• *Test me on Chemistry*\n"
            "• *Quiz me on Mathematics*"
        )
        return
    
    topic = extract_topic_from_message(message)
    
    # Get a question
    question = await get_question_for_student(
        student_id=student['id'],
        subject=subject,
        topic=topic
    )
    
    if not question:
        await send_whatsapp_message(
            phone,
            f"I'm having trouble finding {subject} questions right now. 😕\n\n"
            "Try: asking me to explain a topic first, then quiz you on it.\n"
            "Or try a different subject."
        )
        return
    
    # Format and send the question
    session_q = state.get('session_questions', 0)
    formatted = format_question_for_whatsapp(question, session_q + 1)
    await send_whatsapp_message(phone, formatted)
    
    # Save the question in state so we can evaluate the answer
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'quiz',
        'current_subject': subject,
        'current_topic': topic or question.get('topic'),
        'conversation_state': {
            **state,
            'awaiting_response_for': 'quiz_answer',
            'current_question': question,
            'session_questions': session_q,
            'session_correct': state.get('session_correct', 0),
        }
    })

def extract_subject_from_message(message: str) -> str | None:
    """
    Extracts a subject name from a message like "quiz me on Physics" or "test Chemistry."
    """
    subjects = [
        'Mathematics', 'Math', 'Maths', 'Physics', 'Chemistry', 'Biology',
        'English', 'English Language', 'Economics', 'Government', 'Literature',
        'Geography', 'Commerce', 'Agricultural Science', 'Agric', 'Further Mathematics',
        'History', 'Yoruba', 'Igbo', 'Hausa',
    ]
    
    subject_map = {
        'MATH': 'Mathematics', 'MATHS': 'Mathematics',
        'ENGLISH': 'English Language', 'ENG': 'English Language',
        'BIO': 'Biology', 'CHEM': 'Chemistry', 'PHY': 'Physics', 'PHYSICS': 'Physics',
        'ECON': 'Economics', 'GOVT': 'Government', 'GOV': 'Government',
        'LIT': 'Literature in English', 'LITERATURE': 'Literature in English',
        'AGRIC': 'Agricultural Science', 'COMMERCE': 'Commerce', 'GEO': 'Geography',
        'FURTHER MATH': 'Further Mathematics', 'FURTHER MATHS': 'Further Mathematics',
    }
    
    msg_upper = message.upper()
    
    for abbrev, full_name in subject_map.items():
        if abbrev in msg_upper:
            return full_name
    
    for subject in subjects:
        if subject.upper() in msg_upper:
            return subject
    
    return None

def extract_topic_from_message(message: str) -> str | None:
    """
    Tries to extract a specific topic from a message.
    Example: "quiz me on Newton's Laws in Physics" → "Newton's Laws"
    """
    import re
    
    # Common patterns: "on [topic]", "about [topic]", "in [topic]"
    patterns = [
        r'on\s+(?:the\s+)?(.+?)(?:\s+in\s+\w+|$)',
        r'about\s+(?:the\s+)?(.+?)(?:\s+in\s+\w+|$)',
        r'regarding\s+(.+?)(?:\s+in\s+\w+|$)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            topic = match.group(1).strip()
            # Filter out if it's just a subject name
            if len(topic) > 3 and topic.lower() not in ['physics', 'chemistry', 'biology', 'mathematics', 'english']:
                return topic
    
    return None    
    return badge

"""
WhatsApp Message Handler — Complete

Every single WhatsApp message flows through this file.
This is the central nervous system of WaxPrep.
"""

from fastapi import Request, HTTPException
import json

from whatsapp.sender import send_whatsapp_message, mark_as_read
from whatsapp.flows.onboarding import (
    handle_new_or_existing, handle_onboarding_response
)
from whatsapp.flows.commands import handle_command
from whatsapp.flows.study import (
    handle_study_message, handle_challenge_answer
)
from whatsapp.flows.mock_exam import handle_exam_answer
from whatsapp.flows.subscription import handle_subscription_flow
from database.conversations import (
    get_or_create_conversation, save_message, get_conversation_history,
    update_conversation_state
)
from features.wax_id import student_exists_in_platform
from database.students import (
    can_student_ask_question, update_student_stats, increment_questions_today
)
from ai.classifier import classify_message_fast
from utils.helpers import sanitize_input, hash_phone
from config.settings import settings

ONBOARDING_STATES = [
    'new_or_existing', 'wax_id_entry', 'pin_entry', 'name',
    'class_level', 'target_exam', 'subjects', 'exam_date',
    'state', 'language_pref', 'pin_setup', 'pin_confirm', 'referral_code'
]

COMMAND_LIST = [
    'PROGRESS', 'HELP', 'SUBSCRIBE', 'STREAK', 'PLAN', 'BALANCE',
    'MYID', 'PROMO', 'CODE', 'STOP', 'MODES', 'BADGES', 'REFERRAL',
    'PARENT', 'CHALLENGE', 'DAILY', 'LEARN', 'QUIZ', 'EXAM', 'REVISION',
    'PAUSE', 'CONTINUE'
]

async def handle_whatsapp_webhook(request: Request):
    """Entry point for all incoming WhatsApp messages."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "invalid_json"}
    
    entries = body.get('entry', [])
    
    for entry in entries:
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for message_data in value.get('messages', []):
                try:
                    await process_single_message(message_data, value)
                except Exception as e:
                    print(f"Message processing error: {e}")
                    import traceback
                    traceback.print_exc()
    
    return {"status": "ok"}

async def process_single_message(message_data: dict, context: dict):
    """Processes one incoming WhatsApp message."""
    
    message_id = message_data.get('id')
    phone = message_data.get('from', '')
    message_type = message_data.get('type', 'text')
    
    if not phone:
        return
    
    # Normalize phone format
    phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    if not phone.startswith('234'):
        if phone.startswith('0'):
            phone = '234' + phone[1:]
        else:
            phone = '234' + phone
    
    # Mark as read immediately
    if message_id:
        await mark_as_read(message_id)
    
    # Handle non-text messages
    if message_type == 'image':
        await handle_incoming_image(phone, message_data)
        return
    
    if message_type in ['voice', 'audio']:
        await handle_incoming_voice(phone, message_data)
        return
    
    if message_type not in ['text', 'button']:
        return
    
    # Extract text
    if message_type == 'text':
        message_text = message_data.get('text', {}).get('body', '').strip()
    else:
        message_text = message_data.get('button', {}).get('text', '').strip()
    
    if not message_text:
        return
    
    message_text = sanitize_input(message_text)
    
    # Check if student exists on this platform
    student = await student_exists_in_platform('whatsapp', phone)
    
    # Get or create conversation
    if student:
        conversation = await get_or_create_conversation(student['id'], 'whatsapp', phone)
    else:
        conversation = await get_or_create_conversation_for_phone(phone)
    
    # Get current state
    state = conversation.get('conversation_state', {})
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    
    awaiting = state.get('awaiting_response_for') or conversation.get('awaiting_response_for')
    
    # ============================================================
    # ROUTING DECISION TREE
    # ============================================================
    
    # PRIORITY 1: If in onboarding, handle onboarding
    if awaiting in ONBOARDING_STATES:
        await handle_onboarding_response(phone, conversation, message_text)
        return
    
    # PRIORITY 2: If no student yet, start onboarding
    if not student:
        await handle_new_or_existing(phone, conversation, message_text)
        return
    
    # Save the message to history
    await save_message(
        conversation_id=conversation['id'],
        student_id=student['id'],
        platform='whatsapp',
        role='user',
        content=message_text
    )
    
    # PRIORITY 3: Handle exam mode (no commands allowed during exam except STOP EXAM)
    if conversation.get('current_mode') == 'exam' or awaiting == 'exam_answer':
        if message_text.upper().strip() not in ['STOP', 'STOP EXAM']:
            await handle_exam_answer(phone, student, conversation, message_text)
            return
    
    # PRIORITY 4: Handle challenge answer
    if awaiting == 'challenge_answer':
        await handle_challenge_answer(phone, student, conversation, message_text, state)
        return
    
    # PRIORITY 5: Classify the message
    intent = classify_message_fast(message_text, state)
    
    # PRIORITY 6: Handle commands
    if intent == 'COMMAND':
        command = message_text.strip().upper().split()[0]
        
        # Handle SUBSCRIBE specially
        if command == 'SUBSCRIBE' or 'SCHOLAR' in message_text.upper():
            await handle_subscription_flow(phone, student, conversation, message_text)
            return
        
        await handle_command(phone, student, conversation, message_text, command)
        return
    
    # PRIORITY 7: Handle promo codes
    if intent == 'PROMO_CODE':
        await handle_command(phone, student, conversation, message_text, 'PROMO')
        return
    
    # PRIORITY 8: Check question limits
    can_ask, limit_message = await can_student_ask_question(student)
    if not can_ask:
        await send_whatsapp_message(phone, limit_message)
        return
    
    # PRIORITY 9: Handle study messages (quiz answers, academic questions, etc.)
    await handle_study_message(phone, student, conversation, message_text, intent)
    
    # Update question count and streak
    await increment_questions_today(student['id'])
    await update_streak_and_badges(student)

async def handle_incoming_image(phone: str, message_data: dict):
    """Handles an incoming image message from a student."""
    student = await student_exists_in_platform('whatsapp', phone)
    
    if not student:
        await send_whatsapp_message(phone, "Please sign up first! Type *HI* to get started.")
        return
    
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    
    # Image analysis requires Scholar or above (or trial)
    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "📸 *Image Analysis — Scholar Feature*\n\n"
            "Send photos of textbooks, questions, or notes with *Scholar Plan*!\n\n"
            f"Upgrade for just {format_naira(settings.SCHOLAR_MONTHLY)}/month.\n"
            "Type *SUBSCRIBE* to unlock image analysis."
        )
        return
    
    # Get image ID
    image_data = message_data.get('image', {})
    image_id = image_data.get('id')
    caption = image_data.get('caption', '')
    
    if not image_id:
        return
    
    # Tell student we're processing
    await send_whatsapp_message(
        phone,
        "📸 Got your image! Analyzing it now...\n\n"
        "_(This takes about 5-10 seconds)_ 🔍"
    )
    
    # Download and analyze
    from ai.openai_client import download_whatsapp_image, analyze_image
    
    image_b64 = await download_whatsapp_image(image_id)
    
    if not image_b64:
        await send_whatsapp_message(
            phone,
            "❌ I couldn't download that image.\n\n"
            "Please try sending it again, or type your question in text."
        )
        return
    
    prompt = None
    if caption:
        prompt = (
            f"The student is asking: '{caption}'\n\n"
            f"Please analyze this image and answer their question. "
            f"This student is preparing for {student.get('target_exam', 'JAMB')}."
        )
    
    response = await analyze_image(
        image_base64=image_b64,
        prompt=prompt,
        student=student
    )
    
    await send_whatsapp_message(phone, response)
    await increment_questions_today(student['id'])

async def handle_incoming_voice(phone: str, message_data: dict):
    """Handles voice notes — transcribes and processes as text."""
    student = await student_exists_in_platform('whatsapp', phone)
    
    if not student:
        await send_whatsapp_message(phone, "Please sign up first! Type *HI* to get started.")
        return
    
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    
    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "🎙️ Voice notes are available on Scholar Plan!\n\n"
            "Type *SUBSCRIBE* to unlock voice input."
        )
        return
    
    audio_data = message_data.get('audio', {}) or message_data.get('voice', {})
    audio_id = audio_data.get('id')
    
    if not audio_id:
        return
    
    await send_whatsapp_message(phone, "🎙️ Listening to your voice note...\n_(Transcribing now)_ ✨")
    
    from ai.openai_client import transcribe_voice_note
    
    transcribed = await transcribe_voice_note(audio_id)
    
    if not transcribed:
        await send_whatsapp_message(
            phone,
            "❌ I couldn't understand that voice note.\n\n"
            "Please try speaking more clearly, or type your question."
        )
        return
    
    await send_whatsapp_message(phone, f"🎙️ I heard: _{transcribed}_\n\nLet me help with that...")
    
    # Now process the transcribed text as a normal message
    fake_message_data = {
        'id': audio_id,
        'from': phone,
        'type': 'text',
        'text': {'body': transcribed}
    }
    
    await process_single_message(fake_message_data, {})

async def get_or_create_conversation_for_phone(phone: str) -> dict:
    """Creates a temporary conversation for unregistered users during onboarding."""
    from database.client import supabase, redis_client
    
    cache_key = f"conv:whatsapp:{phone}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass
    
    try:
        result = supabase.table('conversations').upsert({
            'platform': 'whatsapp',
            'platform_user_id': phone,
            'current_mode': 'onboarding',
            'conversation_state': {'awaiting_response_for': 'new_or_existing'},
        }, on_conflict='platform,platform_user_id').execute()
        
        if result.data:
            conv = result.data[0]
            try:
                redis_client.setex(cache_key, 7200, json.dumps(conv, default=str))
            except Exception:
                pass
            return conv
    except Exception as e:
        print(f"Conversation creation error: {e}")
    
    return {
        'id': f'temp_{phone}',
        'conversation_state': {'awaiting_response_for': 'new_or_existing'},
        'current_mode': 'onboarding'
    }

async def update_streak_and_badges(student: dict):
    """Updates the student's streak after they study."""
    from database.students import update_student
    from utils.helpers import nigeria_today
    from datetime import datetime, timedelta
    
    today = nigeria_today()
    last_study = student.get('last_study_date')
    current_streak = student.get('current_streak', 0)
    
    if last_study == today:
        return  # Already studied today
    
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    
    if last_study == yesterday:
        new_streak = current_streak + 1
    elif last_study is None:
        new_streak = 1
    else:
        new_streak = 1
    
    longest_streak = max(student.get('longest_streak', 0), new_streak)
    
    await update_student(student['id'], {
        'current_streak': new_streak,
        'longest_streak': longest_streak,
        'last_study_date': today,
    })
    
    streak_badge_thresholds = {
        7: 'STREAK_7', 14: 'STREAK_14', 30: 'STREAK_30',
        60: 'STREAK_60', 100: 'STREAK_100'
    }
    
    for threshold, badge_code in streak_badge_thresholds.items():
        if new_streak == threshold:
            await award_badge(student['id'], badge_code)
            break
    
    # Notify if milestone streak
    if new_streak in [7, 14, 30, 60, 100]:
        phone_result = __import__('database.client', fromlist=['supabase']).supabase\
            .table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()
        
        if phone_result.data:
            phone = phone_result.data[0]['platform_user_id']
            name = student.get('name', 'Student').split()[0]
            
            milestone_messages = {
                7: f"🔥 *7-DAY STREAK, {name}!*\n\nOne week straight! You're building real habits now. This is how champions are made. Keep going! 💪",
                14: f"⚡ *14-DAY STREAK, {name}!*\n\nTwo weeks! You're in the top 20% of WaxPrep students by consistency. Your exam score WILL reflect this dedication.",
                30: f"💫 *30-DAY STREAK, {name}!*\n\nONE MONTH straight! You've earned the Monthly Master badge. This level of dedication is rare. You're going to pass this exam. I'm certain of it.",
                60: f"💎 *60-DAY STREAK!*\n\nTwo months. You are among the most dedicated students in Nigeria right now. This streak tells me everything about who you are.",
                100: f"👑 *100-DAY STREAK, {name}!*\n\nOne hundred days. Century Scholar badge earned. There is nothing you cannot achieve.",
            }
            
            if new_streak in milestone_messages:
                await send_whatsapp_message(phone, milestone_messages[new_streak])

async def award_badge(student_id: str, badge_code: str) -> dict | None:
    """Awards a badge to a student if they don't already have it."""
    from database.client import supabase
    
    badge_result = supabase.table('badges').select('*').eq('badge_code', badge_code).execute()
    if not badge_result.data:
        return None
    
    badge = badge_result.data[0]
    
    existing = supabase.table('student_badges')\
        .select('id')\
        .eq('student_id', student_id)\
        .eq('badge_id', badge['id'])\
        .execute()
    
    if existing.data:
        return None
    
    supabase.table('student_badges').insert({
        'student_id': student_id,
        'badge_id': badge['id'],
    }).execute()
    
    points = badge.get('points_awarded', 50)
    supabase.rpc('add_points_to_student', {
        'student_id_param': student_id,
        'points_to_add': points
    }).execute()
    
    return badge

def format_naira(amount: int) -> str:
    """Quick helper for formatting Naira amounts."""
    return f"₦{amount:,}"

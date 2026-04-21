"""
WhatsApp Message Handler — Complete Version

Every single WhatsApp message flows through this file.
ALL cross-module imports are LAZY (inside functions) to prevent startup errors.
"""

import json
from fastapi import Request
from config.settings import settings


ONBOARDING_STATES = {
    'new_or_existing', 'wax_id_entry', 'pin_entry', 'name',
    'class_level', 'target_exam', 'subjects', 'exam_date',
    'state', 'language_pref', 'pin_setup', 'pin_confirm', 'referral_code'
}


async def handle_whatsapp_webhook(request: Request):
    """Entry point — receives all WhatsApp messages."""
    try:
        body = await request.json()
    except Exception:
        return {"status": "invalid_json"}

    for entry in body.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            for message_data in value.get('messages', []):
                try:
                    await process_single_message(message_data, value)
                except Exception as e:
                    import traceback
                    print(f"❌ Message processing error: {e}")
                    traceback.print_exc()

    return {"status": "ok"}


async def process_single_message(message_data: dict, context: dict):
    """Processes one incoming WhatsApp message."""
    from whatsapp.sender import send_whatsapp_message, mark_as_read

    message_id = message_data.get('id', '')
    raw_phone = message_data.get('from', '')
    message_type = message_data.get('type', 'text')

    if not raw_phone:
        return

    # Normalize phone — always store without + prefix for consistency
    phone = _normalize_phone(raw_phone)

    # Mark as read
    if message_id:
        await mark_as_read(message_id)

    # Route by message type
    if message_type == 'image':
        await _handle_incoming_image(phone, message_data)
        return

    if message_type in ['voice', 'audio']:
        await _handle_incoming_voice(phone, message_data)
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

    # Sanitize
    message_text = _sanitize(message_text)

    # ============================================================
    # CHECK FOR ADMIN COMMANDS FIRST
    # Only the admin's personal number can trigger these
    # ============================================================
    from admin.dashboard import is_admin, handle_admin_command

    if message_text.upper().startswith('ADMIN') and is_admin(phone):
        await handle_admin_command(phone, message_text)
        return

    # ============================================================
    # REGULAR USER FLOW
    # ============================================================
    from features.wax_id import student_exists_in_platform

    student = await student_exists_in_platform('whatsapp', phone)

    if student:
        from database.conversations import get_or_create_conversation
        conversation = await get_or_create_conversation(student['id'], 'whatsapp', phone)
    else:
        conversation = await _get_or_create_temp_conversation(phone)

    # Parse state
    raw_state = conversation.get('conversation_state', {})
    if isinstance(raw_state, str):
        try:
            state = json.loads(raw_state)
        except Exception:
            state = {}
    else:
        state = raw_state or {}

    awaiting = state.get('awaiting_response_for') or conversation.get('awaiting_response_for', '')

    # PRIORITY 1: Onboarding states
    if awaiting in ONBOARDING_STATES:
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message_text)
        return

    # PRIORITY 2: No student — start onboarding
    if not student:
        from whatsapp.flows.onboarding import handle_new_or_existing
        await handle_new_or_existing(phone, conversation, message_text)
        return

    # Save incoming message
    from database.conversations import save_message
    await save_message(
        conversation_id=conversation['id'],
        student_id=student['id'],
        platform='whatsapp',
        role='user',
        content=message_text
    )

    # PRIORITY 3: Exam mode — only STOP EXAM allowed
    current_mode = conversation.get('current_mode', 'default')
    if current_mode == 'exam' or awaiting == 'exam_answer':
        if 'STOP' in message_text.upper():
            from whatsapp.flows.mock_exam import end_exam_early
            await end_exam_early(phone, student, conversation, state)
        else:
            from whatsapp.flows.mock_exam import handle_exam_answer
            await handle_exam_answer(phone, student, conversation, message_text)
        return

    # PRIORITY 4: Challenge answer
    if awaiting == 'challenge_answer':
        from whatsapp.flows.study import handle_challenge_answer
        await handle_challenge_answer(phone, student, conversation, message_text, state)
        return

    # PRIORITY 5: Quiz answer
    if awaiting == 'quiz_answer':
        from whatsapp.flows.study import handle_quiz_answer
        await handle_quiz_answer(phone, student, conversation, message_text, state)
        return

    # PRIORITY 6: Quiz continuation (yes/no for next question)
    if awaiting == 'quiz_continue':
        msg_upper = message_text.strip().upper()
        if msg_upper in ['YES', 'Y', 'NEXT', 'CONTINUE', '1', 'ANOTHER', 'MORE']:
            from whatsapp.flows.study import deliver_quiz_question
            subject = conversation.get('current_subject', '')
            topic = conversation.get('current_topic', '')
            await deliver_quiz_question(phone, student, conversation, subject, topic, state)
        else:
            from whatsapp.flows.study import handle_academic_message
            from ai.classifier import classify_message_fast
            intent = classify_message_fast(message_text, state)
            await handle_academic_message(phone, student, conversation, message_text, intent)
        return

    # PRIORITY 7: Classify the message
    from ai.classifier import classify_message_fast
    intent = classify_message_fast(message_text, state)

    # PRIORITY 8: Commands
    if intent == 'COMMAND':
        command = message_text.strip().upper().split()[0]

        if command == 'SUBSCRIBE' or ('SCHOLAR' in message_text.upper() and
                                       any(w in message_text.upper() for w in ['MONTHLY', 'YEARLY', 'PLAN'])):
            from whatsapp.flows.subscription import handle_subscription_flow
            await handle_subscription_flow(phone, student, conversation, message_text)
            return

        if command in ['CHALLENGE', 'DAILY']:
            from whatsapp.flows.study import handle_daily_challenge
            await handle_daily_challenge(phone, student, conversation)
            return

        if command == 'EXAM' or 'MOCK EXAM' in message_text.upper():
            from whatsapp.flows.mock_exam import start_mock_exam
            await start_mock_exam(phone, student, conversation)
            return

        from whatsapp.flows.commands import handle_command
        await handle_command(phone, student, conversation, message_text, command)
        return

    # PRIORITY 9: Promo code
    if intent == 'PROMO_CODE':
        from whatsapp.flows.commands import handle_command
        await handle_command(phone, student, conversation, message_text, 'PROMO')
        return

    # PRIORITY 10: Check question limits
    from database.students import can_student_ask_question
    can_ask, limit_message = await can_student_ask_question(student)

    if not can_ask:
        from whatsapp.sender import send_whatsapp_message
        await send_whatsapp_message(phone, limit_message)
        return

    # PRIORITY 11: Study messages (the main learning experience)
    from whatsapp.flows.study import handle_study_message
    await handle_study_message(phone, student, conversation, message_text, intent)

    # Update stats after studying
    from database.students import increment_questions_today
    await increment_questions_today(student['id'])
    await _update_streak(student)


def _normalize_phone(phone: str) -> str:
    """Normalizes phone to format without +, e.g. 2348012345678."""
    phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    if phone.startswith('0') and len(phone) == 11:
        phone = '234' + phone[1:]
    elif not phone.startswith('234') and len(phone) == 10:
        phone = '234' + phone
    return phone


def _sanitize(text: str) -> str:
    """Removes potentially dangerous characters from user input."""
    import re
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()[:2000]


async def _get_or_create_temp_conversation(phone: str) -> dict:
    """Creates a temporary conversation record for unregistered users."""
    from database.client import supabase, redis_client

    cache_key = f"conv:whatsapp:{phone}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    try:
        result = supabase.table('conversations').select('*')\
            .eq('platform', 'whatsapp')\
            .eq('platform_user_id', phone)\
            .execute()

        if result.data:
            conv = result.data[0]
        else:
            insert_result = supabase.table('conversations').insert({
                'platform': 'whatsapp',
                'platform_user_id': phone,
                'current_mode': 'onboarding',
                'conversation_state': {'awaiting_response_for': 'new_or_existing'},
            }).execute()
            conv = insert_result.data[0] if insert_result.data else {
                'id': f'temp_{phone}',
                'conversation_state': {'awaiting_response_for': 'new_or_existing'},
                'current_mode': 'onboarding'
            }

        try:
            redis_client.setex(cache_key, 7200, json.dumps(conv, default=str))
        except Exception:
            pass

        return conv

    except Exception as e:
        print(f"Temp conversation error: {e}")
        return {
            'id': f'temp_{phone}',
            'conversation_state': {'awaiting_response_for': 'new_or_existing'},
            'current_mode': 'onboarding'
        }


async def _handle_incoming_image(phone: str, message_data: dict):
    """Handles image messages from students."""
    from features.wax_id import student_exists_in_platform
    from whatsapp.sender import send_whatsapp_message

    student = await student_exists_in_platform('whatsapp', phone)

    if not student:
        await send_whatsapp_message(phone, "Please sign up first! Type *HI* to get started.")
        return

    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "📸 *Image Analysis — Scholar Feature*\n\n"
            "Scholar Plan lets you send photos of textbooks, notes, and past papers!\n\n"
            "Type *SUBSCRIBE* to unlock. ✅"
        )
        return

    image_data = message_data.get('image', {})
    image_id = image_data.get('id')
    caption = image_data.get('caption', '')

    if not image_id:
        return

    await send_whatsapp_message(phone, "📸 Got your image! Analyzing... _(~10 seconds)_ 🔍")

    try:
        from ai.openai_client import download_whatsapp_image, analyze_image
        image_b64 = await download_whatsapp_image(image_id)

        if not image_b64:
            await send_whatsapp_message(phone, "❌ Couldn't download that image. Please try again.")
            return

        prompt = None
        if caption:
            prompt = (
                f"The student asks: '{caption}'\n\n"
                f"Analyze this image and answer. Student is preparing for {student.get('target_exam', 'JAMB')}."
            )

        response = await analyze_image(image_base64=image_b64, prompt=prompt, student=student)
        await send_whatsapp_message(phone, response)

        from database.students import increment_questions_today
        await increment_questions_today(student['id'])

    except Exception as e:
        print(f"Image analysis error: {e}")
        await send_whatsapp_message(
            phone,
            "❌ Couldn't analyze that image right now.\n\nPlease type your question instead."
        )


async def _handle_incoming_voice(phone: str, message_data: dict):
    """Handles voice notes from students."""
    from features.wax_id import student_exists_in_platform
    from whatsapp.sender import send_whatsapp_message

    student = await student_exists_in_platform('whatsapp', phone)

    if not student:
        await send_whatsapp_message(phone, "Please sign up first! Type *HI* to get started.")
        return

    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "🎙️ Voice notes are a Scholar Plan feature!\n\nType *SUBSCRIBE* to unlock."
        )
        return

    audio_data = message_data.get('audio', {}) or message_data.get('voice', {})
    audio_id = audio_data.get('id')

    if not audio_id:
        return

    await send_whatsapp_message(phone, "🎙️ Listening... _(transcribing now)_ ✨")

    try:
        from ai.openai_client import transcribe_voice_note
        transcribed = await transcribe_voice_note(audio_id)

        if not transcribed:
            await send_whatsapp_message(
                phone,
                "❌ Couldn't understand that voice note.\n\nPlease speak clearly or type your question."
            )
            return

        await send_whatsapp_message(phone, f"🎙️ I heard:\n_{transcribed}_\n\nProcessing...")

        # Process as text
        fake_data = {'id': audio_id, 'from': phone, 'type': 'text', 'text': {'body': transcribed}}
        await process_single_message(fake_data, {})

    except Exception as e:
        print(f"Voice transcription error: {e}")
        await send_whatsapp_message(phone, "❌ Voice note failed. Please type your question.")


async def award_badge(student_id: str, badge_code: str) -> dict | None:
    """Awards a badge to a student if they don't already have it."""
    from database.client import supabase

    try:
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

    except Exception as e:
        print(f"Award badge error: {e}")
        return None


async def _update_streak(student: dict):
    """Updates the student's streak and awards streak badges."""
    from database.students import update_student
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = now.strftime('%Y-%m-%d')
    last_study = student.get('last_study_date')
    current_streak = student.get('current_streak', 0)

    if last_study == today:
        return  # Already studied today, streak unchanged

    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    if last_study == yesterday:
        new_streak = current_streak + 1
    elif last_study is None:
        new_streak = 1
    else:
        new_streak = 1  # Streak broken, restart

    longest = max(student.get('longest_streak', 0), new_streak)

    await update_student(student['id'], {
        'current_streak': new_streak,
        'longest_streak': longest,
        'last_study_date': today,
    })

    # Check streak badge milestones
    badge_map = {7: 'STREAK_7', 14: 'STREAK_14', 30: 'STREAK_30', 60: 'STREAK_60', 100: 'STREAK_100'}

    if new_streak in badge_map:
        await award_badge(student['id'], badge_map[new_streak])

        # Send milestone message
        milestone_messages = {
            7: "🔥 *7-day streak!* One week of consistency. This is how it starts. Keep going!",
            14: "⚡ *14-day streak!* Two weeks straight. You're in the top 20% by consistency.",
            30: "💫 *30-day streak!* One FULL MONTH! Monthly Master badge earned. 🏆",
            60: "💎 *60 days straight!* Diamond Dedication badge earned. Rare. Keep it up.",
            100: "👑 *100 DAYS!* Century Scholar! You are one of the most dedicated students in Nigeria. 🇳🇬",
        }

        if new_streak in milestone_messages:
            from database.client import supabase
            from whatsapp.sender import send_whatsapp_message

            phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

            if phone_result.data:
                phone = phone_result.data[0]['platform_user_id']
                name = student.get('name', 'Student').split()[0]
                msg = milestone_messages[new_streak].replace('!', f', {name}!', 1)
                await send_whatsapp_message(phone, msg)

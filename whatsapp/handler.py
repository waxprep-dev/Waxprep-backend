"""
WhatsApp Message Handler

CRITICAL FIXES IN THIS VERSION:
1. ADMIN ADMIN_MODE is intercepted BEFORE any other check
   so it works even when admin is in student testing mode
2. Groq is now the primary AI (updated model names)
3. Context-aware fallback instead of generic loop message
"""

import json
from fastapi import Request
from config.settings import settings


ONBOARDING_STATES = {
    'new_or_existing', 'wax_id_entry', 'pin_entry', 'name',
    'class_level', 'target_exam', 'subjects', 'exam_date',
    'state', 'language_pref', 'pin_setup', 'pin_confirm'
}


async def handle_whatsapp_webhook(request: Request):
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
                    print(f"❌ Handler error: {e}")
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

    phone = _normalize(raw_phone)

    if message_id:
        await mark_as_read(message_id)

    # Non-text messages
    if message_type == 'image':
        await _handle_image(phone, message_data)
        return

    if message_type in ['voice', 'audio']:
        await _handle_voice(phone, message_data)
        return

    if message_type not in ['text', 'button']:
        return

    message_text = (
        message_data.get('text', {}).get('body', '') or
        message_data.get('button', {}).get('text', '')
    ).strip()

    if not message_text:
        return

    import re
    message_text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', message_text)[:2000]

    print(f"📩 Processing message from: {phone} | Text: {message_text[:60]}")

    # ============================================================
    # STEP 1: ADMIN MODE ESCAPE — intercepts BEFORE any other check
    # ADMIN ADMIN_MODE must ALWAYS work, even in student testing mode
    # This is the fix for the mode switch bug
    # ============================================================
    msg_upper = message_text.strip().upper()

    if msg_upper == 'ADMIN ADMIN_MODE':
        from config.settings import settings as cfg
        from helpers import normalize_phone

        def normalize_for_compare(p):
            return p.replace('+', '').replace(' ', '').replace('-', '')

        admin_num = cfg.ADMIN_WHATSAPP or ''
        if normalize_for_compare(phone) == normalize_for_compare(admin_num):
            try:
                from database.client import redis_client
                redis_client.delete(f"admin_student_mode:{phone}")
            except Exception:
                pass
            await send_whatsapp_message(
                phone,
                "🛠️ *Admin Mode restored.*\n\n"
                "You're back as admin. Type *ADMIN HELP* for commands.\n\n"
                "Type *ADMIN STUDENT_MODE* anytime to test as a student again."
            )
            return

    # ============================================================
    # STEP 2: CHECK IF ADMIN (respects student mode)
    # ============================================================
    from admin.dashboard import is_admin

    if is_admin(phone):
        await _handle_admin_message(phone, message_text)
        return

    # ============================================================
    # STEP 3: GET STUDENT + CONVERSATION
    # ============================================================
    from features.wax_id import student_exists_in_platform

    student = await student_exists_in_platform('whatsapp', phone)

    if student:
        from database.conversations import get_or_create_conversation
        conversation = await get_or_create_conversation(student['id'], 'whatsapp', phone)
    else:
        conversation = await _get_temp_conversation(phone)

    conversation['platform_user_id'] = phone

    raw_state = conversation.get('conversation_state', {})
    state = json.loads(raw_state) if isinstance(raw_state, str) else (raw_state or {})
    awaiting = state.get('awaiting_response_for', '')

    # ============================================================
    # STEP 4: ONBOARDING CHECK
    # ============================================================
    if awaiting in ONBOARDING_STATES:
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message_text)
        return

    if not student:
        from whatsapp.flows.onboarding import handle_new_or_existing
        await handle_new_or_existing(phone, conversation, message_text)
        return

    # ============================================================
    # STEP 5: EXAM MODE (strict — only A/B/C/D allowed)
    # ============================================================
    current_mode = conversation.get('current_mode', 'default')

    if current_mode == 'exam' or awaiting == 'exam_answer':
        await _handle_exam_answer(phone, student, conversation, message_text, state)
        return

    # ============================================================
    # STEP 6: CHECK QUESTION LIMITS
    # ============================================================
    from database.students import can_student_ask_question
    can_ask, limit_msg = await can_student_ask_question(student)

    if not can_ask:
        await send_whatsapp_message(phone, limit_msg)
        return

    # ============================================================
    # STEP 7: SAVE MESSAGE AND PASS TO AI BRAIN
    # ============================================================
    from database.conversations import save_message, get_conversation_history
    await save_message(
        conversation_id=conversation['id'],
        student_id=student['id'],
        platform='whatsapp',
        role='user',
        content=message_text
    )

    history = await get_conversation_history(conversation['id'])

    from ai.brain import process_message_with_ai
    response = await process_message_with_ai(
        message=message_text,
        student=student,
        conversation=conversation,
        conversation_history=history
    )

    await send_whatsapp_message(phone, response)

    await save_message(
        conversation_id=conversation['id'],
        student_id=student['id'],
        platform='whatsapp',
        role='assistant',
        content=response
    )

    from database.students import increment_questions_today
    await increment_questions_today(student['id'])
    await _update_streak(student)

    print(f"✅ Response sent to {phone}")


async def _handle_admin_message(phone: str, message: str):
    """Handles admin messages. Tries direct commands first, then AI."""
    from whatsapp.sender import send_whatsapp_message

    msg_upper = message.strip().upper()

    # Direct ADMIN commands
    if msg_upper.startswith('ADMIN '):
        try:
            from admin.dashboard import handle_admin_command
            await handle_admin_command(phone, message)
            return
        except Exception as e:
            print(f"Admin command error: {e}")
            await send_whatsapp_message(phone, f"Command error: {str(e)[:100]}\n\nType *ADMIN HELP* for commands.")
            return

    # Natural language admin
    try:
        from ai.brain import process_admin_message
        response = await process_admin_message(message, phone)
        await send_whatsapp_message(phone, response)
    except Exception as e:
        print(f"Admin AI error: {e}")
        context = ""
        try:
            from ai.brain import _get_admin_context
            context = await _get_admin_context()
        except Exception:
            pass

        await send_whatsapp_message(
            phone,
            f"{context}\n\n"
            f"Type *ADMIN HELP* for all commands, or *ADMIN STATS* for stats."
        )


async def _handle_exam_answer(phone: str, student: dict, conversation: dict, message: str, state: dict):
    """Handles student answers during mock exam."""
    from whatsapp.sender import send_whatsapp_message

    if any(w in message.upper() for w in ['STOP', 'END', 'QUIT', 'EXIT']):
        from database.conversations import update_conversation_state
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'current_mode': 'default',
            'conversation_state': {},
        })
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Exam ended, {name}. Good practice! 💪\n\nAsk me anything to continue studying."
        )
        return

    answer = message.strip().upper()
    if answer not in ['A', 'B', 'C', 'D']:
        await send_whatsapp_message(
            phone,
            "During the exam, reply with *A*, *B*, *C*, or *D* only.\n_(Type STOP to end)_"
        )
        return

    questions = state.get('all_questions', [])
    question_ids = state.get('questions', [])
    current_idx = state.get('current_question_index', 0)
    answers = state.get('answers', {})
    correct_count = state.get('correct_count', 0)

    current_q = None
    if current_idx < len(questions):
        current_q = questions[current_idx]
    elif current_idx < len(question_ids):
        from database.client import supabase
        q_result = supabase.table('questions').select('*').eq('id', question_ids[current_idx]).execute()
        current_q = q_result.data[0] if q_result.data else None

    total = len(question_ids or questions)

    if not current_q:
        await _complete_exam(phone, student, conversation, state, correct_count, total)
        return

    correct = current_q.get('correct_answer', 'A').upper()
    is_correct = answer == correct
    answers[str(current_idx)] = {
        'answer': answer, 'correct': correct,
        'is_correct': is_correct, 'subject': current_q.get('subject', '')
    }

    if is_correct:
        correct_count += 1

    next_idx = current_idx + 1

    if next_idx >= total:
        state['answers'] = answers
        state['correct_count'] = correct_count
        await _complete_exam(phone, student, conversation, state, correct_count, total)
        return

    next_q = None
    if next_idx < len(questions):
        next_q = questions[next_idx]
    else:
        from database.client import supabase
        q_result = supabase.table('questions').select('*').eq('id', question_ids[next_idx]).execute()
        next_q = q_result.data[0] if q_result.data else None

    from database.conversations import update_conversation_state
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **state,
            'current_question_index': next_idx,
            'answers': answers,
            'correct_count': correct_count,
        }
    })

    if next_q:
        from database.students import increment_questions_today
        await increment_questions_today(student['id'])

        await send_whatsapp_message(
            phone,
            f"*[{next_idx + 1}/{total}]* _{next_q.get('subject', '')}_\n\n"
            f"{next_q.get('question_text', '')}\n\n"
            f"A. {next_q.get('option_a', '')}\n"
            f"B. {next_q.get('option_b', '')}\n"
            f"C. {next_q.get('option_c', '')}\n"
            f"D. {next_q.get('option_d', '')}"
        )
    else:
        await _complete_exam(phone, student, conversation, state, correct_count, total)


async def _complete_exam(phone: str, student: dict, conversation: dict, state: dict, correct: int, total: int):
    """Ends exam and shows results."""
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    from helpers import nigeria_now

    pct = round((correct / total * 100) if total > 0 else 0)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'default',
        'conversation_state': {},
    })

    name = student.get('name', 'Student').split()[0]
    target_exam = student.get('target_exam', 'JAMB')

    msg = f"📝 *Exam Complete, {name}!*\n\nScore: *{correct}/{total}* ({pct}%)\n"

    if total >= 40:
        jamb_equiv = round((correct / total) * 400)
        msg += f"JAMB equivalent: *{jamb_equiv}/400*\n"

    msg += "\n"
    if pct >= 80:
        msg += "Outstanding! You're ready for the real thing. 🏆"
    elif pct >= 60:
        msg += "Good work! A bit more practice and you'll be there. 💪"
    else:
        msg += "Keep going — every practice session makes you stronger. 🔥"

    msg += "\n\nAsk me anything to continue studying."
    await send_whatsapp_message(phone, msg)

    exam_id = state.get('exam_id')
    if exam_id:
        try:
            from database.client import supabase
            supabase.table('mock_exams').update({
                'score': correct, 'percentage': pct,
                'status': 'completed', 'completed_at': nigeria_now().isoformat(),
            }).eq('id', exam_id).execute()
        except Exception:
            pass

    await award_badge(student['id'], 'MOCK_FIRST')


async def _handle_image(phone: str, message_data: dict):
    from whatsapp.sender import send_whatsapp_message
    from features.wax_id import student_exists_in_platform

    student = await student_exists_in_platform('whatsapp', phone)
    if not student:
        await send_whatsapp_message(phone, "Send a message to get started first!")
        return

    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "📸 Image analysis is a Scholar Plan feature!\n\n"
            "Upgrade to Scholar (₦1,500/month) to send photos of textbooks and notes.\n\n"
            "Just ask me 'how do I subscribe?' and I'll help."
        )
        return

    image_id = message_data.get('image', {}).get('id')
    caption = message_data.get('image', {}).get('caption', '')

    if not image_id:
        return

    await send_whatsapp_message(phone, "📸 Got your image! Analyzing... _(~15 seconds)_ 🔍")

    try:
        from ai.openai_client import download_whatsapp_image, analyze_image
        image_b64 = await download_whatsapp_image(image_id)

        if not image_b64:
            await send_whatsapp_message(
                phone,
                "❌ Couldn't download that image. Please try sending it again.\n\n"
                "Or type your question and I'll answer immediately!"
            )
            return

        prompt = f"Student asks: {caption}" if caption else None
        response = await analyze_image(image_base64=image_b64, prompt=prompt, student=student)
        await send_whatsapp_message(phone, response)

        from database.students import increment_questions_today
        await increment_questions_today(student['id'])

    except Exception as e:
        print(f"Image error: {e}")
        await send_whatsapp_message(
            phone,
            "❌ Image analysis failed right now. Please try again, or type your question."
        )

async def _handle_voice(phone: str, message_data: dict):
    from whatsapp.sender import send_whatsapp_message
    from features.wax_id import student_exists_in_platform

    student = await student_exists_in_platform('whatsapp', phone)
    if not student:
        await send_whatsapp_message(phone, "Send a message to get started first!")
        return

    audio_id = (message_data.get('audio', {}) or message_data.get('voice', {})).get('id')
    if not audio_id:
        return

    await send_whatsapp_message(phone, "🎙️ Listening to your voice note...")

    try:
        from ai.openai_client import transcribe_voice_note
        transcribed = await transcribe_voice_note(audio_id)

        if not transcribed:
            await send_whatsapp_message(
                phone,
                "❌ Couldn't understand that clearly.\n\nPlease type your question."
            )
            return

        # Show what was heard, then process it through STUDENT brain only
        # Never route voice transcriptions through admin — even if phone matches admin number
        await send_whatsapp_message(phone, f"🎙️ I heard: _{transcribed}_\n\nLet me help...")

        # Process as student message — bypass admin check entirely for voice
        from database.conversations import get_or_create_conversation, get_conversation_history, save_message
        from ai.brain import process_message_with_ai, get_student_deep_context

        conversation = await get_or_create_conversation(student['id'], 'whatsapp', phone)
        conversation['platform_user_id'] = phone
        history = await get_conversation_history(conversation['id'])
        deep_context = await get_student_deep_context(student)

        response = await process_message_with_ai(
            message=transcribed,
            student=student,
            conversation=conversation,
            conversation_history=history
        )

        await send_whatsapp_message(phone, response)
        await save_message(
            conversation_id=conversation['id'],
            student_id=student['id'],
            platform='whatsapp',
            role='assistant',
            content=response
        )

    except Exception as e:
        print(f"Voice error: {e}")
        await send_whatsapp_message(phone, "Voice note failed. Please type your question.")

async def _handle_voice(phone: str, message_data: dict):
    from whatsapp.sender import send_whatsapp_message
    from features.wax_id import student_exists_in_platform

    student = await student_exists_in_platform('whatsapp', phone)
    if not student:
        await send_whatsapp_message(phone, "Send a message to get started first!")
        return

    audio_id = (message_data.get('audio', {}) or message_data.get('voice', {})).get('id')
    if not audio_id:
        return

    await send_whatsapp_message(phone, "🎙️ Listening to your voice note...")

    try:
        from ai.openai_client import transcribe_voice_note
        transcribed = await transcribe_voice_note(audio_id)

        if not transcribed:
            await send_whatsapp_message(
                phone,
                "❌ Couldn't understand that voice note.\n\n"
                "Please speak clearly, or type your question."
            )
            return

        await send_whatsapp_message(phone, f"🎙️ I heard: _{transcribed}_\n\nLet me help...")

        fake_data = {'id': audio_id, 'from': phone, 'type': 'text', 'text': {'body': transcribed}}
        await process_single_message(fake_data, {})

    except Exception as e:
        print(f"Voice error: {e}")
        await send_whatsapp_message(phone, "Voice note failed. Please type your question.")


async def _get_temp_conversation(phone: str) -> dict:
    from database.client import supabase, redis_client

    cache_key = f"conv:whatsapp:{phone}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            result['platform_user_id'] = phone
            return result
    except Exception:
        pass

    try:
        existing = supabase.table('conversations').select('*')\
            .eq('platform', 'whatsapp').eq('platform_user_id', phone).execute()

        if existing.data:
            conv = existing.data[0]
        else:
            insert = supabase.table('conversations').insert({
                'platform': 'whatsapp',
                'platform_user_id': phone,
                'current_mode': 'onboarding',
                'conversation_state': {'awaiting_response_for': 'new_or_existing'},
            }).execute()
            conv = insert.data[0] if insert.data else {
                'id': f'temp_{phone}',
                'conversation_state': {'awaiting_response_for': 'new_or_existing'},
                'current_mode': 'onboarding'
            }

        try:
            redis_client.setex(cache_key, 7200, json.dumps(conv, default=str))
        except Exception:
            pass

        conv['platform_user_id'] = phone
        return conv

    except Exception as e:
        print(f"Temp conversation error: {e}")
        return {
            'id': f'temp_{phone}',
            'conversation_state': {'awaiting_response_for': 'new_or_existing'},
            'current_mode': 'onboarding',
            'platform_user_id': phone
        }


def _normalize(phone: str) -> str:
    phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    if phone.startswith('0') and len(phone) == 11:
        phone = '234' + phone[1:]
    elif not phone.startswith('234') and len(phone) == 10:
        phone = '234' + phone
    return phone


async def award_badge(student_id: str, badge_code: str) -> dict | None:
    from database.client import supabase
    try:
        badge = supabase.table('badges').select('*').eq('badge_code', badge_code).execute()
        if not badge.data:
            return None
        b = badge.data[0]
        existing = supabase.table('student_badges').select('id')\
            .eq('student_id', student_id).eq('badge_id', b['id']).execute()
        if existing.data:
            return None
        supabase.table('student_badges').insert({'student_id': student_id, 'badge_id': b['id']}).execute()
        supabase.rpc('add_points_to_student', {
            'student_id_param': student_id, 'points_to_add': b.get('points_awarded', 50)
        }).execute()
        return b
    except Exception:
        return None


async def _update_streak(student: dict):
    from database.students import update_student
    from helpers import nigeria_today
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = nigeria_today()
    last = student.get('last_study_date')
    streak = student.get('current_streak', 0)

    if last == today:
        return

    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    new_streak = (streak + 1) if last == yesterday else 1
    longest = max(student.get('longest_streak', 0), new_streak)

    await update_student(student['id'], {
        'current_streak': new_streak,
        'longest_streak': longest,
        'last_study_date': today,
    })

    if new_streak in {7, 14, 30, 60, 100}:
        await award_badge(student['id'], f'STREAK_{new_streak}')

        milestone_msgs = {
            7: "🔥 7-day streak! You're building a real habit now.",
            14: "⚡ 14 days straight! Top 20% by consistency.",
            30: "💫 ONE MONTH! Monthly Master badge earned. 🏆",
            60: "💎 60 days! Diamond Dedication achieved.",
            100: "👑 100 DAYS! You're a legend.",
        }

        if new_streak in milestone_msgs:
            try:
                from database.client import supabase
                from whatsapp.sender import send_whatsapp_message
                phone_r = supabase.table('platform_sessions').select('platform_user_id')\
                    .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()
                if phone_r.data:
                    name = student.get('name', 'Student').split()[0]
                    msg = milestone_msgs[new_streak].replace('!', f', {name}!', 1)
                    await send_whatsapp_message(phone_r.data[0]['platform_user_id'], msg)
            except Exception:
                pass

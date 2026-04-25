"""
WhatsApp Message Handler — Speed-Optimized

Architecture:
- Cache-first for everything
- Parallel async where possible  
- Hard commands routed instantly
- Everything else goes to AI brain
- Background tasks for non-critical updates

Target: Under 2 seconds total response time.
"""

import asyncio
import random
from config.settings import settings
from helpers import nigeria_today, get_time_of_day, sanitize_input


def _get_state(conversation: dict) -> dict:
    import json
    raw = conversation.get('conversation_state', {})
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


async def process_single_message(message_data: dict, value: dict) -> None:
    from whatsapp.sender import send_whatsapp_message

    phone = message_data.get('from', '')
    message_id = message_data.get('id', '')

    # Check deduplication FIRST — WhatsApp retries webhooks 3-4x
    from database.cache import is_message_processed
    if message_id and is_message_processed(message_id):
        print(f"Duplicate message {message_id} — skipped")
        return

    name = "Student"
    contacts = value.get('contacts', [])
    if contacts:
        name = contacts[0].get('profile', {}).get('name', 'Student')

    message_type = message_data.get('type', 'text')
    media_id = None
    message = ""

    if message_type == 'text':
        message = message_data.get('text', {}).get('body', '')
    elif message_type == 'image':
        image_data = message_data.get('image', {})
        message = image_data.get('caption', '')
        media_id = image_data.get('id', '')
    elif message_type in ['voice', 'audio']:
        audio_data = message_data.get('audio', message_data.get('voice', {}))
        media_id = audio_data.get('id', '')
        message = ''
    elif message_type == 'button':
        message = message_data.get('button', {}).get('text', '')
    elif message_type == 'interactive':
        interactive = message_data.get('interactive', {})
        if 'button_reply' in interactive:
            message = interactive['button_reply'].get('title', '')
        elif 'list_reply' in interactive:
            message = interactive['list_reply'].get('title', '')
    else:
        message = message_data.get('text', {}).get('body', '')

    if not phone:
        return

    if not message and message_type not in ['image', 'voice', 'audio']:
        return

    message = sanitize_input(message) if message else message

    try:
        # Mark as read in background — don't wait for it
        if message_id:
            asyncio.ensure_future(_mark_read(message_id))

        await route_message(
            phone=phone,
            name=name,
            message=message,
            message_type=message_type,
            media_id=media_id
        )

    except Exception as e:
        print(f"Error in process_single_message: {e}")
        import traceback
        traceback.print_exc()
        try:
            await send_whatsapp_message(phone, "Sorry, something went wrong on my end. Please try again!")
        except Exception:
            pass


async def _mark_read(message_id: str):
    try:
        from whatsapp.sender import mark_as_read
        await mark_as_read(message_id)
    except Exception:
        pass


async def route_message(phone: str, name: str, message: str,
                         message_type: str = 'text', media_id: str = None) -> None:
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_by_phone
    from database.conversations import get_or_create_conversation
    from admin.dashboard import is_admin, handle_admin_command

    msg_upper = message.strip().upper() if message else ''

    # 1. Admin commands — instant
    if is_admin(phone) and msg_upper.startswith('ADMIN '):
        await handle_admin_command(phone, message)
        return

    # 2. Load student from cache (fast) or DB — do this in parallel with conversation
    student_task = asyncio.ensure_future(get_student_by_phone(phone))
    student = await student_task

    if student and student.get('is_banned'):
        await send_whatsapp_message(phone, "Your account has been suspended. Contact support.")
        return

    student_id = student['id'] if student else 'anonymous'
    conversation = await get_or_create_conversation(
        student_id=student_id,
        platform='whatsapp',
        platform_user_id=phone
    )

    # 3. Unregistered users → onboarding
    if not student:
        from whatsapp.flows.onboarding import handle_new_or_existing, handle_onboarding_response

        state = _get_state(conversation)
        awaiting = state.get('awaiting_response_for', '')

        onboarding_steps = {
            'new_or_existing', 'terms_acceptance', 'wax_id_entry', 'pin_entry',
            'name', 'class_level', 'target_exam', 'subjects', 'exam_date',
            'state', 'language_pref', 'pin_setup', 'pin_confirm'
        }

        if awaiting in onboarding_steps:
            await handle_onboarding_response(phone, conversation, message)
        else:
            await handle_new_or_existing(phone, conversation, message)
        return

    conv_state = _get_state(conversation)
    today = nigeria_today()

    # Reset daily session counter
    if conv_state.get('session_date', '') != today:
        conv_state['session_questions'] = 0
        conv_state['session_correct'] = 0
        conv_state['session_date'] = today

    awaiting = conv_state.get('awaiting_response_for', '')
    current_mode = conversation.get('current_mode', 'default')

    # 4. Remaining onboarding (if student got registered mid-flow)
    onboarding_steps = {
        'new_or_existing', 'terms_acceptance', 'wax_id_entry', 'pin_entry',
        'name', 'class_level', 'target_exam', 'subjects', 'exam_date',
        'state', 'language_pref', 'pin_setup', 'pin_confirm'
    }
    if awaiting in onboarding_steps:
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message)
        return

    # 5. Media handling
    if message_type == 'image':
        await _handle_image(phone, student, media_id, message)
        return

    if message_type in ['voice', 'audio']:
        await _handle_voice(phone, student)
        return

    # 6. Bug/Suggestion
    if msg_upper.startswith('BUG ') or msg_upper == 'BUG':
        from features.feedback import handle_bug_report
        response = await handle_bug_report(phone, student, message)
        await send_whatsapp_message(phone, response)
        return

    if msg_upper.startswith('SUGGEST ') or msg_upper == 'SUGGEST':
        from features.feedback import handle_suggestion
        response = await handle_suggestion(phone, student, message)
        await send_whatsapp_message(phone, response)
        return

    # 7. Explicit account commands
    ACCOUNT_COMMANDS = {
        'PROGRESS', 'MYID', 'STREAK', 'BALANCE', 'BADGES',
        'REFERRAL', 'PLAN', 'PAUSE', 'CONTINUE', 'STOP', 'HELP', 'MODES'
    }
    first_word = msg_upper.split()[0] if msg_upper else ''

    if first_word in ACCOUNT_COMMANDS:
        from whatsapp.flows.commands import handle_command
        await handle_command(phone, student, conversation, message, first_word)
        return

    # 8. PAYG
    if first_word == 'PAYG':
        from whatsapp.flows.commands import handle_payg
        await handle_payg(phone, student, conversation, message)
        return

    # 9. PROMO / CODE
    if first_word in ('PROMO', 'CODE'):
        from whatsapp.flows.commands import handle_promo_code
        await handle_promo_code(phone, student, conversation, message)
        return

    # 10. SUBSCRIBE and plan keywords
    if first_word == 'SUBSCRIBE':
        from whatsapp.flows.subscription import handle_subscription_flow
        await handle_subscription_flow(phone, student, conversation, message)
        return

    PLAN_KEYWORDS = [
        'SCHOLAR MONTHLY', 'SCHOLAR YEARLY', 'PRO MONTHLY',
        'PRO YEARLY', 'ELITE MONTHLY', 'ELITE YEARLY'
    ]
    if any(kw in msg_upper for kw in PLAN_KEYWORDS):
        from whatsapp.flows.subscription import handle_subscription_flow
        await handle_subscription_flow(phone, student, conversation, message)
        return

    # 11. Subscription promo code during checkout
    if awaiting == 'subscription_promo_code':
        from whatsapp.flows.subscription import handle_promo_code_during_checkout
        await handle_promo_code_during_checkout(phone, student, conversation, message, conv_state)
        return

    # 12. Mock exam mode
    if current_mode == 'exam' or awaiting == 'exam_answer':
        from whatsapp.flows.mock_exam import handle_exam_answer
        await handle_exam_answer(phone, student, conversation, message)
        return

    if msg_upper == 'EXAM' or msg_upper.startswith('EXAM '):
        from whatsapp.flows.mock_exam import start_mock_exam
        await start_mock_exam(phone, student, conversation)
        return

    if awaiting == 'exam_setup_choice':
        from whatsapp.flows.mock_exam import handle_exam_setup_choice
        await handle_exam_setup_choice(phone, student, conversation, message, conv_state)
        return

    # 13. Quiz answer evaluation
    if awaiting == 'quiz_answer':
        await _evaluate_quiz_answer(phone, student, conversation, message, conv_state)
        return

    # 14. Daily challenge
    if msg_upper in ['CHALLENGE', 'DAILY CHALLENGE']:
        from whatsapp.flows.study import handle_daily_challenge
        await handle_daily_challenge(phone, student, conversation)
        return

    if awaiting == 'challenge_answer':
        from whatsapp.flows.study import handle_challenge_answer
        await handle_challenge_answer(phone, student, conversation, message, conv_state)
        return

    # 15. EVERYTHING ELSE → AI Brain
    await _think_and_respond(phone, student, conversation, message, conv_state)


async def _think_and_respond(phone: str, student: dict, conversation: dict,
                              message: str, conv_state: dict) -> None:
    """
    The main AI interaction handler.
    Loads full student context, calls the AI brain, handles the response.
    """
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import get_conversation_history, update_conversation_state, save_message
    from database.students import can_student_ask_question, increment_questions_today
    from database.client import supabase
    from ai.brain import think
    from ai.context_manager import get_full_student_context
    from features.quiz_engine import extract_subject_from_message

    msg_lower = message.lower()
    academic_indicators = [
        'what', 'how', 'why', 'explain', 'quiz', 'test', 'question',
        'define', 'calculate', 'solve', 'biology', 'physics', 'chemistry',
        'math', 'english', 'economics', 'government', 'study', 'learn',
        'forgot', 'remind', 'confused', 'understand', 'practice', 'example',
        'formula', 'equation', 'describe', 'differentiate', 'between', 'meaning',
    ]
    is_probably_academic = any(w in msg_lower for w in academic_indicators)

    if is_probably_academic:
        can_ask, limit_msg = await can_student_ask_question(student)
        if not can_ask:
            await send_whatsapp_message(phone, limit_msg)
            return

    # Parallel: get history and context at the same time
    history_task = asyncio.ensure_future(get_conversation_history(conversation['id']))
    context_task = asyncio.ensure_future(get_full_student_context(student))

    history, context = await asyncio.gather(history_task, context_task)
    recent_subject = conversation.get('current_subject')

    # Save student message in background
    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'user', message
    ))

    # Call AI brain
    response_text, question_data = await think(
        message=message,
        student=student,
        conversation_history=history,
        recent_subject=recent_subject,
        context=context,
    )

    # Send response
    await send_whatsapp_message(phone, response_text)

    # Save AI response in background
    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'assistant', response_text
    ))

    # If AI generated a quiz question, set awaiting state
    if question_data:
        today = nigeria_today()
        new_state = {
            **conv_state,
            'awaiting_response_for': 'quiz_answer',
            'current_question': question_data,
            'session_date': today,
        }
        subject = question_data.get('subject', recent_subject or '')
        topic = question_data.get('topic', '')

        await update_conversation_state(
            conversation['id'], 'whatsapp', phone,
            {
                'conversation_state': new_state,
                'current_mode': 'quiz',
                'current_subject': subject,
                'current_topic': topic,
            }
        )

        if is_probably_academic:
            asyncio.ensure_future(increment_questions_today(student['id']))
            asyncio.ensure_future(_update_stats(student, phone, conv_state))

    elif is_probably_academic:
        asyncio.ensure_future(increment_questions_today(student['id']))
        asyncio.ensure_future(_update_stats(student, phone, conv_state))

        detected_subject = extract_subject_from_message(message)
        if detected_subject:
            asyncio.ensure_future(update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {'current_subject': detected_subject}
            ))


async def _evaluate_quiz_answer(phone: str, student: dict, conversation: dict,
                                 message: str, conv_state: dict) -> None:
    """Evaluates a student's A/B/C/D answer to a quiz question."""
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state, save_message
    from database.students import increment_questions_today
    from database.client import supabase
    from features.quiz_engine import evaluate_quiz_answer, calculate_and_award_points
    from features.badges import check_and_award_milestone_badges
    from ai.adaptive_engine import record_interaction_outcome
    from features.question_validator import evaluate_question_quality
    from database.questions import update_question_stats
    from helpers import nigeria_today

    current_question = conv_state.get('current_question')

    if not current_question:
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {**conv_state, 'awaiting_response_for': None}
        })
        await _think_and_respond(phone, student, conversation, message, conv_state)
        return

    is_correct, feedback = evaluate_quiz_answer(
        message.strip(),
        current_question.get('correct', current_question.get('correct_answer', 'A')),
        {
            'question_text': current_question.get('question', current_question.get('question_text', '')),
            'option_a': current_question.get('a', current_question.get('option_a', '')),
            'option_b': current_question.get('b', current_question.get('option_b', '')),
            'option_c': current_question.get('c', current_question.get('option_c', '')),
            'option_d': current_question.get('d', current_question.get('option_d', '')),
            'correct_answer': current_question.get('correct', current_question.get('correct_answer', 'A')),
            'explanation_correct': current_question.get('explanation', current_question.get('explanation_correct', '')),
            'explanation_a': '', 'explanation_b': '', 'explanation_c': '', 'explanation_d': '',
        }
    )

    if is_correct is None:
        await send_whatsapp_message(phone, feedback)
        return

    subject = current_question.get('subject', conversation.get('current_subject', ''))
    topic = current_question.get('topic', conversation.get('current_topic', ''))
    difficulty = current_question.get('difficulty_level', 5)

    # Update mastery and question stats in background
    asyncio.ensure_future(record_interaction_outcome(
        student['id'], subject, topic, difficulty, is_correct
    ))

    if current_question.get('id'):
        asyncio.ensure_future(update_question_stats(current_question['id'], is_correct))
        asyncio.ensure_future(evaluate_question_quality(current_question['id']))

    if is_correct:
        try:
            supabase.table('students').update({
                'total_questions_correct': student.get('total_questions_correct', 0) + 1
            }).eq('id', student['id']).execute()
        except Exception:
            pass

    points, _ = await calculate_and_award_points(
        student_id=student['id'],
        is_correct=is_correct,
        question_difficulty=difficulty
    )

    new_total = student.get('total_questions_answered', 0) + 1
    badges = await check_and_award_milestone_badges(student['id'], new_total)

    full_feedback = feedback + f"\n\n+{points} point{'s' if points != 1 else ''}!"
    for badge in badges:
        full_feedback += f"\n\nNew Badge: *{badge['name']}*!\n{badge['description']}"

    session_q = conv_state.get('session_questions', 0) + 1
    session_correct = conv_state.get('session_correct', 0) + (1 if is_correct else 0)

    if session_q % 5 == 0:
        accuracy = round((session_correct / session_q) * 100)
        full_feedback += f"\n\n_{session_q} questions this session | {accuracy}% accuracy_"

    name = student.get('name', 'Student').split()[0]
    continuations = [
        "\n\nAnother one?",
        f"\n\nReady for the next one, {name}?",
        "\n\nWant to continue or switch topics?",
        "\n\nShall we keep going?",
        f"\n\nGood session, {name}. Next question?",
    ]
    full_feedback += random.choice(continuations)

    await send_whatsapp_message(phone, full_feedback)

    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'assistant', full_feedback
    ))

    today = nigeria_today()
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **conv_state,
            'awaiting_response_for': 'quiz_continue',
            'current_question': None,
            'session_questions': session_q,
            'session_correct': session_correct,
            'session_date': today,
        }
    })

    asyncio.ensure_future(increment_questions_today(student['id']))
    asyncio.ensure_future(_update_stats(student, phone, conv_state))


async def _update_stats(student: dict, phone: str, conv_state: dict) -> None:
    """Updates total questions answered, streak, and checks level up."""
    from database.client import supabase
    from helpers import nigeria_today
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    try:
        supabase.table('students').update({
            'total_questions_answered': student.get('total_questions_answered', 0) + 1
        }).eq('id', student['id']).execute()
    except Exception:
        pass

    try:
        today = nigeria_today()
        yesterday = (datetime.now(ZoneInfo("Africa/Lagos")) - timedelta(days=1)).strftime('%Y-%m-%d')
        fresh = supabase.table('students').select('last_study_date, current_streak, longest_streak')\
            .eq('id', student['id']).execute()

        if fresh.data:
            s = fresh.data[0]
            last_date = s.get('last_study_date')
            current_streak = s.get('current_streak', 0)
            longest_streak = s.get('longest_streak', 0)
            updates = {}
            new_streak = current_streak

            if last_date == today:
                pass
            elif last_date == yesterday:
                new_streak = current_streak + 1
                updates = {
                    'current_streak': new_streak,
                    'longest_streak': max(longest_streak, new_streak),
                    'last_study_date': today
                }
            else:
                new_streak = 1
                updates = {'current_streak': 1, 'last_study_date': today}

            if updates:
                supabase.table('students').update(updates).eq('id', student['id']).execute()

            streak_milestones = {3, 7, 14, 30, 60, 100}
            if new_streak in streak_milestones and last_date != today:
                try:
                    from features.badges import check_streak_badges
                    from whatsapp.sender import send_whatsapp_message
                    new_badges = await check_streak_badges(student['id'], new_streak)
                    for badge in new_badges:
                        await send_whatsapp_message(
                            phone,
                            f"*{new_streak}-Day Streak Badge!*\n\n"
                            f"*{badge['name']}* — {badge['description']}\n\nKeep going!"
                        )
                except Exception:
                    pass
    except Exception:
        pass

    try:
        await _check_level(student['id'], phone)
    except Exception:
        pass


async def _check_level(student_id: str, phone: str):
    from database.client import supabase
    from config.settings import settings
    from whatsapp.sender import send_whatsapp_message

    result = supabase.table('students').select('total_points, current_level, name')\
        .eq('id', student_id).execute()
    if not result.data:
        return

    s = result.data[0]
    points = s.get('total_points', 0)
    current_level = s.get('current_level', 1)
    new_level = 1

    for level, threshold in sorted(settings.LEVEL_THRESHOLDS.items()):
        if points >= threshold:
            new_level = level

    if new_level > current_level:
        new_level_name = settings.get_level_name(new_level)
        supabase.table('students').update({
            'current_level': new_level,
            'level_name': new_level_name,
        }).eq('id', student_id).execute()
        name = s.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Level Up, *{name}*!\n\n"
            f"You reached Level {new_level} — *{new_level_name}*!\n\n"
            f"{points:,} total points. Keep going!"
        )


async def _handle_image(phone: str, student: dict, media_id: str, caption: str):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "Image analysis is a Scholar Plan feature.\n\n"
            "Upgrade for N1,500/month to send textbook photos and get them explained instantly.\n\n"
            "Type *SUBSCRIBE* to upgrade."
        )
        return

    if not settings.OPENAI_API_KEY:
        await send_whatsapp_message(phone, "Image analysis is temporarily unavailable. Type your question instead.")
        return

    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(phone, f"Got your image, {name}! Reading it now...")

    try:
        from ai.openai_client import download_whatsapp_image, analyze_image
        image_b64 = await download_whatsapp_image(media_id)
        if not image_b64:
            await send_whatsapp_message(phone, "Could not download that image. Please try again.")
            return
        result = await analyze_image(image_base64=image_b64, prompt=caption or None, student=student)
        await send_whatsapp_message(phone, result)
    except Exception as e:
        print(f"Image analysis error: {e}")
        await send_whatsapp_message(
            phone,
            "Had trouble reading that image. Try taking a clearer photo, or type your question instead."
        )


async def _handle_voice(phone: str, student: dict):
    from whatsapp.sender import send_whatsapp_message
    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(
        phone,
        f"Got your voice note, {name}!\n\n"
        "Voice transcription is coming very soon. For now, type your question and I'll answer immediately."
    )

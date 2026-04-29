"""
WhatsApp Message Handler — Teaching-First Architecture

The new philosophy:
Almost everything goes to the AI brain (Wax).
Code only intercepts for: onboarding, media, payment commands, admin.
Wax handles the rest naturally as a teacher would.

Target: Under 2 seconds total response time.
"""

import asyncio
import re
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
    from database.cache import is_message_processed

    phone = message_data.get('from', '')
    message_id = message_data.get('id', '')

    # Deduplication — WhatsApp retries webhooks multiple times
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

    if message:
        message = sanitize_input(message)

    try:
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

    # 1. Admin commands — instant, bypass everything
    if is_admin(phone) and msg_upper.startswith('ADMIN '):
        await handle_admin_command(phone, message)
        return

    # 2. Load student
    student = await get_student_by_phone(phone)

    if student and student.get('is_banned'):
        await send_whatsapp_message(phone, "Your account has been suspended. Contact support.")
        return

    student_id = student['id'] if student else 'anonymous'
    conversation = await get_or_create_conversation(
        student_id=student_id,
        platform='whatsapp',
        platform_user_id=phone
    )

    conv_state = _get_state(conversation)

    # 3. No student — onboarding
    if not student:
        from whatsapp.flows.onboarding import handle_new_or_existing, handle_onboarding_response
        from ai.classifier import ONBOARDING_STATES

        awaiting = conv_state.get('awaiting_response_for', '')
        if awaiting in ONBOARDING_STATES:
            await handle_onboarding_response(phone, conversation, message)
        else:
            await handle_new_or_existing(phone, conversation, message)
        return

    # 4. Remaining onboarding steps if student registered mid-flow
    from ai.classifier import ONBOARDING_STATES
    awaiting = conv_state.get('awaiting_response_for', '')

    if awaiting in ONBOARDING_STATES:
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message)
        return

    # 5. Bug and suggestion reports (keep as hard triggers, these need DB writes)
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

    # 6. Image handling
    if message_type == 'image':
        await _handle_image(phone, student, media_id, message)
        return

    # 7. Voice note handling — transcribe then treat as text
    if message_type in ['voice', 'audio']:
        await _handle_voice(phone, student, conversation, media_id, conv_state)
        return

    # 8. Hard-coded command triggers (minimal set)
    from ai.classifier import classify_hard_trigger

    trigger = classify_hard_trigger(message, conv_state)

    if trigger == 'ONBOARDING':
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message)
        return

    if trigger == 'SUBSCRIPTION_PROMO':
        from whatsapp.flows.subscription import handle_promo_code_during_checkout
        await handle_promo_code_during_checkout(phone, student, conversation, message, conv_state)
        return

    if trigger == 'SUBSCRIBE':
        from whatsapp.flows.subscription import handle_subscription_flow
        await handle_subscription_flow(phone, student, conversation, message)
        return

    if trigger == 'MYID':
        await _send_wax_id(phone, student)
        return

    if trigger == 'PAYG':
        from whatsapp.flows.commands import handle_payg
        await handle_payg(phone, student, conversation, message)
        return

    if trigger == 'PROMO':
        from whatsapp.flows.commands import handle_promo_code
        await handle_promo_code(phone, student, conversation, message)
        return

    # 9. Check if student is answering a quiz question
    from ai.classifier import looks_like_quiz_answer

    current_question = conv_state.get('current_question')
    if current_question and looks_like_quiz_answer(message):
        await _evaluate_and_respond(phone, student, conversation, message, conv_state)
        return

    # 10. Everything else goes to the AI brain
    await _think_and_respond(phone, student, conversation, message, conv_state)


async def _send_wax_id(phone: str, student: dict):
    from whatsapp.sender import send_whatsapp_message
    wax_id = student.get('wax_id', 'Unknown')
    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(
        phone,
        f"Your WAX ID, {name}\n\n"
        f"*{wax_id}*\n\n"
        "Keep this safe. It is your permanent identity on WaxPrep.\n"
        "Use it to log in on any device.\n\n"
        "_Never share your PIN with anyone._"
    )


async def _think_and_respond(phone: str, student: dict, conversation: dict,
                              message: str, conv_state: dict) -> None:
    """
    The main AI interaction. Loads context, calls brain, handles response.
    This is where almost everything ends up.
    """
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import (
        get_conversation_history, update_conversation_state, save_message
    )
    from database.students import can_student_ask_question, increment_questions_today
    from ai.brain import think, extract_question_data
    from ai.context_manager import get_full_student_context
    from features.quiz_engine import extract_subject_from_message
    from helpers import nigeria_today

    # Check if this looks like it will consume an AI turn
    # We check usage limits before spending on AI
    can_ask, limit_msg = await can_student_ask_question(student)
    if not can_ask:
        await send_whatsapp_message(phone, limit_msg)
        return

    today = nigeria_today()
    # Reset session counters daily
    if conv_state.get('session_date', '') != today:
        conv_state['session_questions'] = 0
        conv_state['session_correct'] = 0
        conv_state['session_date'] = today

    # Parallel: load history and context simultaneously
    history_task = asyncio.ensure_future(
        get_conversation_history(conversation['id'])
    )
    context_task = asyncio.ensure_future(
        get_full_student_context(student)
    )
    history, context = await asyncio.gather(history_task, context_task)

    recent_subject = conversation.get('current_subject')

    # Save student message in background
    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'user', message
    ))

    # Call the AI brain
    response_text, question_data = await think(
        message=message,
        student=student,
        conversation_history=history,
        recent_subject=recent_subject,
        context=context,
    )

    # Send response to student
    await send_whatsapp_message(phone, response_text)

    # Save AI response in background
    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'assistant', response_text
    ))

    # Track usage
    asyncio.ensure_future(increment_questions_today(student['id']))
    asyncio.ensure_future(_update_stats(student, phone, conv_state))

    # If AI generated a quiz question, save it to conversation state
    if question_data:
        new_state = {
            **conv_state,
            'current_question': question_data,
            'session_date': today,
        }
        subject = question_data.get('subject', recent_subject or '')
        topic = question_data.get('topic', '')

        await update_conversation_state(
            conversation['id'], 'whatsapp', phone,
            {
                'conversation_state': new_state,
                'current_subject': subject,
                'current_topic': topic,
            }
        )
    else:
        # Detect subject from message and update conversation context
        detected_subject = extract_subject_from_message(message)
        if detected_subject:
            asyncio.ensure_future(update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {'current_subject': detected_subject}
            ))
        # Clear any pending question if student moved on
        if conv_state.get('current_question'):
            new_state = {**conv_state, 'current_question': None}
            asyncio.ensure_future(update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {'conversation_state': new_state}
            ))


async def _evaluate_and_respond(phone: str, student: dict, conversation: dict,
                                  message: str, conv_state: dict) -> None:
    """
    Student answered a quiz question.

    Step 1: Use the existing evaluation logic silently to get is_correct,
    update Elo/mastery scores, award points.

    Step 2: Pass the evaluation result to the AI brain as context.
    Wax writes the natural response — not a template.
    """
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import (
        update_conversation_state, save_message, get_conversation_history
    )
    from database.students import increment_questions_today
    from database.client import supabase
    from features.quiz_engine import (
        evaluate_quiz_answer, calculate_and_award_points
    )
    from features.badges import check_and_award_milestone_badges
    from ai.adaptive_engine import record_interaction_outcome
    from features.question_validator import evaluate_question_quality
    from database.questions import update_question_stats
    from ai.brain import think
    from ai.context_manager import get_full_student_context
    from helpers import nigeria_today

    current_question = conv_state.get('current_question', {})

    # Parse the question data — it may come from AI brain (uses short keys)
    # or from the database (uses long keys). Handle both.
    q_text = current_question.get('question', current_question.get('question_text', ''))
    opt_a = current_question.get('a', current_question.get('option_a', ''))
    opt_b = current_question.get('b', current_question.get('option_b', ''))
    opt_c = current_question.get('c', current_question.get('option_c', ''))
    opt_d = current_question.get('d', current_question.get('option_d', ''))
    correct_answer = current_question.get('correct', current_question.get('correct_answer', 'A'))
    explanation = current_question.get('explanation', current_question.get('explanation_correct', ''))
    subject = current_question.get('subject', conversation.get('current_subject', ''))
    topic = current_question.get('topic', conversation.get('current_topic', ''))
    difficulty = current_question.get('difficulty_level', 5)

    question_for_eval = {
        'question_text': q_text,
        'option_a': opt_a,
        'option_b': opt_b,
        'option_c': opt_c,
        'option_d': opt_d,
        'correct_answer': correct_answer,
        'explanation_correct': explanation,
        'explanation_a': '', 'explanation_b': '',
        'explanation_c': '', 'explanation_d': '',
    }

    # Silent evaluation — get is_correct without sending any response yet
    is_correct, _ = evaluate_quiz_answer(message.strip(), correct_answer, question_for_eval)

    if is_correct is None:
        # Could not parse the answer
        await send_whatsapp_message(
            phone,
            "Reply with just *A*, *B*, *C*, or *D* to answer."
        )
        return

    # Update mastery/Elo in background
    asyncio.ensure_future(record_interaction_outcome(
        student['id'], subject, topic, difficulty, is_correct
    ))

    # Update question quality stats in background
    if current_question.get('id'):
        asyncio.ensure_future(update_question_stats(current_question['id'], is_correct))
        asyncio.ensure_future(evaluate_question_quality(current_question['id']))

    # Update correct count
    if is_correct:
        try:
            supabase.table('students').update({
                'total_questions_correct': student.get('total_questions_correct', 0) + 1
            }).eq('id', student['id']).execute()
        except Exception:
            pass

    # Award points
    points, _ = await calculate_and_award_points(
        student_id=student['id'],
        is_correct=is_correct,
        question_difficulty=difficulty
    )

    # Check milestone badges
    new_total = student.get('total_questions_answered', 0) + 1
    badges = await check_and_award_milestone_badges(student['id'], new_total)

    # Get context for AI response
    history_task = asyncio.ensure_future(get_conversation_history(conversation['id']))
    context_task = asyncio.ensure_future(get_full_student_context(student))
    history, context = await asyncio.gather(history_task, context_task)

    # Parse what the student actually answered
    student_answer_clean = message.strip().upper()
    if student_answer_clean and student_answer_clean[0] in 'ABCD':
        student_answer_letter = student_answer_clean[0]
    else:
        student_answer_letter = student_answer_clean

    # Build the option text for the correct answer
    option_map = {'A': opt_a, 'B': opt_b, 'C': opt_c, 'D': opt_d}
    correct_option_text = option_map.get(correct_answer.upper(), '')

    # Build quiz context for the AI brain
    quiz_ctx = {
        'question': q_text,
        'student_answer': f"{student_answer_letter}. {option_map.get(student_answer_letter, message)}",
        'is_correct': is_correct,
        'correct_answer': f"{correct_answer}. {correct_option_text}",
        'explanation': explanation,
        'subject': subject,
        'topic': topic,
    }

    # Points and badge info to weave into context
    extra_info = f"\n\n(The student earned {points} points for this answer."
    if badges:
        badge_names = ', '.join([b['name'] for b in badges])
        extra_info += f" They just earned a badge: {badge_names}."
    extra_info += " Mention the points and badge naturally if it fits the flow.)"

    # Let Wax write the natural evaluation response
    response_text, new_question_data = await think(
        message=message + extra_info,
        student=student,
        conversation_history=history,
        recent_subject=conversation.get('current_subject'),
        context=context,
        quiz_context=quiz_ctx,
    )

    await send_whatsapp_message(phone, response_text)

    # Save response in background
    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'user', message
    ))
    asyncio.ensure_future(save_message(
        conversation['id'], student['id'], 'whatsapp', 'assistant', response_text
    ))

    today = nigeria_today()
    session_q = conv_state.get('session_questions', 0) + 1
    session_correct = conv_state.get('session_correct', 0) + (1 if is_correct else 0)

    # If Wax generated another question, save it
    if new_question_data:
        new_state = {
            **conv_state,
            'current_question': new_question_data,
            'session_questions': session_q,
            'session_correct': session_correct,
            'session_date': today,
        }
        new_subject = new_question_data.get('subject', subject)
        new_topic = new_question_data.get('topic', topic)
        await update_conversation_state(
            conversation['id'], 'whatsapp', phone,
            {
                'conversation_state': new_state,
                'current_subject': new_subject,
                'current_topic': new_topic,
            }
        )
    else:
        # Clear the current question — student and Wax are continuing naturally
        new_state = {
            **conv_state,
            'current_question': None,
            'session_questions': session_q,
            'session_correct': session_correct,
            'session_date': today,
        }
        await update_conversation_state(
            conversation['id'], 'whatsapp', phone,
            {'conversation_state': new_state}
        )

    asyncio.ensure_future(increment_questions_today(student['id']))
    asyncio.ensure_future(_update_stats(student, phone, conv_state))

    # Send badge notifications separately if earned
    if badges:
        for badge in badges:
            try:
                from whatsapp.sender import send_whatsapp_message as swm
                badge_msg = (
                    f"🏅 *New Badge Unlocked!*\n\n"
                    f"*{badge['name']}*\n"
                    f"{badge.get('description', '')}\n\n"
                    f"+{badge.get('points_awarded', 50)} bonus points!"
                )
                await asyncio.sleep(1)
                await swm(phone, badge_msg)
            except Exception:
                pass


async def _handle_image(phone: str, student: dict, media_id: str, caption: str):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)
    tier = status['effective_tier']
    is_trial = status.get('is_trial', False)

    if not settings.can_use_image_analysis(tier, is_trial):
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Hey {name}, image analysis is available on Scholar Plan.\n\n"
            "Upgrade for N1,500/month and you can send me photos of:\n"
            "• Textbook pages\n"
            "• Past question papers\n"
            "• Diagrams and graphs\n"
            "• Handwritten notes\n\n"
            "I will read them and explain everything. Type *SUBSCRIBE* to upgrade."
        )
        return

    if not settings.OPENAI_API_KEY:
        await send_whatsapp_message(
            phone,
            "Image analysis is temporarily unavailable. Type your question instead and I will help you immediately."
        )
        return

    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(phone, f"Got your photo, {name}! Reading it now...")

    try:
        from ai.openai_client import download_whatsapp_image, analyze_image
        image_b64 = await download_whatsapp_image(media_id)
        if not image_b64:
            await send_whatsapp_message(
                phone,
                "Could not download that image. Please try again."
            )
            return
        result = await analyze_image(image_base64=image_b64, prompt=caption or None, student=student)
        await send_whatsapp_message(phone, result)
    except Exception as e:
        print(f"Image analysis error: {e}")
        await send_whatsapp_message(
            phone,
            "Had trouble reading that image. Try taking a clearer photo, or type your question instead."
        )


async def _handle_voice(phone: str, student: dict, conversation: dict,
                         media_id: str, conv_state: dict):
    """
    Downloads voice note, transcribes with Groq Whisper,
    then passes the transcribed text to the AI brain as if it were a text message.
    """
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)
    tier = status['effective_tier']
    is_trial = status.get('is_trial', False)
    name = student.get('name', 'Student').split()[0]

    if not settings.can_use_voice_in(tier, is_trial):
        await send_whatsapp_message(
            phone,
            f"Hey {name}! Voice notes are available on Scholar Plan.\n\n"
            "Upgrade for N1,500/month and you can send me voice notes — I will transcribe them and respond.\n\n"
            "Type *SUBSCRIBE* to upgrade, or just type your question and I will answer immediately."
        )
        return

    if not media_id:
        await send_whatsapp_message(
            phone,
            f"I received a voice note, {name}, but could not access the audio file. Please try sending it again."
        )
        return

    # Transcribe the voice note
    try:
        from ai.openai_client import transcribe_voice_note
        transcribed_text = await transcribe_voice_note(media_id)
    except Exception as e:
        print(f"Voice transcription setup error: {e}")
        transcribed_text = None

    if not transcribed_text or len(transcribed_text.strip()) < 2:
        await send_whatsapp_message(
            phone,
            f"I could not clearly make out your voice note, {name}. "
            "Could you try sending it again, or type your question instead?"
        )
        return

    # Now treat the transcribed text as a normal message going to the AI brain
    # We pass it through the normal flow, but with a small note that it was voice
    print(f"Voice note transcribed: {transcribed_text[:100]}")

    await _think_and_respond(
        phone=phone,
        student=student,
        conversation=conversation,
        message=f"[Voice note]: {transcribed_text}",
        conv_state=conv_state
    )


async def _update_stats(student: dict, phone: str, conv_state: dict) -> None:
    """Updates total interactions, streak, and checks level up."""
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
        yesterday = (
            datetime.now(ZoneInfo("Africa/Lagos")) - timedelta(days=1)
        ).strftime('%Y-%m-%d')

        fresh = supabase.table('students').select(
            'last_study_date, current_streak, longest_streak'
        ).eq('id', student['id']).execute()

        if fresh.data:
            s = fresh.data[0]
            last_date = s.get('last_study_date')
            current_streak = s.get('current_streak', 0)
            longest_streak = s.get('longest_streak', 0)
            updates = {}
            new_streak = current_streak

            if last_date == today:
                pass  # Already counted today
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

            # Streak milestone badges
            streak_milestones = {3, 7, 14, 30, 60, 100}
            if new_streak in streak_milestones and last_date != today:
                try:
                    from features.badges import check_streak_badges
                    from whatsapp.sender import send_whatsapp_message
                    new_badges = await check_streak_badges(student['id'], new_streak)
                    for badge in new_badges:
                        name = student.get('name', 'Student').split()[0]
                        await send_whatsapp_message(
                            phone,
                            f"🔥 *{new_streak}-Day Streak!*\n\n"
                            f"*{badge['name']}* badge earned!\n"
                            f"{badge['description']}\n\n"
                            f"You have been consistent, {name}. That is how exams are won."
                        )
                except Exception:
                    pass
    except Exception as e:
        print(f"Stats update error: {e}")

    try:
        await _check_level(student['id'], phone, student.get('name', 'Student'))
    except Exception:
        pass


async def _check_level(student_id: str, phone: str, student_name: str):
    from database.client import supabase
    from config.settings import settings
    from whatsapp.sender import send_whatsapp_message

    result = supabase.table('students').select('total_points, current_level')\
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
        name = student_name.split()[0]
        await send_whatsapp_message(
            phone,
            f"⚡ *Level Up, {name}!*\n\n"
            f"You just reached Level {new_level} — *{new_level_name}*\n\n"
            f"{points:,} total points. You are building something real here."
        )

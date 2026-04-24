"""
WhatsApp Message Handler
FIXED: Correct function names, proper student lookup, no circular imports
ADDED: Streak updating logic, level up detection, total_questions_correct tracking
"""
from config.settings import settings
from helpers import nigeria_today, get_time_of_day, sanitize_input
import random


async def process_single_message(message_data: dict, value: dict) -> None:
    """Entry point called by main.py."""
    from whatsapp.sender import send_whatsapp_message
    phone = message_data.get('from', '')
    message_id = message_data.get('id', '')

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
        print("No phone number found in message data")
        return

    if not message and message_type not in ['image', 'voice', 'audio']:
        print(f"Empty message from {phone}, type: {message_type}")
        return

    message = sanitize_input(message) if message else message

    try:
        if message_id:
            from whatsapp.sender import mark_as_read
            await mark_as_read(message_id)

        await process_message(
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
            await send_whatsapp_message(
                phone,
                "Sorry, I ran into a small problem. Please try again in a few seconds!"
            )
        except Exception:
            pass


async def process_message(phone: str, name: str, message: str, message_type: str = 'text', media_id: str = None) -> None:
    """Main message router. All WhatsApp messages pass through here."""
    from whatsapp.sender import send_whatsapp_message
    from features.wax_id import student_exists_in_platform
    from database.conversations import get_or_create_conversation, save_message, get_conversation_history
    from admin.dashboard import is_admin, handle_admin_command

    msg_upper = message.strip().upper()

    if is_admin(phone) and msg_upper.startswith('ADMIN '):
        await handle_admin_command(phone, message)
        return

    student = await student_exists_in_platform('whatsapp', phone)

    if student and student.get('is_banned'):
        await send_whatsapp_message(phone, "Your account has been suspended. Contact support for help.")
        return

    conversation = await get_or_create_conversation(
        student_id=student['id'] if student else 'anonymous',
        platform='whatsapp',
        platform_user_id=phone
    )

    if not student:
        from whatsapp.flows.onboarding import handle_new_or_existing, handle_onboarding_response

        state = conversation.get('conversation_state', {})
        if isinstance(state, str):
            import json
            try:
                state = json.loads(state)
            except Exception:
                state = {}

        awaiting = state.get('awaiting_response_for', '')

        if awaiting in ['new_or_existing', 'terms_acceptance', 'wax_id_entry', 'pin_entry',
                        'name', 'class_level', 'target_exam', 'subjects', 'exam_date',
                        'state', 'language_pref', 'pin_setup', 'pin_confirm']:
            await handle_onboarding_response(phone, conversation, message)
        else:
            await handle_new_or_existing(phone, conversation, message)
        return

    conv_state = conversation.get('conversation_state', {})
    if isinstance(conv_state, str):
        import json
        try:
            conv_state = json.loads(conv_state)
        except Exception:
            conv_state = {}

    awaiting = conv_state.get('awaiting_response_for', '')
    current_mode = conversation.get('current_mode', 'default')

    if awaiting in ['new_or_existing', 'terms_acceptance', 'wax_id_entry', 'pin_entry',
                    'name', 'class_level', 'target_exam', 'subjects', 'exam_date',
                    'state', 'language_pref', 'pin_setup', 'pin_confirm']:
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message)
        return

    if current_mode == 'exam' or awaiting == 'exam_answer':
        from whatsapp.flows.mock_exam import handle_exam_answer
        await handle_exam_answer(phone, student, conversation, message)
        return

    if awaiting == 'quiz_answer':
        await _handle_quiz_answer(phone, student, conversation, message, conv_state)
        return

    if awaiting == 'challenge_answer':
        from whatsapp.flows.study import handle_challenge_answer
        await handle_challenge_answer(phone, student, conversation, message, conv_state)
        return

    if awaiting in ['exam_setup_choice', 'exam_subject_choice']:
        from whatsapp.flows.study import handle_study_message
        from ai.classifier import classify_message_fast
        intent = classify_message_fast(message, conv_state)
        await handle_study_message(phone, student, conversation, message, intent)
        return

    if awaiting == 'quiz_continue':
        msg_up = message.strip().upper()
        if msg_up in ['YES', 'Y', 'NEXT', 'CONTINUE', '1', 'ANOTHER', 'MORE']:
            subject = conversation.get('current_subject', '')
            topic = conversation.get('current_topic', '')
            from whatsapp.flows.study import deliver_quiz_question
            await deliver_quiz_question(phone, student, conversation, subject, topic, conv_state)
            return

    if msg_upper in ['GOOD', 'BAD'] and awaiting == 'awaiting_feedback':
        from features.feedback import handle_quick_thumbs
        response = await handle_quick_thumbs(phone, student, message)
        await send_whatsapp_message(phone, response)
        from database.conversations import update_conversation_state
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {}
        })
        return

    if msg_upper.startswith('BUG') or msg_upper.startswith('SUGGEST') or msg_upper.startswith('FEEDBACK'):
        from features.feedback import handle_feedback_command
        response = await handle_feedback_command(phone, student, message)
        await send_whatsapp_message(phone, response)
        return

    if message_type == 'image':
        await _handle_image_message(phone, student, media_id, message)
        return

    if message_type in ['voice', 'audio']:
        await _handle_voice_message(phone, student, media_id)
        return

    command = msg_upper.split()[0] if msg_upper else ''

    COMMANDS = {
        'HELP', 'PROGRESS', 'SUBSCRIBE', 'STREAK', 'PLAN', 'BALANCE',
        'MYID', 'PROMO', 'CODE', 'PAUSE', 'CONTINUE', 'STOP', 'MODES',
        'SUBJECTS', 'BADGES', 'REFERRAL', 'PARENT', 'PAYG'
    }

    if command in COMMANDS:
        from whatsapp.flows.commands import handle_command
        await handle_command(phone, student, conversation, message, command)
        return

    if msg_upper in ['QUIZ', 'EXAM', 'LEARN', 'REVISION', 'CHALLENGE'] or \
       msg_upper.startswith('QUIZ ') or msg_upper.startswith('LEARN ') or \
       msg_upper.startswith('PRACTICE '):
        from whatsapp.flows.study import handle_study_message
        from ai.classifier import classify_message_fast
        intent = classify_message_fast(message, conv_state)
        await handle_study_message(phone, student, conversation, message, intent)
        return

    from ai.classifier import classify_message_fast
    intent = classify_message_fast(message, conv_state)

    await save_conversation_message(conversation['id'], student['id'], 'whatsapp', 'user', message)

    if intent == 'GREETING':
        response = await _handle_greeting(student, phone)
        await send_whatsapp_message(phone, response)

    elif intent in ['ACADEMIC_QUESTION', 'REQUEST_EXPLANATION', 'CALCULATION', 'REQUEST_QUIZ', 'WRONG_RESPONSE']:
        can_ask, limit_msg = await _check_question_limit(student)
        if not can_ask:
            await send_whatsapp_message(phone, limit_msg)
            return

        from whatsapp.flows.study import handle_study_message
        await handle_study_message(phone, student, conversation, message, intent)

        await _increment_and_maybe_prompt_feedback(phone, student, conversation)

    elif intent == 'PAYMENT_INQUIRY':
        response = await _handle_payment_inquiry(student)
        await send_whatsapp_message(phone, response)

    elif intent in ['COMMAND', 'HELP_REQUEST']:
        from whatsapp.flows.commands import handle_command
        await handle_command(phone, student, conversation, message, 'HELP')

    elif intent == 'CASUAL_CHAT':
        response = await _handle_casual_chat(message, student)
        await send_whatsapp_message(phone, response)

    elif intent == 'PROMO_CODE':
        from whatsapp.flows.commands import handle_promo_code
        await handle_promo_code(phone, student, conversation, message)

    else:
        from whatsapp.flows.study import handle_study_message
        await handle_study_message(phone, student, conversation, message, intent)


async def _check_question_limit(student: dict) -> tuple:
    """Returns (can_ask, message) after checking daily limits."""
    from database.students import can_student_ask_question
    return await can_student_ask_question(student)


async def _increment_and_maybe_prompt_feedback(phone: str, student: dict, conversation: dict):
    """
    Increments question count, updates streak, checks level up,
    and shows feedback prompt every 5 questions.
    ADDED: Full streak logic, level-up detection, total_questions_answered tracking.
    """
    from database.students import increment_questions_today
    from database.client import supabase

    await increment_questions_today(student['id'])

    # Update total questions answered
    try:
        supabase.table('students').update({
            'total_questions_answered': student.get('total_questions_answered', 0) + 1
        }).eq('id', student['id']).execute()
    except Exception as e:
        print(f"total_questions_answered update error (non-critical): {e}")

    # ADDED: Streak updating logic
    try:
        from helpers import nigeria_today
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        today = nigeria_today()
        yesterday = (datetime.now(ZoneInfo("Africa/Lagos")) - timedelta(days=1)).strftime('%Y-%m-%d')

        fresh = supabase.table('students')\
            .select('last_study_date, current_streak, longest_streak')\
            .eq('id', student['id']).execute()

        if fresh.data:
            s = fresh.data[0]
            last_date = s.get('last_study_date')
            current_streak = s.get('current_streak', 0)
            longest_streak = s.get('longest_streak', 0)

            streak_updates = {}
            new_streak = current_streak

            if last_date == today:
                # Already studied today — no change needed
                pass
            elif last_date == yesterday:
                # Consecutive day — increment streak
                new_streak = current_streak + 1
                new_longest = max(longest_streak, new_streak)
                streak_updates['current_streak'] = new_streak
                streak_updates['longest_streak'] = new_longest
                streak_updates['last_study_date'] = today
            else:
                # Streak broken or brand new student
                new_streak = 1
                streak_updates['current_streak'] = 1
                streak_updates['last_study_date'] = today

            if streak_updates:
                supabase.table('students').update(streak_updates).eq('id', student['id']).execute()

            # Check for streak milestone badges and notify
            streak_milestones = {3, 7, 14, 30, 60, 100}
            if new_streak in streak_milestones and last_date != today:
                try:
                    from features.badges import check_streak_badges
                    from whatsapp.sender import send_whatsapp_message
                    new_badges = await check_streak_badges(student['id'], new_streak)
                    for badge in new_badges:
                        await send_whatsapp_message(
                            phone,
                            f"Streak Badge Unlocked!\n\n"
                            f"*{badge['name']}*\n{badge['description']}\n\n"
                            f"{new_streak}-day streak! Keep it up!"
                        )
                except Exception as badge_err:
                    print(f"Streak badge error (non-critical): {badge_err}")

    except Exception as streak_err:
        print(f"Streak update error (non-critical): {streak_err}")

    # ADDED: Level up check
    try:
        await _check_and_update_level(student['id'], phone)
    except Exception as level_err:
        print(f"Level check error (non-critical): {level_err}")

    conv_state = conversation.get('conversation_state', {})
    session_questions = conv_state.get('session_questions', 0) + 1

    from database.conversations import update_conversation_state
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **conv_state,
            'session_questions': session_questions,
        }
    })

    if session_questions > 0 and session_questions % 5 == 0:
        from features.feedback import send_session_feedback_prompt
        await send_session_feedback_prompt(phone, student, session_questions)

        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {
                **conv_state,
                'session_questions': session_questions,
                'awaiting_response_for': 'awaiting_feedback',
            }
        })


async def _check_and_update_level(student_id: str, phone: str):
    """
    Checks if a student has earned enough points to level up.
    Sends a celebration message if they leveled up.
    ADDED: This function was completely missing before — no students ever leveled up.
    """
    from database.client import supabase
    from config.settings import settings
    from whatsapp.sender import send_whatsapp_message

    try:
        result = supabase.table('students')\
            .select('total_points, current_level, level_name, name')\
            .eq('id', student_id).execute()

        if not result.data:
            return

        s = result.data[0]
        points = s.get('total_points', 0)
        current_level = s.get('current_level', 1)

        # Find the highest level this student qualifies for
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
                f"LEVEL UP, {name}!\n\n"
                f"You reached *Level {new_level} — {new_level_name}!*\n\n"
                f"Total Points: {points:,}\n\n"
                f"Keep studying to reach the next level!"
            )
    except Exception as e:
        print(f"Level update error (non-critical): {e}")


async def _handle_quiz_answer(phone: str, student: dict, conversation: dict, message: str, state: dict):
    """
    Handles a student's answer during a quiz session.
    ADDED: Now updates total_questions_correct properly.
    """
    from whatsapp.sender import send_whatsapp_message
    from features.quiz_engine import evaluate_quiz_answer, update_mastery_after_answer, calculate_and_award_points
    from database.questions import update_question_stats
    from database.conversations import update_conversation_state
    from features.badges import award_badge, check_and_award_milestone_badges
    from database.client import supabase

    current_question = state.get('current_question')

    if not current_question:
        await send_whatsapp_message(
            phone,
            "I lost track of the question! Let me get you a new one.\n\nWhat subject were you practicing?"
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {}
        })
        return

    is_correct, feedback = evaluate_quiz_answer(
        message.strip(),
        current_question.get('correct_answer', 'A'),
        current_question
    )

    if is_correct is None:
        await send_whatsapp_message(phone, feedback)
        return

    await update_mastery_after_answer(
        student_id=student['id'],
        subject=current_question.get('subject', ''),
        topic=current_question.get('topic', ''),
        question_difficulty=current_question.get('difficulty_level', 5),
        is_correct=is_correct
    )

    if current_question.get('id'):
        await update_question_stats(current_question['id'], is_correct)

    # ADDED: Update total_questions_correct when answer is correct
    try:
        update_data = {}
        if is_correct:
            update_data['total_questions_correct'] = student.get('total_questions_correct', 0) + 1
        if update_data:
            supabase.table('students').update(update_data).eq('id', student['id']).execute()
    except Exception as e:
        print(f"total_questions_correct update error (non-critical): {e}")

    points, _ = await calculate_and_award_points(
        student_id=student['id'],
        is_correct=is_correct,
        question_difficulty=current_question.get('difficulty_level', 5)
    )

    new_total = student.get('total_questions_answered', 0) + 1
    badges = await check_and_award_milestone_badges(student['id'], new_total)

    session_q = state.get('session_questions', 0) + 1
    session_correct = state.get('session_correct', 0) + (1 if is_correct else 0)

    full_feedback = feedback
    full_feedback += f"\n\n+{points} point{'s' if points != 1 else ''}!"

    for badge in badges:
        full_feedback += f"\n\nNew Badge: {badge['name']}!\n{badge['description']}"

    if session_q % 5 == 0 and session_q > 0:
        accuracy = round((session_correct / session_q) * 100)
        full_feedback += (
            f"\n\nSession so far: {session_q} questions | {session_correct} correct | {accuracy}%"
        )

    full_feedback += "\n\nType NEXT for another question, or ask me anything to switch topics."

    await send_whatsapp_message(phone, full_feedback)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **state,
            'awaiting_response_for': 'quiz_continue',
            'session_questions': session_q,
            'session_correct': session_correct,
            'last_question': current_question,
            'current_question': None,
        }
    })

    await _increment_and_maybe_prompt_feedback(phone, student, conversation)


async def _handle_image_message(phone: str, student: dict, media_id: str, caption: str):
    """Handles image uploads."""
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    effective_tier = status['effective_tier']

    if effective_tier == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            "Image analysis is a Scholar Plan feature!\n\n"
            "With Scholar Plan, you can:\n"
            "Send photos of your textbooks\n"
            "Send past question papers\n"
            "Send your handwritten notes\n"
            "Send diagrams for explanation\n\n"
            "Type SUBSCRIBE to upgrade."
        )
        return

    if not settings.OPENAI_API_KEY:
        await send_whatsapp_message(
            phone,
            "Image analysis is temporarily unavailable. Please type your question as text."
        )
        return

    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(phone, f"Got your image, {name}! Let me analyze it...")

    try:
        from ai.openai_client import download_whatsapp_image, analyze_image
        image_b64 = await download_whatsapp_image(media_id)
        if not image_b64:
            await send_whatsapp_message(phone, "I could not download that image. Please try sending it again.")
            return

        result = await analyze_image(
            image_base64=image_b64,
            prompt=caption if caption else None,
            student=student
        )
        await send_whatsapp_message(phone, result)

    except Exception as e:
        print(f"Image analysis error: {e}")
        await send_whatsapp_message(
            phone,
            "I had trouble reading that image.\n\n"
            "Please try:\n"
            "Taking a clearer photo in good lighting\n"
            "Making sure the text is clearly visible\n"
            "Sending just one page at a time\n\n"
            "Or type your question and I will help immediately!"
        )


async def _handle_voice_message(phone: str, student: dict, media_id: str):
    """Handles voice notes."""
    from whatsapp.sender import send_whatsapp_message
    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(
        phone,
        f"Got your voice note, {name}!\n\n"
        "Voice transcription is coming soon.\n\n"
        "For now, please type your question and I will answer it right away!"
    )


async def _handle_greeting(student: dict, phone: str) -> str:
    """Handle greetings with context."""
    from database.client import supabase
    from helpers import get_time_of_day
    from ai.prompts import get_greeting
    name = student.get('name', 'Student')
    first_name = name.split()[0]
    streak = student.get('current_streak', 0)
    tod = get_time_of_day()

    greeting = get_greeting(first_name, tod)
    today = nigeria_today()

    if student.get('last_study_date') != today:
        try:
            weak = supabase.table('mastery_scores').select('subject, topic')\
                .eq('student_id', student['id'])\
                .order('mastery_score').limit(1).execute()
            if weak.data:
                w = weak.data[0]
                return (
                    f"{greeting}\n\n"
                    f"You haven't studied today yet. Want to work on {w['topic']} in {w['subject']}? "
                    f"It's one of your focus areas right now.\n\n"
                    "Or tell me any subject you want to tackle today!"
                )
        except Exception:
            pass

        return (
            f"{greeting}\n\n"
            "Ready to study? What subject do you want to work on today?"
        )

    return (
        f"{greeting}\n\n"
        "Back for more! What do you want to work on next?"
    )


async def _handle_payment_inquiry(student: dict) -> str:
    """Handle subscription questions with correct pricing."""
    from config.settings import settings
    name = student.get('name', 'Student').split()[0]
    tier = student.get('subscription_tier', 'free')
    is_trial = student.get('is_trial_active', False)

    if tier != 'free' or is_trial:
        plan = 'Full Trial Access' if is_trial else tier.capitalize()
        return (
            f"You are on the {plan}, {name}!\n\n"
            "Type PROGRESS to see your full plan details, or SUBSCRIBE to change your plan."
        )

    return (
        f"WaxPrep Plans\n\n"
        f"Scholar Plan — N1,500/month\n"
        f"100 questions per day\n"
        f"Image analysis (send photos of textbooks)\n"
        f"Full mock exams twice a week\n"
        f"Personalized study plan\n"
        f"Spaced repetition reminders\n\n"
        f"Scholar Yearly — N15,000/year (save 17%)\n\n"
        f"Pro Plan — N3,000/month\n"
        f"Everything in Scholar plus more\n\n"
        f"Elite Plan — N5,000/month\n"
        f"Unlimited everything\n\n"
        f"Pay As You Go — No subscription needed\n"
        f"N500 = 100 extra questions\n"
        f"N1,000 = 250 extra questions\n"
        f"N1,800 = 500 extra questions\n\n"
        f"Type SUBSCRIBE to upgrade to a plan, or PAYG for question credits."
    )


async def _handle_casual_chat(message: str, student: dict) -> str:
    """Handle casual chat with a study redirect."""
    from ai.brain import process_message_with_ai
    result = await process_message_with_ai(message, student, {}, [])

    name = student.get('name', 'Student').split()[0]
    redirects = [
        f"\n\nAnyway, {name} — what subject are we tackling today?",
        f"\n\nBut seriously, {name}, what do you want to learn today?",
        f"\n\nOk, now let's study! What subject, {name}?",
    ]

    if result and len(result) < 600:
        result = result.rstrip() + random.choice(redirects)

    return result or f"Ha! Anyway {name}, ready to study? What subject?"


async def save_conversation_message(conversation_id: str, student_id: str, platform: str, role: str, content: str):
    """Saves a message to conversation history."""
    from database.conversations import save_message
    try:
        await save_message(conversation_id, student_id, platform, role, content)
    except Exception as e:
        print(f"Save message error: {e}")


async def award_badge(student_id: str, badge_code: str) -> dict | None:
    """Wrapper for backward compatibility — uses features.badges now."""
    from features.badges import award_badge as _award_badge
    return await _award_badge(student_id, badge_code)

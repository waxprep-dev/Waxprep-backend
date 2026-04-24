"""
Study Flow — The Main Learning Experience
FIXED: Removed broken utils.helpers import
FIXED: Circular import resolved — award_badge now from features.badges
"""

from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state, get_conversation_history
from ai.router import route_and_respond
from ai.prompts import get_main_tutor_prompt
from ai.classifier import classify_message_fast
from features.quiz_engine import (
    get_question_for_student, format_question_for_whatsapp,
    evaluate_quiz_answer, update_mastery_after_answer,
    calculate_and_award_points, extract_subject_from_message,
    extract_topic_from_message
)
from features.daily_challenge import (
    get_todays_challenge, has_student_attempted_today,
    format_daily_challenge, submit_challenge_answer
)
from database.client import supabase
from helpers import nigeria_today


async def handle_study_message(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    intent: str
):
    """
    Main entry point for study-related messages.
    Routes to the appropriate study handler based on intent and mode.
    """
    state = conversation.get('conversation_state', {})
    current_mode = conversation.get('current_mode', 'default')
    awaiting = state.get('awaiting_response_for')

    if intent == 'COMMAND' and message.strip().upper() in ['CHALLENGE', 'DAILY', 'DAILY CHALLENGE']:
        await handle_daily_challenge(phone, student, conversation)
        return

    if awaiting == 'quiz_answer':
        await handle_quiz_answer(phone, student, conversation, message, state)
        return

    if awaiting == 'quiz_continue':
        msg_upper = message.strip().upper()
        if msg_upper in ['YES', 'Y', 'NEXT', 'CONTINUE', '1', 'ANOTHER']:
            subject = conversation.get('current_subject', '')
            topic = conversation.get('current_topic', '')
            await deliver_quiz_question(phone, student, conversation, subject, topic, state)
            return
        else:
            await handle_academic_message(phone, student, conversation, message, intent)
            return

    if awaiting == 'exam_setup_choice':
        from whatsapp.flows.mock_exam import start_mock_exam

        choice = message.strip()
        suggested_type = state.get('suggested_exam_type', 'JAMB')

        if choice == '1':
            await start_mock_exam(phone, student, conversation, suggested_type)
        elif choice == '2':
            await start_mock_exam(phone, student, conversation, suggested_type, num_questions=20)
        elif choice == '3':
            await send_whatsapp_message(
                phone,
                "Which subject do you want to focus on?\n\n" +
                '\n'.join([f"{i+1}. {s}" for i, s in enumerate(student.get('subjects', [])[:6])])
            )
            await update_conversation_state(conversation['id'], 'whatsapp', phone, {
                'conversation_state': {
                    **state,
                    'awaiting_response_for': 'exam_subject_choice',
                }
            })
        return

    if intent == 'REQUEST_QUIZ':
        subject = extract_subject_from_message(message)
        topic = extract_topic_from_message(message)

        if not subject:
            await send_whatsapp_message(
                phone,
                "Which subject should I quiz you on?\n\n"
                "For example: Quiz me on Physics or Test me on Mathematics"
            )
            return

        await deliver_quiz_question(phone, student, conversation, subject, topic, state)
        return

    await handle_academic_message(phone, student, conversation, message, intent)


async def handle_academic_message(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    intent: str
):
    """
    Sends an academic message to the AI and returns the response.
    This handles the core learn/explain/help functions.
    """
    current_mode = conversation.get('current_mode', 'default')

    msg_upper = message.strip().upper()

    if msg_upper.startswith('LEARN ') or msg_upper == 'LEARN':
        current_mode = 'learn'
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'current_mode': 'learn'
        })
    elif msg_upper.startswith('REVISION') or msg_upper == 'REVISION':
        current_mode = 'revision'
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'current_mode': 'revision'
        })

    system_prompt = get_main_tutor_prompt(student, current_mode)
    history = await get_conversation_history(conversation['id'])

    response = await route_and_respond(
        message=message,
        intent=intent,
        student=student,
        conversation_history=history,
        conversation_state=conversation.get('conversation_state', {}),
        system_prompt=system_prompt
    )

    await send_whatsapp_message(phone, response)

    subject = extract_subject_from_message(message)
    topic = extract_topic_from_message(message)

    if subject or topic:
        updates = {}
        if subject:
            updates['current_subject'] = subject
        if topic:
            updates['current_topic'] = topic
        await update_conversation_state(conversation['id'], 'whatsapp', phone, updates)


async def handle_quiz_answer(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    state: dict
):
    """
    Handles a student's answer during a quiz session.
    FIXED: award_badge now from features.badges to avoid circular import.
    """
    # FIXED: Import from features.badges, not from whatsapp.handler
    from features.badges import award_badge

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
        from database.questions import update_question_stats
        await update_question_stats(current_question['id'], is_correct)

    points, badge = await calculate_and_award_points(
        student_id=student['id'],
        is_correct=is_correct,
        question_difficulty=current_question.get('difficulty_level', 5)
    )

    session_q = state.get('session_questions', 0) + 1
    session_correct = state.get('session_correct', 0) + (1 if is_correct else 0)

    full_feedback = feedback
    full_feedback += f"\n\n+{points} point{'s' if points != 1 else ''}!"

    if badge:
        full_feedback += f"\n\nNew Badge Unlocked: {badge['name']}!\n{badge['description']}"

    if session_q % 5 == 0 and session_q > 0:
        accuracy = round((session_correct / session_q) * 100)
        full_feedback += (
            f"\n\nSession Summary:\n"
            f"{session_q} questions | {session_correct} correct | {accuracy}%"
        )

    full_feedback += "\n\n_Type NEXT for another question, or ask me anything to switch topics._"

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


async def deliver_quiz_question(
    phone: str,
    student: dict,
    conversation: dict,
    subject: str,
    topic: str,
    state: dict
):
    """Gets and delivers a quiz question to the student."""
    from database.questions import get_student_recently_seen_questions, record_question_seen

    question = await get_question_for_student(
        student_id=student['id'],
        subject=subject,
        topic=topic,
        exam_type=student.get('target_exam', 'JAMB')
    )

    if not question:
        await send_whatsapp_message(
            phone,
            f"I'm still building my {subject} question bank!\n\n"
            f"Let me generate a fresh question just for you...\n\n"
            f"This uses AI to create exam-quality questions."
        )

        from ai.gemini_client import generate_questions_with_gemini
        questions = await generate_questions_with_gemini(
            subject=subject,
            topic=topic or 'Mixed Topics',
            exam_type=student.get('target_exam', 'JAMB'),
            difficulty=5,
            count=3
        )

        if questions:
            question = questions[0]
        else:
            await send_whatsapp_message(
                phone,
                f"I couldn't generate a {subject} question right now.\n\n"
                f"Try a different subject, or ask me to LEARN {subject} first."
            )
            return

    session_q = state.get('session_questions', 0)
    formatted = format_question_for_whatsapp(question, session_q + 1)
    await send_whatsapp_message(phone, formatted)

    if question.get('id'):
        await record_question_seen(student['id'], question['id'])

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'quiz',
        'current_subject': subject,
        'current_topic': topic or question.get('topic', ''),
        'conversation_state': {
            **state,
            'awaiting_response_for': 'quiz_answer',
            'current_question': question,
        }
    })


async def handle_daily_challenge(phone: str, student: dict, conversation: dict):
    """Handles the CHALLENGE command — shows today's daily challenge."""

    challenge = await get_todays_challenge()

    if not challenge:
        await send_whatsapp_message(
            phone,
            "Today's challenge hasn't been generated yet!\n\n"
            "Daily challenges go live at *8:00 AM Lagos time*.\n\n"
            "Come back then!"
        )
        return

    already_attempted = await has_student_attempted_today(student['id'])

    if already_attempted:
        total_attempts = challenge.get('total_attempts', 0)
        total_correct = challenge.get('total_correct', 0)
        correct_rate = round((total_correct / total_attempts) * 100) if total_attempts > 0 else 0

        await send_whatsapp_message(
            phone,
            f"Daily Challenge — {challenge.get('challenge_date')}\n\n"
            f"You've already attempted today's challenge!\n\n"
            f"Results so far:\n"
            f"Total attempts: {total_attempts}\n"
            f"Got it right: {total_correct} ({correct_rate}%)\n\n"
            f"Come back tomorrow at 8 AM for a new challenge!"
        )
        return

    formatted = format_daily_challenge(challenge)
    await send_whatsapp_message(phone, formatted)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            'awaiting_response_for': 'challenge_answer',
            'challenge_id': challenge['id'],
            'current_challenge': challenge,
        }
    })


async def handle_challenge_answer(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    state: dict
):
    """
    Handles a student's answer to the daily challenge.
    FIXED: award_badge now from features.badges to avoid circular import.
    """
    # FIXED: Import from features.badges, not from whatsapp.handler
    from features.badges import award_badge

    challenge = state.get('current_challenge')

    if not challenge:
        await send_whatsapp_message(phone, "I lost the challenge question! Type *CHALLENGE* to get it again.")
        return

    is_correct, feedback, points = await submit_challenge_answer(
        student_id=student['id'],
        answer=message.strip(),
        challenge=challenge
    )

    if is_correct is None:
        await send_whatsapp_message(phone, feedback)
        return

    await send_whatsapp_message(phone, feedback)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {}
    })

    await award_badge(student['id'], 'DAILY_CHALLENGE_FIRST')

    if is_correct:
        updated_challenge = supabase.table('daily_challenges')\
            .select('winner_student_id')\
            .eq('id', challenge['id'])\
            .execute()

        if updated_challenge.data:
            winner_id = updated_challenge.data[0].get('winner_student_id')
            if str(winner_id) == str(student['id']):
                await award_badge(student['id'], 'DAILY_CHALLENGE_WIN')

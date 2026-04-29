"""
Study Flow Utilities

The AI brain (Wax) handles all conversational teaching and quiz delivery.
This module provides utility functions for structured features:
- Daily challenge
- Spaced repetition nudges

Most of what was here before has been moved into the AI brain.
"""

from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from features.daily_challenge import (
    get_todays_challenge, has_student_attempted_today,
    format_daily_challenge, submit_challenge_answer
)
from database.client import supabase
from helpers import nigeria_today


async def handle_daily_challenge(phone: str, student: dict, conversation: dict):
    """Sends today's daily challenge question."""
    challenge = await get_todays_challenge()

    if not challenge:
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Today's challenge hasn't dropped yet, {name}!\n\n"
            "Daily challenges go live at 8:00 AM Lagos time. "
            "Come back then and let's see if you can get it first."
        )
        return

    already_attempted = await has_student_attempted_today(student['id'])

    if already_attempted:
        total = challenge.get('total_attempts', 0)
        correct = challenge.get('total_correct', 0)
        rate = round((correct / total * 100)) if total > 0 else 0
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"You already took today's challenge, {name}!\n\n"
            f"So far across all students: {total} attempts, {correct} correct ({rate}%).\n\n"
            "New challenge drops tomorrow at 8 AM. "
            "In the meantime, want to study something?"
        )
        return

    formatted = format_daily_challenge(challenge)
    await send_whatsapp_message(phone, formatted)

    from whatsapp.handler import _get_state
    state = _get_state(conversation)
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **state,
            'awaiting_response_for': 'challenge_answer',
            'challenge_id': challenge['id'],
            'current_challenge': challenge,
        }
    })


async def handle_challenge_answer(phone: str, student: dict, conversation: dict,
                                   message: str, state: dict):
    from features.badges import award_badge

    challenge = state.get('current_challenge')
    if not challenge:
        await send_whatsapp_message(
            phone,
            "Lost track of the challenge question. Type *CHALLENGE* to get it again."
        )
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
        updated = supabase.table('daily_challenges').select('winner_student_id')\
            .eq('id', challenge['id']).execute()
        if updated.data:
            winner_id = updated.data[0].get('winner_student_id')
            if str(winner_id) == str(student['id']):
                await award_badge(student['id'], 'DAILY_CHALLENGE_WIN')


async def deliver_quiz_question(phone: str, student: dict, conversation: dict,
                                 subject: str, topic: str, state: dict):
    """
    Utility function to fetch and deliver a question directly from the database.
    Kept for cases where the scheduler or other systems need to push a question.
    In normal conversation flow, Wax generates questions naturally.
    """
    from features.quiz_engine import (
        get_question_for_student, format_question_for_whatsapp
    )
    from database.questions import record_question_seen

    question = await get_question_for_student(
        student_id=student['id'],
        subject=subject,
        topic=topic,
        exam_type=student.get('target_exam', 'JAMB')
    )

    if not question:
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
                f"Having trouble getting a {subject} question right now. "
                "Ask me to explain something and we will work from there."
            )
            return

    session_q = state.get('session_questions', 0)
    formatted = format_question_for_whatsapp(question, session_q + 1)
    await send_whatsapp_message(phone, formatted)

    if question.get('id'):
        await record_question_seen(student['id'], question['id'])

    today = nigeria_today()
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_subject': subject,
        'current_topic': topic or question.get('topic', ''),
        'conversation_state': {
            **state,
            'current_question': question,
            'session_date': today,
        }
    })

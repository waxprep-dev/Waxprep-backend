"""
Mock Exam Flow

The complete mock exam experience over WhatsApp.
FIXED: Removed broken import from utils.helpers
FIXED: Circular import removed — award_badge now comes from features.badges directly
"""

from whatsapp.sender import send_whatsapp_message
from database.questions import get_questions_for_mock_exam
from database.conversations import update_conversation_state
from database.client import supabase
from helpers import nigeria_now, format_naira
from features.quiz_engine import evaluate_quiz_answer
from config.settings import settings
import json


async def start_mock_exam(
    phone: str,
    student: dict,
    conversation: dict,
    exam_type: str = None,
    subjects: list = None,
    num_questions: int = None
):
    """
    Starts a mock exam session.
    If parameters aren't specified, asks the student to choose.
    """
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            f"Full Mock Exams — Scholar Plan Feature\n\n"
            f"Free plan includes 10-question mini mocks.\n\n"
            f"Scholar Plan gives you:\n"
            f"Full JAMB simulation (100 questions)\n"
            f"Full WAEC simulation\n"
            f"Complete post-exam analysis\n"
            f"Score prediction\n"
            f"2 full mocks per week\n\n"
            f"Upgrade for just {format_naira(settings.SCHOLAR_MONTHLY)}/month.\n"
            f"Type *SUBSCRIBE* to upgrade."
        )
        await ask_mini_mock_preferences(phone, student, conversation)
        return

    if not exam_type:
        student_exam = student.get('target_exam', 'JAMB')
        await ask_mock_exam_preferences(phone, student, conversation, student_exam)
        return

    subjects_to_use = subjects or student.get('subjects', ['Mathematics', 'English Language'])

    if num_questions is None:
        if status['effective_tier'] == 'free':
            num_questions = 10
        elif exam_type == 'JAMB':
            num_questions = 100
        else:
            num_questions = 40

    await send_whatsapp_message(
        phone,
        f"Preparing your {exam_type} mock exam...\n\n"
        f"Selecting {num_questions} questions from the question bank.\n"
        f"This takes about 10 seconds..."
    )

    questions = await get_questions_for_mock_exam(exam_type, subjects_to_use, num_questions)

    if not questions:
        await send_whatsapp_message(
            phone,
            "I couldn't generate your mock exam right now.\n\n"
            "The question bank for this subject combination is still being built.\n\n"
            "Try a different subject or try again tomorrow when more questions are available."
        )
        return

    exam_record = supabase.table('mock_exams').insert({
        'student_id': student['id'],
        'exam_type': exam_type,
        'total_questions': len(questions),
        'time_limit_minutes': 100 if exam_type == 'JAMB' else 60,
        'max_score': len(questions),
        'status': 'in_progress',
        'questions_data': questions,
        'started_at': nigeria_now().isoformat(),
    }).execute()

    exam_id = exam_record.data[0]['id'] if exam_record.data else None

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'exam',
        'conversation_state': {
            'exam_id': exam_id,
            'exam_type': exam_type,
            'questions': [q['id'] for q in questions],
            'current_question_index': 0,
            'answers': {},
            'correct_count': 0,
            'started_at': nigeria_now().isoformat(),
            'time_limit_minutes': 100 if exam_type == 'JAMB' else 60,
            'awaiting_response_for': 'exam_answer',
        }
    })

    time_limit = 100 if exam_type == 'JAMB' else 60

    await send_whatsapp_message(
        phone,
        f"*{exam_type} Mock Exam — Starting Now!*\n\n"
        f"Questions: {len(questions)}\n"
        f"Time Limit: {time_limit} minutes\n"
        f"No hints allowed during the exam\n\n"
        f"RULES:\n"
        f"Answer with A, B, C, or D only\n"
        f"You cannot go back to a previous question\n"
        f"Type STOP EXAM at any time to end early\n\n"
        f"The clock starts NOW. Good luck!\n\n"
        f"Question 1 of {len(questions)} is below:"
    )

    await send_exam_question(phone, questions[0], 1, len(questions))


async def send_exam_question(phone: str, question: dict, question_num: int, total: int):
    """Sends a single exam question in exam mode format."""

    q_text = question.get('question_text', '')
    a = question.get('option_a', '')
    b = question.get('option_b', '')
    c = question.get('option_c', '')
    d = question.get('option_d', '')
    subject = question.get('subject', '')

    formatted = (
        f"*[{question_num}/{total}]* _{subject}_\n\n"
        f"{q_text}\n\n"
        f"A. {a}\n"
        f"B. {b}\n"
        f"C. {c}\n"
        f"D. {d}"
    )

    await send_whatsapp_message(phone, formatted)


async def handle_exam_answer(
    phone: str,
    student: dict,
    conversation: dict,
    answer: str
):
    """
    Processes a student's answer during an exam.
    No feedback given — just moves to the next question.
    """
    state = conversation.get('conversation_state', {})

    if answer.upper().strip() in ['STOP EXAM', 'STOP', 'END EXAM']:
        await end_exam_early(phone, student, conversation, state)
        return

    answer_clean = answer.strip().upper()
    if answer_clean not in ['A', 'B', 'C', 'D']:
        await send_whatsapp_message(
            phone,
            "In exam mode, you can only reply with *A*, *B*, *C*, or *D*.\n\n"
            "_(To end the exam early, type *STOP EXAM*)_"
        )
        return

    questions_ids = state.get('questions', [])
    current_index = state.get('current_question_index', 0)
    answers = state.get('answers', {})
    correct_count = state.get('correct_count', 0)

    if current_index >= len(questions_ids):
        await complete_exam(phone, student, conversation, state)
        return

    question_id = questions_ids[current_index]
    question_result = supabase.table('questions').select('*').eq('id', question_id).execute()

    if question_result.data:
        question = question_result.data[0]
        correct = question.get('correct_answer', '').upper()
        is_correct = answer_clean == correct

        answers[question_id] = {
            'answer': answer_clean,
            'correct': correct,
            'is_correct': is_correct,
            'subject': question.get('subject', ''),
            'topic': question.get('topic', ''),
        }

        if is_correct:
            correct_count += 1

    next_index = current_index + 1

    if next_index >= len(questions_ids):
        state['answers'] = answers
        state['correct_count'] = correct_count
        state['current_question_index'] = next_index

        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': state
        })

        await complete_exam(phone, student, conversation, state)
        return

    state['current_question_index'] = next_index
    state['answers'] = answers
    state['correct_count'] = correct_count

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': state
    })

    next_question_id = questions_ids[next_index]
    next_question_result = supabase.table('questions').select('*').eq('id', next_question_id).execute()

    if next_question_result.data:
        await send_exam_question(
            phone,
            next_question_result.data[0],
            next_index + 1,
            len(questions_ids)
        )


async def complete_exam(
    phone: str,
    student: dict,
    conversation: dict,
    state: dict
):
    """
    Completes the exam, calculates results, and sends the analysis.
    FIXED: award_badge now imported from features.badges to avoid circular import.
    """
    from ai.gemini_client import ask_gemini
    from ai.prompts import get_post_exam_analysis_prompt
    from features.badges import award_badge

    answers = state.get('answers', {})
    total = len(state.get('questions', []))
    correct_count = state.get('correct_count', 0)
    started_at_str = state.get('started_at')
    exam_id = state.get('exam_id')
    exam_type = state.get('exam_type', 'JAMB')

    time_taken_minutes = 0
    if started_at_str:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        try:
            started = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
            now = nigeria_now()
            time_taken_minutes = int((now - started).total_seconds() / 60)
        except Exception:
            pass

    if total > 0:
        percentage = round((correct_count / total) * 100, 1)
    else:
        percentage = 0

    jamb_score = None
    if exam_type == 'JAMB' and total > 0:
        jamb_score = round((correct_count / total) * 400)

    subject_performance = {}
    for q_id, ans_data in answers.items():
        subject = ans_data.get('subject', 'Unknown')
        if subject not in subject_performance:
            subject_performance[subject] = {'correct': 0, 'total': 0}
        subject_performance[subject]['total'] += 1
        if ans_data.get('is_correct'):
            subject_performance[subject]['correct'] += 1

    correct_topics = []
    wrong_topics = []

    for subject, perf in subject_performance.items():
        subj_pct = round((perf['correct'] / perf['total']) * 100) if perf['total'] > 0 else 0
        if subj_pct >= 60:
            correct_topics.append(f"{subject} ({subj_pct}%)")
        else:
            wrong_topics.append(f"{subject} ({subj_pct}%)")

    if exam_id:
        try:
            supabase.table('mock_exams').update({
                'score': correct_count,
                'percentage': percentage,
                'time_taken_minutes': time_taken_minutes,
                'status': 'completed',
                'answers_data': answers,
                'completed_at': nigeria_now().isoformat(),
            }).eq('id', exam_id).execute()
        except Exception as e:
            print(f"Mock exam record update error: {e}")

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'default',
        'conversation_state': {},
    })

    score_emoji = 'EXCELLENT' if percentage >= 80 else 'GOOD' if percentage >= 60 else 'KEEP GOING'

    results_msg = (
        f"Exam Complete!\n\n"
        f"*Your Score: {correct_count}/{total} ({percentage}%)*\n"
    )

    if jamb_score is not None:
        results_msg += f"*JAMB Equivalent: {jamb_score}/400*\n"

    results_msg += (
        f"Time Taken: {time_taken_minutes} minutes\n\n"
        f"Performance by Subject:\n"
    )

    for subject, perf in subject_performance.items():
        subj_pct = round((perf['correct'] / perf['total']) * 100) if perf['total'] > 0 else 0
        bar = '█' * (subj_pct // 10) + '░' * (10 - subj_pct // 10)
        results_msg += f"{subject}: {perf['correct']}/{perf['total']} ({subj_pct}%)\n{bar}\n\n"

    await send_whatsapp_message(phone, results_msg)

    name = student.get('name', 'Student').split()[0]

    analysis_prompt = get_post_exam_analysis_prompt(
        student_name=name,
        exam_type=exam_type,
        score=correct_count,
        total=total,
        correct_topics=correct_topics,
        wrong_topics=wrong_topics,
        time_taken=time_taken_minutes
    )

    try:
        analysis = await ask_gemini(
            system_prompt="You are WaxPrep's exam analyst. Give honest, specific, encouraging feedback.",
            user_message=analysis_prompt,
            student_id=student['id']
        )
        await send_whatsapp_message(
            phone,
            f"Your Personal Analysis:\n\n{analysis}"
        )
    except Exception as e:
        print(f"Analysis generation error: {e}")

    # FIXED: Import from features.badges, not from whatsapp.handler
    await award_badge(student['id'], 'MOCK_FIRST')

    if percentage >= 80:
        await award_badge(student['id'], 'MOCK_SCORE_80')

    if percentage >= 100:
        await award_badge(student['id'], 'MOCK_PERFECT')

    points = settings.POINTS_MOCK_EXAM
    try:
        supabase.rpc('add_points_to_student', {
            'student_id_param': student['id'],
            'points_to_add': points
        }).execute()
    except Exception as e:
        print(f"Mock exam points error: {e}")

    await send_whatsapp_message(
        phone,
        f"You earned *{points} points* for completing a mock exam!\n\n"
        f"Type *EXAM* to take another mock, or ask me anything to continue studying."
    )


async def end_exam_early(phone: str, student: dict, conversation: dict, state: dict):
    """Ends an exam early when student types STOP EXAM."""
    total = len(state.get('questions', []))
    answered = state.get('current_question_index', 0)
    correct = state.get('correct_count', 0)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'default',
        'conversation_state': {},
    })

    await send_whatsapp_message(
        phone,
        f"Exam Ended Early\n\n"
        f"Answered: {answered}/{total} questions\n"
        f"Correct so far: {correct}\n\n"
        f"That's okay — stopping sometimes is the right call.\n"
        f"Type *EXAM* whenever you're ready to try a full exam again."
    )


async def ask_mock_exam_preferences(
    phone: str,
    student: dict,
    conversation: dict,
    suggested_exam_type: str
):
    """Asks the student what kind of mock exam they want."""

    subjects = student.get('subjects', ['Mathematics', 'English Language'])
    subjects_display = ', '.join(subjects[:4])

    msg = (
        f"Mock Exam Setup\n\n"
        f"Which exam simulation do you want?\n\n"
        f"1 — Full {suggested_exam_type} — {100 if suggested_exam_type == 'JAMB' else 40} questions, timed\n"
        f"   Subjects: {subjects_display}\n\n"
        f"2 — Quick Practice — 20 questions, no timer\n\n"
        f"3 — Subject Focus — 15 questions on one subject\n\n"
        f"Reply with 1, 2, or 3"
    )

    await send_whatsapp_message(phone, msg)
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            'awaiting_response_for': 'exam_setup_choice',
            'suggested_exam_type': suggested_exam_type,
        }
    })


async def ask_mini_mock_preferences(phone: str, student: dict, conversation: dict):
    """For free tier — offers a 10-question mini mock."""
    await send_whatsapp_message(
        phone,
        f"Mini Mock Exam (Free Tier)\n\n"
        f"I'll give you a 10-question practice set!\n\n"
        f"Which subject?\n\n" +
        '\n'.join([f"{i+1}. {s}" for i, s in enumerate(student.get('subjects', ['Mathematics', 'English Language'])[:5])]) +
        f"\n\nReply with the number"
    )

"""
Mock Exam Flow
"""

from whatsapp.sender import send_whatsapp_message
from database.questions import get_questions_for_mock_exam
from database.conversations import update_conversation_state
from database.client import supabase
from helpers import nigeria_now, format_naira
from features.quiz_engine import evaluate_quiz_answer
from config.settings import settings
import json


async def start_mock_exam(phone: str, student: dict, conversation: dict,
                           exam_type: str = None, subjects: list = None, num_questions: int = None):
    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free' and not status['is_trial']:
        await send_whatsapp_message(
            phone,
            f"Full mock exams are a Scholar Plan feature.\n\n"
            f"Scholar Plan gives you full JAMB/WAEC simulation (100 questions), complete score analysis, and 2 full mocks per week.\n\n"
            f"Upgrade for just {format_naira(settings.SCHOLAR_MONTHLY)}/month. Type SUBSCRIBE."
        )
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
        f"Preparing your {exam_type} mock exam...\nSelecting {num_questions} questions. Give me about 10 seconds..."
    )

    questions = await get_questions_for_mock_exam(exam_type, subjects_to_use, num_questions)

    if not questions:
        await send_whatsapp_message(
            phone,
            "Could not generate the mock exam right now — question bank for this combination is still building.\n\nTry again tomorrow or try a different subject combination."
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
    time_limit = 100 if exam_type == 'JAMB' else 60

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'exam',
        'conversation_state': {
            'awaiting_response_for': 'exam_answer',
            'exam_id': exam_id,
            'exam_type': exam_type,
            'questions': [q['id'] for q in questions],
            'current_question_index': 0,
            'answers': {},
            'correct_count': 0,
            'started_at': nigeria_now().isoformat(),
            'time_limit_minutes': time_limit,
        }
    })

    await send_whatsapp_message(
        phone,
        f"*{exam_type} Mock Exam — Starting Now!*\n\n"
        f"Questions: {len(questions)} | Time: {time_limit} minutes\n\n"
        f"Rules:\n"
        f"Answer with A, B, C, or D only\n"
        f"No going back to previous questions\n"
        f"Type STOP EXAM to end early\n\n"
        f"Clock starts NOW. Good luck!"
    )

    await send_exam_question(phone, questions[0], 1, len(questions))


async def handle_exam_setup_choice(phone: str, student: dict, conversation: dict,
                                    message: str, state: dict):
    choice = message.strip()
    suggested_type = state.get('suggested_exam_type', 'JAMB')

    if choice == '1':
        await start_mock_exam(phone, student, conversation, suggested_type)
    elif choice == '2':
        await start_mock_exam(phone, student, conversation, suggested_type, num_questions=20)
    elif choice == '3':
        await send_whatsapp_message(
            phone,
            "Which subject?\n\n" +
            '\n'.join([f"{i+1}. {s}" for i, s in enumerate(student.get('subjects', [])[:6])])
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {**state, 'awaiting_response_for': 'exam_subject_choice'}
        })
    else:
        await ask_mock_exam_preferences(phone, student, conversation, suggested_type)


async def send_exam_question(phone: str, question: dict, question_num: int, total: int):
    q_text = question.get('question_text', '')
    a = question.get('option_a', '')
    b = question.get('option_b', '')
    c = question.get('option_c', '')
    d = question.get('option_d', '')
    subject = question.get('subject', '')

    await send_whatsapp_message(
        phone,
        f"*[{question_num}/{total}]* _{subject}_\n\n"
        f"{q_text}\n\n"
        f"A. {a}\n"
        f"B. {b}\n"
        f"C. {c}\n"
        f"D. {d}"
    )


async def handle_exam_answer(phone: str, student: dict, conversation: dict, answer: str):
    from whatsapp.handler import _get_state
    state = _get_state(conversation)

    if answer.upper().strip() in ['STOP EXAM', 'STOP', 'END EXAM']:
        await end_exam_early(phone, student, conversation, state)
        return

    answer_clean = answer.strip().upper()
    if answer_clean not in ['A', 'B', 'C', 'D']:
        await send_whatsapp_message(
            phone,
            "In exam mode, reply with *A*, *B*, *C*, or *D* only.\n_(Type STOP EXAM to end early)_"
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
            'answer': answer_clean, 'correct': correct,
            'is_correct': is_correct, 'subject': question.get('subject', ''),
            'topic': question.get('topic', ''),
        }
        if is_correct:
            correct_count += 1

    next_index = current_index + 1
    state['current_question_index'] = next_index
    state['answers'] = answers
    state['correct_count'] = correct_count

    if next_index >= len(questions_ids):
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': state})
        await complete_exam(phone, student, conversation, state)
        return

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'conversation_state': state})

    next_q_result = supabase.table('questions').select('*').eq('id', questions_ids[next_index]).execute()
    if next_q_result.data:
        await send_exam_question(phone, next_q_result.data[0], next_index + 1, len(questions_ids))


async def complete_exam(phone: str, student: dict, conversation: dict, state: dict):
    from ai.gemini_client import ask_gemini
    from ai.prompts import get_post_exam_analysis_prompt
    from features.badges import award_badge

    answers = state.get('answers', {})
    total = len(state.get('questions', []))
    correct_count = state.get('correct_count', 0)
    exam_type = state.get('exam_type', 'JAMB')
    exam_id = state.get('exam_id')
    started_at_str = state.get('started_at')

    time_taken = 0
    if started_at_str:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        try:
            started = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
            time_taken = int((nigeria_now() - started).total_seconds() / 60)
        except Exception:
            pass

    percentage = round((correct_count / total) * 100, 1) if total > 0 else 0
    jamb_score = round((correct_count / total) * 400) if exam_type == 'JAMB' and total > 0 else None

    subject_performance = {}
    for q_id, ans_data in answers.items():
        subj = ans_data.get('subject', 'Unknown')
        if subj not in subject_performance:
            subject_performance[subj] = {'correct': 0, 'total': 0}
        subject_performance[subj]['total'] += 1
        if ans_data.get('is_correct'):
            subject_performance[subj]['correct'] += 1

    correct_topics = []
    wrong_topics = []
    for subj, perf in subject_performance.items():
        pct = round((perf['correct'] / perf['total']) * 100) if perf['total'] > 0 else 0
        (correct_topics if pct >= 60 else wrong_topics).append(f"{subj} ({pct}%)")

    if exam_id:
        try:
            supabase.table('mock_exams').update({
                'score': correct_count, 'percentage': percentage,
                'time_taken_minutes': time_taken, 'status': 'completed',
                'answers_data': answers, 'completed_at': nigeria_now().isoformat(),
            }).eq('id', exam_id).execute()
        except Exception:
            pass

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'default', 'conversation_state': {}
    })

    results_msg = f"*Exam Complete!*\n\n*Score: {correct_count}/{total} ({percentage}%)*\n"
    if jamb_score:
        results_msg += f"*JAMB Equivalent: {jamb_score}/400*\n"
    results_msg += f"Time: {time_taken} minutes\n\nBy Subject:\n"

    for subj, perf in subject_performance.items():
        pct = round((perf['correct'] / perf['total']) * 100) if perf['total'] > 0 else 0
        bar = '█' * (pct // 10) + '░' * (10 - pct // 10)
        results_msg += f"{subj}: {perf['correct']}/{perf['total']} ({pct}%)\n{bar}\n\n"

    await send_whatsapp_message(phone, results_msg)

    name = student.get('name', 'Student').split()[0]
    analysis_prompt = get_post_exam_analysis_prompt(
        name, exam_type, correct_count, total, correct_topics, wrong_topics, time_taken
    )
    try:
        analysis = await ask_gemini(
            system_prompt="You are WaxPrep's exam analyst. Be honest, specific, encouraging.",
            user_message=analysis_prompt,
            student_id=student['id']
        )
        await send_whatsapp_message(phone, f"*Your Analysis:*\n\n{analysis}")
    except Exception:
        pass

    await award_badge(student['id'], 'MOCK_FIRST')
    if percentage >= 80:
        await award_badge(student['id'], 'MOCK_SCORE_80')

    points = settings.POINTS_MOCK_EXAM
    try:
        supabase.rpc('add_points_to_student', {'student_id_param': student['id'], 'points_to_add': points}).execute()
    except Exception:
        pass

    await send_whatsapp_message(
        phone,
        f"+{points} points for completing a mock exam!\n\nType EXAM to take another, or just ask me anything to keep studying."
    )


async def end_exam_early(phone: str, student: dict, conversation: dict, state: dict):
    total = len(state.get('questions', []))
    answered = state.get('current_question_index', 0)
    correct = state.get('correct_count', 0)

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'default', 'conversation_state': {}
    })

    await send_whatsapp_message(
        phone,
        f"Exam ended early.\n\nAnswered {answered}/{total} | {correct} correct\n\nThat's okay. Type EXAM when you're ready to try again."
    )


async def ask_mock_exam_preferences(phone: str, student: dict, conversation: dict, suggested_exam_type: str):
    subjects = student.get('subjects', ['Mathematics', 'English Language'])
    subjects_display = ', '.join(subjects[:4])

    await send_whatsapp_message(
        phone,
        f"Mock Exam Setup\n\n"
        f"1 — Full {suggested_exam_type} ({100 if suggested_exam_type == 'JAMB' else 40} questions, timed)\n"
        f"   Subjects: {subjects_display}\n\n"
        f"2 — Quick Practice (20 questions, no timer)\n\n"
        f"3 — Subject Focus (15 questions on one subject)\n\n"
        f"Reply with 1, 2, or 3"
    )

    from whatsapp.handler import _get_state
    state = _get_state(conversation)
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {
            **state,
            'awaiting_response_for': 'exam_setup_choice',
            'suggested_exam_type': suggested_exam_type,
        }
    })

"""
Study Plan Generator

Creates personalized weekly study plans for each student.

The study plan is based on:
1. Days until the exam
2. Number of subjects
3. Current mastery scores (weak topics get more time)
4. Daily question limit for their tier
5. Study time preference

Plans are regenerated weekly or when significant progress is made.

The study plan appears when a student types PLAN.
It also influences which topics the AI focuses on.
"""

from database.client import supabase
from ai.gemini_client import ask_gemini
from helpers import nigeria_now, nigeria_today
from config.settings import settings
from datetime import datetime, timedelta


async def generate_study_plan(student: dict) -> dict:
    """
    Generates a personalized study plan for a student.
    Returns a dict with the plan data and saves it to the database.
    """
    student_id = student['id']
    subjects = student.get('subjects', [])
    exam_date = student.get('exam_date')
    target_exam = student.get('target_exam', 'JAMB')

    days_until_exam = 180
    if exam_date:
        try:
            exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
            days_until_exam = max(1, (exam_dt - datetime.now()).days)
        except Exception:
            pass

    mastery_result = supabase.table('mastery_scores')\
        .select('subject, topic, mastery_score, questions_attempted')\
        .eq('student_id', student_id)\
        .order('mastery_score', desc=False)\
        .execute()

    mastery_data = mastery_result.data or []

    weak_topics = [m for m in mastery_data if m['mastery_score'] < 60]
    strong_topics = [m for m in mastery_data if m['mastery_score'] >= 80]
    unstudied_subjects = [s for s in subjects if not any(m['subject'] == s for m in mastery_data)]

    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)
    tier = status['effective_tier']
    daily_limit = settings.get_daily_question_limit(tier, status['is_trial'])

    if daily_limit >= 9999:
        daily_target = 40
    else:
        daily_target = min(daily_limit, 40)

    plan_data = {
        'generated_at': nigeria_now().isoformat(),
        'exam_date': exam_date,
        'days_until_exam': days_until_exam,
        'daily_question_target': daily_target,
        'subjects': subjects,
        'weak_topics': [
            {'subject': m['subject'], 'topic': m['topic'], 'mastery': m['mastery_score']}
            for m in weak_topics[:5]
        ],
        'unstudied_subjects': unstudied_subjects,
        'study_allocation': {},
        'weekly_schedule': {},
    }

    if subjects:
        questions_per_subject = daily_target // len(subjects)

        for subject in subjects:
            subject_weak = [m for m in weak_topics if m['subject'] == subject]
            is_unstudied = subject in unstudied_subjects

            if is_unstudied or subject_weak:
                allocation = min(daily_target, questions_per_subject + 5)
            else:
                allocation = questions_per_subject

            plan_data['study_allocation'][subject] = allocation

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    for i, day in enumerate(days):
        if day == 'Sunday':
            plan_data['weekly_schedule'][day] = {
                'focus': 'Revision — Review your weakest topics from the week',
                'target_questions': daily_target // 2,
                'mode': 'revision'
            }
        elif day == 'Saturday':
            plan_data['weekly_schedule'][day] = {
                'focus': 'Mock Exam — Full practice test',
                'target_questions': daily_target,
                'mode': 'exam'
            }
        else:
            subject_index = i % len(subjects) if subjects else 0
            focus_subject = subjects[subject_index] if subjects else 'All subjects'

            plan_data['weekly_schedule'][day] = {
                'focus': f'{focus_subject} — Study and practice',
                'target_questions': daily_target,
                'mode': 'learn_and_quiz',
                'subject': focus_subject
            }

    try:
        supabase.table('study_plans').upsert({
            'student_id': student_id,
            'plan_data': plan_data,
            'daily_question_target': daily_target,
            'focus_subjects': subjects[:3] if subjects else [],
            'weak_topics': [m['topic'] for m in weak_topics[:5]],
            'is_active': True,
            'generated_at': nigeria_now().isoformat(),
            'valid_until': (nigeria_now() + timedelta(days=7)).isoformat(),
        }).execute()
    except Exception as e:
        print(f"Study plan save error: {e}")

    return plan_data


def format_study_plan_for_whatsapp(plan_data: dict, student_name: str) -> str:
    """Formats the study plan as a readable WhatsApp message."""
    name = student_name.split()[0]
    days_left = plan_data.get('days_until_exam', 0)
    daily_target = plan_data.get('daily_question_target', 20)
    weak_topics = plan_data.get('weak_topics', [])

    msg = f"Your Study Plan, {name}\n\n"

    if days_left:
        msg += f"{days_left} days until your exam\n\n"

    msg += f"Daily Target: {daily_target} questions\n\n"

    msg += "This Week:\n"
    schedule = plan_data.get('weekly_schedule', {})

    for day, info in schedule.items():
        focus = info.get('focus', '')
        msg += f"{day}: {focus}\n"

    if weak_topics:
        msg += "\nPriority Areas (Weak Topics):\n"
        for topic in weak_topics[:3]:
            subject = topic.get('subject', '')
            name_t = topic.get('topic', '')
            mastery = topic.get('mastery', 0)
            msg += f"- {subject}: {name_t} ({mastery:.0f}% mastery)\n"

    msg += (
        f"\nPlan updates weekly based on your progress.\n\n"
        f"Ready to study? Just ask me anything or type QUIZ [subject] to get started!"
    )

    return msg

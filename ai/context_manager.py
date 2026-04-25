"""
Student Context Manager

Builds rich, cached context for each student before AI calls.
This is what makes the AI feel like it truly knows the student.

Context includes:
- Performance data (accuracy, streak, level)
- Weak and strong topics from mastery scores
- Recent conversation subjects
- Learning style preferences
- Days until exam
- Current subscription status

All context is cached in Redis to avoid repeated DB calls.
"""

import json
from database.client import supabase, redis_client
from config.settings import settings
from helpers import nigeria_now


CONTEXT_TTL = 180  # 3 minutes — refresh frequently to stay accurate


async def get_full_student_context(student: dict) -> dict:
    """
    Returns complete student context for AI use.
    Checks Redis cache first. Falls back to DB if cache expired.
    """
    student_id = student.get('id', '')
    cache_key = f"ctx:{student_id}"

    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    context = await _build_context_from_db(student)

    try:
        redis_client.setex(cache_key, CONTEXT_TTL, json.dumps(context, default=str))
    except Exception:
        pass

    return context


async def _build_context_from_db(student: dict) -> dict:
    """Builds context dict from fresh database queries."""
    student_id = student.get('id', '')
    now = nigeria_now()

    context = {
        'weak_topics': [],
        'strong_topics': [],
        'unstudied_subjects': [],
        'days_until_exam': 0,
        'exam_date': None,
        'accuracy_overall': 0,
        'accuracy_trend': 'stable',
        'session_count': 0,
        'preferred_difficulty': 5,
        'learning_style': 'balanced',
        'most_studied_subject': None,
        'least_studied_subject': None,
        'spaced_repetition_due': [],
    }

    try:
        # Mastery scores — weak and strong topics
        mastery = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score, elo_rating, questions_attempted, next_review_at')\
            .eq('student_id', student_id)\
            .execute()

        mastery_data = mastery.data or []

        if mastery_data:
            sorted_by_mastery = sorted(mastery_data, key=lambda x: x.get('mastery_score', 50))

            context['weak_topics'] = [
                {
                    'subject': m['subject'],
                    'topic': m['topic'],
                    'mastery': round(m.get('mastery_score', 0), 1),
                    'elo': m.get('elo_rating', 1200),
                }
                for m in sorted_by_mastery[:5]
                if m.get('mastery_score', 100) < 60
            ]

            context['strong_topics'] = [
                {
                    'subject': m['subject'],
                    'topic': m['topic'],
                    'mastery': round(m.get('mastery_score', 0), 1),
                }
                for m in sorted_by_mastery
                if m.get('mastery_score', 0) >= 80
            ][:3]

            # Spaced repetition: topics due for review
            context['spaced_repetition_due'] = [
                f"{m['topic']} ({m['subject']})"
                for m in mastery_data
                if m.get('next_review_at') and m['next_review_at'] <= now.isoformat()
                and 20 <= m.get('mastery_score', 0) <= 85
            ][:3]

            # Most and least studied subjects
            subject_attempts = {}
            for m in mastery_data:
                subj = m.get('subject', '')
                subject_attempts[subj] = subject_attempts.get(subj, 0) + m.get('questions_attempted', 0)

            if subject_attempts:
                context['most_studied_subject'] = max(subject_attempts, key=subject_attempts.get)
                context['least_studied_subject'] = min(subject_attempts, key=subject_attempts.get)

        # Unstudied subjects
        all_subjects = student.get('subjects', [])
        studied_subjects = {m.get('subject') for m in mastery_data}
        context['unstudied_subjects'] = [s for s in all_subjects if s not in studied_subjects]

        # Days until exam
        exam_date = student.get('exam_date')
        if exam_date:
            from datetime import datetime
            try:
                exam_dt = datetime.strptime(str(exam_date)[:10], '%Y-%m-%d')
                days = (exam_dt - now.replace(tzinfo=None)).days
                context['days_until_exam'] = max(0, days)
                context['exam_date'] = str(exam_date)[:10]
            except Exception:
                pass

        # Overall accuracy
        answered = student.get('total_questions_answered', 0)
        correct = student.get('total_questions_correct', 0)
        if answered > 0:
            context['accuracy_overall'] = round((correct / answered) * 100, 1)

        # Preferred difficulty based on accuracy
        acc = context['accuracy_overall']
        if acc > 80:
            context['preferred_difficulty'] = 8
        elif acc > 65:
            context['preferred_difficulty'] = 6
        elif acc > 45:
            context['preferred_difficulty'] = 4
        else:
            context['preferred_difficulty'] = 2

        # Learning style based on usage patterns
        language_pref = student.get('language_preference', 'english')
        context['learning_style'] = 'pidgin' if language_pref == 'pidgin' else 'english'

    except Exception as e:
        print(f"Context build error: {e}")

    return context


def invalidate_context(student_id: str):
    """Clears cached context — call this after updating mastery or student profile."""
    try:
        redis_client.delete(f"ctx:{student_id}")
    except Exception:
        pass


def format_context_for_prompt(context: dict) -> str:
    """Converts context dict into a compact string for injection into prompts."""
    parts = []

    if context.get('weak_topics'):
        weak_str = ', '.join([
            f"{t['topic']} ({t['subject']}, {t['mastery']}% mastery)"
            for t in context['weak_topics'][:3]
        ])
        parts.append(f"WEAK AREAS (prioritize these): {weak_str}")

    if context.get('strong_topics'):
        strong_str = ', '.join([t['topic'] for t in context['strong_topics'][:2]])
        parts.append(f"STRONG AREAS: {strong_str}")

    if context.get('days_until_exam') and context['days_until_exam'] > 0:
        parts.append(f"DAYS UNTIL EXAM: {context['days_until_exam']}")

    if context.get('spaced_repetition_due'):
        due_str = ', '.join(context['spaced_repetition_due'][:2])
        parts.append(f"DUE FOR REVIEW (spaced repetition): {due_str}")

    if context.get('unstudied_subjects'):
        parts.append(f"NOT YET STUDIED: {', '.join(context['unstudied_subjects'][:2])}")

    if context.get('accuracy_overall'):
        parts.append(f"OVERALL ACCURACY: {context['accuracy_overall']}%")

    return '\n'.join(parts) if parts else ""

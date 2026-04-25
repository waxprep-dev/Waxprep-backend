"""
Adaptive Learning Engine

Adjusts question difficulty, topic suggestions, and AI tone
based on real-time student performance.

This is what makes WaxPrep feel like it truly understands
how the student learns — not just what they know.
"""

from database.client import supabase, redis_client


async def get_adaptive_difficulty(student_id: str, subject: str, topic: str = '') -> tuple[int, int]:
    """
    Returns (difficulty_min, difficulty_max) for a student's next question.
    Based on their Elo rating for this subject/topic.
    """
    try:
        query = supabase.table('mastery_scores')\
            .select('elo_rating, mastery_score, questions_attempted')\
            .eq('student_id', student_id)\
            .eq('subject', subject)

        if topic:
            query = query.eq('topic', topic)

        result = query.execute()

        if result.data:
            elo = result.data[0].get('elo_rating', 1200)
            mastery = result.data[0].get('mastery_score', 50)
        else:
            elo = 1200
            mastery = 50

    except Exception:
        elo = 1200
        mastery = 50

    # Map Elo to difficulty range
    if elo < 800:
        return 1, 3
    elif elo < 1000:
        return 2, 4
    elif elo < 1100:
        return 3, 5
    elif elo < 1200:
        return 4, 6
    elif elo < 1350:
        return 5, 7
    elif elo < 1500:
        return 6, 8
    else:
        return 7, 10


async def get_next_suggested_topic(student_id: str, subjects: list) -> dict | None:
    """
    Suggests the next topic the student should study.
    Priority order:
    1. Spaced repetition topics due for review
    2. Weak topics (low mastery, not recently studied)
    3. Unstudied subjects
    4. Random from subjects list
    """
    from helpers import nigeria_now

    now = nigeria_now()

    try:
        # 1. Spaced repetition: topics due for review
        due = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score, elo_rating')\
            .eq('student_id', student_id)\
            .lte('next_review_at', now.isoformat())\
            .gte('mastery_score', 20)\
            .lt('mastery_score', 85)\
            .order('next_review_at', desc=False)\
            .limit(3)\
            .execute()

        if due.data:
            import random
            return random.choice(due.data)

        # 2. Weak topics not recently studied
        weak = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score, elo_rating, last_studied_at')\
            .eq('student_id', student_id)\
            .lt('mastery_score', 50)\
            .order('mastery_score', desc=False)\
            .limit(5)\
            .execute()

        if weak.data:
            import random
            return random.choice(weak.data[:3])

        # 3. Unstudied subjects
        studied_subjects = {m['subject'] for m in (
            supabase.table('mastery_scores')
            .select('subject')
            .eq('student_id', student_id)
            .execute()
            .data or []
        )}

        unstudied = [s for s in subjects if s not in studied_subjects]
        if unstudied:
            import random
            return {'subject': random.choice(unstudied), 'topic': None}

        # 4. Fallback: random subject
        if subjects:
            import random
            return {'subject': random.choice(subjects), 'topic': None}

    except Exception as e:
        print(f"Next topic suggestion error: {e}")

    return None


def calculate_new_elo(student_elo: int, question_difficulty: int, is_correct: bool) -> int:
    """Calculates new Elo rating using the standard Elo formula."""
    K = 32
    question_elo = 800 + (question_difficulty * 120)
    expected = 1 / (1 + 10 ** ((question_elo - student_elo) / 400))
    actual = 1.0 if is_correct else 0.0
    new_elo = student_elo + K * (actual - expected)
    return max(400, min(2800, int(new_elo)))


async def record_interaction_outcome(
    student_id: str,
    subject: str,
    topic: str,
    difficulty: int,
    is_correct: bool
):
    """
    Records the outcome of a student interaction and updates mastery.
    Called after every quiz answer.
    """
    from helpers import nigeria_now
    from ai.context_manager import invalidate_context
    from datetime import timedelta

    now = nigeria_now()

    try:
        # Get current mastery
        existing = supabase.table('mastery_scores')\
            .select('id, elo_rating, mastery_score, questions_attempted, questions_correct')\
            .eq('student_id', student_id)\
            .eq('subject', subject)\
            .eq('topic', topic)\
            .execute()

        current_elo = existing.data[0].get('elo_rating', 1200) if existing.data else 1200
        new_elo = calculate_new_elo(current_elo, difficulty, is_correct)
        mastery_score = min(100, max(0, (new_elo - 400) / 16))

        # Calculate next review date based on mastery (spaced repetition)
        if mastery_score < 30:
            next_review_days = 1
        elif mastery_score < 50:
            next_review_days = 2
        elif mastery_score < 65:
            next_review_days = 4
        elif mastery_score < 80:
            next_review_days = 7
        else:
            next_review_days = 14

        next_review_at = (now + timedelta(days=next_review_days)).isoformat()

        if existing.data:
            record = existing.data[0]
            new_attempted = record.get('questions_attempted', 0) + 1
            new_correct = record.get('questions_correct', 0) + (1 if is_correct else 0)

            supabase.table('mastery_scores').update({
                'elo_rating': new_elo,
                'mastery_score': round(mastery_score, 2),
                'questions_attempted': new_attempted,
                'questions_correct': new_correct,
                'last_studied_at': now.isoformat(),
                'next_review_at': next_review_at,
                'updated_at': now.isoformat(),
            }).eq('id', record['id']).execute()
        else:
            supabase.table('mastery_scores').insert({
                'student_id': student_id,
                'subject': subject,
                'topic': topic,
                'elo_rating': new_elo,
                'mastery_score': round(mastery_score, 2),
                'questions_attempted': 1,
                'questions_correct': 1 if is_correct else 0,
                'last_studied_at': now.isoformat(),
                'next_review_at': next_review_at,
            }).execute()

        # Invalidate context cache so next message gets fresh data
        invalidate_context(student_id)

    except Exception as e:
        print(f"Record interaction outcome error: {e}")

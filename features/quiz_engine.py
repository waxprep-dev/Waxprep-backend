"""
Quiz Engine

Handles quiz logic, Elo ratings, question selection, and scoring.
NO imports from whatsapp.handler — that would create a circular import.
Badge awarding is done by passing a callback or handled by the caller.
"""

import random
from database.client import supabase
from config.settings import settings


# ============================================================
# QUESTION SELECTION
# ============================================================

async def get_question_for_student(
    student_id: str,
    subject: str,
    topic: str = None,
    exam_type: str = None
) -> dict | None:
    """
    Selects the best question for a student based on their Elo rating.
    Falls back to AI generation if question bank is empty for this topic.
    """
    elo = await get_student_elo(student_id, subject, topic or '')

    # Convert Elo to difficulty range
    if elo < 900:
        diff_min, diff_max = 1, 3
    elif elo < 1100:
        diff_min, diff_max = 3, 5
    elif elo < 1300:
        diff_min, diff_max = 5, 7
    elif elo < 1500:
        diff_min, diff_max = 7, 8
    else:
        diff_min, diff_max = 8, 10

    # Get recently seen question IDs to avoid repeats
    seen_ids = await get_student_recently_seen_questions(student_id)

    query = supabase.table('questions')\
        .select('*')\
        .eq('subject', subject)\
        .eq('is_active', True)\
        .gte('difficulty_level', diff_min)\
        .lte('difficulty_level', diff_max)

    if topic:
        query = query.ilike('topic', f'%{topic}%')
    if exam_type:
        query = query.eq('exam_type', exam_type)

    result = query.order('quality_score', desc=True).limit(15).execute()
    questions = result.data or []

    # Filter out recently seen
    if seen_ids and questions:
        questions = [q for q in questions if str(q.get('id', '')) not in seen_ids]

    if questions:
        random.shuffle(questions)
        return questions[0]

    # No questions in bank — generate with AI
    if topic:
        try:
            from ai.gemini_client import generate_questions_with_gemini
            generated = await generate_questions_with_gemini(
                subject=subject,
                topic=topic,
                exam_type=exam_type or 'JAMB',
                difficulty=(diff_min + diff_max) // 2,
                count=3
            )
            if generated:
                return generated[0]
        except Exception as e:
            print(f"Question generation error: {e}")

    return None


async def get_student_elo(student_id: str, subject: str, topic: str) -> int:
    """Gets a student's Elo rating for a topic. Returns 1200 (average) if not found."""
    try:
        result = supabase.table('mastery_scores')\
            .select('elo_rating')\
            .eq('student_id', student_id)\
            .eq('subject', subject)\
            .eq('topic', topic)\
            .execute()

        if result.data:
            return result.data[0].get('elo_rating', 1200)
    except Exception:
        pass

    return 1200


def calculate_new_elo(student_elo: int, question_difficulty: int, is_correct: bool) -> int:
    """Calculates new Elo rating after answering a question."""
    K = 32
    question_elo = 800 + (question_difficulty * 120)
    expected = 1 / (1 + 10 ** ((question_elo - student_elo) / 400))
    actual = 1.0 if is_correct else 0.0
    new_elo = student_elo + K * (actual - expected)
    return max(400, min(2800, int(new_elo)))


async def update_mastery_after_answer(
    student_id: str,
    subject: str,
    topic: str,
    question_difficulty: int,
    is_correct: bool
):
    """Updates mastery score and Elo after a student answers a question."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos")).isoformat()
    current_elo = await get_student_elo(student_id, subject, topic)
    new_elo = calculate_new_elo(current_elo, question_difficulty, is_correct)
    mastery_score = min(100, max(0, (new_elo - 400) / 16))

    try:
        existing = supabase.table('mastery_scores')\
            .select('id, questions_attempted, questions_correct')\
            .eq('student_id', student_id)\
            .eq('subject', subject)\
            .eq('topic', topic)\
            .execute()

        if existing.data:
            current = existing.data[0]
            new_attempted = current['questions_attempted'] + 1
            new_correct = current['questions_correct'] + (1 if is_correct else 0)

            supabase.table('mastery_scores').update({
                'elo_rating': new_elo,
                'mastery_score': round(mastery_score, 2),
                'questions_attempted': new_attempted,
                'questions_correct': new_correct,
                'last_studied_at': now,
                'updated_at': now,
            }).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('mastery_scores').insert({
                'student_id': student_id,
                'subject': subject,
                'topic': topic,
                'elo_rating': new_elo,
                'mastery_score': round(mastery_score, 2),
                'questions_attempted': 1,
                'questions_correct': 1 if is_correct else 0,
                'last_studied_at': now,
            }).execute()

    except Exception as e:
        print(f"Mastery update error: {e}")


def format_question_for_whatsapp(question: dict, question_number: int = 1) -> str:
    """Formats a question for WhatsApp display."""
    q_text = question.get('question_text', '')
    a = question.get('option_a', '')
    b = question.get('option_b', '')
    c = question.get('option_c', '')
    d = question.get('option_d', '')
    subject = question.get('subject', '')
    topic = question.get('topic', '')
    difficulty = question.get('difficulty_level', 5)

    stars = '⭐' * min(5, max(1, difficulty // 2))

    return (
        f"❓ *Question {question_number}* {stars}\n"
        f"_{subject} — {topic}_\n\n"
        f"{q_text}\n\n"
        f"*A.* {a}\n"
        f"*B.* {b}\n"
        f"*C.* {c}\n"
        f"*D.* {d}\n\n"
        f"_Reply with A, B, C, or D_"
    )


def evaluate_quiz_answer(
    student_answer: str,
    correct_answer: str,
    question: dict
) -> tuple:
    """
    Evaluates a student's answer.
    Returns (is_correct: bool | None, feedback: str)
    Returns (None, message) if answer couldn't be parsed.
    """
    import random

    student_ans = student_answer.strip().upper()

    # Parse the answer
    answer_map = {'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D'}
    actual_answer = None

    if student_ans in answer_map:
        actual_answer = student_ans
    elif student_ans.startswith(('A.', 'A)', '(A)')):
        actual_answer = 'A'
    elif student_ans.startswith(('B.', 'B)', '(B)')):
        actual_answer = 'B'
    elif student_ans.startswith(('C.', 'C)', '(C)')):
        actual_answer = 'C'
    elif student_ans.startswith(('D.', 'D)', '(D)')):
        actual_answer = 'D'
    else:
        return None, "Please reply with just *A*, *B*, *C*, or *D* to answer the question."

    correct = correct_answer.strip().upper()
    is_correct = actual_answer == correct

    option_map = {
        'A': question.get('option_a', ''),
        'B': question.get('option_b', ''),
        'C': question.get('option_c', ''),
        'D': question.get('option_d', ''),
    }

    correct_text = option_map.get(correct, '')
    correct_explanation = (
        question.get('explanation_correct') or
        question.get(f'explanation_{correct.lower()}', '') or
        ''
    )

    almost_messages = [
        "Almost! You were right about part of it 💪",
        "Close — you're thinking about it the right way, just one piece shifted",
        "Good thinking — let me show you where it went a slightly different direction",
        "You're on the right track! Small adjustment needed 🎯",
    ]

    correct_messages = [
        "Excellent! That's exactly right! 🎉",
        "Perfect! You nailed it! ⭐",
        "Correct! Outstanding! 🏆",
        "That's exactly it! Well done! 🌟",
    ]

    if is_correct:
        feedback = f"{random.choice(correct_messages)}\n\n*Correct: {correct}. {correct_text}*\n\n"
        if correct_explanation:
            feedback += f"💡 *Why?*\n{correct_explanation}"
    else:
        wrong_explanation = question.get(f'explanation_{actual_answer.lower()}', '')
        feedback = (
            f"{random.choice(almost_messages)}\n\n"
            f"You chose: *{actual_answer}. {option_map.get(actual_answer, '')}*\n"
            f"Correct: *{correct}. {correct_text}*\n\n"
        )
        if correct_explanation:
            feedback += f"💡 *Why {correct} is correct:*\n{correct_explanation}\n\n"
        if wrong_explanation:
            feedback += f"❌ *Why {actual_answer} is wrong:*\n{wrong_explanation}"

    return is_correct, feedback


async def calculate_and_award_points(
    student_id: str,
    is_correct: bool,
    question_difficulty: int = 5,
    is_daily_challenge: bool = False
) -> tuple:
    """
    Calculates and awards points.
    Returns (points_earned: int, badge_awarded: dict | None)
    """
    if is_correct:
        base = settings.POINTS_CORRECT_ANSWER
        bonus = (question_difficulty - 5) * 2
        points = max(5, base + bonus)
        if is_daily_challenge:
            points += settings.POINTS_DAILY_CHALLENGE_WIN
    else:
        points = settings.POINTS_WRONG_ATTEMPT
        if is_daily_challenge:
            points = settings.POINTS_DAILY_CHALLENGE_ATTEMPT

    try:
        supabase.rpc('add_points_to_student', {
            'student_id_param': student_id,
            'points_to_add': points
        }).execute()
    except Exception as e:
        print(f"Points award error: {e}")

    # Check for milestone badges
    badge = None
    try:
        student_result = supabase.table('students')\
            .select('total_questions_answered')\
            .eq('id', student_id).execute()

        if student_result.data:
            total = student_result.data[0].get('total_questions_answered', 0)
            badge_map = {1: 'FIRST_QUESTION', 100: 'QUESTIONS_100',
                        500: 'QUESTIONS_500', 1000: 'QUESTIONS_1000'}

            if total in badge_map:
                badge = await _award_badge_internal(student_id, badge_map[total])
    except Exception as e:
        print(f"Badge check error: {e}")

    return points, badge


async def _award_badge_internal(student_id: str, badge_code: str) -> dict | None:
    """
    Internal badge awarding — no import from whatsapp.handler.
    This avoids the circular import.
    """
    try:
        badge_result = supabase.table('badges').select('*').eq('badge_code', badge_code).execute()
        if not badge_result.data:
            return None

        badge = badge_result.data[0]

        existing = supabase.table('student_badges')\
            .select('id')\
            .eq('student_id', student_id)\
            .eq('badge_id', badge['id'])\
            .execute()

        if existing.data:
            return None

        supabase.table('student_badges').insert({
            'student_id': student_id,
            'badge_id': badge['id'],
        }).execute()

        try:
            supabase.rpc('add_points_to_student', {
                'student_id_param': student_id,
                'points_to_add': badge.get('points_awarded', 50)
            }).execute()
        except Exception:
            pass

        return badge

    except Exception as e:
        print(f"Badge award error: {e}")
        return None


async def get_student_recently_seen_questions(student_id: str, limit: int = 50) -> list:
    """Gets recently seen question IDs from Redis cache."""
    try:
        from database.client import redis_client
        cache_key = f"seen_questions:{student_id}"
        cached = redis_client.lrange(cache_key, 0, limit - 1)
        return [q.decode() if isinstance(q, bytes) else q for q in cached]
    except Exception:
        return []


async def record_question_seen(student_id: str, question_id: str):
    """Records that a student has seen a question."""
    try:
        from database.client import redis_client
        cache_key = f"seen_questions:{student_id}"
        redis_client.lpush(cache_key, str(question_id))
        redis_client.ltrim(cache_key, 0, 99)
        redis_client.expire(cache_key, 86400 * 7)
    except Exception:
        pass


def extract_subject_from_message(message: str) -> str | None:
    """Extracts a subject name from a message like 'quiz me on Physics'."""
    import re

    subject_map = {
        r'\bmath(s|ematics)?\b': 'Mathematics',
        r'\bphysics?\b': 'Physics',
        r'\bchem(istry)?\b': 'Chemistry',
        r'\bbio(logy)?\b': 'Biology',
        r'\benglish\b': 'English Language',
        r'\beconom(ics|y)\b': 'Economics',
        r'\bgovernment?\b': 'Government',
        r'\blit(erature)?\b': 'Literature in English',
        r'\bgeo(graphy)?\b': 'Geography',
        r'\bcommerce?\b': 'Commerce',
        r'\bagric(ultural science)?\b': 'Agricultural Science',
        r'\bfurther math(s|ematics)?\b': 'Further Mathematics',
        r'\bhistory\b': 'History',
        r'\byoruba\b': 'Yoruba',
        r'\bigbo\b': 'Igbo',
        r'\bhausa\b': 'Hausa',
    }

    msg_lower = message.lower()
    for pattern, subject in subject_map.items():
        if re.search(pattern, msg_lower):
            return subject

    return None


def extract_topic_from_message(message: str) -> str | None:
    """Extracts a specific topic from a message like 'quiz me on Newton's Laws in Physics'."""
    import re

    # Look for "on [topic]" or "about [topic]" patterns
    patterns = [
        r'(?:quiz\s+(?:me\s+)?on|test\s+(?:me\s+)?on|about|regarding|on)\s+(?:the\s+)?([A-Za-z\'s\s]+?)(?:\s+in\s+\w+|$|\?)',
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            topic = match.group(1).strip()
            # Don't return if it's just a subject name
            if len(topic) > 3 and topic.lower() not in [
                'physics', 'chemistry', 'biology', 'mathematics', 'english',
                'economics', 'government', 'geography', 'commerce', 'history'
            ]:
                return topic

    return None

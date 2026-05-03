"""
Question Bank Fetcher — pulls real past questions from Supabase.
Returns None if no questions exist for the requested subject; the caller falls back to AI.
"""

import random
from database.client import supabase


async def get_real_question(subject: str) -> dict | None:
    """
    Fetch one random verified question for the given subject.
    Returns a dict compatible with the quiz engine, or None.
    """
    subject_lower = subject.lower().strip()
    try:
        result = supabase.table("questions") \
            .select("*") \
            .eq("subject", subject_lower) \
            .eq("verified", True) \
            .execute()
        if not result.data:
            return None

        q = random.choice(result.data)
        return {
            "question": q.get("question_text", ""),
            "a": q.get("option_a", ""),
            "b": q.get("option_b", ""),
            "c": q.get("option_c", ""),
            "d": q.get("option_d", ""),
            "correct": q.get("correct_answer", "").upper(),
            "explanation": q.get("explanation", "") or q.get("explanation_correct", ""),
            "subject": subject_lower,
            "topic": q.get("topic", "General"),
            "difficulty_level": 5,
            "source": "past_question",
        }
    except Exception as e:
        print(f"Question bank fetch error: {e}")
        return None

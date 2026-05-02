"""
Recent Questions Tracker — prevents AI from repeating questions.
Stores the last 10 question texts per student in Redis.
"""

import json
from database.client import redis_client

MAX_RECENT = 10
TTL_SECONDS = 3600  # 1 hour


def _key(student_id: str) -> str:
    return f"recent_questions:{student_id}"


def add_recent_question(student_id: str, question_text: str):
    """Add a question text to the student's recent list."""
    if not question_text or not student_id:
        return
    try:
        raw = redis_client.get(_key(student_id))
        recent = json.loads(raw) if raw else []
        # Remove if already exists (avoid duplicates in list)
        recent = [q for q in recent if q != question_text]
        recent.append(question_text)
        # Keep only the last MAX_RECENT
        if len(recent) > MAX_RECENT:
            recent = recent[-MAX_RECENT:]
        redis_client.setex(_key(student_id), TTL_SECONDS, json.dumps(recent))
    except Exception as e:
        print(f"Add recent question error: {e}")


def get_recent_questions(student_id: str) -> list:
    """Return the list of recently asked questions for this student."""
    try:
        raw = redis_client.get(_key(student_id))
        return json.loads(raw) if raw else []
    except Exception as e:
        print(f"Get recent questions error: {e}")
        return []

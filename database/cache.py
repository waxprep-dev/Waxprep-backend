"""
Centralized caching layer.
All Redis caching goes through here for consistency.
This is the primary speed layer — keeping response times under 2 seconds.
"""

import json
from database.client import redis_client
from config.settings import settings


def _safe_json(obj) -> str:
    return json.dumps(obj, default=str)


def _safe_loads(data: str) -> dict | None:
    try:
        return json.loads(data)
    except Exception:
        return None


# ── Student Profile Cache ──────────────────────────────────────────────────

def cache_student(student: dict):
    """Cache student profile for 5 minutes."""
    student_id = student.get('id')
    if not student_id:
        return
    try:
        redis_client.setex(
            f"student:{student_id}",
            settings.STUDENT_CACHE_TTL,
            _safe_json(student)
        )
    except Exception:
        pass


def get_cached_student(student_id: str) -> dict | None:
    try:
        data = redis_client.get(f"student:{student_id}")
        return _safe_loads(data) if data else None
    except Exception:
        return None


def invalidate_student_cache(student_id: str):
    try:
        redis_client.delete(f"student:{student_id}")
    except Exception:
        pass


def cache_student_by_phone(phone: str, student_id: str):
    """Map phone → student_id for fast lookup."""
    try:
        redis_client.setex(
            f"phone_student:{phone}",
            settings.STUDENT_CACHE_TTL,
            student_id
        )
    except Exception:
        pass


def get_student_id_by_phone(phone: str) -> str | None:
    try:
        return redis_client.get(f"phone_student:{phone}")
    except Exception:
        return None


# ── Conversation State Cache ───────────────────────────────────────────────

def cache_conversation(platform: str, platform_user_id: str, conversation: dict):
    key = f"conv:{platform}:{platform_user_id}"
    try:
        redis_client.setex(key, settings.CONVERSATION_CACHE_TTL, _safe_json(conversation))
    except Exception:
        pass


def get_cached_conversation(platform: str, platform_user_id: str) -> dict | None:
    key = f"conv:{platform}:{platform_user_id}"
    try:
        data = redis_client.get(key)
        return _safe_loads(data) if data else None
    except Exception:
        return None


def invalidate_conversation(platform: str, platform_user_id: str):
    try:
        redis_client.delete(f"conv:{platform}:{platform_user_id}")
    except Exception:
        pass


# ── Session State Cache ────────────────────────────────────────────────────

def set_session_state(phone: str, state: dict, ttl: int = None):
    key = f"session:{phone}"
    ttl = ttl or settings.SESSION_CACHE_TTL
    try:
        redis_client.setex(key, ttl, _safe_json(state))
    except Exception:
        pass


def get_session_state(phone: str) -> dict | None:
    try:
        data = redis_client.get(f"session:{phone}")
        return _safe_loads(data) if data else None
    except Exception:
        return None


def clear_session_state(phone: str):
    try:
        redis_client.delete(f"session:{phone}")
    except Exception:
        pass


# ── Question Cache ─────────────────────────────────────────────────────────

def cache_question_set(cache_key: str, questions: list, ttl: int = None):
    ttl = ttl or settings.QUESTION_CACHE_TTL
    try:
        redis_client.setex(cache_key, ttl, _safe_json(questions))
    except Exception:
        pass


def get_cached_question_set(cache_key: str) -> list | None:
    try:
        data = redis_client.get(cache_key)
        if data:
            result = _safe_loads(data)
            return result if isinstance(result, list) else None
        return None
    except Exception:
        return None


# ── Seen Questions (avoid repetition) ─────────────────────────────────────

def mark_question_seen(student_id: str, question_id: str):
    key = f"seen_q:{student_id}"
    try:
        redis_client.lpush(key, str(question_id))
        redis_client.ltrim(key, 0, 149)
        redis_client.expire(key, 86400 * 7)
    except Exception:
        pass


def get_seen_questions(student_id: str) -> list:
    key = f"seen_q:{student_id}"
    try:
        items = redis_client.lrange(key, 0, 149)
        return [q for q in items] if items else []
    except Exception:
        return []


# ── Deduplication ──────────────────────────────────────────────────────────

def is_message_processed(message_id: str) -> bool:
    key = f"msg_done:{message_id}"
    try:
        result = redis_client.set(key, "1", nx=True, ex=300)
        return result is None
    except Exception:
        return False


# ── AI Budget ─────────────────────────────────────────────────────────────

def increment_ai_cost(cost: float, date_str: str):
    key = f"ai_cost:{date_str}"
    try:
        redis_client.incrbyfloat(key, cost)
        redis_client.expire(key, 86400 * 2)
    except Exception:
        pass


def get_ai_cost(date_str: str) -> float:
    try:
        val = redis_client.get(f"ai_cost:{date_str}")
        return float(val) if val else 0.0
    except Exception:
        return 0.0


# ── Rate Limiting ──────────────────────────────────────────────────────────

def check_rate_limit(key: str, max_calls: int, window_seconds: int) -> bool:
    """Returns True if call is allowed, False if rate limited."""
    try:
        current = redis_client.get(key)
        if current and int(current) >= max_calls:
            return False
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        pipe.execute()
        return True
    except Exception:
        return True


# ── Failed PIN Attempts ────────────────────────────────────────────────────

def record_failed_pin(student_id: str) -> int:
    key = f"failed_pin:{student_id}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, 1800)
        return int(count)
    except Exception:
        return 0


def get_failed_pin_count(student_id: str) -> int:
    try:
        val = redis_client.get(f"failed_pin:{student_id}")
        return int(val) if val else 0
    except Exception:
        return 0


def clear_failed_pins(student_id: str):
    try:
        redis_client.delete(f"failed_pin:{student_id}")
    except Exception:
        pass


# ── Admin Mode Toggle ─────────────────────────────────────────────────────

def set_admin_student_mode(phone: str, enabled: bool):
    key = f"admin_student_mode:{phone}"
    try:
        if enabled:
            redis_client.setex(key, 3600, "1")
        else:
            redis_client.delete(key)
    except Exception:
        pass


def is_admin_in_student_mode(phone: str) -> bool:
    try:
        return redis_client.get(f"admin_student_mode:{phone}") is not None
    except Exception:
        return False


# ── Bonus Questions ────────────────────────────────────────────────────────

def get_bonus_questions(student_id: str) -> int:
    try:
        val = redis_client.get(f"bonus_questions:{student_id}")
        return int(val) if val else 0
    except Exception:
        return 0


def set_bonus_questions(student_id: str, count: int, days: int):
    try:
        redis_client.setex(f"bonus_questions:{student_id}", days * 86400, str(count))
    except Exception:
        pass

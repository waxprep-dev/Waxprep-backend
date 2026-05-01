"""
Silent Diagnosis Engine — Phase 3
Tracks student signals (hesitation, confusion) without asking questions.
"""
import re

HESITATION_PHRASES = [
    "i don't understand", "i dont understand", "i no understand",
    "i'm confused", "im confused", "i am confused",
    "explain again", "explain differently", "rephrase",
    "still confused", "i don't get it", "i dont get it",
    "can you explain", "try another way", "make it simpler",
    "break it down", "i'm lost", "im lost", "not clear",
    "that doesn't make sense", "that doesnt make sense",
    "i didn't get that", "i didnt get that", "e too hard",
    "i'm not following", "im not following", "help me understand"
]

def detect_hesitation(message: str) -> bool:
    """Returns True if the message contains hesitation language."""
    # Clean punctuation and normalize whitespace
    clean_message = re.sub(r'[^\w\s]', '', message.lower()).strip()
    return any(phrase in clean_message for phrase in HESITATION_PHRASES)

async def log_signal(
    student_id: str,
    subject: str,
    topic: str,
    signal_type: str,
    value: str = None,
):
    """Logs a signal to the student_signals table."""
    from database.client import supabase

    try:
        supabase.table("student_signals").insert({
            "student_id": student_id,
            "subject": subject or "general",
            "topic": topic or "general",
            "signal_type": signal_type,
            "value": value,
        }).execute()
    except Exception as e:
        print(f"Signal log error: {e}")

async def count_recent_hesitations(
    student_id: str,
    subject: str,
    topic: str,
    minutes: int = 30,
) -> int:
    """Returns how many hesitation signals exist for this student/topic recently."""
    from database.client import supabase
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    try:
        result = supabase.table("student_signals") \
            .select("id", count="exact") \
            .eq("student_id", student_id) \
            .eq("subject", subject) \
            .eq("topic", topic) \
            .eq("signal_type", "hesitation") \
            .gte("created_at", cutoff) \
            .execute()
        return result.count if result.count else 0
    except Exception as e:
        print(f"Hesitation count error: {e}")
        return 0

async def log_understanding(student_id: str, subject: str, topic: str):
    """Optional: Call this when a student says 'I get it' to balance the data."""
    await log_signal(student_id, subject, topic, "comprehension", "aha_moment")

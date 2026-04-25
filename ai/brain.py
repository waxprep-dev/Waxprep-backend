"""
WaxPrep AI Brain - Redesigned

Philosophy: AI-first. Everything flows through the brain.
The brain handles context, detects intent, generates quizzes, explains concepts.
Minimal external routing needed.
"""

from groq import Groq
from config.settings import settings
import random
import json
import re

_groq = None


def get_groq():
    global _groq
    if _groq is None:
        _groq = Groq(api_key=settings.GROQ_API_KEY)
    return _groq


def is_gemini_available() -> bool:
    try:
        from database.client import redis_client
        return redis_client.get("gemini_rate_limited") is None
    except Exception:
        return True


def mark_gemini_limited(is_daily_limit: bool = False):
    try:
        from database.client import redis_client
        ttl = 3600 if is_daily_limit else 90
        redis_client.setex("gemini_rate_limited", ttl, "1")
    except Exception:
        pass


def extract_question_data(response_text: str) -> dict | None:
    """
    Extracts structured question data from AI response if present.
    The AI embeds question data in a special marker when generating quiz questions.
    """
    pattern = r'\[QUESTION_DATA:\s*(\{.*?\})\]'
    match = re.search(pattern, response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


def clean_response(response_text: str) -> str:
    """Removes the hidden question data marker from the response shown to the student."""
    return re.sub(r'\[QUESTION_DATA:.*?\]', '', response_text, flags=re.DOTALL).strip()


async def get_student_context(student: dict) -> dict:
    """Gets weak/strong topics and exam countdown for the student."""
    from database.client import supabase

    student_id = student.get('id', '')
    context = {'weak_topics': [], 'strong_topics': [], 'days_until_exam': 0}

    try:
        mastery = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score')\
            .eq('student_id', student_id)\
            .order('mastery_score', desc=False)\
            .limit(3).execute()

        if mastery.data:
            context['weak_topics'] = [
                f"{m['topic']} ({m['subject']})"
                for m in mastery.data
            ]

        strong = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score')\
            .eq('student_id', student_id)\
            .order('mastery_score', desc=True)\
            .limit(2).execute()

        if strong.data:
            context['strong_topics'] = [
                f"{m['topic']} ({m['subject']})"
                for m in strong.data
                if m['mastery_score'] > 60
            ]

        exam_date = student.get('exam_date', '')
        if exam_date:
            from datetime import datetime
            try:
                exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
                days = (exam_dt - datetime.now()).days
                context['days_until_exam'] = max(0, days)
            except Exception:
                pass

    except Exception as e:
        print(f"Context fetch error: {e}")

    return context


async def think(
    message: str,
    student: dict,
    conversation_history: list,
    recent_subject: str = None,
) -> tuple[str, dict | None]:
    """
    The main AI thinking function.
    
    Returns:
    - response_text: What to send the student
    - question_data: If a quiz question was generated, the structured data. Otherwise None.
    
    This replaces the entire routing/classification/intent system for academic interactions.
    The AI handles context naturally through conversation history.
    """
    from ai.prompts import get_wax_system_prompt

    ctx = await get_student_context(student)
    system_prompt = get_wax_system_prompt(student, recent_subject)

    # Add context about weak topics to the system prompt
    if ctx['weak_topics']:
        system_prompt += f"\n\nWEAK TOPICS (prioritize these): {', '.join(ctx['weak_topics'])}"
    if ctx['days_until_exam'] > 0:
        system_prompt += f"\nDAYS UNTIL EXAM: {ctx['days_until_exam']}"

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history for context (last 20 messages)
    for msg in conversation_history[-20:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    # Try Groq smart model first
    try:
        client = get_groq()
        response = client.chat.completions.create(
            model=settings.GROQ_SMART_MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.75,
        )
        result = response.choices[0].message.content
        if result and len(result.strip()) > 10:
            question_data = extract_question_data(result)
            clean = clean_response(result)
            return clean.strip(), question_data
    except Exception as e:
        print(f"Groq smart error: {e}")

    # Try Groq fast model
    try:
        client = get_groq()
        response = client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=messages,
            max_tokens=800,
            temperature=0.7,
        )
        result = response.choices[0].message.content
        if result and len(result.strip()) > 10:
            question_data = extract_question_data(result)
            clean = clean_response(result)
            return clean.strip(), question_data
    except Exception as e:
        print(f"Groq fast error: {e}")

    # Try Gemini as last resort
    if is_gemini_available():
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)

            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=system_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=900,
                )
            )

            history = []
            for msg in conversation_history[-8:]:
                role = "user" if msg.get("role") == "user" else "model"
                history.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

            chat = model.start_chat(history=history)
            response = chat.send_message(message)

            text = ""
            try:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        text += part.text
            except Exception:
                pass

            if text.strip():
                question_data = extract_question_data(text)
                clean = clean_response(text)
                return clean.strip(), question_data

        except Exception as e:
            err = str(e)
            print(f"Gemini error: {err[:200]}")
            is_daily = "GenerateRequestsPerDayPerProjectPerModel" in err
            if "429" in err or "quota" in err.lower():
                mark_gemini_limited(is_daily_limit=is_daily)

    # Smart fallback
    return _fallback(message, student, ctx), None


def _fallback(message: str, student: dict, ctx: dict) -> str:
    """Context-aware fallback when all AI fails."""
    name = student.get('name', 'Student').split()[0]
    msg_lower = message.lower().strip()
    subjects = student.get('subjects', [])
    target_exam = student.get('target_exam', 'JAMB')
    streak = student.get('current_streak', 0)
    weak_topics = ctx.get('weak_topics', [])

    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'morning', 'evening', 'sup']):
        streak_note = f"Your {streak}-day streak is going strong!" if streak > 1 else ""
        weak_note = f"Your weakest area right now is {weak_topics[0]}." if weak_topics else f"Tell me what {target_exam} subject you want to work on."
        return f"Hey {name}! {streak_note}\n\n{weak_note}"

    if any(w in msg_lower for w in ['quiz', 'test', 'question', 'practice', 'quiz me']):
        subject = subjects[0] if subjects else 'Mathematics'
        for s in subjects:
            if s.lower() in msg_lower:
                subject = s
                break
        return f"On it, {name}! Getting a {subject} question ready. Ask again in 20 seconds if nothing appears."

    if any(w in msg_lower for w in ['subscribe', 'upgrade', 'pay', 'plan']):
        return f"To upgrade, {name}, type SUBSCRIBE then SCHOLAR MONTHLY. Scholar Plan is ₦1,500/month — 100 questions daily."

    defaults = [
        f"I'm here, {name}. Connection is a bit slow right now — ask again in 30 seconds.",
        f"Got your message, {name}! Brief delay on my end. Ask again and I'll respond properly.",
        f"Hey {name}, give me 30 seconds and try again — I'll give you a proper response.",
    ]
    return random.choice(defaults)

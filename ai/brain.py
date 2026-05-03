"""
WaxPrep AI Brain

The central intelligence.
Key fix: quiz context is now passed clearly so the AI evaluates
answers naturally without triggering "sorry something went wrong."
Model selection is now tier-aware.
"""

import re
import json
import random
from groq import Groq
from config.settings import settings

_groq_client = None


def get_groq() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


def extract_question_data(response_text: str) -> dict | None:
    """Extracts hidden question data from AI response."""
    pattern = r'\[QUESTION_DATA:\s*(\{.*?\})\]'
    match = re.search(pattern, response_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


def clean_response(response_text: str) -> str:
    """Removes the hidden question data marker from the visible response."""
    return re.sub(r'\[QUESTION_DATA:.*?\]', '', response_text, flags=re.DOTALL).strip()


async def think(
    message: str,
    student: dict,
    conversation_history: list,
    recent_subject: str = None,
    context: dict = None,
    quiz_context: dict = None,
) -> tuple[str, dict | None]:
    """
    Main AI thinking function.

    quiz_context: When provided, the student just answered a quiz.
    Contains: question, student_answer, is_correct, correct_answer,
    explanation, subject, topic.

    Returns (response_text, question_data_or_None).
    """
    from ai.prompts import get_wax_system_prompt
    from ai.context_manager import format_context_for_prompt

    context = context or {}
    context_str = format_context_for_prompt(context)

    # Get the right model for this student's tier
    tier = student.get('subscription_tier', 'free')
    is_trial = student.get('is_trial_active', False)
    ai_model = settings.get_ai_model_for_tier(tier, is_trial)

    system_prompt = get_wax_system_prompt(
        student, recent_subject, context_str, ai_model
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history (last 20 messages)
    for msg in conversation_history[-20:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    # Build the final user message
    if quiz_context:
        # Student just answered a quiz question
        q_text = quiz_context.get('question', '')
        student_answer = quiz_context.get('student_answer', '')
        is_correct = quiz_context.get('is_correct', False)
        correct_answer = quiz_context.get('correct_answer', '')
        explanation = quiz_context.get('explanation', '')
        subject = quiz_context.get('subject', '')
        topic = quiz_context.get('topic', '')

        system_inject = (
            f"[CONTEXT FOR THIS RESPONSE — NOT FROM STUDENT]\n"
            f"The student just answered a quiz question.\n"
            f"Subject: {subject} | Topic: {topic}\n"
            f"Question asked: {q_text}\n"
            f"Student answered: {student_answer}\n"
            f"This answer is: {'CORRECT' if is_correct else 'INCORRECT'}\n"
            f"Correct answer is: {correct_answer}\n"
            f"Explanation: {explanation}\n"
            f"Now respond as Wax would — naturally evaluate the answer, explain if needed, keep going.\n"
            f"[END CONTEXT]\n\n"
            f"Student's message: {message}"
        )
        messages.append({"role": "user", "content": system_inject})
    else:
        messages.append({"role": "user", "content": message})

    # ── Real past‑question injection ────────────────────────────────
    # If the student is asking for a quiz, check our Supabase bank first.
    # When a real question is found, we return only a short intro line;
    # the handler will add the tappable buttons and the timer automatically.
    if not quiz_context and any(kw in message.lower() for kw in ['quiz', 'test me', 'question']):
        detected_subject = None
        for subject in ['english', 'mathematics', 'physics', 'chemistry',
                         'biology', 'economics', 'government', 'literature',
                         'geography', 'commerce', 'agriculture']:
            if subject in message.lower():
                detected_subject = subject
                break
        if detected_subject:
            from features.question_bank import get_real_question
            real_q = await get_real_question(detected_subject)
            if real_q:
                # Only return a short intro — no options in the text.
                # The handler will attach the keyboard and timer.
                response = f"Here's a real JAMB {detected_subject.capitalize()} question:"
                return response, real_q

    # Try primary model (based on tier)
    result = await _call_groq(messages, model=ai_model, max_tokens=1200)
    if result:
        question_data = extract_question_data(result)
        return clean_response(result), question_data

    # If primary model fails, try fast model as fallback
    fallback_model = settings.GROQ_FAST_MODEL if ai_model == settings.GROQ_SMART_MODEL else settings.GROQ_SMART_MODEL
    result = await _call_groq(messages, model=fallback_model, max_tokens=900)
    if result:
        question_data = extract_question_data(result)
        return clean_response(result), question_data

    # Try Gemini as last resort
    result = await _call_gemini(system_prompt, message, conversation_history[-8:])
    if result:
        question_data = extract_question_data(result)
        return clean_response(result), question_data

    # Contextual fallback
    return _fallback(message, student, context), None


async def _call_groq(messages: list, model: str, max_tokens: int = 1200) -> str | None:
    try:
        client = get_groq()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.75,
        )
        result = response.choices[0].message.content
        if result and len(result.strip()) > 10:
            return result.strip()
    except Exception as e:
        err = str(e)
        if '429' in err or 'rate_limit' in err.lower():
            print(f"Groq rate limited on {model}: {err[:100]}")
        else:
            print(f"Groq error ({model}): {err[:150]}")
    return None


async def _call_gemini(system_prompt: str, message: str,
                        conversation_history: list) -> str | None:
    try:
        from database.client import redis_client
        if redis_client.get("gemini_rate_limited"):
            return None

        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)

        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.8,
                max_output_tokens=1000,
            )
        )

        history = []
        for msg in conversation_history:
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
            return text.strip()

    except Exception as e:
        err = str(e)
        print(f"Gemini brain error: {err[:150]}")
        if "429" in err or "quota" in err.lower():
            is_daily = "PerDay" in err
            try:
                from database.client import redis_client
                redis_client.setex("gemini_rate_limited", 3600 if is_daily else 90, "1")
            except Exception:
                pass

    return None


def _fallback(message: str, student: dict, context: dict) -> str:
    """Contextual fallback when all AI models fail."""
    name = student.get('name', 'Student').split()[0]
    msg_lower = message.lower().strip()
    subjects = student.get('subjects', [])
    target_exam = student.get('target_exam', 'JAMB')
    streak = student.get('current_streak', 0)
    weak_topics = context.get('weak_topics', [])

    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'morning', 'evening', 'sup', 'oya']):
        streak_note = f"Your {streak}-day streak is still going! " if streak > 1 else ""
        if weak_topics:
            weak_note = (
                f"Your weakest area right now is {weak_topics[0].get('topic', '')} "
                f"in {weak_topics[0].get('subject', '')}. Want to work on that?"
            )
        elif subjects:
            weak_note = f"Which {target_exam} subject do you want to work on?"
        else:
            weak_note = "What would you like to study today?"
        return f"Hey {name}! {streak_note}{weak_note}"

    responses = [
        f"I had a brief hiccup on my end, {name}. Ask me again and I'll give you a proper answer.",
        f"Small technical delay, {name}. Try again in about 20 seconds.",
        f"I'm back, {name}. Ask again and I'll respond properly.",
    ]
    return random.choice(responses)

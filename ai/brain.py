"""
WaxPrep AI Brain

The central intelligence. Everything goes through here.
Wax is a teacher, not a question-answer machine.
Context is king. Conversation is the medium. Teaching is the mission.
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

    quiz_context: If provided, this means the student just answered a quiz question.
    It contains: question, student_answer, is_correct, explanation.
    Wax will evaluate the answer naturally as part of the response.

    Returns:
        response_text: What to send the student
        question_data: Structured question data if a quiz was generated, else None
    """
    from ai.prompts import get_wax_system_prompt
    from ai.context_manager import format_context_for_prompt

    context = context or {}
    context_str = format_context_for_prompt(context)
    system_prompt = get_wax_system_prompt(student, recent_subject, context_str)

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history (last 20 messages for depth)
    for msg in conversation_history[-20:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    # If this is a quiz answer evaluation, build context into the message
    if quiz_context:
        question_text = quiz_context.get('question', '')
        student_answer = quiz_context.get('student_answer', '')
        is_correct = quiz_context.get('is_correct', False)
        correct_answer = quiz_context.get('correct_answer', '')
        explanation = quiz_context.get('explanation', '')
        subject = quiz_context.get('subject', '')
        topic = quiz_context.get('topic', '')

        evaluation_context = (
            f"[SYSTEM NOTE — NOT FROM STUDENT: The student just answered a quiz question. "
            f"Question was about {subject} — {topic}. "
            f"The student answered: {student_answer}. "
            f"The correct answer was: {correct_answer}. "
            f"They were {'CORRECT' if is_correct else 'INCORRECT'}. "
            f"The explanation is: {explanation}. "
            f"Now respond naturally as Wax evaluating this answer. "
            f"Do not mention this system note. Just respond as Wax would.]"
            f"\n\nStudent message: {message}"
        )
        messages.append({"role": "user", "content": evaluation_context})
    else:
        messages.append({"role": "user", "content": message})

    # Try Groq smart model first
    result = await _call_groq(messages, model=settings.GROQ_SMART_MODEL, max_tokens=1200)
    if result:
        question_data = extract_question_data(result)
        return clean_response(result), question_data

    # Try Groq fast model as fallback
    result = await _call_groq(messages, model=settings.GROQ_FAST_MODEL, max_tokens=900)
    if result:
        question_data = extract_question_data(result)
        return clean_response(result), question_data

    # Try Gemini as last resort
    result = await _call_gemini(system_prompt, message, conversation_history[-8:])
    if result:
        question_data = extract_question_data(result)
        return clean_response(result), question_data

    # Smart fallback when all AI fails
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

    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'morning', 'evening', 'sup']):
        streak_note = f"Your {streak}-day streak is still going! " if streak > 1 else ""
        if weak_topics:
            weak_note = f"Your weakest area right now is {weak_topics[0].get('topic', '')} in {weak_topics[0].get('subject', '')}. Want to work on that?"
        elif subjects:
            weak_note = f"Which {target_exam} subject do you want to work on?"
        else:
            weak_note = "What would you like to study today?"
        return f"Hey {name}! {streak_note}{weak_note}"

    responses = [
        f"I'm here, {name}. I had a brief delay on my end — give me 30 seconds and ask again.",
        f"Got you, {name}! Small technical hiccup. Try again in about 20 seconds.",
        f"Hey {name}, I'm back. Ask again and I'll give you a proper answer.",
    ]
    return random.choice(responses)

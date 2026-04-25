"""
Gemini Client — Heavy AI Tasks
Used for question generation and post-exam analysis.
NOT used for real-time chat responses (too slow, quota-limited).
"""

import google.generativeai as genai
from config.settings import settings
import json

genai.configure(api_key=settings.GEMINI_API_KEY)


async def ask_gemini(
    system_prompt: str,
    user_message: str,
    conversation_history: list = None,
    use_pro: bool = False,
    max_tokens: int = 2000,
    temperature: float = 0.7,
    student_id: str = None
) -> str:
    model_name = settings.GEMINI_PRO_MODEL if use_pro else settings.GEMINI_MODEL

    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
        )

        history = []
        if conversation_history:
            for msg in conversation_history[-10:]:
                role = "user" if msg["role"] == "user" else "model"
                history.append({"role": role, "parts": [{"text": msg["content"]}]})

        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)
        return response.text or ""

    except Exception as e:
        err = str(e)
        print(f"Gemini ask error: {err[:200]}")
        if "429" in err or "quota" in err.lower():
            try:
                from database.client import redis_client
                is_daily = "PerDay" in err
                redis_client.setex("gemini_rate_limited", 3600 if is_daily else 90, "1")
            except Exception:
                pass
        return ""


async def generate_questions_with_gemini(
    subject: str,
    topic: str,
    exam_type: str,
    difficulty: int,
    count: int = 3
) -> list:
    """Generates questions. Tries Gemini first, falls back to Groq."""
    from ai.prompts import get_question_generator_prompt

    prompt = get_question_generator_prompt(subject, topic, exam_type, difficulty, count)

    questions = await _generate_with_gemini(prompt, subject, topic, exam_type, difficulty)
    if questions:
        return questions

    print(f"Gemini question gen failed for {subject} — trying Groq fallback")
    questions = await _generate_with_groq(prompt, subject, topic, exam_type, difficulty)
    if questions:
        return questions

    print(f"Both Gemini and Groq failed for {subject}/{topic}")
    return []


async def _generate_with_gemini(prompt: str, subject: str, topic: str,
                                 exam_type: str, difficulty: int) -> list:
    try:
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=3000,
                temperature=0.3,
            )
        )
        response = model.generate_content(prompt)
        text = response.text.strip()
        questions = _parse_questions_json(text, subject, topic, exam_type, difficulty)
        if questions:
            _save_questions_to_db(questions)
        return questions
    except Exception as e:
        print(f"Gemini question generation error: {e}")
        return []


async def _generate_with_groq(prompt: str, subject: str, topic: str,
                               exam_type: str, difficulty: int) -> list:
    try:
        from groq import Groq
        client = Groq(api_key=settings.GROQ_API_KEY)
        response = client.chat.completions.create(
            model=settings.GROQ_SMART_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Nigerian exam question creator. "
                        "You ALWAYS respond with valid JSON only. "
                        "No markdown code blocks. No explanation. No preamble. "
                        "Start your response with { and end with }."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            max_tokens=3000,
            temperature=0.3,
        )
        text = response.choices[0].message.content.strip()
        questions = _parse_questions_json(text, subject, topic, exam_type, difficulty)
        if questions:
            _save_questions_to_db(questions)
        return questions
    except Exception as e:
        print(f"Groq question generation error: {e}")
        return []


def _parse_questions_json(text: str, subject: str, topic: str,
                           exam_type: str, difficulty: int) -> list:
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    start = text.find('{')
    if start > 0:
        text = text[start:]

    try:
        data = json.loads(text.strip())
        questions = data.get('questions', [])
        valid = []
        required = ['question_text', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer']
        for q in questions:
            if all(k in q for k in required):
                q['is_ai_generated'] = True
                q['is_verified'] = False
                q['created_by'] = 'ai'
                q.setdefault('subject', subject)
                q.setdefault('topic', topic)
                q.setdefault('exam_type', exam_type)
                q.setdefault('difficulty_level', difficulty)
                q.setdefault('quality_score', 5.0)
                valid.append(q)
        return valid
    except json.JSONDecodeError as e:
        print(f"JSON parse error in question generation: {e}")
        return []


def _save_questions_to_db(questions: list):
    if not questions:
        return
    try:
        from database.client import supabase
        allowed_fields = [
            'question_text', 'option_a', 'option_b', 'option_c', 'option_d',
            'correct_answer', 'explanation_correct',
            'explanation_a', 'explanation_b', 'explanation_c', 'explanation_d',
            'difficulty_level', 'topic', 'subject', 'exam_type',
            'is_ai_generated', 'is_verified', 'created_by', 'quality_score'
        ]
        db_questions = [{k: v for k, v in q.items() if k in allowed_fields} for q in questions]
        supabase.table('questions').insert(db_questions).execute()
        print(f"Saved {len(db_questions)} generated questions to database")
    except Exception as e:
        print(f"Question save error (non-critical): {e}")

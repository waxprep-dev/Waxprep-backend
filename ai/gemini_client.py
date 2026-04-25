"""
Gemini Client — Smart AI for WaxPrep

FIXED: Removed response_mime_type from GenerationConfig (not reliable in SDK 0.8.x)
FIXED: Added Groq fallback for question generation so quizzes never fail
FIXED: Better error handling and JSON parsing
"""

import google.generativeai as genai
from config.settings import settings

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
                history.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })

        chat = model.start_chat(history=history)
        response = chat.send_message(user_message)
        result = response.text

        try:
            from ai.cost_tracker import track_ai_cost
            estimated_tokens_in = len(user_message.split()) * 1.3
            estimated_tokens_out = len(result.split()) * 1.3
            await track_ai_cost(
                student_id=student_id,
                model=model_name,
                tokens_input=int(estimated_tokens_in),
                tokens_output=int(estimated_tokens_out),
                query_type='gemini_response'
            )
        except Exception:
            pass

        return result

    except Exception as e:
        print(f"Gemini ask_gemini error: {e}")
        return "I'm having a small technical issue right now. Please try again in a moment!"


async def generate_questions_with_gemini(
    subject: str,
    topic: str,
    exam_type: str,
    difficulty: int,
    count: int = 5
) -> list:
    """
    Generates exam questions. Tries Gemini first, falls back to Groq if Gemini fails.
    This ensures students always get questions even if Gemini is having issues.
    """
    from ai.prompts import get_question_generator_prompt

    prompt = get_question_generator_prompt(subject, topic, exam_type, difficulty, count)

    # Try Gemini first
    questions = await _generate_with_gemini(prompt, subject, topic, exam_type, difficulty)
    if questions:
        return questions

    # Gemini failed — fall back to Groq
    print(f"Gemini question generation failed, trying Groq fallback for {subject}")
    questions = await _generate_with_groq(prompt, subject, topic, exam_type, difficulty)
    if questions:
        return questions

    print(f"Both Gemini and Groq question generation failed for {subject} - {topic}")
    return []


async def _generate_with_gemini(prompt: str, subject: str, topic: str, exam_type: str, difficulty: int) -> list:
    """Tries to generate questions using Gemini."""
    import json

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


async def _generate_with_groq(prompt: str, subject: str, topic: str, exam_type: str, difficulty: int) -> list:
    """Generates questions using Groq as fallback."""
    import json
    from groq import Groq
    from config.settings import settings

    try:
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


def _parse_questions_json(text: str, subject: str, topic: str, exam_type: str, difficulty: int) -> list:
    """Parses JSON from AI response, handling common formatting issues."""
    import json

    # Strip markdown code blocks if present
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    # Try to find JSON object in the text
    start = text.find('{')
    if start > 0:
        text = text[start:]

    try:
        data = json.loads(text.strip())
        questions = data.get('questions', [])

        # Validate questions have required fields
        valid_questions = []
        for q in questions:
            if all(k in q for k in ['question_text', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_answer']):
                q['is_ai_generated'] = True
                q['is_verified'] = False
                q['created_by'] = 'ai'
                if 'subject' not in q:
                    q['subject'] = subject
                if 'topic' not in q:
                    q['topic'] = topic
                if 'exam_type' not in q:
                    q['exam_type'] = exam_type
                if 'difficulty_level' not in q:
                    q['difficulty_level'] = difficulty
                valid_questions.append(q)

        return valid_questions

    except json.JSONDecodeError as e:
        print(f"JSON parse error in question generation: {e}")
        print(f"Raw text was: {text[:300]}")
        return []


def _save_questions_to_db(questions: list):
    """Saves generated questions to the database for future reuse."""
    if not questions:
        return
    try:
        from database.client import supabase
        # Save without fields that are not in the DB schema
        db_questions = []
        for q in questions:
            db_q = {k: v for k, v in q.items() if k in [
                'question_text', 'option_a', 'option_b', 'option_c', 'option_d',
                'correct_answer', 'explanation_correct', 'explanation_a', 'explanation_b',
                'explanation_c', 'explanation_d', 'difficulty_level', 'topic', 'subject',
                'exam_type', 'is_ai_generated', 'is_verified', 'created_by'
            ]}
            db_questions.append(db_q)
        supabase.table('questions').insert(db_questions).execute()
        print(f"Saved {len(db_questions)} generated questions to database")
    except Exception as e:
        print(f"Question save error (non-critical): {e}")

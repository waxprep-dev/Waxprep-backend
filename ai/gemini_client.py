"""
Gemini Client — Smart AI for WaxPrep

Gemini is used for:
1. Complex academic explanations
2. Essay analysis and grading (Pro feature)
3. Question generation
4. Study plan creation
5. Post-exam analysis
6. Anything that needs deep understanding

Gemini Flash is fast and free-tier generous.
Gemini Pro is the most powerful model we use.
"""

import google.generativeai as genai
from config.settings import settings
from ai.cost_tracker import track_ai_cost

# Configure Gemini with our API key
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
    """
    Sends a message to Gemini and returns the response.
    
    use_pro=True uses Gemini Pro (more powerful but slower)
    use_pro=False uses Gemini Flash (fast and good quality)
    """
    
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
        
        # Build conversation history for Gemini
        # Gemini uses a different format than OpenAI
        history = []
        if conversation_history:
            for msg in conversation_history[-10:]:
                role = "user" if msg["role"] == "user" else "model"
                history.append({
                    "role": role,
                    "parts": [msg["content"]]
                })
        
        # Start or continue a chat session
        chat = model.start_chat(history=history)
        
        # Send the message
        response = chat.send_message(user_message)
        
        result = response.text
        
        # Rough cost tracking for Gemini (it doesn't always report tokens)
        estimated_tokens_in = len(user_message.split()) * 1.3
        estimated_tokens_out = len(result.split()) * 1.3
        
        await track_ai_cost(
            student_id=student_id,
            model=model_name,
            tokens_input=int(estimated_tokens_in),
            tokens_output=int(estimated_tokens_out),
            query_type='gemini_response'
        )
        
        return result
        
    except Exception as e:
        print(f"Gemini error: {e}")
        return "I'm having a small technical issue right now. Please try again in a moment! 🙏"

async def generate_questions_with_gemini(
    subject: str,
    topic: str,
    exam_type: str,
    difficulty: int,
    count: int = 5
) -> list:
    """
    Uses Gemini to generate exam questions.
    Returns a list of question dictionaries.
    """
    import json
    from ai.prompts import get_question_generator_prompt
    
    prompt = get_question_generator_prompt(subject, topic, exam_type, difficulty, count)
    
    try:
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=3000,
                temperature=0.3,  # Low temperature for consistent, accurate questions
                response_mime_type="application/json",  # Ask for JSON directly
            )
        )
        
        response = model.generate_content(prompt)
        
        # Parse the JSON response
        text = response.text.strip()
        
        # Clean up common JSON formatting issues
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        data = json.loads(text.strip())
        questions = data.get('questions', [])
        
        # Store generated questions in the database for future use
        from database.client import supabase
        for q in questions:
            q['is_ai_generated'] = True
            q['is_verified'] = False
            q['created_by'] = 'gemini'
        
        if questions:
            supabase.table('questions').insert(questions).execute()
        
        return questions
        
    except json.JSONDecodeError as e:
        print(f"JSON parsing error for question generation: {e}")
        return []
    except Exception as e:
        print(f"Question generation error: {e}")
        return []

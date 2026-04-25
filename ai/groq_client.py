"""
Groq Client — Fast AI Responses
Used for academic questions, explanations, greetings, and commands.
"""

from groq import Groq
from config.settings import settings

_client = None


def get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


async def ask_groq(
    system_prompt: str,
    user_message: str,
    conversation_history: list = None,
    model: str = None,
    max_tokens: int = 1500,
    temperature: float = 0.7,
    student_id: str = None
) -> str:
    model = model or settings.GROQ_FAST_MODEL
    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        for msg in conversation_history[-10:]:
            role = msg.get('role', 'user')
            if role in ['user', 'assistant']:
                messages.append({"role": role, "content": msg.get('content', '')})

    messages.append({"role": "user", "content": user_message})

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        result = response.choices[0].message.content

        if hasattr(response, 'usage') and student_id:
            try:
                from ai.cost_tracker import track_ai_cost
                await track_ai_cost(
                    student_id=student_id,
                    model=model,
                    tokens_input=response.usage.prompt_tokens,
                    tokens_output=response.usage.completion_tokens,
                    query_type='groq_response'
                )
            except Exception:
                pass

        return result or ""

    except Exception as e:
        print(f"Groq client error ({model}): {e}")
        return "I am having a brief technical issue. Please try again in a moment!"

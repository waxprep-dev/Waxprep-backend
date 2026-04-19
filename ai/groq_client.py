"""
Groq Client — Fast AI for WaxPrep

Groq is used for:
1. Intent classification (fastest possible)
2. Simple academic questions
3. Quick factual lookups
4. Command responses

Groq uses open-source models running on specialized hardware (LPUs).
It's much faster than OpenAI and free up to the generous free tier limit.
"""

from groq import Groq
from config.settings import settings
from ai.cost_tracker import track_ai_cost

groq_client = Groq(api_key=settings.GROQ_API_KEY)

async def ask_groq(
    system_prompt: str,
    user_message: str,
    conversation_history: list = None,
    model: str = None,
    max_tokens: int = 1500,
    temperature: float = 0.7,
    student_id: str = None
) -> str:
    """
    Sends a message to Groq and returns the response.
    
    Parameters:
    - system_prompt: Instructions for how the AI should behave
    - user_message: What the student said
    - conversation_history: Previous messages in this session (for context)
    - model: Which Groq model to use (defaults to fast model)
    - max_tokens: Maximum length of response
    - temperature: Creativity (0.0 = predictable, 1.0 = creative)
    - student_id: For cost tracking purposes
    
    Returns the AI's response as a string.
    """
    model = model or settings.GROQ_FAST_MODEL
    
    # Build the messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history for context (last 10 messages to avoid huge context)
    if conversation_history:
        messages.extend(conversation_history[-10:])
    
    # Add the current message
    messages.append({"role": "user", "content": user_message})
    
    try:
        response = groq_client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        
        result = response.choices[0].message.content
        
        # Track costs
        if hasattr(response, 'usage'):
            await track_ai_cost(
                student_id=student_id,
                model=model,
                tokens_input=response.usage.prompt_tokens,
                tokens_output=response.usage.completion_tokens,
                query_type='groq_response'
            )
        
        return result
        
    except Exception as e:
        print(f"Groq error: {e}")
        # Return a helpful error message rather than crashing
        return "I'm having a small technical issue right now. Please try again in a while our technical team is working to resolve the issue! 🙏"

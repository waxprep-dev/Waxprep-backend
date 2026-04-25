"""
AI Routing Engine

FIXED: Tier 2 now uses Groq smart model instead of Gemini.
This eliminates the Gemini 429 quota problem for academic questions.
Gemini is now only used for specific heavy tasks (post-exam analysis,
question generation) via direct calls to ask_gemini, not via this router.

Routing tiers:
- Tier 1 (Fast): Groq llama3-8b — greetings, commands
- Tier 2 (Standard): Groq llama3-70b — all academic questions
- Tier 3 (Fallback only): Groq llama3-70b with higher tokens for complex math
"""

from config.settings import settings
from ai.groq_client import ask_groq
from ai.cost_tracker import should_use_cheaper_model, is_ai_budget_exceeded

# Intents that only need Tier 1 (fast/cheap)
TIER_1_INTENTS = {
    'GREETING', 'COMMAND', 'CASUAL_CHAT', 'HELP_REQUEST'
}

# Intents that need Tier 2 (standard academic)
TIER_2_INTENTS = {
    'ACADEMIC_QUESTION', 'REQUEST_QUIZ', 'REQUEST_EXPLANATION',
    'WRONG_RESPONSE', 'EXAM_RESPONSE', 'PAYMENT_INQUIRY'
}

# Intents that need more depth
TIER_3_INTENTS = {
    'CALCULATION'
}


async def route_and_respond(
    message: str,
    intent: str,
    student: dict,
    conversation_history: list,
    conversation_state: dict,
    system_prompt: str
) -> str:
    """
    Routes the message to Groq and returns the response.

    IMPORTANT: Gemini is no longer used here.
    Gemini is too quota-limited on the free tier for real-time chat.
    Gemini is only called directly for question generation and post-exam analysis.

    This function uses Groq for everything, which has a very generous
    free tier (roughly 14,400 requests per day on the free plan).
    """

    # Check if budget is completely exceeded
    if await is_ai_budget_exceeded():
        return (
            "I'm having some technical limitations right now and can't process new questions.\n\n"
            "Please try again in a few hours. Your questions aren't lost — just paused.\n\n"
            "While you wait, check your study plan with *PLAN* or review your progress with *PROGRESS*."
        )

    use_budget_mode = await should_use_cheaper_model()

    tier = get_routing_tier(intent, student, use_budget_mode)

    if tier == 1:
        return await ask_groq(
            system_prompt=system_prompt,
            user_message=message,
            conversation_history=conversation_history,
            model=settings.GROQ_FAST_MODEL,
            max_tokens=800,
            temperature=0.7,
            student_id=student.get('id')
        )

    elif tier == 2:
        # FIXED: Use Groq smart model instead of Gemini.
        # llama-3.3-70b-versatile is excellent for academic content and has
        # a very generous free tier compared to Gemini.
        return await ask_groq(
            system_prompt=system_prompt,
            user_message=message,
            conversation_history=conversation_history,
            model=settings.GROQ_SMART_MODEL,
            max_tokens=1200,
            temperature=0.7,
            student_id=student.get('id')
        )

    else:
        # Tier 3: Complex calculations and analysis
        # Still use Groq smart but with more tokens
        return await ask_groq(
            system_prompt=system_prompt,
            user_message=message,
            conversation_history=conversation_history,
            model=settings.GROQ_SMART_MODEL,
            max_tokens=2000,
            temperature=0.6,
            student_id=student.get('id')
        )


def get_routing_tier(intent: str, student: dict, budget_mode: bool) -> int:
    """
    Determines which routing tier a message should use.
    """
    if budget_mode:
        if intent in TIER_1_INTENTS:
            return 1
        return 2

    if intent in TIER_1_INTENTS:
        return 1

    if intent in TIER_3_INTENTS:
        return 3

    return 2

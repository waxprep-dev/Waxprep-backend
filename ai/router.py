"""
AI Routing Engine

This is the brain that decides which AI model handles each message.
The routing decision is based on:
1. The classified intent of the message
2. The student's subscription tier
3. The complexity of the query
4. The current AI budget status

Routing tiers:
- Tier 1 (Fast/Cheap): Groq llama3-8b — greetings, commands, simple questions
- Tier 2 (Standard): Groq llama3-70b or Gemini Flash — most academic questions
- Tier 3 (Powerful): Gemini Pro — complex explanations, essay grading, exam analysis
"""

from config.settings import settings
from ai.groq_client import ask_groq
from ai.gemini_client import ask_gemini
from ai.cost_tracker import should_use_cheaper_model, is_ai_budget_exceeded

# Intents that only need Tier 1 (fast/cheap)
TIER_1_INTENTS = {
    'GREETING', 'COMMAND', 'CASUAL_CHAT', 'HELP_REQUEST'
}

# Intents that need Tier 2 (standard)
TIER_2_INTENTS = {
    'ACADEMIC_QUESTION', 'REQUEST_QUIZ', 'REQUEST_EXPLANATION', 
    'WRONG_RESPONSE', 'EXAM_RESPONSE'
}

# Intents that need Tier 3 (powerful)
TIER_3_INTENTS = {
    'CALCULATION'  # Math sometimes needs extra accuracy
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
    Routes the message to the appropriate AI and returns the response.
    
    This is the main function called by message handlers.
    Everything else in this file is in service of this function.
    """
    
    # First check if budget is completely exceeded
    if await is_ai_budget_exceeded():
        return (
            "I'm having some technical limitations right now and can't process new questions. 😔\n\n"
            "Please try again in a few hours. Your questions aren't lost — just paused.\n\n"
            "While you wait, check your study plan with *PLAN* or review your progress with *PROGRESS*."
        )
    
    # Determine if we should downgrade to cheaper models
    use_budget_mode = await should_use_cheaper_model()
    
    # Determine which tier is needed
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
        # Use Gemini Flash for standard questions — better quality than Groq for complex topics
        return await ask_gemini(
            system_prompt=system_prompt,
            user_message=message,
            conversation_history=conversation_history,
            use_pro=False,
            max_tokens=1500,
            temperature=0.7,
            student_id=student.get('id')
        )
    
    else:  # Tier 3
        # Use Gemini Pro for complex questions
        # But in budget mode, fall back to Gemini Flash
        return await ask_gemini(
            system_prompt=system_prompt,
            user_message=message,
            conversation_history=conversation_history,
            use_pro=(not use_budget_mode),
            max_tokens=2500,
            temperature=0.6,
            student_id=student.get('id')
        )

def get_routing_tier(intent: str, student: dict, budget_mode: bool) -> int:
    """
    Determines which routing tier (1, 2, or 3) a message should use.
    """
    if budget_mode:
        # In budget mode, everything uses Tier 1 or 2 max
        if intent in TIER_1_INTENTS:
            return 1
        return 2
    
    if intent in TIER_1_INTENTS:
        return 1
    
    if intent in TIER_3_INTENTS:
        return 3
    
    # Default to Tier 2 for most academic content
    return 2

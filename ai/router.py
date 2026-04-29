"""
AI Routing Engine — Simplified

All academic and conversational content goes to Groq smart model.
Only falls back to fast model if smart model fails.
Gemini is for question generation and post-exam analysis only.
"""

from config.settings import settings
from ai.groq_client import ask_groq
from ai.cost_tracker import is_ai_budget_exceeded


async def route_and_respond(
    message: str,
    student: dict,
    conversation_history: list,
    system_prompt: str,
    quiz_context: dict = None,
) -> str:
    """
    Routes to Groq and returns the response.
    Everything goes to the smart model. Falls back to fast if needed.
    """
    if await is_ai_budget_exceeded():
        return (
            "I'm having some technical limitations right now.\n\n"
            "Please try again in a few hours. Your progress is safe.\n\n"
            "While you wait, think about what topic you want to pick up next."
        )

    # Build the actual message with quiz context if needed
    final_message = message
    if quiz_context:
        question_text = quiz_context.get('question', '')
        student_answer = quiz_context.get('student_answer', '')
        is_correct = quiz_context.get('is_correct', False)
        correct_answer = quiz_context.get('correct_answer', '')
        explanation = quiz_context.get('explanation', '')
        subject = quiz_context.get('subject', '')
        topic = quiz_context.get('topic', '')

        final_message = (
            f"[SYSTEM NOTE: Student answered quiz. Subject: {subject}, Topic: {topic}. "
            f"Student answered: {student_answer}. Correct answer: {correct_answer}. "
            f"They were {'CORRECT' if is_correct else 'INCORRECT'}. "
            f"Explanation: {explanation}. Respond as Wax naturally evaluating this.]\n\n"
            f"Student message: {message}"
        )

    # Try smart model first
    result = await ask_groq(
        system_prompt=system_prompt,
        user_message=final_message,
        conversation_history=conversation_history,
        model=settings.GROQ_SMART_MODEL,
        max_tokens=1200,
        temperature=0.75,
        student_id=student.get('id')
    )

    if result and len(result.strip()) > 10:
        return result

    # Fall back to fast model
    result = await ask_groq(
        system_prompt=system_prompt,
        user_message=final_message,
        conversation_history=conversation_history,
        model=settings.GROQ_FAST_MODEL,
        max_tokens=900,
        temperature=0.75,
        student_id=student.get('id')
    )

    if result and len(result.strip()) > 10:
        return result

    # Last resort fallback message
    name = student.get('name', 'Student').split()[0]
    return f"I had a brief technical issue, {name}. Ask me again and I'll give you a proper answer!"

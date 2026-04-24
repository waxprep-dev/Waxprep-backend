"""
Daily Challenge System

Every day at 8 AM, a new hard question is posted.
All WaxPrep students attempt the same question.
The first person to answer correctly gets 100 bonus points.
Everyone who attempts gets 50 points.

This creates a shared daily experience — everyone is tackling
the same hard question, creating a sense of community.

At the end of the day, results are available: how many students attempted,
what percentage got it right, who won.
"""

from database.client import supabase
from helpers import nigeria_today, nigeria_now, get_correct_message, get_almost_message

async def get_todays_challenge() -> dict | None:
    """Returns today's challenge question."""
    today = nigeria_today()
    result = supabase.table('daily_challenges')\
        .select('*')\
        .eq('challenge_date', today)\
        .execute()
    
    return result.data[0] if result.data else None

async def has_student_attempted_today(student_id: str) -> bool:
    """Checks if a student has already attempted today's challenge."""
    challenge = await get_todays_challenge()
    if not challenge:
        return False
    
    attempt = supabase.table('daily_challenge_attempts')\
        .select('id')\
        .eq('challenge_id', challenge['id'])\
        .eq('student_id', student_id)\
        .execute()
    
    return bool(attempt.data)

def format_daily_challenge(challenge: dict) -> str:
    """Formats the daily challenge for display."""
    return (
        f"⚔️ *Daily Challenge — {challenge.get('challenge_date')}*\n\n"
        f"_{challenge.get('subject', 'Mixed')} — Hard Level_\n\n"
        f"{challenge['question_text']}\n\n"
        f"*A.* {challenge.get('option_a', '')}\n"
        f"*B.* {challenge.get('option_b', '')}\n"
        f"*C.* {challenge.get('option_c', '')}\n"
        f"*D.* {challenge.get('option_d', '')}\n\n"
        f"🏆 First correct answer wins 100 bonus points!\n"
        f"💰 Everyone who attempts earns 50 points.\n\n"
        f"_Reply with A, B, C, or D_"
    )

async def submit_challenge_answer(
    student_id: str,
    answer: str,
    challenge: dict
) -> tuple[bool, str, int]:
    """
    Submits a student's answer to the daily challenge.
    
    Returns:
    - is_correct: bool
    - feedback: str (the message to send the student)
    - points_earned: int
    """
    correct_answer = challenge.get('correct_answer', '').upper()
    student_answer = answer.strip().upper()
    
    if student_answer not in ['A', 'B', 'C', 'D']:
        return None, "Please reply with *A*, *B*, *C*, or *D* for the daily challenge.", 0
    
    is_correct = student_answer == correct_answer
    
    # Check if this is the first correct answer (winner)
    is_winner = False
    if is_correct and not challenge.get('winner_student_id'):
        # This student is the first to answer correctly!
        is_winner = True
        supabase.table('daily_challenges').update({
            'winner_student_id': student_id,
            'winner_time': nigeria_now().isoformat()
        }).eq('id', challenge['id']).execute()
    
    # Calculate points
    if is_winner:
        points = 150  # 50 for attempting + 100 winner bonus
    elif is_correct:
        points = 60  # 50 for attempting + 10 correct
    else:
        points = 50  # 50 just for attempting
    
    # Record the attempt
    supabase.table('daily_challenge_attempts').insert({
        'challenge_id': challenge['id'],
        'student_id': student_id,
        'answer': student_answer,
        'is_correct': is_correct,
        'points_earned': points,
    }).execute()
    
    # Update challenge stats
    supabase.table('daily_challenges').update({
        'total_attempts': challenge['total_attempts'] + 1,
        'total_correct': challenge['total_correct'] + (1 if is_correct else 0),
    }).eq('id', challenge['id']).execute()
    
    # Award points
    supabase.rpc('add_points_to_student', {
        'student_id_param': student_id,
        'points_to_add': points
    }).execute()
    
    # Build feedback message
    explanation = challenge.get('explanation', '')
    option_map = {
        'A': challenge.get('option_a', ''),
        'B': challenge.get('option_b', ''),
        'C': challenge.get('option_c', ''),
        'D': challenge.get('option_d', ''),
    }
    correct_text = option_map.get(correct_answer, '')
    
    if is_winner:
        feedback = (
            f"🥇 *FIRST CORRECT ANSWER!*\n\n"
            f"Incredible, {student_answer} is right and you got it FIRST!\n\n"
            f"*{correct_answer}. {correct_text}*\n\n"
        )
        if explanation:
            feedback += f"💡 {explanation}\n\n"
        feedback += f"🎉 You earned *{points} points* — including the 100-point winner bonus!"
    elif is_correct:
        feedback = (
            f"{get_correct_message()}\n\n"
            f"*{correct_answer}. {correct_text}*\n\n"
        )
        if explanation:
            feedback += f"💡 {explanation}\n\n"
        feedback += f"You earned *{points} points*! ⭐"
    else:
        feedback = (
            f"{get_almost_message()}\n\n"
            f"You chose: *{student_answer}*\n"
            f"Correct answer: *{correct_answer}. {correct_text}*\n\n"
        )
        if explanation:
            feedback += f"💡 {explanation}\n\n"
        feedback += f"You still earned *{points} points* for participating! Keep it up."
    
    return is_correct, feedback, points

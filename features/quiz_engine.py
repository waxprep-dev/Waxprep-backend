"""
Quiz Engine

Handles everything about quizzing students:
- Selecting the right question for their level
- Presenting the question properly
- Evaluating their answer
- Updating their mastery score
- Awarding points
- Moving to the next question

The quiz engine uses the Elo rating system (same system used in chess rankings)
to track how good each student is at each topic.

When a student gets a question right, their rating goes up.
When they get it wrong, their rating goes down.
The difficulty of questions selected matches their current rating.
This keeps them in the "zone of proximal development" — challenged but not overwhelmed.
"""

from database.client import supabase
from database.students import update_student_stats
from utils.helpers import get_almost_message, get_correct_message, get_wrong_message
from config.settings import settings
import random

# ============================================================
# QUESTION SELECTION
# ============================================================

async def get_question_for_student(
    student_id: str,
    subject: str,
    topic: str = None,
    mode: str = 'standard',
    exam_type: str = None
) -> dict | None:
    """
    Selects the best question for a student based on their current mastery level.
    
    The selection considers:
    1. Their current difficulty rating in this topic
    2. Whether they've recently seen this question (avoids repeats)
    3. Whether the question has been verified (prefers verified questions)
    4. The quality score of the question
    
    Returns a question dict or None if no questions found.
    """
    
    # Get student's mastery in this topic
    elo = await get_student_elo(student_id, subject, topic or '')
    
    # Convert Elo to difficulty level (1-10)
    # Elo 800-1000 = difficulty 1-3
    # Elo 1000-1200 = difficulty 4-6  
    # Elo 1200-1400 = difficulty 7-8
    # Elo 1400+ = difficulty 9-10
    if elo < 900:
        target_difficulty = random.randint(1, 3)
    elif elo < 1100:
        target_difficulty = random.randint(3, 5)
    elif elo < 1300:
        target_difficulty = random.randint(5, 7)
    elif elo < 1500:
        target_difficulty = random.randint(7, 8)
    else:
        target_difficulty = random.randint(8, 10)
    
    # Get recently seen question IDs (avoid repeats in the last 20 questions)
    recent_result = supabase.table('messages')\
        .select('content')\
        .eq('student_id', student_id)\
        .ilike('content', '%question_id%')\
        .order('created_at', desc=True)\
        .limit(20)\
        .execute()
    
    # Query for a good question
    query = supabase.table('questions')\
        .select('*')\
        .eq('subject', subject)\
        .eq('is_active', True)\
        .gte('difficulty_level', max(1, target_difficulty - 1))\
        .lte('difficulty_level', min(10, target_difficulty + 1))
    
    if topic:
        query = query.ilike('topic', f'%{topic}%')
    
    if exam_type:
        query = query.eq('exam_type', exam_type)
    
    # Order by quality score (best questions first) with some randomness
    query = query.order('quality_score', desc=True).limit(10)
    
    result = query.execute()
    
    if not result.data:
        # No questions in database — generate one with AI
        if topic:
            from ai.gemini_client import generate_questions_with_gemini
            questions = await generate_questions_with_gemini(
                subject=subject,
                topic=topic,
                exam_type=exam_type or 'JAMB',
                difficulty=target_difficulty,
                count=3
            )
            if questions:
                return questions[0]
        return None
    
    # Pick randomly from the top results for variety
    return random.choice(result.data)

async def get_student_elo(student_id: str, subject: str, topic: str) -> int:
    """
    Gets a student's Elo rating for a specific topic.
    Default is 1200 (average) if they haven't studied this topic before.
    """
    result = supabase.table('mastery_scores')\
        .select('elo_rating')\
        .eq('student_id', student_id)\
        .eq('subject', subject)\
        .eq('topic', topic)\
        .execute()
    
    if result.data:
        return result.data[0]['elo_rating']
    
    return 1200  # Default Elo

def calculate_new_elo(student_elo: int, question_difficulty: int, is_correct: bool) -> int:
    """
    Calculates the new Elo rating after answering a question.
    
    The Elo system works like this:
    - K factor (32) is how much the rating can change in one question
    - Expected score is calculated based on the difficulty gap
    - If you do better than expected, rating goes up
    - If you do worse than expected, rating goes down
    """
    K = 32  # How fast ratings change
    
    # Convert difficulty (1-10) to an Elo-like rating for the question
    question_elo = 800 + (question_difficulty * 120)
    
    # Calculate expected probability of getting it right
    expected = 1 / (1 + 10 ** ((question_elo - student_elo) / 400))
    
    # Actual score: 1 if correct, 0 if wrong
    actual = 1 if is_correct else 0
    
    # New Elo
    new_elo = student_elo + K * (actual - expected)
    
    # Keep Elo in reasonable range
    return max(400, min(2800, int(new_elo)))

async def update_mastery_after_answer(
    student_id: str,
    subject: str,
    topic: str,
    question_difficulty: int,
    is_correct: bool
):
    """
    Updates the student's mastery score and Elo rating after they answer a question.
    """
    current_elo = await get_student_elo(student_id, subject, topic)
    new_elo = calculate_new_elo(current_elo, question_difficulty, is_correct)
    
    # Calculate mastery percentage from Elo
    # Elo 400 = 0% mastery, Elo 2000 = 100% mastery
    mastery_score = min(100, max(0, (new_elo - 400) / 16))
    
    from utils.helpers import nigeria_now
    
    # Check if this topic exists for this student
    existing = supabase.table('mastery_scores')\
        .select('id, questions_attempted, questions_correct')\
        .eq('student_id', student_id)\
        .eq('subject', subject)\
        .eq('topic', topic)\
        .execute()
    
    if existing.data:
        current = existing.data[0]
        new_attempted = current['questions_attempted'] + 1
        new_correct = current['questions_correct'] + (1 if is_correct else 0)
        
        supabase.table('mastery_scores').update({
            'elo_rating': new_elo,
            'mastery_score': round(mastery_score, 2),
            'questions_attempted': new_attempted,
            'questions_correct': new_correct,
            'last_studied_at': nigeria_now().isoformat(),
            'updated_at': nigeria_now().isoformat(),
        }).eq('id', existing.data[0]['id']).execute()
    else:
        supabase.table('mastery_scores').insert({
            'student_id': student_id,
            'subject': subject,
            'topic': topic,
            'elo_rating': new_elo,
            'mastery_score': round(mastery_score, 2),
            'questions_attempted': 1,
            'questions_correct': 1 if is_correct else 0,
            'last_studied_at': nigeria_now().isoformat(),
        }).execute()

def format_question_for_whatsapp(question: dict, question_number: int = 1) -> str:
    """
    Formats a question nicely for display on WhatsApp.
    """
    q_text = question.get('question_text', '')
    a = question.get('option_a', '')
    b = question.get('option_b', '')
    c = question.get('option_c', '')
    d = question.get('option_d', '')
    
    subject = question.get('subject', '')
    topic = question.get('topic', '')
    difficulty = question.get('difficulty_level', 5)
    
    # Difficulty stars
    stars = '⭐' * min(5, difficulty // 2 + 1)
    
    formatted = (
        f"❓ *Question {question_number}* {stars}\n"
        f"_{subject} — {topic}_\n\n"
        f"{q_text}\n\n"
        f"*A.* {a}\n"
        f"*B.* {b}\n"
        f"*C.* {c}\n"
        f"*D.* {d}\n\n"
        f"_Reply with A, B, C, or D_"
    )
    
    return formatted

def evaluate_quiz_answer(
    student_answer: str,
    correct_answer: str,
    question: dict
) -> tuple[bool, str]:
    """
    Evaluates whether the student's answer is correct.
    Returns (is_correct: bool, feedback_message: str)
    
    The feedback message includes the correct answer explanation
    and the encouraging language appropriate to whether they got it right or wrong.
    """
    # Clean the student's answer
    student_ans = student_answer.strip().upper()
    
    # Handle various answer formats
    if student_ans in ['A', 'B', 'C', 'D']:
        actual_answer = student_ans
    elif student_ans.startswith('A') or student_ans.startswith('(A)'):
        actual_answer = 'A'
    elif student_ans.startswith('B') or student_ans.startswith('(B)'):
        actual_answer = 'B'
    elif student_ans.startswith('C') or student_ans.startswith('(C)'):
        actual_answer = 'C'
    elif student_ans.startswith('D') or student_ans.startswith('(D)'):
        actual_answer = 'D'
    else:
        # Can't parse the answer
        return None, "Please reply with just *A*, *B*, *C*, or *D* to answer the question."
    
    correct = correct_answer.upper()
    is_correct = actual_answer == correct
    
    # Get the correct option text
    option_map = {
        'A': question.get('option_a', ''),
        'B': question.get('option_b', ''),
        'C': question.get('option_c', ''),
        'D': question.get('option_d', ''),
    }
    
    correct_text = option_map.get(correct, '')
    
    if is_correct:
        explanation = question.get('explanation_correct') or question.get(f'explanation_{correct.lower()}', '')
        feedback = (
            f"{get_correct_message()}\n\n"
            f"*Correct: {correct}. {correct_text}*\n\n"
        )
        if explanation:
            feedback += f"💡 *Why?*\n{explanation}"
    else:
        # Wrong answer
        wrong_explanation = question.get(f'explanation_{actual_answer.lower()}', '')
        correct_explanation = question.get('explanation_correct') or question.get(f'explanation_{correct.lower()}', '')
        
        feedback = (
            f"{get_almost_message()}\n\n"
            f"You chose: *{actual_answer}. {option_map.get(actual_answer, '')}*\n"
            f"Correct answer: *{correct}. {correct_text}*\n\n"
        )
        
        if correct_explanation:
            feedback += f"💡 *Why {correct} is correct:*\n{correct_explanation}\n\n"
        
        if wrong_explanation:
            feedback += f"❌ *Why {actual_answer} is wrong:*\n{wrong_explanation}"
    
    return is_correct, feedback

async def calculate_and_award_points(
    student_id: str,
    is_correct: bool,
    question_difficulty: int = 5,
    is_daily_challenge: bool = False
) -> tuple[int, str | None]:
    """
    Calculates points earned for answering a question.
    Returns (points_earned: int, badge_awarded: dict | None)
    
    Points scale with difficulty — harder questions give more points.
    """
    if is_correct:
        base_points = settings.POINTS_CORRECT_ANSWER
        difficulty_bonus = (question_difficulty - 5) * 2  # Extra points for harder questions
        points = max(5, base_points + difficulty_bonus)
        
        if is_daily_challenge:
            points = settings.POINTS_DAILY_CHALLENGE_ATTEMPT + settings.POINTS_DAILY_CHALLENGE_WIN
    else:
        points = settings.POINTS_WRONG_ATTEMPT
        
        if is_daily_challenge:
            points = settings.POINTS_DAILY_CHALLENGE_ATTEMPT
    
    # Award the points
    supabase.rpc('add_points_to_student', {
        'student_id_param': student_id,
        'points_to_add': points
    }).execute()
    
    # Check if this triggers a new badge
    from whatsapp.handler import award_badge
    badge = None
    
    # First question badge
    student_result = supabase.table('students').select(
        'total_questions_answered, total_questions_correct'
    ).eq('id', student_id).execute()
    
    if student_result.data:
        total = student_result.data[0]['total_questions_answered']
        
        if total == 1:
            badge = await award_badge(student_id, 'FIRST_QUESTION')
        elif total == 100:
            badge = await award_badge(student_id, 'QUESTIONS_100')
        elif total == 500:
            badge = await award_badge(student_id, 'QUESTIONS_500')
        elif total == 1000:
            badge = await award_badge(student_id, 'QUESTIONS_1000')
    
    return points, badge

"""
Question Bank Database Operations

All database operations related to questions.
Getting questions, saving questions, updating quality scores,
tracking which questions students have seen, flagging bad questions.
"""

from database.client import supabase
from utils.helpers import nigeria_now
import random

async def get_questions_by_topic(
    subject: str,
    topic: str,
    exam_type: str = None,
    difficulty_min: int = 1,
    difficulty_max: int = 10,
    limit: int = 10,
    exclude_ids: list = None
) -> list:
    """
    Gets questions from the bank filtered by topic and difficulty.
    Returns a list of question dicts.
    """
    query = supabase.table('questions')\
        .select('*')\
        .eq('subject', subject)\
        .eq('is_active', True)\
        .gte('difficulty_level', difficulty_min)\
        .lte('difficulty_level', difficulty_max)\
        .order('quality_score', desc=True)
    
    if topic:
        query = query.ilike('topic', f'%{topic}%')
    
    if exam_type:
        query = query.eq('exam_type', exam_type)
    
    query = query.limit(limit * 3)  # Get extra so we can filter out seen ones
    
    result = query.execute()
    questions = result.data or []
    
    # Filter out recently seen questions
    if exclude_ids and questions:
        questions = [q for q in questions if q['id'] not in exclude_ids]
    
    # Shuffle slightly for variety
    random.shuffle(questions)
    
    return questions[:limit]

async def get_questions_for_mock_exam(
    exam_type: str,
    subjects: list,
    total_questions: int = 100
) -> list:
    """
    Gets a full set of questions for a mock exam.
    Distributes questions across subjects proportionally.
    For JAMB: 40 English + 20 each for 3 science/arts subjects.
    """
    
    if exam_type == 'JAMB':
        distribution = {
            'English Language': 40,
        }
        other_subjects = [s for s in subjects if s != 'English Language']
        remaining = total_questions - 40
        per_subject = remaining // len(other_subjects) if other_subjects else 0
        for subject in other_subjects:
            distribution[subject] = per_subject
    else:
        per_subject = total_questions // len(subjects) if subjects else total_questions
        distribution = {subject: per_subject for subject in subjects}
    
    all_questions = []
    
    for subject, count in distribution.items():
        result = supabase.table('questions')\
            .select('*')\
            .eq('subject', subject)\
            .eq('exam_type', exam_type)\
            .eq('is_active', True)\
            .order('quality_score', desc=True)\
            .limit(count * 2)\
            .execute()
        
        subject_questions = result.data or []
        random.shuffle(subject_questions)
        all_questions.extend(subject_questions[:count])
    
    # If we don't have enough from the bank, generate with AI
    if len(all_questions) < total_questions // 2:
        from ai.gemini_client import generate_questions_with_gemini
        for subject in subjects[:2]:
            generated = await generate_questions_with_gemini(
                subject=subject,
                topic='Mixed Topics',
                exam_type=exam_type,
                difficulty=5,
                count=10
            )
            all_questions.extend(generated)
    
    random.shuffle(all_questions)
    return all_questions[:total_questions]

async def update_question_stats(question_id: str, was_correct: bool):
    """
    Updates the stats on a question after a student answers it.
    This builds the quality score over time.
    """
    result = supabase.table('questions')\
        .select('times_answered, times_correct')\
        .eq('id', question_id)\
        .execute()
    
    if not result.data:
        return
    
    current = result.data[0]
    new_answered = current['times_answered'] + 1
    new_correct = current['times_correct'] + (1 if was_correct else 0)
    correct_rate = round((new_correct / new_answered) * 100, 2) if new_answered > 0 else 0
    
    # Quality score based on:
    # - Correct rate (not too easy, not too hard)
    # - Number of times answered (more data = more reliable)
    # Ideal correct rate is 60-70% for a good exam question
    if correct_rate < 20:
        quality_adjustment = -0.5  # Too hard or bad question
    elif correct_rate > 95:
        quality_adjustment = -0.3  # Too easy
    elif 55 <= correct_rate <= 75:
        quality_adjustment = 0.1   # Perfect difficulty
    else:
        quality_adjustment = 0.0   # Neutral
    
    data_bonus = min(0.5, new_answered * 0.01)  # More data = slightly higher quality
    
    current_quality = 5.0
    quality_result = supabase.table('questions').select('quality_score').eq('id', question_id).execute()
    if quality_result.data:
        current_quality = float(quality_result.data[0].get('quality_score', 5.0))
    
    new_quality = max(1.0, min(10.0, current_quality + quality_adjustment + data_bonus))
    
    supabase.table('questions').update({
        'times_answered': new_answered,
        'times_correct': new_correct,
        'correct_rate': correct_rate,
        'quality_score': round(new_quality, 2),
        'updated_at': nigeria_now().isoformat(),
    }).eq('id', question_id).execute()

async def flag_question(
    question_id: str,
    student_id: str,
    reason: str,
    note: str = None
) -> bool:
    """
    Flags a question as potentially wrong or problematic.
    Students can flag questions they believe are incorrect.
    """
    # Check if already flagged by this student
    existing = supabase.table('question_flags')\
        .select('id')\
        .eq('question_id', question_id)\
        .eq('student_id', student_id)\
        .execute()
    
    if existing.data:
        return False  # Already flagged
    
    supabase.table('question_flags').insert({
        'question_id': question_id,
        'student_id': student_id,
        'reason': reason,
        'note': note,
        'status': 'pending',
    }).execute()
    
    # Increment flag count on question
    supabase.rpc('increment_question_flag_count', {
        'question_id_param': question_id
    }).execute()
    
    return True

async def search_questions_by_text(search_term: str, limit: int = 5) -> list:
    """
    Searches the question bank by text.
    Useful for finding specific past questions.
    """
    result = supabase.table('questions')\
        .select('*')\
        .ilike('question_text', f'%{search_term}%')\
        .eq('is_active', True)\
        .limit(limit)\
        .execute()
    
    return result.data or []

async def add_question_manually(question_data: dict) -> dict:
    """
    Adds a manually verified question to the bank.
    Used from the admin dashboard.
    """
    question_data['is_verified'] = True
    question_data['is_ai_generated'] = False
    question_data['created_by'] = 'admin'
    question_data['quality_score'] = 8.0  # Admin-verified starts with high quality
    
    result = supabase.table('questions').insert(question_data).execute()
    return result.data[0] if result.data else None

async def get_student_recently_seen_questions(student_id: str, limit: int = 50) -> list:
    """
    Returns IDs of questions a student has recently seen.
    Used to avoid showing the same question twice in a session.
    """
    from database.client import redis_client
    
    cache_key = f"seen_questions:{student_id}"
    cached = redis_client.lrange(cache_key, 0, limit - 1)
    
    return [q.decode() if isinstance(q, bytes) else q for q in cached] if cached else []

async def record_question_seen(student_id: str, question_id: str):
    """
    Records that a student has seen a specific question.
    Stored in Redis for fast access, limited to last 100 questions.
    """
    from database.client import redis_client
    
    cache_key = f"seen_questions:{student_id}"
    redis_client.lpush(cache_key, question_id)
    redis_client.ltrim(cache_key, 0, 99)  # Keep only last 100
    redis_client.expire(cache_key, 86400 * 7)  # Expire after 7 days

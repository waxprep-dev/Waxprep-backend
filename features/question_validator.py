"""
Question Validation Pipeline

This is how the system knows if a question is right or wrong.

Three mechanisms:
1. Statistical: After enough answers, if correct_rate is suspiciously low
   (< 5%) or suspiciously high (> 98%), the question is flagged automatically.
   A correct_rate under 5% usually means the stored answer is wrong.
   A correct_rate over 98% usually means the question is too easy or trivial.

2. Community: If 3 or more students flag a question, it is auto-suspended
   pending admin review.

3. Admin: Admin can manually verify, edit, or delete any question.

Questions go through these states:
  is_ai_generated=True, is_verified=False → Under evaluation
  is_verified=True → Confirmed good
  is_active=False → Suspended (bad quality or flagged)
"""

from database.client import supabase
from config.settings import settings


async def evaluate_question_quality(question_id: str) -> dict:
    """
    Evaluates a question after it has been answered enough times.
    Returns action taken: 'none', 'flagged', 'deactivated', 'ok'.
    """
    try:
        result = supabase.table('questions').select(
            'id, question_text, subject, topic, times_answered, times_correct, '
            'correct_rate, quality_score, is_verified, is_active, flag_count, '
            'is_ai_generated, created_by'
        ).eq('id', question_id).execute()

        if not result.data:
            return {'action': 'not_found'}

        q = result.data[0]
        times_answered = q.get('times_answered', 0)
        times_correct = q.get('times_correct', 0)
        flag_count = q.get('flag_count', 0) or 0
        is_active = q.get('is_active', True)

        if not is_active:
            return {'action': 'already_inactive'}

        action = 'none'
        notes = []

        # Auto-suspend if too many community flags
        if flag_count >= 3:
            supabase.table('questions').update({
                'is_active': False,
                'quality_notes': f'Auto-suspended: {flag_count} student flags',
            }).eq('id', question_id).execute()
            action = 'deactivated_by_flags'
            notes.append(f'Suspended: {flag_count} flags from students')

            await _notify_admin_question_issue(q, f"Auto-suspended after {flag_count} student flags")
            return {'action': action, 'notes': notes}

        # Only evaluate statistically after enough answers
        min_answers = settings.QUESTION_MIN_ANSWERS_TO_EVALUATE
        if times_answered < min_answers:
            return {'action': 'insufficient_data', 'answers_so_far': times_answered}

        correct_rate = times_correct / times_answered if times_answered > 0 else 0

        # Suspiciously low correct rate — stored answer may be wrong
        min_rate = settings.QUESTION_SUSPICIOUS_CORRECT_RATE_MIN
        max_rate = settings.QUESTION_SUSPICIOUS_CORRECT_RATE_MAX
        
        if correct_rate < min_rate:
            supabase.table('questions').update({
                'is_active': False,
                'quality_notes': (
                    f'Auto-suspended: correct_rate={correct_rate:.1%} '
                    f'after {times_answered} answers — possible wrong stored answer'
                ),
            }).eq('id', question_id).execute()
            action = 'deactivated_wrong_answer'
            notes.append(f'Correct rate only {correct_rate:.1%} — stored answer may be wrong')
            await _notify_admin_question_issue(
                q,
                f"Possible wrong answer: only {correct_rate:.1%} of {times_answered} students got it right"
            )

        # Suspiciously high correct rate — question may be too trivial
        elif correct_rate > max_rate:
            new_quality = max(q.get('quality_score', 5.0) - 1.5, 1.0)
            supabase.table('questions').update({
                'quality_score': new_quality,
                'quality_notes': (
                    f'Quality reduced: correct_rate={correct_rate:.1%} — too easy'
                ),
            }).eq('id', question_id).execute()
            action = 'quality_reduced_too_easy'
            notes.append(f'Too easy: {correct_rate:.1%} correct rate')

        else:
            # Normal range — good question, boost quality score slightly
            ideal_rate = 0.55  # ideal is 55% correct rate
            deviation = abs(correct_rate - ideal_rate)
            quality_boost = max(0, 0.1 - deviation * 0.2)

            current_quality = q.get('quality_score', 5.0) or 5.0
            data_bonus = min(0.5, times_answered * 0.01)
            new_quality = min(10.0, current_quality + quality_boost + data_bonus)

            supabase.table('questions').update({
                'quality_score': round(new_quality, 2),
            }).eq('id', question_id).execute()
            action = 'ok'

        return {
            'action': action,
            'correct_rate': correct_rate,
            'times_answered': times_answered,
            'notes': notes,
        }

    except Exception as e:
        print(f"Question quality evaluation error: {e}")
        return {'action': 'error', 'error': str(e)}


async def submit_student_flag(
    question_id: str,
    student_id: str,
    reason: str,
    note: str = None
) -> tuple[bool, str]:
    """
    Allows a student to flag a question as wrong or problematic.
    Returns (success: bool, message: str).
    """
    try:
        # Check if already flagged by this student
        existing = supabase.table('question_flags')\
            .select('id')\
            .eq('question_id', question_id)\
            .eq('student_id', student_id)\
            .execute()

        if existing.data:
            return False, "You have already flagged this question."

        # Record the flag
        supabase.table('question_flags').insert({
            'question_id': question_id,
            'student_id': student_id,
            'reason': reason,
            'note': note or '',
            'status': 'pending',
        }).execute()

        # Increment flag count on the question
        try:
            supabase.rpc('increment_question_flag_count', {
                'question_id_param': question_id
            }).execute()
        except Exception:
            # Fallback manual increment
            q = supabase.table('questions').select('flag_count').eq('id', question_id).execute()
            if q.data:
                current = q.data[0].get('flag_count', 0) or 0
                supabase.table('questions').update({
                    'flag_count': current + 1
                }).eq('id', question_id).execute()

        # Evaluate quality after flagging
        await evaluate_question_quality(question_id)

        return True, "Thank you! Your flag has been recorded and will be reviewed."

    except Exception as e:
        print(f"Question flag error: {e}")
        return False, "Could not record your flag right now. Please try again."


async def verify_question(question_id: str, admin_verified: bool = True) -> bool:
    """Marks a question as admin-verified (good) or deactivated (bad)."""
    try:
        supabase.table('questions').update({
            'is_verified': admin_verified,
            'is_active': admin_verified,
            'quality_score': 8.0 if admin_verified else 0.0,
            'quality_notes': 'Admin verified' if admin_verified else 'Admin rejected',
        }).eq('id', question_id).execute()

        if admin_verified:
            supabase.table('question_flags').update({'status': 'resolved_kept'})\
                .eq('question_id', question_id).execute()
        else:
            supabase.table('question_flags').update({'status': 'resolved_removed'})\
                .eq('question_id', question_id).execute()

        return True
    except Exception as e:
        print(f"Question verification error: {e}")
        return False


async def get_questions_needing_review(limit: int = 10) -> list:
    """Returns questions that need admin review."""
    try:
        flagged = supabase.table('question_flags')\
            .select('question_id, reason, note, created_at, questions(question_text, subject, topic, correct_answer, correct_rate, times_answered)')\
            .eq('status', 'pending')\
            .order('created_at', desc=False)\
            .limit(limit)\
            .execute()

        return flagged.data or []
    except Exception as e:
        print(f"Get flagged questions error: {e}")
        return []


async def run_nightly_quality_check():
    """
    Runs every night to evaluate all questions that have enough answers.
    Called by the scheduler.
    """
    try:
        min_answers = settings.QUESTION_MIN_ANSWERS_TO_EVALUATE

        candidates = supabase.table('questions')\
            .select('id')\
            .eq('is_active', True)\
            .gte('times_answered', min_answers)\
            .execute()

        if not candidates.data:
            return

        count = 0
        deactivated = 0
        for row in candidates.data:
            result = await evaluate_question_quality(row['id'])
            count += 1
            if 'deactivated' in result.get('action', ''):
                deactivated += 1

        print(f"Nightly quality check: {count} questions evaluated, {deactivated} deactivated")

    except Exception as e:
        print(f"Nightly quality check error: {e}")


async def _notify_admin_question_issue(question: dict, reason: str):
    """Notifies admin when a question is auto-suspended."""
    try:
        from features.notifications import notify_admin_alert
        subject = question.get('subject', 'Unknown')
        topic = question.get('topic', 'Unknown')
        q_text = (question.get('question_text', '') or '')[:100]
        q_id = str(question.get('id', ''))[:8]

        details = (
            f"Question auto-suspended\n\n"
            f"Subject: {subject}\n"
            f"Topic: {topic}\n"
            f"ID prefix: {q_id}\n"
            f"Reason: {reason}\n"
            f"Question: {q_text}...\n\n"
            f"Review with: ADMIN QUESTIONS PENDING"
        )
        await notify_admin_alert('question_quality', details)
    except Exception as e:
        print(f"Question issue notification error: {e}")

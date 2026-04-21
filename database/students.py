"""
Student Database Operations

All cross-module imports are lazy to prevent startup errors.
"""


async def create_student(
    phone: str,
    name: str,
    pin: str,
    class_level: str = None,
    target_exam: str = None,
    subjects: list = None,
    exam_date: str = None,
    school_name: str = None,
    state: str = None,
    referred_by_wax_id: str = None
) -> dict:
    """Creates a new student account. Called at end of onboarding."""
    from database.client import supabase
    from helpers import hash_phone, hash_pin, clean_name, generate_referral_code, nigeria_now
    from features.wax_id import create_new_wax_id, create_new_recovery_code
    from config.settings import settings
    from datetime import timedelta

    wax_id = await create_new_wax_id()
    recovery_code = await create_new_recovery_code()
    phone_hash = hash_phone(phone)
    pin_hash_value = hash_pin(pin)
    referral_code = generate_referral_code(wax_id)

    now = nigeria_now()
    trial_end = now + timedelta(days=settings.TRIAL_DURATION_DAYS)

    student_data = {
        'wax_id': wax_id,
        'name': clean_name(name),
        'phone_hash': phone_hash,
        'pin_hash': pin_hash_value,
        'recovery_code': recovery_code,
        'class_level': class_level,
        'target_exam': target_exam,
        'subjects': subjects or [],
        'exam_date': exam_date,
        'school_name': school_name,
        'state': state,
        'referral_code': referral_code,
        'referred_by_wax_id': referred_by_wax_id,
        'trial_started_at': now.isoformat(),
        'trial_expires_at': trial_end.isoformat(),
        'is_trial_active': True,
        'subscription_tier': 'free',
        'onboarding_complete': True,
    }

    result = supabase.table('students').insert(student_data).execute()
    if not result.data:
        raise Exception("Failed to create student account — Supabase returned no data")

    new_student = result.data[0]

    if referred_by_wax_id:
        try:
            await record_referral(referred_by_wax_id, new_student['id'], wax_id)
        except Exception as e:
            print(f"Referral recording error (non-critical): {e}")

    return new_student


async def update_student(student_id: str, updates: dict) -> dict | None:
    """Updates any fields in a student's record."""
    from database.client import supabase
    from helpers import nigeria_now

    updates['updated_at'] = nigeria_now().isoformat()

    try:
        result = supabase.table('students').update(updates).eq('id', student_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"update_student error: {e}")
        return None


async def get_student_subscription_status(student: dict) -> dict:
    """
    Returns the effective subscription status.
    Checks trial, paid subscription, grace period.
    """
    from helpers import nigeria_now
    from config.settings import settings
    from datetime import timedelta, datetime

    now = nigeria_now()

    # Check trial first
    trial_active = student.get('is_trial_active', False)
    trial_expires_str = student.get('trial_expires_at')

    if trial_active and trial_expires_str:
        try:
            if isinstance(trial_expires_str, str):
                trial_exp = datetime.fromisoformat(trial_expires_str.replace('Z', '+00:00'))
            else:
                trial_exp = trial_expires_str

            if trial_exp > now:
                days_left = (trial_exp - now).days
                return {
                    'effective_tier': 'trial',
                    'is_active': True,
                    'expires_at': trial_exp,
                    'days_remaining': days_left,
                    'is_in_grace_period': False,
                    'is_trial': True,
                    'display_tier': 'Full Trial Access'
                }
            else:
                await update_student(student['id'], {'is_trial_active': False})
        except Exception as e:
            print(f"Trial check error: {e}")

    # Check paid subscription
    tier = student.get('subscription_tier', 'free')
    sub_expires_str = student.get('subscription_expires_at')

    if tier != 'free' and sub_expires_str:
        try:
            if isinstance(sub_expires_str, str):
                sub_exp = datetime.fromisoformat(sub_expires_str.replace('Z', '+00:00'))
            else:
                sub_exp = sub_expires_str

            if sub_exp > now:
                days_left = (sub_exp - now).days
                return {
                    'effective_tier': tier,
                    'is_active': True,
                    'expires_at': sub_exp,
                    'days_remaining': days_left,
                    'is_in_grace_period': False,
                    'is_trial': False,
                    'display_tier': tier.capitalize()
                }
            else:
                grace_end = sub_exp + timedelta(days=settings.GRACE_PERIOD_DAYS)
                if now < grace_end:
                    days_left = (grace_end - now).days
                    return {
                        'effective_tier': tier,
                        'is_active': True,
                        'expires_at': grace_end,
                        'days_remaining': days_left,
                        'is_in_grace_period': True,
                        'is_trial': False,
                        'display_tier': f'{tier.capitalize()} (Grace Period)'
                    }
        except Exception as e:
            print(f"Subscription check error: {e}")

    # Free tier
    return {
        'effective_tier': 'free',
        'is_active': True,
        'expires_at': None,
        'days_remaining': None,
        'is_in_grace_period': False,
        'is_trial': False,
        'display_tier': 'Free'
    }


async def can_student_ask_question(student: dict) -> tuple:
    """
    Checks if a student can ask another question today.
    Always fetches fresh data to avoid stale counts.
    Returns (can_ask: bool, message: str)
    """
    from database.client import supabase
    from config.settings import settings
    from helpers import nigeria_today, nigeria_now, format_naira
    from datetime import datetime
    from zoneinfo import ZoneInfo

    student_id = student.get('id')
    if not student_id:
        return False, "Account error. Please contact support."

    # Always get fresh question count
    fresh = supabase.table('students')\
        .select('questions_today, questions_today_reset_date, subscription_tier, '
                'subscription_expires_at, is_trial_active, trial_expires_at')\
        .eq('id', student_id)\
        .execute()

    if not fresh.data:
        return False, "Account not found."

    f = fresh.data[0]
    today = nigeria_today()

    if f.get('questions_today_reset_date') != today:
        supabase.table('students').update({
            'questions_today': 0,
            'questions_today_reset_date': today,
        }).eq('id', student_id).execute()
        questions_today = 0
    else:
        questions_today = f.get('questions_today', 0)

    # Determine tier
    now = datetime.now(ZoneInfo("Africa/Lagos"))
    is_on_trial = False

    trial_active = f.get('is_trial_active', False)
    trial_expires_str = f.get('trial_expires_at')

    if trial_active and trial_expires_str:
        try:
            trial_exp = datetime.fromisoformat(trial_expires_str.replace('Z', '+00:00'))
            if trial_exp > now:
                is_on_trial = True
        except Exception:
            pass

    effective_tier = 'trial' if is_on_trial else f.get('subscription_tier', 'free')
    limit = settings.get_daily_question_limit(effective_tier, is_on_trial)

    if questions_today >= limit:
        if effective_tier == 'free':
            return False, (
                f"You've used all {limit} free questions for today 📊\n\n"
                f"Your questions reset at midnight Nigerian time.\n\n"
                f"*Scholar Plan — {format_naira(settings.SCHOLAR_MONTHLY)}/month*\n"
                f"Get 60 questions daily + image analysis + mock exams + more.\n\n"
                f"Type *SUBSCRIBE* to upgrade now. 💡"
            )
        else:
            return False, (
                f"You've used all {limit} questions for today 📊\n\n"
                f"Questions reset at midnight. Great work today! 🌙"
            )

    return True, ""


async def increment_questions_today(student_id: str):
    """Safely increments the question count for today."""
    from database.client import supabase

    try:
        supabase.rpc('increment_questions_today', {'student_id': student_id}).execute()
    except Exception as e:
        print(f"increment_questions_today error: {e}")


async def get_student_profile_summary(student: dict) -> str:
    """Returns a formatted profile summary for the PROGRESS command."""
    from helpers import format_naira
    from config.settings import settings

    status = await get_student_subscription_status(student)
    name = student.get('name', 'Student')
    wax_id = student.get('wax_id', 'Unknown')
    tier = status['display_tier']
    streak = student.get('current_streak', 0)
    points = student.get('total_points', 0)
    level = student.get('current_level', 1)
    level_name = student.get('level_name', 'Scholar')
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0, 1)

    summary = (
        f"📊 *{name.split()[0]}'s WaxPrep Profile*\n\n"
        f"🆔 WAX ID: {wax_id}\n"
        f"⭐ Plan: {tier}\n"
        f"🏆 Level: {level} — {level_name}\n"
        f"💰 Points: {points:,}\n\n"
        f"📈 *Your Progress*\n"
        f"✅ Questions Answered: {answered:,}\n"
        f"🎯 Correct: {correct:,}\n"
        f"📊 Accuracy: {accuracy}%\n"
        f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}\n\n"
    )

    if status['is_trial']:
        days_left = status.get('days_remaining', 0)
        summary += (
            f"⏰ Trial ends in: {days_left} day{'s' if days_left != 1 else ''}\n"
            f"Type *SUBSCRIBE* to keep full access.\n"
        )
    elif status.get('is_in_grace_period'):
        days_left = status.get('days_remaining', 0)
        summary += (
            f"⚠️ Grace period: {days_left} day{'s' if days_left != 1 else ''} left\n"
            f"Type *SUBSCRIBE* to renew now.\n"
        )

    summary += f"\n_Your WAX ID is permanent. Never share your PIN._"
    return summary


async def record_referral(referrer_wax_id: str, referred_student_id: str, referred_wax_id: str):
    """Records a referral relationship between two students."""
    from database.client import supabase

    referrer = supabase.table('students').select('id').eq('wax_id', referrer_wax_id).execute()
    if not referrer.data:
        return

    referrer_id = referrer.data[0]['id']

    try:
        supabase.table('referrals').insert({
            'referrer_student_id': referrer_id,
            'referred_student_id': referred_student_id,
            'referrer_wax_id': referrer_wax_id,
            'status': 'active'
        }).execute()
    except Exception:
        pass

    try:
        supabase.rpc('increment_referral_count', {'student_id': referrer_id}).execute()
    except Exception as e:
        print(f"Referral count increment error: {e}")

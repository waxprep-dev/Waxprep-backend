from database.client import supabase
from utils.helpers import (
    hash_phone, generate_wax_id, clean_name,
    nigeria_now, nigeria_today
)
from features.wax_id import create_new_wax_id, create_new_recovery_code
from features.pin import hash_pin
from config.settings import settings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NIGERIA_TZ = ZoneInfo("Africa/Lagos")

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
    """
    Creates a new student account.
    This is called when someone completes onboarding for the first time.
    Returns the newly created student record.
    """
    from utils.helpers import generate_referral_code
    
    # Generate all the unique identifiers
    wax_id = await create_new_wax_id()
    recovery_code = await create_new_recovery_code()
    phone_hash = hash_phone(phone)
    pin_hash_value = hash_pin(pin)
    referral_code = generate_referral_code(wax_id)
    
    # Calculate trial expiry
    trial_start = nigeria_now()
    trial_end = trial_start + timedelta(days=settings.TRIAL_DURATION_DAYS)
    
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
        'trial_started_at': trial_start.isoformat(),
        'trial_expires_at': trial_end.isoformat(),
        'is_trial_active': True,
        'subscription_tier': 'free',
        'onboarding_complete': True,
    }
    
    result = supabase.table('students').insert(student_data).execute()
    
    if not result.data:
        raise Exception("Failed to create student account")
    
    new_student = result.data[0]
    
    # If they were referred, record the referral
    if referred_by_wax_id:
        await record_referral(referred_by_wax_id, new_student['id'], wax_id)
    
    return new_student

async def update_student(student_id: str, updates: dict) -> dict:
    """
    Updates any fields in a student's record.
    Always updates the 'updated_at' timestamp automatically.
    """
    updates['updated_at'] = nigeria_now().isoformat()
    result = supabase.table('students').update(updates).eq('id', student_id).execute()
    return result.data[0] if result.data else None

async def get_student_subscription_status(student: dict) -> dict:
    """
    Returns the effective subscription status of a student.
    This considers: trial status, subscription tier, expiry, and grace period.
    
    Returns a dict with:
    - effective_tier: what tier they currently have access to
    - is_active: whether their access is active
    - expires_at: when their access expires
    - days_remaining: how many days left
    - is_in_grace_period: True if subscription expired but in 3-day grace
    - is_trial: True if currently on trial
    """
    now = nigeria_now()
    
    # Check trial first
    trial_expires = student.get('trial_expires_at')
    if trial_expires and student.get('is_trial_active'):
        if isinstance(trial_expires, str):
            trial_expires = datetime.fromisoformat(trial_expires.replace('Z', '+00:00'))
        
        if trial_expires > now:
            days_left = (trial_expires - now).days
            return {
                'effective_tier': 'trial',
                'is_active': True,
                'expires_at': trial_expires,
                'days_remaining': days_left,
                'is_in_grace_period': False,
                'is_trial': True,
                'display_tier': 'Full Trial Access'
            }
        else:
            # Trial has expired — mark it as no longer active
            await update_student(student['id'], {'is_trial_active': False})
    
    # Check paid subscription
    subscription_tier = student.get('subscription_tier', 'free')
    subscription_expires = student.get('subscription_expires_at')
    
    if subscription_tier != 'free' and subscription_expires:
        if isinstance(subscription_expires, str):
            subscription_expires = datetime.fromisoformat(subscription_expires.replace('Z', '+00:00'))
        
        if subscription_expires > now:
            days_left = (subscription_expires - now).days
            return {
                'effective_tier': subscription_tier,
                'is_active': True,
                'expires_at': subscription_expires,
                'days_remaining': days_left,
                'is_in_grace_period': False,
                'is_trial': False,
                'display_tier': subscription_tier.capitalize()
            }
        else:
            # Check grace period (3 days after expiry)
            grace_end = subscription_expires + timedelta(days=settings.GRACE_PERIOD_DAYS)
            if now < grace_end:
                days_in_grace = (grace_end - now).days
                return {
                    'effective_tier': subscription_tier,
                    'is_active': True,
                    'expires_at': grace_end,
                    'days_remaining': days_in_grace,
                    'is_in_grace_period': True,
                    'is_trial': False,
                    'display_tier': f'{subscription_tier.capitalize()} (Grace Period)'
                }
    
    # Free tier — never expires
    return {
        'effective_tier': 'free',
        'is_active': True,
        'expires_at': None,
        'days_remaining': None,
        'is_in_grace_period': False,
        'is_trial': False,
        'display_tier': 'Free'
    }

async def check_and_reset_daily_questions(student: dict) -> dict:
    """
    Checks if the student's daily question count needs to be reset.
    Questions reset at midnight Nigerian time each day.
    Returns the updated student dict.
    """
    today = nigeria_today()
    last_reset = student.get('questions_today_reset_date')
    
    if last_reset != today:
        # It's a new day — reset the counter
        updates = {
            'questions_today': 0,
            'questions_today_reset_date': today
        }
        await update_student(student['id'], updates)
        student['questions_today'] = 0
        student['questions_today_reset_date'] = today
    
    return student

async def can_student_ask_question(student: dict) -> tuple[bool, str]:
    """
    Checks if a student can ask another question (hasn't hit their daily limit).
    Returns (can_ask: bool, message: str)
    
    The message is what we say to the student if they can't ask more.
    """
    student = await check_and_reset_daily_questions(student)
    status = await get_student_subscription_status(student)
    effective_tier = status['effective_tier']
    
    limit = settings.get_daily_question_limit(effective_tier, status['is_trial'])
    current = student.get('questions_today', 0)
    
    if current >= limit:
        if effective_tier == 'free':
            return False, (
                f"You've used all {limit} free questions for today 📊\n\n"
                f"Your questions reset at midnight.\n\n"
                f"To keep studying right now, upgrade to Scholar Plan for just ₦1,500/month — "
                f"that's less than ₦50 per day! You get 60 questions daily and much more.\n\n"
                f"Type *SUBSCRIBE* to upgrade now, or come back at midnight for your free questions."
            )
        else:
            return False, (
                f"You've used all {limit} questions for today 📊\n\n"
                f"Your questions reset at midnight Nigerian time.\n\n"
                f"Great job putting in the work today! See you again at midnight 🌙"
            )
    
    return True, ""

async def increment_questions_today(student_id: str):
    """Adds 1 to the student's question count for today."""
    supabase.rpc('increment_questions_today', {'student_id': student_id}).execute()

async def update_student_stats(
    student_id: str,
    correct: bool,
    points_earned: int
):
    """
    Updates a student's overall statistics after answering a question.
    Called every time a student answers a question.
    """
    # Get current stats
    result = supabase.table('students').select(
        'total_questions_answered, total_questions_correct, total_points, current_level, level_name'
    ).eq('id', student_id).execute()
    
    if not result.data:
        return
    
    current = result.data[0]
    new_total_answered = current['total_questions_answered'] + 1
    new_total_correct = current['total_questions_correct'] + (1 if correct else 0)
    new_total_points = current['total_points'] + points_earned
    
    # Check if they leveled up
    new_level = calculate_level(new_total_points)
    new_level_name = settings.get_level_name(new_level)
    
    updates = {
        'total_questions_answered': new_total_answered,
        'total_questions_correct': new_total_correct,
        'total_points': new_total_points,
        'current_level': new_level,
        'level_name': new_level_name,
    }
    
    await update_student(student_id, updates)
    
    # Check for level up
    old_level = current['current_level']
    if new_level > old_level:
        return {'leveled_up': True, 'new_level': new_level, 'new_level_name': new_level_name}
    return {'leveled_up': False}

def calculate_level(total_points: int) -> int:
    """
    Calculates what level a student should be at based on their total points.
    """
    level = 1
    thresholds = settings.LEVEL_THRESHOLDS
    
    for lvl, threshold in sorted(thresholds.items()):
        if total_points >= threshold:
            level = lvl
        else:
            break
    
    return level

async def get_student_profile_summary(student: dict) -> str:
    """
    Creates a formatted text summary of a student's profile.
    Used for the PROGRESS command and profile viewing.
    """
    status = await get_student_subscription_status(student)
    name = student.get('name', 'Student')
    wax_id = student.get('wax_id', 'Unknown')
    tier = status['display_tier']
    streak = student.get('current_streak', 0)
    points = student.get('total_points', 0)
    level = student.get('current_level', 1)
    level_name = student.get('level_name', 'Scholar')
    total_answered = student.get('total_questions_answered', 0)
    total_correct = student.get('total_questions_correct', 0)
    accuracy = round((total_correct / total_answered * 100) if total_answered > 0 else 0, 1)
    
    summary = f"""📊 *{name}'s WaxPrep Profile*

🆔 WAX ID: {wax_id}
⭐ Plan: {tier}
🏆 Level: {level} — {level_name}
💰 Points: {points:,}

📈 *Your Progress*
✅ Questions Answered: {total_answered:,}
🎯 Correct Answers: {total_correct:,}
📊 Accuracy Rate: {accuracy}%
🔥 Current Streak: {streak} day{"s" if streak != 1 else ""}

"""
    
    if status['is_trial']:
        days_left = status.get('days_remaining', 0)
        summary += f"⏰ Trial ends in: {days_left} day{'s' if days_left != 1 else ''}\n"
        summary += "Type *SUBSCRIBE* to keep full access after your trial.\n"
    elif status.get('is_in_grace_period'):
        days_left = status.get('days_remaining', 0)
        summary += f"⚠️ Grace period: {days_left} day{'s' if days_left != 1 else ''} left\n"
        summary += "Renew now to keep your progress and access.\nType *SUBSCRIBE* to renew.\n"
    
    summary += f"\n_WAX ID is your permanent student identity. Keep it safe._"
    
    return summary

async def record_referral(referrer_wax_id: str, referred_student_id: str, referred_wax_id: str):
    """Records a referral relationship between two students."""
    # Get referrer's student ID
    referrer = supabase.table('students').select('id').eq('wax_id', referrer_wax_id).execute()
    if not referrer.data:
        return
    
    referrer_id = referrer.data[0]['id']
 async def check_and_award_referral_rewards(referrer_id: str):
    """
    Checks if a referrer has earned a referral milestone reward
    and automatically applies it.
    
    3 referrals = 7 days Pro free
    10 referrals = 1 month Pro free
    25 referrals = 1 year Scholar free
    """
    from database.client import supabase
    from utils.helpers import nigeria_now
    from datetime import timedelta
    
    referrer = supabase.table('students').select('referral_count, name')\
        .eq('id', referrer_id).execute()
    
    if not referrer.data:
        return
    
    count = referrer.data[0]['referral_count']
    name = referrer.data[0]['name'].split()[0]
    
    reward = None
    if count == 3:
        reward = {'days': 7, 'tier': 'pro', 'message': f"🎉 *{name}, you referred 3 friends!*\n\nYou've earned 7 days of Pro Plan — FREE!\n\nYour Pro access has been activated. 🚀"}
    elif count == 10:
        reward = {'days': 30, 'tier': 'pro', 'message': f"🏆 *{name}, 10 referrals!*\n\nYou've earned 1 MONTH of Pro Plan — FREE!\n\nYou're making WaxPrep bigger. Thank you! 🙏"}
    elif count == 25:
        reward = {'days': 365, 'tier': 'scholar', 'message': f"👑 *{name}, 25 referrals!*\n\nYou've earned 1 FULL YEAR of Scholar Plan — FREE!\n\nYou're a WaxPrep legend. 🌟"}
    
    if reward:
        new_expires = nigeria_now() + timedelta(days=reward['days'])
        
        await update_student(referrer_id, {
            'subscription_tier': reward['tier'],
            'subscription_expires_at': new_expires.isoformat(),
        })
        
        # Send notification
        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', referrer_id).eq('platform', 'whatsapp').execute()
        
        if phone_result.data:
            phone = phone_result.data[0]['platform_user_id']
            await send_whatsapp_message(phone, reward['message'])   
    # Create referral record
    supabase.table('referrals').insert({
        'referrer_student_id': referrer_id,
        'referred_student_id': referred_student_id,
        'referrer_wax_id': referrer_wax_id,
        'status': 'active'
    }).execute()
    
    # Increment referrer's count
    supabase.rpc('increment_referral_count', {'student_id': referrer_id}).execute()

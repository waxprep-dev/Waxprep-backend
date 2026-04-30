"""
Student Database Operations
Updated: unlimited free tier, cost-based limits, tier-aware model routing.
"""

import asyncio


async def get_student_by_platform_id(platform: str, platform_user_id: str) -> dict | None:
    """
    Lookup a student by platform (whatsapp, telegram) and its user ID.
    Used for Telegram and any future platform.
    """
    from database.client import supabase
    from database.cache import get_cached_student, cache_student

    try:
        result = supabase.table('platform_sessions')\
            .select('student_id')\
            .eq('platform', platform)\
            .eq('platform_user_id', platform_user_id)\
            .execute()

        if not result.data:
            return None

        student_id = result.data[0]['student_id']
        student_result = supabase.table('students').select('*').eq('id', student_id).execute()

        if not student_result.data:
            return None

        student = student_result.data[0]
        cache_student(student)
        return student

    except Exception as e:
        print(f"get_student_by_platform_id error: {e}")
        return None
async def get_student_by_phone(phone: str) -> dict | None:
    if phone.startswith('telegram:'):
    chat_id = phone.split(':', 1)[1]
    return await get_student_by_platform_id('telegram', chat_id)
    from database.client import supabase
    from database.cache import (
        get_student_id_by_phone, get_cached_student,
        cache_student, cache_student_by_phone
    )

    cached_id = get_student_id_by_phone(phone)
    if cached_id:
        cached = get_cached_student(cached_id)
        if cached:
            return cached

    try:
        result = supabase.table('platform_sessions')\
            .select('student_id')\
            .eq('platform', 'whatsapp')\
            .eq('platform_user_id', phone)\
            .execute()

        if not result.data:
            return None

        student_id = result.data[0]['student_id']
        student_result = supabase.table('students').select('*').eq('id', student_id).execute()

        if not student_result.data:
            return None

        student = student_result.data[0]
        cache_student(student)
        cache_student_by_phone(phone, student['id'])
        return student

    except Exception as e:
        print(f"get_student_by_phone error: {e}")
        return None


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
    referred_by_wax_id: str = None,
    language_preference: str = 'english',
) -> dict:
    from database.client import supabase
    from database.cache import cache_student, cache_student_by_phone
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
        'language_preference': language_preference,
        'referral_code': referral_code,
        'referred_by_wax_id': referred_by_wax_id,
        'trial_started_at': now.isoformat(),
        'trial_expires_at': trial_end.isoformat(),
        'is_trial_active': True,
        'subscription_tier': 'free',
        'onboarding_complete': True,
        'terms_accepted': True,
        'terms_accepted_at': now.isoformat(),
        'total_questions_answered': 0,
        'total_questions_correct': 0,
        'current_streak': 0,
        'longest_streak': 0,
        'total_points': 0,
        'current_level': 1,
        'level_name': 'Freshman',
        'questions_today': 0,
        'questions_today_reset_date': now.strftime('%Y-%m-%d'),
        'credits_balance': 0,
    }

    result = supabase.table('students').insert(student_data).execute()
    if not result.data:
        raise Exception("Failed to create student — Supabase returned no data")

    new_student = result.data[0]
    cache_student(new_student)
    cache_student_by_phone(phone, new_student['id'])

    if referred_by_wax_id:
        try:
            await record_referral(referred_by_wax_id, new_student['id'], wax_id)
        except Exception as e:
            print(f"Referral recording error: {e}")

    return new_student


async def update_student(student_id: str, updates: dict) -> dict | None:
    from database.client import supabase
    from database.cache import invalidate_student_cache
    from helpers import nigeria_now

    updates['updated_at'] = nigeria_now().isoformat()

    try:
        result = supabase.table('students').update(updates).eq('id', student_id).execute()
        if result.data:
            invalidate_student_cache(student_id)
            return result.data[0]
        return None
    except Exception as e:
        print(f"update_student error: {e}")
        return None


async def get_student_by_id(student_id: str) -> dict | None:
    from database.client import supabase
    from database.cache import get_cached_student, cache_student

    cached = get_cached_student(student_id)
    if cached:
        return cached

    try:
        result = supabase.table('students').select('*').eq('id', student_id).execute()
        if result.data:
            cache_student(result.data[0])
            return result.data[0]
        return None
    except Exception as e:
        print(f"get_student_by_id error: {e}")
        return None


async def get_student_subscription_status(student: dict) -> dict:
    from helpers import nigeria_now
    from config.settings import settings
    from datetime import timedelta, datetime

    now = nigeria_now()

    trial_active = student.get('is_trial_active', False)
    trial_expires_str = student.get('trial_expires_at')

    if trial_active and trial_expires_str:
        try:
            trial_exp = datetime.fromisoformat(str(trial_expires_str).replace('Z', '+00:00'))
            if trial_exp.tzinfo is None:
                trial_exp = trial_exp.replace(tzinfo=now.tzinfo)
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
                # Trial expired — update silently
                asyncio.ensure_future(
                    update_student(student['id'], {'is_trial_active': False})
                )
        except Exception as e:
            print(f"Trial check error: {e}")

    tier = student.get('subscription_tier', 'free')
    sub_expires_str = student.get('subscription_expires_at')

    if tier != 'free' and sub_expires_str:
        try:
            sub_exp = datetime.fromisoformat(str(sub_expires_str).replace('Z', '+00:00'))
            if sub_exp.tzinfo is None:
                sub_exp = sub_exp.replace(tzinfo=now.tzinfo)
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
    Returns (can_ask: bool, message: str).

    Free tier is now UNLIMITED in questions.
    The limit is on per-student daily AI COST to prevent abuse.
    Normal students will never hit this — it only catches bots or abusers.
    """
    from database.client import supabase, redis_client
    from config.settings import settings
    from helpers import nigeria_today, nigeria_now, format_naira
    from datetime import datetime
    from zoneinfo import ZoneInfo

    student_id = student.get('id')
    if not student_id:
        return False, "Account error. Please contact support."

    try:
        # Check per-student daily AI cost cap
        today = nigeria_today()
        cost_key = f"student_ai_cost:{student_id}:{today}"

        try:
            student_cost_raw = redis_client.get(cost_key)
            student_cost = float(student_cost_raw) if student_cost_raw else 0.0

            # Determine tier to know which cap applies
            fresh = supabase.table('students')\
                .select('is_trial_active, trial_expires_at, subscription_tier')\
                .eq('id', student_id)\
                .execute()

            if fresh.data:
                f = fresh.data[0]
                now_tz = datetime.now(ZoneInfo("Africa/Lagos"))
                is_trial = False
                if f.get('is_trial_active') and f.get('trial_expires_at'):
                    try:
                        trial_exp = datetime.fromisoformat(
                            str(f['trial_expires_at']).replace('Z', '+00:00')
                        )
                        if trial_exp > now_tz:
                            is_trial = True
                    except Exception:
                        pass

                tier = f.get('subscription_tier', 'free')
                effective = 'trial' if is_trial else tier

                if effective == 'free':
                    cap = settings.FREE_DAILY_AI_COST_CAP_USD
                else:
                    cap = settings.SCHOLAR_DAILY_AI_COST_CAP_USD

                if student_cost >= cap:
                    name = student.get('name', 'Student').split()[0]
                    if effective == 'free':
                        return False, (
                            f"You have been studying a lot today, {name}! "
                            "I need to pace things a little. Try again in a few minutes.\n\n"
                            f"Upgrade to Scholar for unlimited uninterrupted learning. "
                            f"Type *SUBSCRIBE* — it is only {format_naira(settings.SCHOLAR_MONTHLY)}/month."
                        )
                    else:
                        return False, (
                            f"Incredible session today, {name}! "
                            "I need a brief pause — try again in a few minutes."
                        )
        except Exception as cost_err:
            # If cost tracking fails, allow the request
            print(f"Cost cap check error (non-critical): {cost_err}")

        return True, ""

    except Exception as e:
        print(f"can_student_ask_question error: {e}")
        return True, ""  # Default to allowing on error


async def increment_questions_today(student_id: str):
    from database.client import supabase
    try:
        supabase.rpc('increment_questions_today', {'student_id': student_id}).execute()
    except Exception:
        try:
            from helpers import nigeria_today
            fresh = supabase.table('students').select('questions_today, questions_today_reset_date')\
                .eq('id', student_id).execute()
            if fresh.data:
                f = fresh.data[0]
                today = nigeria_today()
                if f.get('questions_today_reset_date') != today:
                    supabase.table('students').update({
                        'questions_today': 1,
                        'questions_today_reset_date': today
                    }).eq('id', student_id).execute()
                else:
                    current = f.get('questions_today', 0) or 0
                    supabase.table('students').update({
                        'questions_today': current + 1
                    }).eq('id', student_id).execute()
        except Exception as e2:
            print(f"increment_questions_today fallback error: {e2}")


async def get_student_profile_summary(student: dict) -> str:
    from helpers import format_naira
    from config.settings import settings
    from database.client import supabase
    from helpers import nigeria_today

    status = await get_student_subscription_status(student)
    name = student.get('name', 'Student')
    wax_id = student.get('wax_id', 'Unknown')
    tier = status['display_tier']
    streak = student.get('current_streak', 0)
    best_streak = student.get('longest_streak', 0)
    points = student.get('total_points', 0)
    level = student.get('current_level', 1)
    level_name = student.get('level_name', 'Freshman')
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0, 1)
    credits = student.get('credits_balance', 0) or 0

    today_interactions = 0
    try:
        fresh = supabase.table('students')\
            .select('questions_today, questions_today_reset_date')\
            .eq('id', student['id']).execute()
        if fresh.data:
            f = fresh.data[0]
            if f.get('questions_today_reset_date') == nigeria_today():
                today_interactions = f.get('questions_today', 0)
    except Exception:
        pass

    bar_filled = min(int(accuracy / 10), 10)
    bar = '█' * bar_filled + '░' * (10 - bar_filled)

    summary = (
        f"*{name.split()[0]}'s WaxPrep Profile*\n\n"
        f"WAX ID: {wax_id}\n"
        f"Plan: {tier}\n"
        f"Level {level} — {level_name}\n"
        f"Points: {points:,}\n\n"
        f"*Progress*\n"
        f"{bar} {accuracy}%\n"
        f"Total: {answered:,} interactions | {correct:,} correct\n"
        f"Today: {today_interactions}\n"
        f"Current Streak: {streak} day{'s' if streak != 1 else ''}\n"
        f"Best Streak: {best_streak} day{'s' if best_streak != 1 else ''}\n"
    )

    if credits > 0:
        summary += f"Credits Balance: {credits}\n"

    summary += "\n"

    if status['is_trial']:
        days_left = status.get('days_remaining', 0)
        summary += (
            f"Trial ends in: {days_left} day{'s' if days_left != 1 else ''}\n"
            f"Type *SUBSCRIBE* to keep full access.\n\n"
        )
    elif status.get('is_in_grace_period'):
        days_left = status.get('days_remaining', 0)
        summary += (
            f"Grace period: {days_left} day{'s' if days_left != 1 else ''} left\n"
            f"Type *SUBSCRIBE* to renew.\n\n"
        )

    summary += "_Your WAX ID is permanent. Never share your PIN._"
    return summary


async def record_referral(referrer_wax_id: str, referred_student_id: str, referred_wax_id: str):
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
            'status': 'pending'
        }).execute()
    except Exception:
        pass

    try:
        supabase.rpc('increment_referral_count', {'student_id': referrer_id}).execute()
    except Exception as e:
        print(f"Referral count error: {e}")


async def apply_referral_reward(referrer_wax_id: str):
    """
    Called when a referred student makes their first payment.
    Gives the referrer 1 free month of Scholar.
    """
    from database.client import supabase
    from helpers import nigeria_now
    from datetime import timedelta, datetime

    try:
        referrer = supabase.table('students').select('id, name, subscription_tier, subscription_expires_at')\
            .eq('wax_id', referrer_wax_id).execute()

        if not referrer.data:
            return

        r = referrer.data[0]
        now = nigeria_now()

        # Extend subscription by 30 days
        current_expires = r.get('subscription_expires_at')
        if current_expires:
            try:
                exp = datetime.fromisoformat(str(current_expires).replace('Z', '+00:00'))
                new_exp = max(exp, now) + timedelta(days=30)
            except Exception:
                new_exp = now + timedelta(days=30)
        else:
            new_exp = now + timedelta(days=30)

        supabase.table('students').update({
            'subscription_tier': 'scholar',
            'subscription_expires_at': new_exp.isoformat(),
            'is_trial_active': False,
        }).eq('id', r['id']).execute()

        # Notify the referrer
        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', r['id']).eq('platform', 'whatsapp').execute()

        if phone_result.data:
            from whatsapp.sender import send_whatsapp_message
            phone = phone_result.data[0]['platform_user_id']
            name = r['name'].split()[0]
            await send_whatsapp_message(
                phone,
                f"Your referral reward just landed, {name}!\n\n"
                f"Someone you referred just subscribed — so we have given you *1 free month of Scholar*.\n\n"
                f"Your plan is now active until {new_exp.strftime('%d %B %Y')}.\n\n"
                "Keep sharing WaxPrep with your classmates!"
            )

    except Exception as e:
        print(f"Referral reward error: {e}")

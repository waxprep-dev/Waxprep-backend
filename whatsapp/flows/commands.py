"""
Command Handler

Handles all direct commands: PROGRESS, HELP, SUBSCRIBE, STREAK, etc.
FIXED: Added PAYG to the handlers dict (it was defined but not routed).
ALL imports are lazy.
"""

HELP_MESSAGE = """*WaxPrep Commands*

*Study:*
LEARN [topic] — Explain a topic
QUIZ [subject] — Get quizzed
EXAM — Mock exam mode
REVISION — Review weak topics
CHALLENGE — Daily challenge
PAUSE / CONTINUE — Pause session
STOP — End session

*Account:*
PROGRESS — Your stats
MYID — Your WAX ID
STREAK — Study streak
PLAN — Study plan
BALANCE — Questions left today
BADGES — Your badges
REFERRAL — Referral code

*Payments:*
SUBSCRIBE — Upgrade plan
PAYG 100 — Buy 100 question credits (N500)
PAYG 250 — Buy 250 question credits (N1,000)
PAYG 500 — Buy 500 question credits (N1,800)
PROMO [code] — Apply promo code
HELP — This message"""


async def handle_command(phone: str, student: dict, conversation: dict, message: str, command: str):
    """Routes a command to the right handler."""
    handlers = {
        'PROGRESS': handle_progress,
        'HELP': handle_help,
        'SUBSCRIBE': handle_subscribe,
        'STREAK': handle_streak,
        'PLAN': handle_plan,
        'BALANCE': handle_balance,
        'MYID': handle_my_id,
        'PROMO': handle_promo_code,
        'CODE': handle_promo_code,
        'STOP': handle_stop,
        'MODES': handle_modes,
        'BADGES': handle_badges,
        'REFERRAL': handle_referral,
        'PAUSE': handle_pause,
        'CONTINUE': handle_continue,
        # FIXED: PAYG was defined as a function but never added to this routing dict
        'PAYG': handle_payg,
    }

    handler = handlers.get(command)
    if handler:
        await handler(phone, student, conversation, message)
    else:
        await handle_help(phone, student, conversation, message)


async def handle_payg(phone: str, student: dict, conversation: dict, message: str):
    """Handles Pay-As-You-Go question credit purchases."""
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings

    parts = message.strip().upper().split()
    package = parts[1] if len(parts) > 1 else None

    if not package or package not in ['100', '250', '500']:
        await send_whatsapp_message(
            phone,
            "Pay As You Go — Buy Question Credits\n\n"
            "No subscription needed. Buy exactly what you need.\n\n"
            f"PAYG 100 — N{settings.PAYG_100_QUESTIONS:,} for 100 questions\n"
            f"PAYG 250 — N{settings.PAYG_250_QUESTIONS:,} for 250 questions\n"
            f"PAYG 500 — N{settings.PAYG_500_QUESTIONS:,} for 500 questions\n\n"
            "Credits never expire.\n\n"
            "Example: Type PAYG 100 to buy 100 question credits"
        )
        return

    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(phone, f"Generating your payment link, {name}...")

    try:
        from database.subscriptions import generate_payg_payment_link
        link = await generate_payg_payment_link(student, package)

        package_prices = {
            '100': settings.PAYG_100_QUESTIONS,
            '250': settings.PAYG_250_QUESTIONS,
            '500': settings.PAYG_500_QUESTIONS,
        }
        amount = package_prices[package]

        await send_whatsapp_message(
            phone,
            f"Your Payment Link is Ready!\n\n"
            f"Package: {package} question credits\n"
            f"Amount: N{amount:,}\n\n"
            f"Tap to pay securely:\n{link}\n\n"
            f"Credits are added automatically after payment."
        )

    except Exception as e:
        print(f"PAYG link error: {e}")
        await send_whatsapp_message(
            phone,
            "I could not generate a payment link right now.\n\n"
            "Please try again in a few minutes, or type SUBSCRIBE for a monthly plan."
        )


async def handle_progress(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_profile_summary

    summary = await get_student_profile_summary(student)
    await send_whatsapp_message(phone, summary)


async def handle_help(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    await send_whatsapp_message(phone, HELP_MESSAGE)


async def handle_my_id(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message

    wax_id = student.get('wax_id', 'Unknown')
    name = student.get('name', 'Student').split()[0]

    await send_whatsapp_message(
        phone,
        f"Your WAX ID, {name}\n\n"
        f"*{wax_id}*\n\n"
        "Use this to:\n"
        "Log in on any device\n"
        "Recover your account\n"
        "Share with friends for referral rewards\n\n"
        "Keep it safe!"
    )


async def handle_streak(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from helpers import nigeria_today

    streak = student.get('current_streak', 0)
    longest = student.get('longest_streak', 0)
    last_study = student.get('last_study_date')
    today = nigeria_today()
    name = student.get('name', 'Student').split()[0]
    studied_today = last_study == today

    emoji = 'ON FIRE' if streak > 0 else 'START TODAY'

    msg = (
        f"*{name}'s Streak*\n\n"
        f"Current: *{streak} day{'s' if streak != 1 else ''}*\n"
        f"Best Ever: *{longest} day{'s' if longest != 1 else ''}*\n\n"
    )

    if studied_today:
        msg += "Studied today — streak safe!"
    elif streak > 0:
        msg += f"Haven't studied today yet!\nStudy at least 1 question to keep your {streak}-day streak!"
    else:
        msg += "Start studying today to build a streak!"

    await send_whatsapp_message(phone, msg)


async def handle_balance(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status
    from helpers import format_naira
    from config.settings import settings

    status = await get_student_subscription_status(student)
    effective_tier = status['effective_tier']
    limit = settings.get_daily_question_limit(effective_tier, status['is_trial'])

    from database.client import supabase
    from helpers import nigeria_today

    fresh = supabase.table('students').select('questions_today, questions_today_reset_date')\
        .eq('id', student['id']).execute()

    questions_today = 0
    if fresh.data:
        f = fresh.data[0]
        if f.get('questions_today_reset_date') == nigeria_today():
            questions_today = f.get('questions_today', 0)

    remaining = max(0, limit - questions_today)

    if limit >= 9999:
        limit_display = "Unlimited"
        remaining_display = "Unlimited"
    else:
        limit_display = str(limit)
        remaining_display = str(remaining)

    msg = (
        f"*Question Balance*\n\n"
        f"Plan: {status['display_tier']}\n"
        f"Daily Limit: {limit_display}\n"
        f"Used Today: {questions_today}\n"
        f"Remaining: *{remaining_display}*\n\n"
    )

    if remaining == 0 and effective_tier == 'free':
        msg += (
            f"You've used all your free questions today.\n\n"
            f"Upgrade to Scholar for {format_naira(settings.SCHOLAR_MONTHLY)}/month "
            f"— 100 questions daily!\n\n"
            "Type SUBSCRIBE to upgrade, or PAYG 100 to buy 100 credits now."
        )

    await send_whatsapp_message(phone, msg)


async def handle_subscribe(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.flows.subscription import handle_subscription_flow
    await handle_subscription_flow(phone, student, conversation, message)


async def handle_plan(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.client import supabase

    result = supabase.table('study_plans').select('*')\
        .eq('student_id', student['id'])\
        .eq('is_active', True)\
        .order('created_at', desc=True)\
        .limit(1).execute()

    if not result.data:
        await send_whatsapp_message(
            phone,
            "No study plan yet!\n\n"
            "Type *PLAN CREATE* to generate your personalized plan,\n"
            "or just start studying and I'll build one based on how you learn."
        )
    else:
        plan = result.data[0]
        daily_target = plan.get('daily_question_target', 20)
        subjects = plan.get('focus_subjects', student.get('subjects', []))
        subjects_str = ', '.join(subjects[:3]) if subjects else 'all your subjects'

        await send_whatsapp_message(
            phone,
            f"*Your Study Plan*\n\n"
            f"Daily Target: {daily_target} questions\n"
            f"Focus: {subjects_str}\n\n"
            f"Your plan updates weekly based on your progress.\n\n"
            f"Ready? Ask me any question or type *QUIZ [subject]* to start!"
        )


async def handle_promo_code(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.client import supabase
    from helpers import nigeria_now

    parts = message.strip().upper().split()
    code = parts[1] if len(parts) >= 2 else None

    if not code:
        await send_whatsapp_message(
            phone,
            "To apply a promo code, type:\n*PROMO [YOUR CODE]*\n\nExample: *PROMO DAYXK2P*"
        )
        return

    result = supabase.table('promo_codes').select('*')\
        .eq('code', code).eq('is_active', True).execute()

    if not result.data:
        await send_whatsapp_message(phone, f"Code *{code}* is not valid or has expired.")
        return

    promo = result.data[0]

    from datetime import datetime
    if promo.get('expires_at'):
        try:
            exp = datetime.fromisoformat(promo['expires_at'].replace('Z', '+00:00'))
            if exp < nigeria_now():
                await send_whatsapp_message(phone, f"Code *{code}* has expired.")
                return
        except Exception:
            pass

    if promo.get('max_uses') and promo.get('current_uses', 0) >= promo['max_uses']:
        await send_whatsapp_message(phone, f"Code *{code}* has reached its usage limit.")
        return

    existing = supabase.table('promo_code_uses').select('id')\
        .eq('promo_code_id', promo['id']).eq('student_id', student['id']).execute()

    if existing.data:
        await send_whatsapp_message(phone, f"You've already used code *{code}*.")
        return

    benefit_msg = await _apply_promo_benefit(student, promo)

    supabase.table('promo_code_uses').insert({
        'promo_code_id': promo['id'],
        'student_id': student['id'],
        'benefit_applied': {'code': code, 'type': promo['code_type']}
    }).execute()

    supabase.table('promo_codes').update({
        'current_uses': promo.get('current_uses', 0) + 1
    }).eq('id', promo['id']).execute()

    await send_whatsapp_message(phone, f"*Code Applied: {code}*\n\n{benefit_msg}")


async def _apply_promo_benefit(student: dict, promo: dict) -> str:
    from database.client import supabase
    from database.students import update_student
    from helpers import nigeria_now
    from datetime import timedelta, datetime

    code_type = promo['code_type']
    student_id = student['id']

    if code_type == 'full_trial':
        bonus_days = promo.get('bonus_days', 3)
        trial_exp_str = student.get('trial_expires_at')
        if trial_exp_str:
            try:
                current_end = datetime.fromisoformat(trial_exp_str.replace('Z', '+00:00'))
                new_end = max(current_end, nigeria_now()) + timedelta(days=bonus_days)
            except Exception:
                new_end = nigeria_now() + timedelta(days=bonus_days)
        else:
            new_end = nigeria_now() + timedelta(days=bonus_days)

        await update_student(student_id, {
            'trial_expires_at': new_end.isoformat(),
            'is_trial_active': True
        })
        return (
            f"+{bonus_days} extra trial days!\n\n"
            f"Trial now expires: {new_end.strftime('%d %B %Y')}\n\n"
            "Enjoy full access to all WaxPrep features!"
        )

    elif code_type == 'discount_percent':
        discount = promo.get('discount_percent', 10)
        return (
            f"{discount}% discount on your next subscription!\n\n"
            "Type *SUBSCRIBE* to use your discount."
        )

    elif code_type == 'tier_upgrade':
        tier = promo.get('tier_to_unlock', 'scholar')
        days = promo.get('bonus_days', 30)
        new_expires = nigeria_now() + timedelta(days=days)
        await update_student(student_id, {
            'subscription_tier': tier,
            'subscription_expires_at': new_expires.isoformat()
        })
        return (
            f"Upgraded to {tier.capitalize()} Plan for {days} days!\n\n"
            f"Expires: {new_expires.strftime('%d %B %Y')}"
        )

    elif code_type == 'bonus_questions':
        bonus = promo.get('bonus_questions_per_day', 20)
        days = promo.get('bonus_days', 7)
        from database.client import redis_client
        redis_client.setex(f"bonus_questions:{student_id}", days * 86400, str(bonus))
        return f"+{bonus} extra questions per day for {days} days!"

    return "Promo code applied successfully!"


async def handle_stop(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import clear_conversation_state

    await clear_conversation_state(conversation['id'], 'whatsapp', phone)

    name = student.get('name', 'Student').split()[0]
    streak = student.get('current_streak', 0)

    await send_whatsapp_message(
        phone,
        f"Session ended, {name}!\n\n"
        f"Streak: {streak} day{'s' if streak != 1 else ''}\n\n"
        "Great work. Come back and study more later!\n\n"
        "Type anything to start a new session."
    )


async def handle_modes(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message

    await send_whatsapp_message(
        phone,
        "*Study Modes*\n\n"
        "LEARN [topic] — Deep explanation\n"
        "   e.g. Learn Newton's Laws\n\n"
        "QUIZ [subject] — Test yourself\n"
        "   e.g. Quiz me on Chemistry\n\n"
        "EXAM — Timed mock exam\n"
        "   Full exam simulation\n\n"
        "REVISION — Review weak areas\n"
        "   Spaced repetition mode\n\n"
        "CHALLENGE — Today's hard question\n\n"
        "Or just ask me any question directly!"
    )


async def handle_badges(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.client import supabase

    result = supabase.table('student_badges').select('*, badges(*)')\
        .eq('student_id', student['id'])\
        .order('earned_at', desc=True)\
        .execute()

    if not result.data:
        await send_whatsapp_message(
            phone,
            "*Your Badges*\n\n"
            "No badges yet!\n\n"
            "Your first badge comes after your very first question. Ask me anything to earn it!"
        )
        return

    badges_text = ""
    for entry in result.data[:8]:
        badge = entry.get('badges', {})
        if not badge:
            continue
        emoji = badge.get('icon_emoji', '')
        rarity = badge.get('rarity', 'common').upper()
        badges_text += f"{emoji} *{badge['name']}* _({rarity})_\n   {badge['description']}\n\n"

    await send_whatsapp_message(
        phone,
        f"*Your Badges ({len(result.data)} earned)*\n\n"
        f"{badges_text}"
        "Keep studying to unlock more!"
    )


async def handle_referral(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message

    code = student.get('referral_code', student.get('wax_id', '').replace('-', '')[:6])
    count = student.get('referral_count', 0)

    await send_whatsapp_message(
        phone,
        f"*Your Referral Code*\n\n"
        f"*{code}*\n\n"
        f"You've referred *{count}* student{'s' if count != 1 else ''}!\n\n"
        f"*Rewards:*\n"
        f"3 referrals = 7 days Pro FREE\n"
        f"10 referrals = 1 month Pro FREE\n"
        f"25 referrals = 1 year Scholar FREE\n\n"
        f"Share your code! Friends type *PROMO {code}* when signing up."
    )


async def handle_pause(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'is_paused': True})
    name = student.get('name', 'Student').split()[0]

    await send_whatsapp_message(
        phone,
        f"Session paused, {name}.\n\n"
        "Type *CONTINUE* to pick up right where you left off."
    )


async def handle_continue(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {'is_paused': False})

    topic = conversation.get('current_topic', '')
    subject = conversation.get('current_subject', '')

    if topic:
        await send_whatsapp_message(
            phone,
            f"Session resumed!\n\n"
            f"We were studying *{topic}* in {subject}.\n\n"
            "Ask me anything to continue."
        )
    else:
        await send_whatsapp_message(
            phone,
            "Session resumed! What would you like to study?"
        )

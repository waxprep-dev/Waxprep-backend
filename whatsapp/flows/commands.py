"""
Command Handler

This handles all direct commands that students can send:
PROGRESS — see their stats
HELP — list all commands
SUBSCRIBE — start subscription process
STREAK — check their streak
PLAN — view their study plan
BALANCE — check questions remaining today
MYID — get their WAX ID
PROMO [code] — apply a promo code
PAUSE / CONTINUE — pause and resume sessions
STOP — stop current activity
MODES — see available study modes

Commands are the fastest responses because they don't need AI.
"""

from whatsapp.sender import send_whatsapp_message
from database.students import get_student_subscription_status, get_student_profile_summary
from config.settings import settings
from utils.helpers import format_naira, nigeria_now

HELP_MESSAGE = """📚 *WaxPrep Commands*

*Study Commands:*
📖 *LEARN* [topic] — Start learning a topic
❓ *QUIZ* [subject] — Get quizzed on a subject
📝 *EXAM* — Start mock exam mode
🔄 *REVISION* — Review weak topics
⏸️ *PAUSE* — Pause current session
▶️ *CONTINUE* — Resume paused session
⏹️ *STOP* — End current session

*Account Commands:*
📊 *PROGRESS* — Your stats and progress
🆔 *MYID* — Your WAX ID
🔥 *STREAK* — Your study streak
📋 *PLAN* — Your study plan
💰 *BALANCE* — Questions remaining today
🏅 *BADGES* — Your earned badges

*Other Commands:*
💳 *SUBSCRIBE* — Upgrade your plan
🎁 *PROMO [code]* — Apply promo code
👥 *REFERRAL* — Your referral code
👨‍👩‍👧 *PARENT* — Link parent account
❓ *HELP* — This message

_Just ask any question to start studying!_ 🚀"""

async def handle_command(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    command: str
):
    """
    Routes a command to the right handler.
    'command' is the first word of the message, uppercased.
    """
    
    command_handlers = {
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
    }
    
    handler = command_handlers.get(command)
    if handler:
        await handler(phone, student, conversation, message)
    else:
        await handle_help(phone, student, conversation, message)

async def handle_progress(phone: str, student: dict, conversation: dict, message: str):
    """Shows the student their complete profile and progress."""
    summary = await get_student_profile_summary(student)
    await send_whatsapp_message(phone, summary)

async def handle_help(phone: str, student: dict, conversation: dict, message: str):
    """Shows the complete list of commands."""
    await send_whatsapp_message(phone, HELP_MESSAGE)

async def handle_my_id(phone: str, student: dict, conversation: dict, message: str):
    """Shows the student their WAX ID prominently."""
    wax_id = student.get('wax_id', 'Unknown')
    name = student.get('name', 'Student').split()[0]
    
    message_text = (
        f"🆔 *Your WAX ID*\n\n"
        f"*{wax_id}*\n\n"
        f"This is your permanent WaxPrep identity, {name}.\n\n"
        f"Use it to:\n"
        f"• Log in on any device (WhatsApp, Telegram, website)\n"
        f"• Recover your account if you lose your phone\n"
        f"• Share with friends (they'll know who referred them)\n\n"
        f"_Keep this WAX ID safe!_"
    )
    await send_whatsapp_message(phone, message_text)

async def handle_streak(phone: str, student: dict, conversation: dict, message: str):
    """Shows the student their streak information."""
    streak = student.get('current_streak', 0)
    longest = student.get('longest_streak', 0)
    last_study = student.get('last_study_date')
    name = student.get('name', 'Student').split()[0]
    
    from utils.helpers import nigeria_today
    today = nigeria_today()
    studied_today = last_study == today
    
    streak_emoji = '🔥' if streak > 0 else '❄️'
    
    msg = (
        f"{streak_emoji} *{name}'s Study Streak*\n\n"
        f"Current Streak: *{streak} day{'s' if streak != 1 else ''}*\n"
        f"Longest Ever: *{longest} day{'s' if longest != 1 else ''}*\n\n"
    )
    
    if studied_today:
        msg += "✅ You've already studied today! Streak is safe. 💪"
    elif streak > 0:
        msg += f"⚠️ You haven't studied today yet!\nStudy at least 1 question to keep your {streak}-day streak alive!"
    else:
        msg += "Start studying today to begin a new streak! 🚀"
    
    await send_whatsapp_message(phone, msg)

async def handle_balance(phone: str, student: dict, conversation: dict, message: str):
    """Shows questions remaining for today."""
    from database.students import check_and_reset_daily_questions, get_student_subscription_status
    
    student = await check_and_reset_daily_questions(student)
    status = await get_student_subscription_status(student)
    effective_tier = status['effective_tier']
    
    limit = settings.get_daily_question_limit(effective_tier, status['is_trial'])
    used = student.get('questions_today', 0)
    remaining = max(0, limit - used)
    
    if limit >= 9999:
        limit_display = "Unlimited ♾️"
        remaining_display = "Unlimited ♾️"
    else:
        limit_display = str(limit)
        remaining_display = str(remaining)
    
    msg = (
        f"💰 *Your Question Balance*\n\n"
        f"Plan: {status['display_tier']}\n"
        f"Daily Limit: {limit_display}\n"
        f"Used Today: {used}\n"
        f"Remaining: *{remaining_display}*\n\n"
    )
    
    if remaining == 0 and effective_tier == 'free':
        msg += (
            "You've used all your free questions for today.\n\n"
            f"Upgrade to Scholar for just {format_naira(settings.SCHOLAR_MONTHLY)}/month "
            f"and get 100 questions daily!\n\n"
            "Type *SUBSCRIBE* to upgrade."
        )
    
    await send_whatsapp_message(phone, msg)

async def handle_subscribe(phone: str, student: dict, conversation: dict, message: str):
    """Starts the subscription process."""
    from database.students import get_student_subscription_status
    
    status = await get_student_subscription_status(student)
    current_tier = status['effective_tier']
    name = student.get('name', 'Student').split()[0]
    
    msg = (
        f"💳 *WaxPrep Plans*\n\n"
        f"Your current plan: *{status['display_tier']}*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📗 *Scholar Plan — {format_naira(settings.SCHOLAR_MONTHLY)}/month*\n"
        f"• 100 questions per day\n"
        f"• Image and photo analysis\n"
        f"• Voice note input\n"
        f"• Full mock exams (2x weekly)\n"
        f"• Personalized study plan\n"
        f"• Spaced repetition\n"
        f"• Weak area focus mode\n"
        f"_(Yearly: {format_naira(settings.SCHOLAR_YEARLY)} — 17% off)_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💛 *Pro Plan — {format_naira(settings.PRO_MONTHLY)}/month* _(V2 — Coming Soon)_\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"To subscribe to Scholar:\n"
        f"Reply with *SCHOLAR MONTHLY* or *SCHOLAR YEARLY*\n\n"
        f"_Payments are secure via Paystack. All Nigerian payment methods accepted._"
    )
    
    await send_whatsapp_message(phone, msg)

async def handle_plan(phone: str, student: dict, conversation: dict, message: str):
    """Shows the student's current study plan."""
    
    from database.client import supabase
    
    result = supabase.table('study_plans')\
        .select('*')\
        .eq('student_id', student['id'])\
        .eq('is_active', True)\
        .order('created_at', desc=True)\
        .limit(1)\
        .execute()
    
    if not result.data:
        # No study plan yet — generate one
        msg = (
            "You don't have a study plan yet! 📋\n\n"
            "Let me create one for you based on your subjects and exam date.\n\n"
            "Type *PLAN CREATE* to generate your personalized study plan."
        )
    else:
        plan = result.data[0]
        plan_data = plan.get('plan_data', {})
        daily_target = plan.get('daily_question_target', 20)
        focus_subjects = plan.get('focus_subjects', [])
        
        subjects_str = ", ".join(focus_subjects[:3]) if focus_subjects else "all your subjects"
        
        msg = (
            f"📋 *Your Study Plan*\n\n"
            f"Daily Target: {daily_target} questions\n"
            f"Focus Areas: {subjects_str}\n\n"
            f"_Your plan updates weekly based on your progress._\n\n"
            f"Want to start studying now?\n"
            f"Just ask me a question or type *QUIZ [subject]* to get started!"
        )
    
    await send_whatsapp_message(phone, msg)

async def handle_promo_code(phone: str, student: dict, conversation: dict, message: str):
    """Applies a promo code for the student."""
    
    # Extract the code from the message
    parts = message.strip().upper().split()
    code = None
    
    if len(parts) >= 2:
        code = parts[1]
    
    if not code:
        await send_whatsapp_message(
            phone,
            "To apply a promo code, type:\n"
            "*PROMO [YOUR CODE]*\n\n"
            "Example: *PROMO WAXDAY4B2P*"
        )
        return
    
    from database.client import supabase
    
    # Look up the promo code
    result = supabase.table('promo_codes')\
        .select('*')\
        .eq('code', code)\
        .eq('is_active', True)\
        .execute()
    
    if not result.data:
        await send_whatsapp_message(
            phone,
            f"❌ The code *{code}* is not valid or has expired.\n\n"
            "Please check the code and try again."
        )
        return
    
    promo = result.data[0]
    
    # Check expiry
    from datetime import datetime
    if promo.get('expires_at'):
        expires = datetime.fromisoformat(promo['expires_at'].replace('Z', '+00:00'))
        if expires < nigeria_now():
            await send_whatsapp_message(
                phone,
                f"❌ The code *{code}* has expired.\n\n"
                "Check if there's a newer code available."
            )
            return
    
    # Check max uses
    if promo.get('max_uses') and promo['current_uses'] >= promo['max_uses']:
        await send_whatsapp_message(
            phone,
            f"❌ The code *{code}* has been fully used and is no longer available."
        )
        return
    
    # Check if student already used this code
    existing_use = supabase.table('promo_code_uses')\
        .select('id')\
        .eq('promo_code_id', promo['id'])\
        .eq('student_id', student['id'])\
        .execute()
    
    if existing_use.data:
        await send_whatsapp_message(
            phone,
            f"You've already used the code *{code}* before.\n\n"
            "Each code can only be used once per account."
        )
        return
    
    # Apply the promo code benefit
    benefit_message = await apply_promo_benefit(student, promo)
    
    # Record the use
    supabase.table('promo_code_uses').insert({
        'promo_code_id': promo['id'],
        'student_id': student['id'],
        'benefit_applied': {'code': code, 'type': promo['code_type']}
    }).execute()
    
    # Increment use count
    supabase.table('promo_codes')\
        .update({'current_uses': promo['current_uses'] + 1})\
        .eq('id', promo['id'])\
        .execute()
    
    await send_whatsapp_message(
        phone,
        f"✅ *Promo Code Applied: {code}*\n\n{benefit_message}"
    )

async def apply_promo_benefit(student: dict, promo: dict) -> str:
    """
    Applies the benefit from a promo code to a student's account.
    Returns a message describing what was applied.
    """
    from database.client import supabase
    from database.students import update_student
    from datetime import datetime, timedelta
    
    code_type = promo['code_type']
    student_id = student['id']
    
    if code_type == 'full_trial':
        bonus_days = promo.get('bonus_days', 3)
        
        current_trial_end = student.get('trial_expires_at')
        if current_trial_end:
            if isinstance(current_trial_end, str):
                current_trial_end = datetime.fromisoformat(current_trial_end.replace('Z', '+00:00'))
            new_end = max(current_trial_end, nigeria_now()) + timedelta(days=bonus_days)
        else:
            new_end = nigeria_now() + timedelta(days=bonus_days)
        
        await update_student(student_id, {
            'trial_expires_at': new_end.isoformat(),
            'is_trial_active': True
        })
        
        return (
            f"🎁 You got *{bonus_days} extra days* of full trial access!\n\n"
            f"Your trial now expires: {new_end.strftime('%B %d, %Y')}\n\n"
            f"Enjoy full access to all WaxPrep features!"
        )
    
    elif code_type == 'discount_percent':
        discount = promo.get('discount_percent', 10)
        return (
            f"💰 You have a *{discount}% discount* on your next subscription!\n\n"
            f"Type *SUBSCRIBE* and use code *{promo['code']}* at checkout.\n\n"
            f"_(Discount is automatically applied when you subscribe)_"
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
            f"⭐ You've been upgraded to *{tier.capitalize()} Plan* for {days} days!\n\n"
            f"Enjoy all {tier.capitalize()} features until {new_expires.strftime('%B %d, %Y')}!"
        )
    
    elif code_type == 'bonus_questions':
        bonus = promo.get('bonus_questions_per_day', 20)
        days = promo.get('bonus_days', 7)
        
        # Store bonus in Redis for the specified days
        from database.client import redis_client
        redis_client.setex(
            f"bonus_questions:{student_id}",
            days * 86400,
            str(bonus)
        )
        
        return (
            f"❓ You got *{bonus} extra questions per day* for {days} days!\n\n"
            f"Your question limit is now higher until the bonus expires."
        )
    
    else:
        return "Your promo code has been applied successfully! ✅"

async def handle_stop(phone: str, student: dict, conversation: dict, message: str):
    """Stops the current session."""
    from database.conversations import clear_conversation_state
    
    await clear_conversation_state(conversation['id'], 'whatsapp', phone)
    
    name = student.get('name', 'Student').split()[0]
    streak = student.get('current_streak', 0)
    
    msg = (
        f"Session ended, {name}! 👋\n\n"
        f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}\n\n"
        f"Great work today. Come back soon!\n\n"
        f"Type anything to start a new session."
    )
    await send_whatsapp_message(phone, msg)

async def handle_modes(phone: str, student: dict, conversation: dict, message: str):
    """Shows available study modes."""
    msg = (
        f"📚 *Study Modes*\n\n"
        f"📖 *LEARN* — Deep explanations for new topics\n"
        f"Example: _Learn Newton's Laws_\n\n"
        f"❓ *QUIZ* — Get tested on a topic\n"
        f"Example: _Quiz me on Photosynthesis_\n\n"
        f"📝 *EXAM* — Mock exam simulation (timed)\n"
        f"Example: _Start a JAMB mock exam_\n\n"
        f"🔄 *REVISION* — Review your weak areas\n"
        f"Example: _Revision mode_\n\n"
        f"Type any of these to switch modes!\n\n"
        f"Or just ask a question normally and I'll figure out the best mode. 😊"
    )
    await send_whatsapp_message(phone, msg)

async def handle_badges(phone: str, student: dict, conversation: dict, message: str):
    """Shows the student's earned badges."""
    from database.client import supabase
    
    result = supabase.table('student_badges')\
        .select('*, badges(*)')\
        .eq('student_id', student['id'])\
        .order('earned_at', desc=True)\
        .execute()
    
    if not result.data:
        msg = (
            "🏅 *Your Badges*\n\n"
            "You haven't earned any badges yet!\n\n"
            "Start studying to earn your first badge. "
            "Your first badge comes after your very first question! 🌟"
        )
    else:
        badges_text = ""
        rarity_order = ['legendary', 'rare', 'uncommon', 'common']
        
        for entry in result.data[:10]:  # Show last 10 badges
            badge = entry['badges']
            emoji = badge.get('icon_emoji', '🏅')
            rarity = badge.get('rarity', 'common').upper()
            badges_text += f"{emoji} *{badge['name']}* _({rarity})_\n"
            badges_text += f"   {badge['description']}\n\n"
        
        total = len(result.data)
        
        msg = (
            f"🏅 *Your Badges ({total} earned)*\n\n"
            f"{badges_text}"
            f"_Keep studying to unlock more!_ 💪"
        )
    
    await send_whatsapp_message(phone, msg)

async def handle_referral(phone: str, student: dict, conversation: dict, message: str):
    """Shows the student's referral information."""
    referral_code = student.get('referral_code', student.get('wax_id', '').replace('-', '')[:6])
    referral_count = student.get('referral_count', 0)
    
    msg = (
        f"👥 *Your Referral Code*\n\n"
        f"*{referral_code}*\n\n"
        f"Share this code with friends! When they sign up and start studying, you both get rewards.\n\n"
        f"📊 You've referred *{referral_count}* student{'s' if referral_count != 1 else ''}!\n\n"
        f"*Referral Rewards:*\n"
        f"3 referrals = 7 days Pro access FREE\n"
        f"10 referrals = 1 month Pro access FREE\n"
        f"25 referrals = 1 year Scholar access FREE\n\n"
        f"_Your friend can enter your code when signing up or type_ *PROMO {referral_code}*"
    )
    await send_whatsapp_message(phone, msg)

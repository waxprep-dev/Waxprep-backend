"""
Admin Dashboard — WhatsApp Command Interface

You control WaxPrep entirely from your personal WhatsApp.
Every command starting with ADMIN (when sent from ADMIN_WHATSAPP number) works.

SECURITY: Commands only work when sent from the ADMIN_WHATSAPP number.
Any other number sending ADMIN commands is completely ignored.

AVAILABLE COMMANDS:
ADMIN HELP                          - List all commands
ADMIN STATS                         - Current platform stats
ADMIN REVENUE [today/week/month]    - Revenue breakdown
ADMIN STUDENT [WAX_ID]              - Full student profile
ADMIN SEARCH [name]                 - Search students by name
ADMIN UPGRADE [WAX_ID] [tier] [days] - Give free upgrade
ADMIN BAN [WAX_ID] [reason]         - Ban a student
ADMIN UNBAN [WAX_ID]                - Unban a student
ADMIN MSG [WAX_ID] [message]        - Send message to one student
ADMIN BROADCAST ALL [message]       - Send to all active students
ADMIN BROADCAST FREE [message]      - Send to free tier only
ADMIN BROADCAST SCHOLAR [message]   - Send to Scholar subscribers
ADMIN BROADCAST TRIAL [message]     - Send to students on trial
ADMIN BROADCAST EXAM [type] [msg]   - Send to students of specific exam (JAMB/WAEC/NECO)
ADMIN BROADCAST STATE [state] [msg] - Send to students in a state
ADMIN BROADCAST STREAK [n+] [msg]   - Send to students with streak >= n
ADMIN CODE CREATE [code] [type] [days/percent] [maxuses] - Create promo code
ADMIN CODE LIST                     - List active promo codes
ADMIN CODE DISABLE [code]           - Disable a promo code
ADMIN QUESTIONS PENDING             - List flagged questions needing review
ADMIN QUESTIONS APPROVE [id]        - Mark question as reviewed/good
ADMIN REPORT                        - Trigger daily report right now
ADMIN CHALLENGE                     - Generate today's challenge now
ADMIN ONLINE                        - See how many students are active
ADMIN TOP [n]                       - Top n students by points
"""

from config.settings import settings


def is_admin(phone: str) -> bool:
    """
    Checks if a phone number is the admin number.
    Only the admin can run these commands.
    """
    if not settings.ADMIN_WHATSAPP:
        return False

    # Normalize both numbers for comparison
    def normalize(p: str) -> str:
        return p.replace('+', '').replace(' ', '').replace('-', '')

    return normalize(phone) == normalize(settings.ADMIN_WHATSAPP)


async def handle_admin_command(phone: str, message: str):
    """
    Main entry point for admin commands.
    Parses the command and routes to the right handler.
    """
    from whatsapp.sender import send_whatsapp_message

    # Safety check
    if not is_admin(phone):
        return

    parts = message.strip().split(None, 2)  # Split into max 3 parts

    if len(parts) < 2:
        await send_admin_help(phone)
        return

    command = parts[1].upper() if len(parts) > 1 else ''
    sub_command = parts[2].upper().split()[0] if len(parts) > 2 else ''
    rest = parts[2] if len(parts) > 2 else ''

    # Route to handler
    if command == 'HELP':
        await send_admin_help(phone)

    elif command == 'STATS':
        await admin_stats(phone)

    elif command == 'REVENUE':
        period = rest.lower() if rest else 'today'
        await admin_revenue(phone, period)

    elif command == 'STUDENT':
        wax_id = rest.strip().upper() if rest else ''
        await admin_student_profile(phone, wax_id)

    elif command == 'SEARCH':
        await admin_search_student(phone, rest.strip())

    elif command == 'UPGRADE':
        await admin_upgrade_student(phone, rest.strip())

    elif command == 'BAN':
        await admin_ban_student(phone, rest.strip())

    elif command == 'UNBAN':
        wax_id = rest.strip().upper() if rest else ''
        await admin_unban_student(phone, wax_id)

    elif command == 'MSG':
        await admin_message_student(phone, rest.strip())

    elif command == 'BROADCAST':
        await admin_broadcast(phone, rest.strip())

    elif command == 'CODE':
        await admin_manage_codes(phone, rest.strip())

    elif command == 'QUESTIONS':
        await admin_questions(phone, sub_command, rest)

    elif command == 'REPORT':
        from utils.scheduler import send_daily_admin_report
        await send_whatsapp_message(phone, "⚙️ Generating report now...")
        await send_daily_admin_report()

    elif command == 'CHALLENGE':
        from utils.scheduler import generate_daily_challenge
        await send_whatsapp_message(phone, "⚙️ Generating daily challenge...")
        await generate_daily_challenge()
        await send_whatsapp_message(phone, "✅ Daily challenge generated!")

    elif command == 'ONLINE':
        await admin_online_count(phone)

    elif command == 'TOP':
        try:
            n = int(rest.strip()) if rest.strip().isdigit() else 10
        except Exception:
            n = 10
        await admin_top_students(phone, n)

    else:
        await send_whatsapp_message(
            phone,
            f"❓ Unknown admin command: *ADMIN {command}*\n\nType *ADMIN HELP* for all commands."
        )


async def send_admin_help(phone: str):
    """Sends the complete admin command reference."""
    from whatsapp.sender import send_whatsapp_message

    help_text = (
        "🛠️ *WaxPrep Admin Commands*\n\n"

        "*Platform Info:*\n"
        "ADMIN STATS — Current stats\n"
        "ADMIN REVENUE today/week/month\n"
        "ADMIN ONLINE — Active students now\n"
        "ADMIN TOP 10 — Top students by points\n"
        "ADMIN REPORT — Trigger daily report\n"
        "ADMIN CHALLENGE — Generate challenge now\n\n"

        "*Students:*\n"
        "ADMIN STUDENT [WAX-ID] — Full profile\n"
        "ADMIN SEARCH [name] — Search by name\n"
        "ADMIN UPGRADE [WAX-ID] scholar 30 — Give 30 days Scholar\n"
        "ADMIN BAN [WAX-ID] [reason] — Ban student\n"
        "ADMIN UNBAN [WAX-ID] — Unban student\n"
        "ADMIN MSG [WAX-ID] [message] — DM a student\n\n"

        "*Broadcasts:*\n"
        "ADMIN BROADCAST ALL [message]\n"
        "ADMIN BROADCAST FREE [message]\n"
        "ADMIN BROADCAST SCHOLAR [message]\n"
        "ADMIN BROADCAST TRIAL [message]\n"
        "ADMIN BROADCAST EXAM JAMB [message]\n"
        "ADMIN BROADCAST STATE Lagos [message]\n"
        "ADMIN BROADCAST STREAK 7 [message]\n\n"

        "*Promo Codes:*\n"
        "ADMIN CODE LIST — Active codes\n"
        "ADMIN CODE CREATE WAX2024 trial 7 100\n"
        "  (code, type, days/percent, maxuses)\n"
        "ADMIN CODE DISABLE [code] — Turn off code\n\n"

        "*Content:*\n"
        "ADMIN QUESTIONS PENDING — Flagged questions\n"
        "ADMIN QUESTIONS APPROVE [ID] — Mark reviewed"
    )

    await send_whatsapp_message(phone, help_text)


async def admin_stats(phone: str):
    """Returns comprehensive platform stats."""
    from database.client import supabase, redis_client
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')

    try:
        total = supabase.table('students').select('id', count='exact').execute()
        new_today = supabase.table('students').select('id', count='exact')\
            .gte('created_at', today).execute()
        active_today = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', today).execute()
        active_week = supabase.table('students').select('id', count='exact')\
            .gte('last_study_date', week_ago).execute()

        free_count = supabase.table('students').select('id', count='exact')\
            .eq('subscription_tier', 'free').eq('is_trial_active', False).execute()
        trial_count = supabase.table('students').select('id', count='exact')\
            .eq('is_trial_active', True).execute()
        scholar_count = supabase.table('students').select('id', count='exact')\
            .eq('subscription_tier', 'scholar').execute()

        banned_count = supabase.table('students').select('id', count='exact')\
            .eq('is_banned', True).execute()

        q_count = supabase.table('questions').select('id', count='exact').execute()
        verified_q = supabase.table('questions').select('id', count='exact')\
            .eq('is_verified', True).execute()

        ai_key = f"ai_cost:{today}"
        ai_cost = float(redis_client.get(ai_key) or 0)

        payments_today = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        revenue_today = sum(p.get('amount_naira', 0) for p in (payments_today.data or []))

        payments_week = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', week_ago).eq('status', 'completed').execute()
        revenue_week = sum(p.get('amount_naira', 0) for p in (payments_week.data or []))

        flags = supabase.table('question_flags').select('id', count='exact')\
            .eq('status', 'pending').execute()

        stats = (
            f"📊 *WaxPrep Live Stats*\n"
            f"_{datetime.now(ZoneInfo('Africa/Lagos')).strftime('%H:%M on %d %b %Y')}_\n\n"

            f"👥 *Students*\n"
            f"Total Registered: {total.count or 0:,}\n"
            f"New Today: +{new_today.count or 0}\n"
            f"Studying Today: {active_today.count or 0:,}\n"
            f"Active This Week: {active_week.count or 0:,}\n\n"

            f"💳 *Subscription Breakdown*\n"
            f"Free Tier: {free_count.count or 0:,}\n"
            f"On Trial: {trial_count.count or 0:,}\n"
            f"Scholar: {scholar_count.count or 0:,}\n"
            f"Banned: {banned_count.count or 0}\n\n"

            f"💰 *Revenue*\n"
            f"Today: ₦{revenue_today:,}\n"
            f"This Week: ₦{revenue_week:,}\n\n"

            f"🤖 *AI Budget*\n"
            f"Today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD:.2f}\n\n"

            f"📚 *Question Bank*\n"
            f"Total: {q_count.count or 0:,}\n"
            f"Verified: {verified_q.count or 0:,}\n"
            f"Pending Review: {flags.count or 0}\n"
        )

        await send_whatsapp_message(phone, stats)

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Stats error: {str(e)[:200]}")


async def admin_revenue(phone: str, period: str):
    """Detailed revenue breakdown for a time period."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))

    period_map = {
        'today': (now.strftime('%Y-%m-%d'), None, "Today"),
        'week': ((now - timedelta(days=7)).strftime('%Y-%m-%d'), None, "Last 7 Days"),
        'month': ((now - timedelta(days=30)).strftime('%Y-%m-%d'), None, "Last 30 Days"),
        '3month': ((now - timedelta(days=90)).strftime('%Y-%m-%d'), None, "Last 90 Days"),
    }

    start_date, end_date, label = period_map.get(period.lower(), period_map['today'])

    try:
        query = supabase.table('payments').select('amount_naira, created_at')\
            .gte('completed_at', start_date)\
            .eq('status', 'completed')

        result = query.execute()
        payments = result.data or []

        total = sum(p.get('amount_naira', 0) for p in payments)
        count = len(payments)
        avg = round(total / count) if count > 0 else 0

        # New subscribers in period
        new_paying = supabase.table('subscriptions').select('id', count='exact')\
            .gte('created_at', start_date).execute()

        msg = (
            f"💰 *Revenue: {label}*\n\n"
            f"Total: ₦{total:,}\n"
            f"Transactions: {count}\n"
            f"Average: ₦{avg:,}\n"
            f"New Subscribers: {new_paying.count or 0}\n"
        )

        await send_whatsapp_message(phone, msg)

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Revenue error: {str(e)[:200]}")


async def admin_student_profile(phone: str, wax_id: str):
    """Returns the complete profile of any student by WAX ID."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime

    if not wax_id:
        await send_whatsapp_message(phone, "Usage: ADMIN STUDENT [WAX-ID]\nExample: ADMIN STUDENT WAX-A74892")
        return

    # Clean up WAX ID format
    wax_id = wax_id.strip().upper()
    if not wax_id.startswith('WAX-') and wax_id.startswith('WAX'):
        wax_id = 'WAX-' + wax_id[3:]

    try:
        result = supabase.table('students').select('*').eq('wax_id', wax_id).execute()

        if not result.data:
            await send_whatsapp_message(phone, f"❌ No student found with WAX ID: {wax_id}")
            return

        s = result.data[0]

        # Get platform info
        platforms = supabase.table('platform_sessions').select('platform, last_active')\
            .eq('student_id', s['id']).execute()

        platform_list = ', '.join([p['platform'] for p in (platforms.data or [])]) or 'None'

        # Get recent badges
        badges = supabase.table('student_badges').select('badges(name)')\
            .eq('student_id', s['id']).order('earned_at', desc=True).limit(3).execute()

        badge_names = ', '.join([b['badges']['name'] for b in (badges.data or []) if b.get('badges')]) or 'None yet'

        # Subscription info
        tier = s.get('subscription_tier', 'free')
        trial_active = s.get('is_trial_active', False)
        sub_expires = s.get('subscription_expires_at', 'N/A')
        trial_expires = s.get('trial_expires_at', 'N/A')

        answered = s.get('total_questions_answered', 0)
        correct = s.get('total_questions_correct', 0)
        accuracy = round((correct / answered * 100) if answered > 0 else 0)

        profile = (
            f"👤 *Student Profile*\n\n"
            f"Name: {s.get('name', 'Unknown')}\n"
            f"WAX ID: {s.get('wax_id', 'N/A')}\n"
            f"State: {s.get('state', 'Unknown')}\n"
            f"Class: {s.get('class_level', 'Unknown')}\n"
            f"Exam: {s.get('target_exam', 'Unknown')}\n"
            f"Subjects: {', '.join(s.get('subjects', []))}\n\n"

            f"💳 *Subscription*\n"
            f"Tier: {tier.upper()}\n"
            f"Trial Active: {'Yes' if trial_active else 'No'}\n"
            f"Trial Expires: {str(trial_expires)[:10] if trial_expires else 'N/A'}\n"
            f"Sub Expires: {str(sub_expires)[:10] if sub_expires != 'N/A' else 'N/A'}\n\n"

            f"📊 *Performance*\n"
            f"Questions Answered: {answered:,}\n"
            f"Correct: {correct:,}\n"
            f"Accuracy: {accuracy}%\n"
            f"Streak: {s.get('current_streak', 0)} days\n"
            f"Best Streak: {s.get('longest_streak', 0)} days\n"
            f"Points: {s.get('total_points', 0):,}\n"
            f"Level: {s.get('current_level', 1)} ({s.get('level_name', 'Scholar')})\n\n"

            f"🏅 Recent Badges: {badge_names}\n\n"

            f"📱 Platforms: {platform_list}\n"
            f"Referrals Made: {s.get('referral_count', 0)}\n"
            f"Joined: {str(s.get('created_at', ''))[:10]}\n"
            f"Last Studied: {s.get('last_study_date', 'Never')}\n"
            f"Banned: {'YES ⚠️' if s.get('is_banned') else 'No'}\n"
            f"Onboarding Done: {'Yes' if s.get('onboarding_complete') else 'No'}"
        )

        await send_whatsapp_message(phone, profile)

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Error fetching student: {str(e)[:200]}")


async def admin_search_student(phone: str, search_term: str):
    """Searches for students by name."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    if not search_term:
        await send_whatsapp_message(phone, "Usage: ADMIN SEARCH [name]\nExample: ADMIN SEARCH Chidi")
        return

    try:
        result = supabase.table('students').select('wax_id, name, subscription_tier, last_study_date, is_banned')\
            .ilike('name', f'%{search_term}%')\
            .limit(10)\
            .execute()

        if not result.data:
            await send_whatsapp_message(phone, f"❌ No students found matching: {search_term}")
            return

        lines = [f"🔍 *Search Results for '{search_term}'*\n"]
        for s in result.data:
            tier = s.get('subscription_tier', 'free').upper()
            last = s.get('last_study_date', 'Never')
            banned = " ⚠️BANNED" if s.get('is_banned') else ""
            lines.append(f"• *{s['name']}* — {s['wax_id']}\n  Tier: {tier} | Last studied: {last}{banned}")

        msg = '\n\n'.join(lines)
        msg += f"\n\nType *ADMIN STUDENT [WAX-ID]* for full details."

        await send_whatsapp_message(phone, msg)

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Search error: {str(e)[:200]}")


async def admin_upgrade_student(phone: str, args: str):
    """
    Gives a student a free tier upgrade.
    Usage: ADMIN UPGRADE WAX-A74892 scholar 30
    (WAX ID, tier, number of days)
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    parts = args.strip().split()
    if len(parts) < 3:
        await send_whatsapp_message(
            phone,
            "Usage: ADMIN UPGRADE [WAX-ID] [tier] [days]\n"
            "Example: ADMIN UPGRADE WAX-A74892 scholar 30"
        )
        return

    wax_id = parts[0].upper()
    tier = parts[1].lower()
    try:
        days = int(parts[2])
    except ValueError:
        await send_whatsapp_message(phone, "❌ Days must be a number. Example: ADMIN UPGRADE WAX-A74892 scholar 30")
        return

    if tier not in ['scholar', 'pro', 'elite']:
        await send_whatsapp_message(phone, "❌ Valid tiers: scholar, pro, elite")
        return

    if not wax_id.startswith('WAX-'):
        wax_id = 'WAX-' + wax_id.replace('WAX', '')

    try:
        student_result = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()

        if not student_result.data:
            await send_whatsapp_message(phone, f"❌ Student not found: {wax_id}")
            return

        student = student_result.data[0]
        now = datetime.now(ZoneInfo("Africa/Lagos"))
        expires = now + timedelta(days=days)

        supabase.table('students').update({
            'subscription_tier': tier,
            'subscription_expires_at': expires.isoformat(),
            'is_trial_active': False,
            'updated_at': now.isoformat(),
        }).eq('id', student['id']).execute()

        name = student['name'].split()[0]

        await send_whatsapp_message(
            phone,
            f"✅ *Upgrade Applied*\n\n"
            f"Student: {student['name']} ({wax_id})\n"
            f"New Tier: {tier.capitalize()}\n"
            f"Duration: {days} days\n"
            f"Expires: {expires.strftime('%d %B %Y')}"
        )

        # Notify the student
        student_phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

        if student_phone_result.data:
            from whatsapp.sender import send_whatsapp_message as swm
            student_phone = student_phone_result.data[0]['platform_user_id']
            await swm(
                student_phone,
                f"🎉 *Great news, {name}!*\n\n"
                f"Your account has been upgraded to *{tier.capitalize()} Plan* for {days} days!\n\n"
                f"Enjoy all {tier.capitalize()} features until {expires.strftime('%d %B %Y')}. 🚀"
            )

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Upgrade error: {str(e)[:200]}")


async def admin_ban_student(phone: str, args: str):
    """Bans a student account."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    parts = args.strip().split(None, 1)
    if not parts:
        await send_whatsapp_message(phone, "Usage: ADMIN BAN [WAX-ID] [reason]")
        return

    wax_id = parts[0].upper()
    reason = parts[1] if len(parts) > 1 else "Admin decision"

    if not wax_id.startswith('WAX-'):
        wax_id = 'WAX-' + wax_id.replace('WAX', '')

    try:
        result = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()

        if not result.data:
            await send_whatsapp_message(phone, f"❌ Student not found: {wax_id}")
            return

        student = result.data[0]

        supabase.table('students').update({
            'is_banned': True,
            'is_active': False,
            'ban_reason': reason,
        }).eq('id', student['id']).execute()

        await send_whatsapp_message(
            phone,
            f"✅ *Banned:* {student['name']} ({wax_id})\nReason: {reason}"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Ban error: {str(e)[:200]}")


async def admin_unban_student(phone: str, wax_id: str):
    """Unbans a student account."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    if not wax_id:
        await send_whatsapp_message(phone, "Usage: ADMIN UNBAN [WAX-ID]")
        return

    if not wax_id.startswith('WAX-'):
        wax_id = 'WAX-' + wax_id.replace('WAX', '')

    try:
        result = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()

        if not result.data:
            await send_whatsapp_message(phone, f"❌ Student not found: {wax_id}")
            return

        student = result.data[0]

        supabase.table('students').update({
            'is_banned': False,
            'is_active': True,
            'ban_reason': None,
        }).eq('id', student['id']).execute()

        await send_whatsapp_message(
            phone,
            f"✅ *Unbanned:* {student['name']} ({wax_id})\nAccount restored."
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Unban error: {str(e)[:200]}")


async def admin_message_student(phone: str, args: str):
    """Sends a direct message to a specific student from admin."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        await send_whatsapp_message(
            phone,
            "Usage: ADMIN MSG [WAX-ID] [message]\n"
            "Example: ADMIN MSG WAX-A74892 Your account issue has been resolved!"
        )
        return

    wax_id = parts[0].upper()
    message = parts[1].strip()

    if not wax_id.startswith('WAX-'):
        wax_id = 'WAX-' + wax_id.replace('WAX', '')

    try:
        student_result = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()

        if not student_result.data:
            await send_whatsapp_message(phone, f"❌ Student not found: {wax_id}")
            return

        student = student_result.data[0]

        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

        if not phone_result.data:
            await send_whatsapp_message(phone, f"❌ {student['name']} has no WhatsApp linked.")
            return

        student_phone = phone_result.data[0]['platform_user_id']

        await send_whatsapp_message(
            student_phone,
            f"📢 *Message from WaxPrep:*\n\n{message}"
        )

        await send_whatsapp_message(
            phone,
            f"✅ Message sent to {student['name']} ({wax_id})"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Message error: {str(e)[:200]}")


async def admin_broadcast(phone: str, args: str):
    """
    Sends a message to a filtered group of students.

    Format: [TARGET] [message]
    Targets: ALL, FREE, SCHOLAR, PRO, TRIAL, EXAM [type], STATE [name], STREAK [n]
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        await send_whatsapp_message(
            phone,
            "Usage: ADMIN BROADCAST [TARGET] [message]\n\n"
            "Targets: ALL, FREE, SCHOLAR, PRO, TRIAL, EXAM JAMB, STATE Lagos, STREAK 7"
        )
        return

    target = parts[0].upper()
    message_text = parts[1].strip()

    if not message_text:
        await send_whatsapp_message(phone, "❌ Message cannot be empty.")
        return

    await send_whatsapp_message(
        phone,
        f"⚙️ *Starting broadcast to {target}...*\n\nThis may take a few minutes for large groups."
    )

    try:
        # Build the student query based on target
        query = supabase.table('students').select('id, name, subscription_tier, target_exam, state, current_streak')\
            .eq('is_active', True)\
            .eq('is_banned', False)

        # Handle compound targets like "EXAM JAMB" or "STATE Lagos"
        target_parts = target.split(None, 1)
        main_target = target_parts[0]
        sub_target = target_parts[1] if len(target_parts) > 1 else ''

        if main_target == 'FREE':
            query = query.eq('subscription_tier', 'free').eq('is_trial_active', False)
            label = "Free tier students"
        elif main_target == 'SCHOLAR':
            query = query.eq('subscription_tier', 'scholar')
            label = "Scholar subscribers"
        elif main_target == 'PRO':
            query = query.eq('subscription_tier', 'pro')
            label = "Pro subscribers"
        elif main_target == 'TRIAL':
            query = query.eq('is_trial_active', True)
            label = "Trial students"
        elif main_target == 'EXAM' and sub_target:
            query = query.eq('target_exam', sub_target.upper())
            label = f"{sub_target.upper()} students"
        elif main_target == 'STATE' and sub_target:
            query = query.ilike('state', f'%{sub_target}%')
            label = f"Students in {sub_target}"
        elif main_target == 'STREAK' and sub_target:
            try:
                min_streak = int(sub_target)
                query = query.gte('current_streak', min_streak)
                label = f"Students with {min_streak}+ day streak"
            except ValueError:
                await send_whatsapp_message(phone, "❌ STREAK target needs a number. Example: ADMIN BROADCAST STREAK 7 [message]")
                return
        else:
            # Default: ALL active students
            label = "All active students"

        students = query.limit(2000).execute()

        if not students.data:
            await send_whatsapp_message(phone, f"❌ No students found matching target: {target}")
            return

        total = len(students.data)
        sent = 0
        failed = 0

        for student in students.data:
            try:
                phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                    .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

                if not phone_result.data:
                    continue

                student_phone = phone_result.data[0]['platform_user_id']
                name = student['name'].split()[0]

                # Personalize the message with the student's first name
                personalized = message_text.replace('{name}', name)

                await send_whatsapp_message(student_phone, personalized)
                sent += 1

                # Rate limiting: don't send too fast or WhatsApp throttles us
                await asyncio.sleep(0.4)

            except Exception:
                failed += 1

        await send_whatsapp_message(
            phone,
            f"✅ *Broadcast Complete*\n\n"
            f"Target: {label}\n"
            f"Total matched: {total:,}\n"
            f"Successfully sent: {sent:,}\n"
            f"Failed: {failed}\n\n"
            f"_Tip: Use {{name}} in your message to personalize it._"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Broadcast error: {str(e)[:200]}")


async def admin_manage_codes(phone: str, args: str):
    """Manages promo codes — list, create, or disable."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    parts = args.strip().split()
    if not parts:
        await send_whatsapp_message(phone, "Usage: ADMIN CODE LIST / CREATE / DISABLE")
        return

    action = parts[0].upper()

    if action == 'LIST':
        try:
            result = supabase.table('promo_codes').select('*')\
                .eq('is_active', True)\
                .order('created_at', desc=True)\
                .limit(10)\
                .execute()

            if not result.data:
                await send_whatsapp_message(phone, "No active promo codes.")
                return

            lines = ["🎁 *Active Promo Codes*\n"]
            for code in result.data:
                uses = f"{code.get('current_uses', 0)}/{code.get('max_uses', '∞')}"
                expires = str(code.get('expires_at', 'Never'))[:10]
                code_type = code.get('code_type', 'unknown')
                desc = code.get('description', '')[:40]
                lines.append(
                    f"• *{code['code']}* ({code_type})\n"
                    f"  Uses: {uses} | Expires: {expires}\n"
                    f"  {desc}"
                )

            await send_whatsapp_message(phone, '\n\n'.join(lines))

        except Exception as e:
            await send_whatsapp_message(phone, f"❌ Error: {str(e)[:200]}")

    elif action == 'CREATE':
        # Format: CREATE [code] [type] [value] [maxuses]
        # Types: trial, discount, upgrade
        # Example: CREATE LAGOS50 discount 50 100
        # Example: CREATE FREEWK trial 7 50
        if len(parts) < 5:
            await send_whatsapp_message(
                phone,
                "Usage: ADMIN CODE CREATE [code] [type] [value] [maxuses]\n\n"
                "Types and values:\n"
                "• trial [days] — e.g. trial 7 gives 7 extra trial days\n"
                "• discount [percent] — e.g. discount 20 gives 20% off\n"
                "• upgrade [tier] [days] — e.g. upgrade scholar 30\n\n"
                "Examples:\n"
                "ADMIN CODE CREATE LAGOS50 discount 50 100\n"
                "ADMIN CODE CREATE FREEWK trial 7 50\n"
                "ADMIN CODE CREATE VIP upgrade scholar 30"
            )
            return

        new_code = parts[1].upper()
        code_type = parts[2].lower()
        value = parts[3]
        try:
            max_uses = int(parts[4])
        except (ValueError, IndexError):
            max_uses = 100

        try:
            code_data = {
                'code': new_code,
                'code_type': 'full_trial' if code_type == 'trial' else
                             'discount_percent' if code_type == 'discount' else 'tier_upgrade',
                'is_active': True,
                'max_uses': max_uses,
                'current_uses': 0,
                'description': f"Admin created: {code_type} {value}",
            }

            if code_type == 'trial':
                code_data['bonus_days'] = int(value)
            elif code_type == 'discount':
                code_data['discount_percent'] = int(value)
            elif code_type == 'upgrade':
                code_data['tier_to_unlock'] = value.lower()
                code_data['bonus_days'] = int(parts[5]) if len(parts) > 5 else 30

            supabase.table('promo_codes').insert(code_data).execute()

            await send_whatsapp_message(
                phone,
                f"✅ *Promo Code Created*\n\n"
                f"Code: *{new_code}*\n"
                f"Type: {code_type}\n"
                f"Value: {value}\n"
                f"Max Uses: {max_uses}\n\n"
                f"Students apply it by typing:\n"
                f"*PROMO {new_code}*"
            )

        except Exception as e:
            await send_whatsapp_message(phone, f"❌ Code creation error: {str(e)[:200]}")

    elif action == 'DISABLE':
        if len(parts) < 2:
            await send_whatsapp_message(phone, "Usage: ADMIN CODE DISABLE [code]")
            return

        code_to_disable = parts[1].upper()
        try:
            supabase.table('promo_codes').update({'is_active': False})\
                .eq('code', code_to_disable).execute()

            await send_whatsapp_message(phone, f"✅ Code *{code_to_disable}* has been disabled.")

        except Exception as e:
            await send_whatsapp_message(phone, f"❌ Error: {str(e)[:200]}")


async def admin_questions(phone: str, sub_command: str, rest: str):
    """Manages flagged questions."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    if sub_command == 'PENDING':
        try:
            result = supabase.table('question_flags')\
                .select('id, question_id, reason, note, created_at, questions(question_text, subject)')\
                .eq('status', 'pending')\
                .order('created_at', desc=False)\
                .limit(5)\
                .execute()

            if not result.data:
                await send_whatsapp_message(phone, "✅ No pending question flags! All clear.")
                return

            lines = [f"🚩 *Pending Question Flags ({len(result.data)} shown)*\n"]
            for flag in result.data:
                q = flag.get('questions', {}) or {}
                flag_id = str(flag['id'])[:8]
                subject = q.get('subject', 'Unknown')
                question_text = (q.get('question_text', '') or '')[:100]
                reason = flag.get('reason', 'unspecified')

                lines.append(
                    f"• *Flag ID:* {flag_id}\n"
                    f"  Subject: {subject}\n"
                    f"  Reason: {reason}\n"
                    f"  Q: {question_text}...\n"
                    f"  Use: ADMIN QUESTIONS APPROVE {flag_id}"
                )

            await send_whatsapp_message(phone, '\n\n'.join(lines))

        except Exception as e:
            await send_whatsapp_message(phone, f"❌ Error: {str(e)[:200]}")

    elif sub_command == 'APPROVE':
        flag_id_prefix = rest.strip().split()[1] if len(rest.split()) > 1 else ''
        if not flag_id_prefix:
            await send_whatsapp_message(phone, "Usage: ADMIN QUESTIONS APPROVE [flag-id-prefix]")
            return

        try:
            result = supabase.table('question_flags').select('id, question_id')\
                .ilike('id::text', f'{flag_id_prefix}%')\
                .limit(1).execute()

            if not result.data:
                await send_whatsapp_message(phone, f"❌ Flag not found with ID starting: {flag_id_prefix}")
                return

            flag = result.data[0]
            supabase.table('question_flags').update({'status': 'reviewed'})\
                .eq('id', flag['id']).execute()

            await send_whatsapp_message(phone, f"✅ Flag marked as reviewed. Question kept active.")

        except Exception as e:
            await send_whatsapp_message(phone, f"❌ Error: {str(e)[:200]}")

async def handle_admin_command(phone: str, message: str):
    """
    Main entry point for admin commands.
    Now supports MODE SWITCH for testing as a student.
    """
    from whatsapp.sender import send_whatsapp_message

    parts = message.strip().split(None, 2)

    if len(parts) < 2:
        await send_admin_help(phone)
        return

    command = parts[1].upper() if len(parts) > 1 else ''
    rest = parts[2] if len(parts) > 2 else ''

    # ============================================================
    # MODE SWITCH — Test as a student from your own phone
    # ============================================================
    if command == 'STUDENT_MODE':
        await _enable_student_mode(phone)
        return

    if command == 'ADMIN_MODE':
        await _enable_admin_mode(phone)
        return

    # All other commands
    if command == 'HELP':
        await send_admin_help(phone)
    elif command == 'STATS':
        await admin_stats(phone)
    elif command == 'REVENUE':
        await admin_revenue(phone, rest.lower() if rest else 'today')
    elif command == 'STUDENT':
        await admin_student_profile(phone, rest.strip().upper())
    elif command == 'SEARCH':
        await admin_search_student(phone, rest.strip())
    elif command == 'UPGRADE':
        await admin_upgrade_student(phone, rest.strip())
    elif command == 'BAN':
        await admin_ban_student(phone, rest.strip())
    elif command == 'UNBAN':
        await admin_unban_student(phone, rest.strip().upper())
    elif command == 'MSG':
        await admin_message_student(phone, rest.strip())
    elif command == 'BROADCAST':
        await admin_broadcast(phone, rest.strip())
    elif command == 'CODE':
        await admin_manage_codes(phone, rest.strip())
    elif command == 'QUESTIONS':
        sub = rest.strip().upper().split()[0] if rest.strip() else ''
        await admin_questions(phone, sub, rest)
    elif command == 'REPORT':
        from utils.scheduler import send_daily_admin_report
        await send_whatsapp_message(phone, "⚙️ Generating report now...")
        await send_daily_admin_report()
    elif command == 'CHALLENGE':
        from utils.scheduler import generate_daily_challenge
        await send_whatsapp_message(phone, "⚙️ Generating challenge...")
        await generate_daily_challenge()
        await send_whatsapp_message(phone, "✅ Done!")
    elif command == 'ONLINE':
        await admin_online_count(phone)
    elif command == 'TOP':
        try:
            n = int(rest.strip()) if rest.strip().isdigit() else 10
        except Exception:
            n = 10
        await admin_top_students(phone, n)
    else:
        await send_whatsapp_message(
            phone,
            f"❓ Unknown command: *ADMIN {command}*\n\nType *ADMIN HELP* for all commands."
        )


async def _enable_student_mode(phone: str):
    """
    Switches admin to student testing mode.
    The admin temporarily stops being treated as admin
    and experiences WaxPrep exactly as a real student would.
    """
    from database.client import redis_client
    from whatsapp.sender import send_whatsapp_message

    redis_client.setex(f"admin_student_mode:{phone}", 3600, "1")  # 1 hour

    await send_whatsapp_message(
        phone,
        "🎓 *Student Mode ON* (1 hour)\n\n"
        "You are now experiencing WaxPrep as a student.\n"
        "Everything you send will be processed as a real student message.\n\n"
        "To go back to admin, type:\n"
        "*ADMIN ADMIN_MODE*\n\n"
        "_Now send 'Hi' to test the student onboarding!_"
    )


async def _enable_admin_mode(phone: str):
    """Switches back to admin mode."""
    from database.client import redis_client
    from whatsapp.sender import send_whatsapp_message

    redis_client.delete(f"admin_student_mode:{phone}")

    await send_whatsapp_message(
        phone,
        "🛠️ *Admin Mode restored.*\n\nYou're back to admin. Type *ADMIN HELP* for commands."
    )


def is_admin(phone: str) -> bool:
    """
    Checks if a phone number is the admin.
    Returns False if admin has switched to student testing mode.
    """
    from config.settings import settings

    if not settings.ADMIN_WHATSAPP:
        return False

    def normalize(p: str) -> str:
        return p.replace('+', '').replace(' ', '').replace('-', '')

    if normalize(phone) != normalize(settings.ADMIN_WHATSAPP):
        return False

    # Check if admin has enabled student mode
    try:
        from database.client import redis_client
        student_mode = redis_client.get(f"admin_student_mode:{phone}")
        if student_mode:
            return False  # In student mode — not treated as admin
    except Exception:
        pass

    return True

async def admin_online_count(phone: str):
    """Shows how many students are actively studying right now."""
    from database.client import redis_client, supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    thirty_min_ago = (now - timedelta(minutes=30)).isoformat()

    try:
        active = supabase.table('conversations').select('student_id', count='exact')\
            .gte('last_message_at', thirty_min_ago)\
            .execute()

        count = active.count or 0

        await send_whatsapp_message(
            phone,
            f"👥 *Students Online Right Now*\n\n"
            f"Active in last 30 minutes: *{count}*\n\n"
            f"_Time: {now.strftime('%H:%M WAT')}_"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Error: {str(e)[:200]}")


async def admin_top_students(phone: str, n: int):
    """Shows the top n students by total points."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    try:
        result = supabase.table('students').select('name, wax_id, total_points, current_streak, subscription_tier')\
            .eq('is_active', True)\
            .order('total_points', desc=True)\
            .limit(min(n, 20))\
            .execute()

        if not result.data:
            await send_whatsapp_message(phone, "No students found.")
            return

        lines = [f"🏆 *Top {len(result.data)} Students by Points*\n"]
        medals = ['🥇', '🥈', '🥉'] + ['⭐'] * 17

        for i, s in enumerate(result.data):
            medal = medals[i] if i < len(medals) else '•'
            tier = s.get('subscription_tier', 'free').upper()
            lines.append(
                f"{medal} *{s['name']}*\n"
                f"   {s['wax_id']} | {s.get('total_points', 0):,} pts | "
                f"{s.get('current_streak', 0)}🔥 | {tier}"
            )

        await send_whatsapp_message(phone, '\n\n'.join(lines))

    except Exception as e:
        await send_whatsapp_message(phone, f"❌ Error: {str(e)[:200]}")


import asyncio  # needed for broadcast sleep

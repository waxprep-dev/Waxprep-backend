"""
Admin Dashboard — WhatsApp Command Interface
FIXED: Removed duplicate function definitions
ADDED: Student name search, bug report viewing, suggestion viewing, ALOC Question Import
"""
import asyncio
from config.settings import settings

def is_admin(phone: str) -> bool:
    """
    Checks if a phone number is the admin.
    Returns False if admin has switched to student testing mode.
    """
    if not settings.ADMIN_WHATSAPP:
        return False
        
    def normalize(p: str) -> str:
        return p.replace('+', '').replace(' ', '').replace('-', '')

    if normalize(phone) != normalize(settings.ADMIN_WHATSAPP):
        return False

    try:
        from database.client import redis_client
        student_mode = redis_client.get(f"admin_student_mode:{phone}")
        if student_mode:
            return False
    except Exception:
        pass

    return True

async def handle_admin_command(phone: str, message: str):
    """
    Main entry point for admin commands.
    Routes to the right handler.
    """
    from whatsapp.sender import send_whatsapp_message
    if not is_admin(phone):
        return

    parts = message.strip().split(None, 2)

    if len(parts) < 2:
        await send_admin_help(phone)
        return

    command = parts[1].upper() if len(parts) > 1 else ''
    rest = parts[2] if len(parts) > 2 else ''
    sub_command = rest.strip().upper().split()[0] if rest.strip() else ''

    if command == 'STUDENT_MODE':
        await _enable_student_mode(phone)
        return

    if command == 'ADMIN_MODE':
        await _enable_admin_mode(phone)
        return

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
        await admin_questions(phone, sub_command, rest)
    elif command == 'IMPORT_QUESTIONS':
        from features.aloc_importer import import_questions_from_aloc
        await send_whatsapp_message(phone, "Importing past questions from ALOC... This may take a few minutes.")
        result = await import_questions_from_aloc()
        await send_whatsapp_message(phone, result)
    elif command == 'TEST_ALOC':
        from whatsapp.sender import send_whatsapp_message
        import httpx
        # Using the token provided directly for this debug phase
        token = "ALOC-e07704e53978b4066e73"
        url = "https://questions.aloc.com.ng/api/v2/q?subject=chemistry"
        # Using AccessToken as requested by their 400 error response
        headers = {"AccessToken": token}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)
                status = resp.status_code
                body = resp.text[:300]
            await send_whatsapp_message(phone, f"ALOC Test Result\nStatus: {status}\nResponse: {body}")
        except Exception as e:
            await send_whatsapp_message(phone, f"ALOC test error: {str(e)[:200]}")
    elif command == 'REPORT':
        from utils.scheduler import send_daily_admin_report
        await send_whatsapp_message(phone, "Generating report now...")
        await send_daily_admin_report()
    elif command == 'CHALLENGE':
        from utils.scheduler import generate_daily_challenge
        await send_whatsapp_message(phone, "Generating challenge...")
        await generate_daily_challenge()
        await send_whatsapp_message(phone, "Done!")
    elif command == 'ONLINE':
        await admin_online_count(phone)
    elif command == 'TOP':
        try:
            n = int(rest.strip()) if rest.strip().isdigit() else 10
        except Exception:
            n = 10
        await admin_top_students(phone, n)
    elif command == 'BUGS':
        await admin_view_bugs(phone)
    elif command == 'SUGGESTIONS':
        await admin_view_suggestions(phone)
    elif command == 'PAYG':
        await admin_payg_stats(phone)
    elif command == 'FINDNAME':
        await admin_search_by_name(phone, rest.strip())
    else:
        await send_whatsapp_message(
            phone,
            f"Unknown command: *ADMIN {command}*\n\nType *ADMIN HELP* for all commands."
        )

async def send_admin_help(phone: str):
    """Sends the complete admin command reference."""
    from whatsapp.sender import send_whatsapp_message
    help_text = (
        "WaxPrep Admin Commands\n\n"

        "Platform Info:\n"
        "ADMIN STATS\n"
        "ADMIN REVENUE today/week/month\n"
        "ADMIN ONLINE\n"
        "ADMIN TOP 10\n"
        "ADMIN REPORT\n"
        "ADMIN CHALLENGE\n\n"

        "Students:\n"
        "ADMIN STUDENT [WAX-ID]\n"
        "ADMIN SEARCH [name or WAX-ID]\n"
        "ADMIN FINDNAME [name] — search by name only\n"
        "ADMIN UPGRADE [WAX-ID] scholar 30\n"
        "ADMIN BAN [WAX-ID] [reason]\n"
        "ADMIN UNBAN [WAX-ID]\n"
        "ADMIN MSG [WAX-ID] [message]\n\n"

        "Broadcasts:\n"
        "ADMIN BROADCAST ALL [message]\n"
        "ADMIN BROADCAST FREE [message]\n"
        "ADMIN BROADCAST SCHOLAR [message]\n"
        "ADMIN BROADCAST TRIAL [message]\n"
        "ADMIN BROADCAST EXAM JAMB [message]\n"
        "ADMIN BROADCAST STATE Lagos [message]\n"
        "ADMIN BROADCAST STREAK 7 [message]\n\n"

        "Promo Codes:\n"
        "ADMIN CODE LIST\n"
        "ADMIN CODE CREATE WAX2024 trial 7 100\n"
        "ADMIN CODE DISABLE [code]\n\n"

        "Feedback:\n"
        "ADMIN BUGS — View bug reports\n"
        "ADMIN SUGGESTIONS — View student suggestions\n\n"

        "Payments:\n"
        "ADMIN PAYG — Pay-as-you-go stats\n\n"

        "Content:\n"
        "ADMIN QUESTIONS PENDING\n"
        "ADMIN QUESTIONS APPROVE [ID]\n"
        "ADMIN IMPORT_QUESTIONS — Import from ALOC\n"
        "ADMIN TEST_ALOC — Debug ALOC Token\n\n"

        "Mode Switch:\n"
        "ADMIN STUDENT_MODE — Test as student\n"
        "ADMIN ADMIN_MODE — Switch back"
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

        try:
            bugs = supabase.table('bug_reports').select('id', count='exact')\
                .eq('status', 'new').execute()
            bug_count = bugs.count or 0
        except Exception:
            bug_count = 0

        stats = (
            f"WaxPrep Live Stats\n"
            f"{now.strftime('%H:%M on %d %b %Y')}\n\n"

            f"Students\n"
            f"Total: {total.count or 0:,}\n"
            f"New Today: +{new_today.count or 0}\n"
            f"Studying Today: {active_today.count or 0:,}\n"
            f"Active This Week: {active_week.count or 0:,}\n\n"

            f"Subscription\n"
            f"Free: {free_count.count or 0:,}\n"
            f"On Trial: {trial_count.count or 0:,}\n"
            f"Scholar: {scholar_count.count or 0:,}\n"
            f"Banned: {banned_count.count or 0}\n\n"

            f"Revenue\n"
            f"Today: N{revenue_today:,}\n"
            f"This Week: N{revenue_week:,}\n\n"

            f"AI Budget\n"
            f"Today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD:.2f}\n\n"

            f"Question Bank\n"
            f"Total: {q_count.count or 0:,}\n"
            f"Verified: {verified_q.count or 0:,}\n"
            f"Pending Review: {flags.count or 0}\n"
            f"Unread Bug Reports: {bug_count}\n"
        )

        await send_whatsapp_message(phone, stats)

    except Exception as e:
        await send_whatsapp_message(phone, f"Stats error: {str(e)[:200]}")

async def admin_revenue(phone: str, period: str):
    """Detailed revenue breakdown."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Africa/Lagos"))

    period_map = {
        'today': (now.strftime('%Y-%m-%d'), "Today"),
        'week': ((now - timedelta(days=7)).strftime('%Y-%m-%d'), "Last 7 Days"),
        'month': ((now - timedelta(days=30)).strftime('%Y-%m-%d'), "Last 30 Days"),
        '3month': ((now - timedelta(days=90)).strftime('%Y-%m-%d'), "Last 90 Days"),
    }

    start_date, label = period_map.get(period.lower(), period_map['today'])

    try:
        query = supabase.table('payments').select('amount_naira, created_at, metadata')\
            .gte('completed_at', start_date)\
            .eq('status', 'completed')

        result = query.execute()
        payments = result.data or []

        total = sum(p.get('amount_naira', 0) for p in payments)
        count = len(payments)
        avg = round(total / count) if count > 0 else 0

        subscription_count = sum(1 for p in payments if not str(p.get('metadata', {}) or {}).get('payg_questions'))
        payg_count = count - subscription_count

        new_paying = supabase.table('subscriptions').select('id', count='exact')\
            .gte('created_at', start_date).execute()

        msg = (
            f"Revenue: {label}\n\n"
            f"Total: N{total:,}\n"
            f"Transactions: {count}\n"
            f"Average: N{avg:,}\n"
            f"Subscriptions: {subscription_count}\n"
            f"Pay-As-You-Go: {payg_count}\n"
            f"New Subscribers: {new_paying.count or 0}\n"
        )

        await send_whatsapp_message(phone, msg)

    except Exception as e:
        await send_whatsapp_message(phone, f"Revenue error: {str(e)[:200]}")

async def admin_student_profile(phone: str, wax_id: str):
    """Returns the complete profile of any student by WAX ID."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    if not wax_id:
        await send_whatsapp_message(phone, "Usage: ADMIN STUDENT [WAX-ID]\nExample: ADMIN STUDENT WAX-A74892")
        return

    wax_id = wax_id.strip().upper()
    if not wax_id.startswith('WAX-') and wax_id.startswith('WAX'):
        wax_id = 'WAX-' + wax_id[3:]

    try:
        result = supabase.table('students').select('*').eq('wax_id', wax_id).execute()

        if not result.data:
            await send_whatsapp_message(phone, f"No student found with WAX ID: {wax_id}")
            return

        s = result.data[0]

        platforms = supabase.table('platform_sessions').select('platform, last_active')\
            .eq('student_id', s['id']).execute()
        platform_list = ', '.join([p['platform'] for p in (platforms.data or [])]) or 'None'

        badges = supabase.table('student_badges').select('badges(name)')\
            .eq('student_id', s['id']).order('earned_at', desc=True).limit(3).execute()
        badge_names = ', '.join([b['badges']['name'] for b in (badges.data or []) if b.get('badges')]) or 'None yet'

        tier = s.get('subscription_tier', 'free')
        trial_active = s.get('is_trial_active', False)
        sub_expires = s.get('subscription_expires_at', 'N/A')
        trial_expires = s.get('trial_expires_at', 'N/A')

        answered = s.get('total_questions_answered', 0)
        correct = s.get('total_questions_correct', 0)
        accuracy = round((correct / answered * 100) if answered > 0 else 0)

        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', s['id']).eq('platform', 'whatsapp').execute()
        student_phone = phone_result.data[0]['platform_user_id'] if phone_result.data else 'Not linked'

        profile = (
            f"Student Profile\n\n"
            f"Name: {s.get('name', 'Unknown')}\n"
            f"WAX ID: {s.get('wax_id', 'N/A')}\n"
            f"Phone: {student_phone}\n"
            f"State: {s.get('state', 'Unknown')}\n"
            f"Class: {s.get('class_level', 'Unknown')}\n"
            f"Exam: {s.get('target_exam', 'Unknown')}\n"
            f"Subjects: {', '.join(s.get('subjects', []))}\n\n"

            f"Subscription\n"
            f"Tier: {tier.upper()}\n"
            f"Trial: {'Active' if trial_active else 'No'}\n"
            f"Trial Expires: {str(trial_expires)[:10] if trial_expires else 'N/A'}\n"
            f"Sub Expires: {str(sub_expires)[:10] if sub_expires != 'N/A' else 'N/A'}\n\n"

            f"Performance\n"
            f"Questions Answered: {answered:,}\n"
            f"Correct: {correct:,}\n"
            f"Accuracy: {accuracy}%\n"
            f"Streak: {s.get('current_streak', 0)} days\n"
            f"Best Streak: {s.get('longest_streak', 0)} days\n"
            f"Points: {s.get('total_points', 0):,}\n"
            f"Level: {s.get('current_level', 1)} ({s.get('level_name', 'Scholar')})\n\n"

            f"Recent Badges: {badge_names}\n\n"
            f"Platforms: {platform_list}\n"
            f"Referrals: {s.get('referral_count', 0)}\n"
            f"Joined: {str(s.get('created_at', ''))[:10]}\n"
            f"Last Studied: {s.get('last_study_date', 'Never')}\n"
            f"Banned: {'YES' if s.get('is_banned') else 'No'}\n"
            f"Terms Accepted: {'Yes' if s.get('terms_accepted') else 'No'}"
        )

        await send_whatsapp_message(phone, profile)

    except Exception as e:
        await send_whatsapp_message(phone, f"Error fetching student: {str(e)[:200]}")

async def admin_search_student(phone: str, search_term: str):
    """Searches for students by name or WAX ID."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from helpers import is_valid_wax_id
    if not search_term:
        await send_whatsapp_message(phone, "Usage: ADMIN SEARCH [name or WAX-ID]\nExample: ADMIN SEARCH Chidi")
        return

    try:
        clean = search_term.upper().strip()
        if clean.startswith('WAX') or is_valid_wax_id(clean):
            result = supabase.table('students').select('wax_id, name, subscription_tier, last_study_date, is_banned')\
                .ilike('wax_id', f'%{clean}%')\
                .limit(5)\
                .execute()
        else:
            result = supabase.table('students').select('wax_id, name, subscription_tier, last_study_date, is_banned')\
                .ilike('name', f'%{search_term}%')\
                .limit(10)\
                .execute()

        if not result.data:
            await send_whatsapp_message(phone, f"No students found matching: {search_term}")
            return

        lines = [f"Search Results for '{search_term}'\n"]
        for s in result.data:
            tier = s.get('subscription_tier', 'free').upper()
            last = s.get('last_study_date', 'Never')
            banned = " BANNED" if s.get('is_banned') else ""
            lines.append(f"• {s['name']} — {s['wax_id']}\n  Tier: {tier} | Last: {last}{banned}")

        msg = '\n\n'.join(lines)
        msg += "\n\nType ADMIN STUDENT [WAX-ID] for full details."
        await send_whatsapp_message(phone, msg)

    except Exception as e:
        await send_whatsapp_message(phone, f"Search error: {str(e)[:200]}")

async def admin_search_by_name(phone: str, name_query: str):
    """Searches specifically by student name and returns their phone too."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    if not name_query:
        await send_whatsapp_message(phone, "Usage: ADMIN FINDNAME [name]\nExample: ADMIN FINDNAME Chidi")
        return

    try:
        result = supabase.table('students').select('id, wax_id, name, subscription_tier, last_study_date, is_banned')\
            .ilike('name', f'%{name_query}%')\
            .limit(8)\
            .execute()

        if not result.data:
            await send_whatsapp_message(phone, f"No students found matching name: {name_query}")
            return

        lines = [f"Name Search: '{name_query}'\n"]
        for s in result.data:
            phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                .eq('student_id', s['id']).eq('platform', 'whatsapp').execute()
            student_phone = phone_result.data[0]['platform_user_id'] if phone_result.data else 'No phone'

            tier = s.get('subscription_tier', 'free').upper()
            banned = " BANNED" if s.get('is_banned') else ""
            lines.append(
                f"• {s['name']}{banned}\n"
                f"  WAX ID: {s['wax_id']}\n"
                f"  Phone: {student_phone}\n"
                f"  Tier: {tier}"
            )

        await send_whatsapp_message(phone, '\n\n'.join(lines))

    except Exception as e:
        await send_whatsapp_message(phone, f"Search error: {str(e)[:200]}")

async def admin_upgrade_student(phone: str, args: str):
    """Gives a student a free tier upgrade."""
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
        await send_whatsapp_message(phone, "Days must be a number.")
        return

    if tier not in ['scholar', 'pro', 'elite']:
        await send_whatsapp_message(phone, "Valid tiers: scholar, pro, elite")
        return

    if not wax_id.startswith('WAX-'):
        wax_id = 'WAX-' + wax_id.replace('WAX', '')

    try:
        student_result = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()

        if not student_result.data:
            await send_whatsapp_message(phone, f"Student not found: {wax_id}")
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
            f"Upgrade Applied\n\n"
            f"Student: {student['name']} ({wax_id})\n"
            f"New Tier: {tier.capitalize()}\n"
            f"Duration: {days} days\n"
            f"Expires: {expires.strftime('%d %B %Y')}"
        )

        student_phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

        if student_phone_result.data:
            from whatsapp.sender import send_whatsapp_message as swm
            student_phone = student_phone_result.data[0]['platform_user_id']
            await swm(
                student_phone,
                f"Great news, {name}!\n\n"
                f"Your account has been upgraded to {tier.capitalize()} Plan for {days} days!\n\n"
                f"Enjoy all features until {expires.strftime('%d %B %Y')}. Keep studying!"
            )

    except Exception as e:
        await send_whatsapp_message(phone, f"Upgrade error: {str(e)[:200]}")

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
            await send_whatsapp_message(phone, f"Student not found: {wax_id}")
            return

        student = result.data[0]

        supabase.table('students').update({
            'is_banned': True,
            'is_active': False,
            'ban_reason': reason,
        }).eq('id', student['id']).execute()

        await send_whatsapp_message(
            phone,
            f"Banned: {student['name']} ({wax_id})\nReason: {reason}"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"Ban error: {str(e)[:200]}")

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
            await send_whatsapp_message(phone, f"Student not found: {wax_id}")
            return

        student = result.data[0]

        supabase.table('students').update({
            'is_banned': False,
            'is_active': True,
            'ban_reason': None,
        }).eq('id', student['id']).execute()

        await send_whatsapp_message(
            phone,
            f"Unbanned: {student['name']} ({wax_id})\nAccount restored."
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"Unban error: {str(e)[:200]}")

async def admin_message_student(phone: str, args: str):
    """Sends a direct message to a specific student from admin."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        await send_whatsapp_message(
            phone,
            "Usage: ADMIN MSG [WAX-ID] [message]\n"
            "Example: ADMIN MSG WAX-A74892 Your issue is resolved!"
        )
        return

    wax_id = parts[0].upper()
    message = parts[1].strip()

    if not wax_id.startswith('WAX-'):
        wax_id = 'WAX-' + wax_id.replace('WAX', '')

    try:
        student_result = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()

        if not student_result.data:
            await send_whatsapp_message(phone, f"Student not found: {wax_id}")
            return

        student = student_result.data[0]

        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

        if not phone_result.data:
            await send_whatsapp_message(phone, f"{student['name']} has no WhatsApp linked.")
            return

        student_phone = phone_result.data[0]['platform_user_id']

        await send_whatsapp_message(
            student_phone,
            f"Message from WaxPrep:\n\n{message}"
        )

        await send_whatsapp_message(
            phone,
            f"Message sent to {student['name']} ({wax_id})"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"Message error: {str(e)[:200]}")

async def admin_broadcast(phone: str, args: str):
    """Sends a message to a filtered group of students."""
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
        await send_whatsapp_message(phone, "Message cannot be empty.")
        return

    await send_whatsapp_message(
        phone,
        f"Starting broadcast to {target}...\nThis may take a few minutes."
    )

    try:
        query = supabase.table('students').select('id, name, subscription_tier, target_exam, state, current_streak')\
            .eq('is_active', True)\
            .eq('is_banned', False)

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
                await send_whatsapp_message(phone, "STREAK target needs a number.")
                return
        else:
            label = "All active students"

        students = query.limit(2000).execute()

        if not students.data:
            await send_whatsapp_message(phone, f"No students found matching target: {target}")
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
                personalized = message_text.replace('{name}', name)

                await send_whatsapp_message(student_phone, personalized)
                sent += 1
                await asyncio.sleep(0.4)

            except Exception:
                failed += 1

        await send_whatsapp_message(
            phone,
            f"Broadcast Complete\n\n"
            f"Target: {label}\n"
            f"Total matched: {total:,}\n"
            f"Sent: {sent:,}\n"
            f"Failed: {failed}\n\n"
            f"Tip: Use {{name}} to personalize messages."
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"Broadcast error: {str(e)[:200]}")

async def admin_manage_codes(phone: str, args: str):
    """Manages promo codes."""
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

            lines = ["Active Promo Codes\n"]
            for code in result.data:
                uses = f"{code.get('current_uses', 0)}/{code.get('max_uses', 'unlimited')}"
                expires = str(code.get('expires_at', 'Never'))[:10]
                code_type = code.get('code_type', 'unknown')
                lines.append(
                    f"• {code['code']} ({code_type})\n"
                    f"  Uses: {uses} | Expires: {expires}"
                )

            await send_whatsapp_message(phone, '\n\n'.join(lines))

        except Exception as e:
            await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

    elif action == 'CREATE':
        if len(parts) < 5:
            await send_whatsapp_message(
                phone,
                "Usage: ADMIN CODE CREATE [code] [type] [value] [maxuses]\n\n"
                "Types: trial [days] / discount [percent] / upgrade [tier]\n\n"
                "Examples:\n"
                "ADMIN CODE CREATE LAGOS50 discount 50 100\n"
                "ADMIN CODE CREATE FREEWK trial 7 50"
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
                f"Promo Code Created\n\n"
                f"Code: {new_code}\n"
                f"Type: {code_type}\n"
                f"Value: {value}\n"
                f"Max Uses: {max_uses}\n\n"
                f"Students apply it by typing:\n"
                f"PROMO {new_code}"
            )

        except Exception as e:
            await send_whatsapp_message(phone, f"Code creation error: {str(e)[:200]}")

    elif action == 'DISABLE':
        if len(parts) < 2:
            await send_whatsapp_message(phone, "Usage: ADMIN CODE DISABLE [code]")
            return

        code_to_disable = parts[1].upper()
        try:
            supabase.table('promo_codes').update({'is_active': False})\
                .eq('code', code_to_disable).execute()
            await send_whatsapp_message(phone, f"Code {code_to_disable} has been disabled.")
        except Exception as e:
            await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

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
                await send_whatsapp_message(phone, "No pending question flags!")
                return

            lines = [f"Pending Question Flags ({len(result.data)} shown)\n"]
            for flag in result.data:
                q = flag.get('questions', {}) or {}
                flag_id = str(flag['id'])[:8]
                subject = q.get('subject', 'Unknown')
                question_text = (q.get('question_text', '') or '')[:100]
                reason = flag.get('reason', 'unspecified')

                lines.append(
                    f"• Flag ID: {flag_id}\n"
                    f"  Subject: {subject}\n"
                    f"  Reason: {reason}\n"
                    f"  Q: {question_text}...\n"
                    f"  ADMIN QUESTIONS APPROVE {flag_id}"
                )

            await send_whatsapp_message(phone, '\n\n'.join(lines))

        except Exception as e:
            await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

    elif sub_command == 'APPROVE':
        rest_parts = rest.strip().split()
        flag_id_prefix = rest_parts[1] if len(rest_parts) > 1 else ''
        if not flag_id_prefix:
            await send_whatsapp_message(phone, "Usage: ADMIN QUESTIONS APPROVE [flag-id-prefix]")
            return

        try:
            result = supabase.table('question_flags').select('id, question_id')\
                .ilike('id::text', f'{flag_id_prefix}%')\
                .limit(1).execute()

            if not result.data:
                await send_whatsapp_message(phone, f"Flag not found starting with: {flag_id_prefix}")
                return

            flag = result.data[0]
            supabase.table('question_flags').update({'status': 'reviewed'})\
                .eq('id', flag['id']).execute()

            await send_whatsapp_message(phone, "Flag marked as reviewed. Question kept active.")

        except Exception as e:
            await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

async def admin_online_count(phone: str):
    """Shows how many students are actively studying right now."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Africa/Lagos"))
    thirty_min_ago = (now - timedelta(minutes=30)).isoformat()
    one_hour_ago = (now - timedelta(hours=1)).isoformat()

    try:
        active_30 = supabase.table('conversations').select('student_id', count='exact')\
            .gte('last_message_at', thirty_min_ago)\
            .execute()

        active_1h = supabase.table('conversations').select('student_id', count='exact')\
            .gte('last_message_at', one_hour_ago)\
            .execute()

        await send_whatsapp_message(
            phone,
            f"Students Online Now\n\n"
            f"Active (last 30 min): {active_30.count or 0}\n"
            f"Active (last 1 hour): {active_1h.count or 0}\n\n"
            f"Time: {now.strftime('%H:%M WAT')}"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

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

        lines = [f"Top {len(result.data)} Students by Points\n"]
        medals = ['1st', '2nd', '3rd'] + [f'{i+1}th' for i in range(3, 20)]

        for i, s in enumerate(result.data):
            medal = medals[i] if i < len(medals) else ''
            tier = s.get('subscription_tier', 'free').upper()
            lines.append(
                f"{medal} {s['name']}\n"
                f"   {s['wax_id']} | {s.get('total_points', 0):,} pts | "
                f"{s.get('current_streak', 0)} day streak | {tier}"
            )

        await send_whatsapp_message(phone, '\n\n'.join(lines))

    except Exception as e:
        await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

async def admin_view_bugs(phone: str):
    """Shows recent unread bug reports."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    try:
        result = supabase.table('bug_reports').select('*')\
            .eq('status', 'new')\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()

        if not result.data:
            await send_whatsapp_message(phone, "No new bug reports.")
            return

        lines = [f"New Bug Reports ({len(result.data)})\n"]
        for bug in result.data:
            wax_id = bug.get('wax_id', 'Unknown')
            description = bug.get('description', '')[:150]
            created = str(bug.get('created_at', ''))[:16]
            lines.append(
                f"• From: {wax_id}\n"
                f"  Time: {created}\n"
                f"  Issue: {description}"
            )

        await send_whatsapp_message(phone, '\n\n'.join(lines))

        supabase.table('bug_reports').update({'status': 'seen'})\
            .eq('status', 'new').execute()

    except Exception as e:
        await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

async def admin_view_suggestions(phone: str):
    """Shows recent student suggestions."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    try:
        result = supabase.table('suggestions').select('*')\
            .eq('status', 'new')\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()

        if not result.data:
            await send_whatsapp_message(phone, "No new suggestions.")
            return

        lines = [f"Student Suggestions ({len(result.data)})\n"]
        for s in result.data:
            wax_id = s.get('wax_id', 'Unknown')
            suggestion = s.get('suggestion', '')[:200]
            created = str(s.get('created_at', ''))[:16]
            lines.append(
                f"• From: {wax_id}\n"
                f"  Time: {created}\n"
                f"  Idea: {suggestion}"
            )

        await send_whatsapp_message(phone, '\n\n'.join(lines))

        supabase.table('suggestions').update({'status': 'seen'})\
            .eq('status', 'new').execute()

    except Exception as e:
        await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

async def admin_payg_stats(phone: str):
    """Shows pay-as-you-go stats."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from helpers import nigeria_today
    today = nigeria_today()

    try:
        payg_today = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today)\
            .eq('status', 'completed')\
            .like('paystack_reference', 'PAYG-%')\
            .execute()

        total_payg = sum(p.get('amount_naira', 0) for p in (payg_today.data or []))

        await send_whatsapp_message(
            phone,
            f"Pay-As-You-Go Stats\n\n"
            f"PAYG Revenue Today: N{total_payg:,}\n"
            f"PAYG Transactions: {len(payg_today.data or [])}\n\n"
            f"Packages:\n"
            f"100 questions = N500\n"
            f"250 questions = N1,000\n"
            f"500 questions = N1,800"
        )

    except Exception as e:
        await send_whatsapp_message(phone, f"Error: {str(e)[:200]}")

async def _enable_student_mode(phone: str):
    """Switches admin to student testing mode."""
    from database.client import redis_client
    from whatsapp.sender import send_whatsapp_message
    redis_client.setex(f"admin_student_mode:{phone}", 3600, "1")

    await send_whatsapp_message(
        phone,
        "Student Mode ON (1 hour)\n\n"
        "You are now experiencing WaxPrep as a student.\n"
        "Type ADMIN ADMIN_MODE to go back."
    )

async def _enable_admin_mode(phone: str):
    """Switches back to admin mode."""
    from database.client import redis_client
    from whatsapp.sender import send_whatsapp_message
    redis_client.delete(f"admin_student_mode:{phone}")

    await send_whatsapp_message(
        phone,
        "Admin Mode restored. Type ADMIN HELP for commands."
    )

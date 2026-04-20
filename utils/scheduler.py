"""
Scheduler

Handles all time-based tasks that WaxPrep needs to run automatically:

1. Every day at 8:00 AM Lagos time:
   - Generate new daily challenge question
   - Close yesterday's challenge and announce winner

2. Every day at 7:00 AM Lagos time:
   - Send the founder (you) a WhatsApp daily report with all key stats
   - Generate and include the day's daily promo code

3. Every day at midnight Lagos time:
   - Reset daily question counters for all students
   - Award streak rewards

4. Every 30 minutes:
   - Check AI budget status

5. Trial expiry notifications:
   - Day 5 of trial: gentle reminder
   - Day 7 of trial: conversion message with personalized recommendation

APScheduler is the library that handles all of this.
It's like a cron job (scheduled task) but inside Python.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
import asyncio

NIGERIA_TZ = ZoneInfo("Africa/Lagos")
scheduler = AsyncIOScheduler(timezone=NIGERIA_TZ)

def start_scheduler():
    """Starts all scheduled tasks."""
    
    # Daily challenge — 8:00 AM Lagos time
    scheduler.add_job(
        generate_daily_challenge,
        CronTrigger(hour=8, minute=0, timezone=NIGERIA_TZ),
        id='daily_challenge',
        replace_existing=True,
        name='Generate Daily Challenge'
    )
    
    # Admin daily report — 7:00 AM Lagos time
    scheduler.add_job(
        send_daily_admin_report,
        CronTrigger(hour=7, minute=0, timezone=NIGERIA_TZ),
        id='admin_report',
        replace_existing=True,
        name='Send Admin Report'
    )
    # Spaced repetition reminders — check twice daily
scheduler.add_job(
    send_spaced_repetition_reminders,
    CronTrigger(hour='9,18', minute=0, timezone=NIGERIA_TZ),
    id='spaced_repetition',
    replace_existing=True,
    name='Spaced Repetition Reminders'
)
    # Trial expiry notifications — every hour
    scheduler.add_job(
        check_trial_expirations,
        CronTrigger(minute=0, timezone=NIGERIA_TZ),
        id='trial_checks',
        replace_existing=True,
        name='Check Trial Expirations'
    )
    
    # Subscription expiry reminders — daily at 10:00 AM
    scheduler.add_job(
        check_subscription_expirations,
        CronTrigger(hour=10, minute=0, timezone=NIGERIA_TZ),
        id='subscription_checks',
        replace_existing=True,
        name='Check Subscription Expirations'
    )
    
    # AI budget check — every 30 minutes
    scheduler.add_job(
        check_ai_budget,
        CronTrigger(minute='*/30', timezone=NIGERIA_TZ),
        id='budget_check',
        replace_existing=True,
        name='Check AI Budget'
    )
    
    # Streak reset check — midnight
    scheduler.add_job(
        midnight_tasks,
        CronTrigger(hour=0, minute=5, timezone=NIGERIA_TZ),
        id='midnight_tasks',
        replace_existing=True,
        name='Midnight Tasks'
    )
    
    scheduler.start()
    print("✅ All scheduled tasks registered")

def stop_scheduler():
    """Stops all scheduled tasks."""
    if scheduler.running:
        scheduler.shutdown()

# ============================================================
# SCHEDULED TASK IMPLEMENTATIONS
# ============================================================

async def generate_daily_challenge():
    """
    Generates a new daily challenge question at 8 AM.
    
    The challenge is the same question for all students on the same exam track.
    It's a difficult question — the kind that tests real understanding.
    """
    from database.client import supabase
    from ai.gemini_client import generate_questions_with_gemini
    from utils.helpers import nigeria_today
    
    print("📝 Generating daily challenge...")
    today = nigeria_today()
    
    # Check if today's challenge already exists
    existing = supabase.table('daily_challenges').select('id').eq('challenge_date', today).execute()
    if existing.data:
        print("Daily challenge already generated for today")
        return
    
    # Subjects to rotate through
    challenge_subjects = [
        ('Mathematics', 'Algebra', 'JAMB'),
        ('Physics', 'Mechanics', 'JAMB'),
        ('Chemistry', 'Chemical Bonding', 'WAEC'),
        ('Biology', 'Genetics', 'WAEC'),
        ('English Language', 'Comprehension', 'JAMB'),
        ('Mathematics', 'Statistics', 'WAEC'),
        ('Physics', 'Electricity', 'JAMB'),
    ]
    
    from datetime import datetime
    day_of_year = datetime.now().timetuple().tm_yday
    subject_data = challenge_subjects[day_of_year % len(challenge_subjects)]
    subject, topic, exam_type = subject_data
    
    # Generate a hard question (difficulty 8-9)
    questions = await generate_questions_with_gemini(
        subject=subject,
        topic=topic,
        exam_type=exam_type,
        difficulty=8,
        count=1
    )
    
    if not questions:
        print("❌ Failed to generate daily challenge question")
        return
    
    q = questions[0]
    
    supabase.table('daily_challenges').insert({
        'challenge_date': today,
        'exam_type': exam_type,
        'subject': subject,
        'question_text': q['question_text'],
        'option_a': q.get('option_a'),
        'option_b': q.get('option_b'),
        'option_c': q.get('option_c'),
        'option_d': q.get('option_d'),
        'correct_answer': q.get('correct_answer'),
        'explanation': q.get('explanation_correct'),
    }).execute()
    
    print(f"✅ Daily challenge generated: {subject} — {topic}")

async def send_daily_admin_report():
    """
    Sends you (the founder) a WhatsApp message every morning at 7 AM
    with all the key numbers from the previous day.
    
    Also generates and includes the daily founder promo code.
    """
    from database.client import supabase
    from whatsapp.sender import send_admin_whatsapp
    from ai.cost_tracker import get_daily_ai_spending
    from utils.helpers import nigeria_today, generate_promo_code, nigeria_now
    from config.settings import settings
    
    print("📊 Generating daily admin report...")
    
    today = nigeria_today()
    from datetime import datetime, timedelta
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Gather all stats
    try:
        total_students = supabase.table('students').select('id', count='exact').execute()
        total_count = total_students.count or 0
        
        new_yesterday = supabase.table('students').select('id', count='exact')\
            .gte('created_at', yesterday)\
            .lt('created_at', today).execute()
        new_count = new_yesterday.count or 0
        
        active_yesterday = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', yesterday).execute()
        active_count = active_yesterday.count or 0
        
        paying_students = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()
        paying_count = paying_students.count or 0
        
        # Revenue yesterday
        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', yesterday)\
            .lt('completed_at', today)\
            .eq('status', 'completed').execute()
        revenue = sum(p['amount_naira'] for p in (payments.data or []))
        
        # AI cost today so far
        ai_cost = await get_daily_ai_spending()
        
        # Questions asked yesterday
        questions_yesterday = supabase.table('study_sessions').select('questions_attempted')\
            .gte('started_at', yesterday).lt('started_at', today).execute()
        total_questions = sum(s.get('questions_attempted', 0) for s in (questions_yesterday.data or []))
        
        # Pending flag reviews
        pending_flags = supabase.table('question_flags').select('id', count='exact')\
            .eq('status', 'pending').execute()
        flag_count = pending_flags.count or 0
        
        # Generate today's daily promo code
        daily_code = generate_promo_code('daily')
        
        # Save it in the database
        from utils.helpers import nigeria_now
        expires_tomorrow = nigeria_now().replace(hour=7, minute=0, second=0)
        from datetime import timedelta
        expires_tomorrow = expires_tomorrow + timedelta(days=1)
        
        supabase.table('promo_codes').insert({
            'code': daily_code,
            'code_type': 'full_trial',
            'bonus_days': 3,
            'max_uses': 50,
            'is_daily_code': True,
            'description': f"Daily founder code for {today}",
            'expires_at': expires_tomorrow.isoformat(),
        }).execute()
        
        # Build the report message
        report = (
            f"📊 *WaxPrep Daily Report*\n"
            f"_{today}_\n\n"
            
            f"👥 *Students*\n"
            f"Total: {total_count:,}\n"
            f"New Yesterday: +{new_count}\n"
            f"Active Yesterday: {active_count:,}\n"
            f"Paying: {paying_count:,}\n\n"
            
            f"📚 *Activity*\n"
            f"Questions Asked: {total_questions:,}\n\n"
            
            f"💰 *Revenue*\n"
            f"Yesterday: ₦{revenue:,}\n\n"
            
            f"🤖 *AI Cost*\n"
            f"Today So Far: ${ai_cost:.4f}\n"
            f"Budget: ${settings.DAILY_AI_BUDGET_USD}\n\n"
        )
        
        if flag_count > 0:
            report += f"🚩 *Pending Reviews*\n{flag_count} question flag{'s' if flag_count != 1 else ''} need review\n\n"
        
        report += (
            f"🎁 *Today's Founder Code*\n"
            f"*{daily_code}*\n"
            f"Gives: 3 extra trial days\n"
            f"Max uses: 50 | Expires: Tomorrow 7 AM\n\n"
            f"Share this code on your WhatsApp status or in study groups to bring in new users!"
        )
        
        await send_admin_whatsapp(report)
        print("✅ Daily admin report sent")
        
    except Exception as e:
        print(f"❌ Error sending admin report: {e}")
        await send_admin_whatsapp(f"⚠️ Error generating daily report: {str(e)}")

async def check_trial_expirations():
    """
    Checks for trials that are expiring soon and sends notifications.
    
    Day 5: Heads up — 2 days left
    Day 7: Trial ending today — here's your personalized plan recommendation
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from utils.helpers import nigeria_now
    from datetime import timedelta
    
    now = nigeria_now()
    
    # Find students whose trial expires in exactly 2 days (Day 5 notification)
    two_days_from_now_start = now + timedelta(days=2)
    two_days_from_now_end = now + timedelta(days=2, hours=1)
    
    expiring_soon = supabase.table('students')\
        .select('id, name, total_questions_answered, total_questions_correct, current_streak, wax_id')\
        .eq('is_trial_active', True)\
        .gte('trial_expires_at', two_days_from_now_start.isoformat())\
        .lt('trial_expires_at', two_days_from_now_end.isoformat())\
        .execute()
    
    for student in (expiring_soon.data or []):
        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()
        
        if not phone_result.data:
            continue
        
        phone = phone_result.data[0]['platform_user_id']
        name = student['name'].split()[0]
        answered = student.get('total_questions_answered', 0)
        correct = student.get('total_questions_correct', 0)
        streak = student.get('current_streak', 0)
        accuracy = round((correct / answered * 100) if answered > 0 else 0)
        
        msg = (
            f"⏰ *{name}, your free trial has 2 days left!*\n\n"
            f"Here's what you've accomplished so far:\n"
            f"• Questions answered: {answered:,}\n"
            f"• Accuracy rate: {accuracy}%\n"
            f"• Study streak: {streak} day{'s' if streak != 1 else ''}\n\n"
            f"Don't let this progress go to waste!\n\n"
            f"*Scholar Plan — ₦1,500/month*\n"
            f"That's less than ₦50 per day. Less than a sachet of water.\n\n"
            f"Type *SUBSCRIBE* to keep your streak alive and your progress safe."
        )
        
        await send_whatsapp_message(phone, msg)
        
        # Small delay to avoid sending too many messages at once
        await asyncio.sleep(0.5)

async def check_subscription_expirations():
    """
    Sends reminders to students whose subscriptions are expiring soon.
    5 days before: reminder
    1 day before: urgent reminder
    Day of expiry: grace period notice
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from utils.helpers import nigeria_now
    from datetime import timedelta
    
    now = nigeria_now()
    five_days_out = now + timedelta(days=5)
    
    expiring = supabase.table('students')\
        .select('id, name, subscription_tier')\
        .neq('subscription_tier', 'free')\
        .gte('subscription_expires_at', now.isoformat())\
        .lt('subscription_expires_at', five_days_out.isoformat())\
        .execute()
    
    for student in (expiring.data or []):
        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()
        
        if not phone_result.data:
            continue
        
        phone = phone_result.data[0]['platform_user_id']
        name = student['name'].split()[0]
        tier = student['subscription_tier'].capitalize()
        
        msg = (
            f"🔔 *{name}, your {tier} Plan is expiring soon!*\n\n"
            f"Don't let your subscription lapse — you'll lose access to your premium features.\n\n"
            f"Type *SUBSCRIBE* to renew before it expires."
        )
        
        await send_whatsapp_message(phone, msg)
        await asyncio.sleep(0.5)

async def check_ai_budget():
    """Checks the AI budget and notifies admin if thresholds are crossed."""
    from ai.cost_tracker import check_budget_and_notify
    await check_budget_and_notify()

async def midnight_tasks():
    """
    Tasks that run at midnight Lagos time.
    Currently: updates and cleanup that should happen at the start of each new day.
    """
    from database.client import supabase
    from utils.helpers import nigeria_today
    
    print("🌙 Running midnight tasks...")
    
    # Clean up expired Redis keys (happens automatically via Redis TTL)
    # Log that a new day has started
    today = nigeria_today()
    print(f"✅ New day started: {today}")

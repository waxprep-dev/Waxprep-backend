"""
WaxPrep Scheduler

All time-based automatic tasks.
ALL imports are inside functions (lazy imports) to prevent startup errors.

Jobs registered:
1. 07:00 AM Lagos - Daily admin WhatsApp report + daily promo code
2. 08:00 AM Lagos - Generate new daily challenge question
3. 09:00 AM + 18:00 PM Lagos - Spaced repetition reminders
4. 10:00 AM Lagos - Subscription expiry reminders
5. Every hour - Trial expiry checks
6. Every 30 minutes - AI budget monitoring
7. 00:05 AM Lagos - Midnight cleanup tasks
8. Every Monday 08:30 AM - Weekly summary report
9. Every Sunday 20:00 PM - Weekly exam countdown motivational message
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

NIGERIA_TZ = ZoneInfo("Africa/Lagos")
scheduler = AsyncIOScheduler(timezone=NIGERIA_TZ)


def start_scheduler():
    """Registers and starts all scheduled jobs."""

    # Daily admin report - 7:00 AM Lagos
    scheduler.add_job(
        send_daily_admin_report,
        CronTrigger(hour=7, minute=0, timezone=NIGERIA_TZ),
        id='admin_report',
        replace_existing=True,
        name='Daily Admin Report'
    )

    # Daily challenge generation - 8:00 AM Lagos
    scheduler.add_job(
        generate_daily_challenge,
        CronTrigger(hour=8, minute=0, timezone=NIGERIA_TZ),
        id='daily_challenge',
        replace_existing=True,
        name='Generate Daily Challenge'
    )

    # Spaced repetition reminders - 9:00 AM and 6:00 PM Lagos
    scheduler.add_job(
        send_spaced_repetition_reminders,
        CronTrigger(hour='9,18', minute=0, timezone=NIGERIA_TZ),
        id='spaced_repetition',
        replace_existing=True,
        name='Spaced Repetition Reminders'
    )

    # Subscription expiry reminders - 10:00 AM Lagos
    scheduler.add_job(
        check_subscription_expirations,
        CronTrigger(hour=10, minute=0, timezone=NIGERIA_TZ),
        id='subscription_checks',
        replace_existing=True,
        name='Subscription Expiry Checks'
    )

    # Trial expiry checks - every hour
    scheduler.add_job(
        check_trial_expirations,
        CronTrigger(minute=0, timezone=NIGERIA_TZ),
        id='trial_checks',
        replace_existing=True,
        name='Trial Expiry Checks'
    )

    # AI budget monitoring - every 30 minutes
    scheduler.add_job(
        check_ai_budget,
        CronTrigger(minute='*/30', timezone=NIGERIA_TZ),
        id='budget_check',
        replace_existing=True,
        name='AI Budget Check'
    )

    # Midnight cleanup - 00:05 AM Lagos
    scheduler.add_job(
        midnight_tasks,
        CronTrigger(hour=0, minute=5, timezone=NIGERIA_TZ),
        id='midnight_tasks',
        replace_existing=True,
        name='Midnight Cleanup Tasks'
    )

    # Weekly summary - every Monday 8:30 AM Lagos
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week='mon', hour=8, minute=30, timezone=NIGERIA_TZ),
        id='weekly_report',
        replace_existing=True,
        name='Weekly Admin Report'
    )

    # Weekly exam countdown motivational message - every Sunday 8:00 PM Lagos
    scheduler.add_job(
        send_weekly_exam_countdown,
        CronTrigger(day_of_week='sun', hour=20, minute=0, timezone=NIGERIA_TZ),
        id='weekly_countdown',
        replace_existing=True,
        name='Weekly Exam Countdown'
    )

    scheduler.start()
    print("✅ All scheduled tasks registered")


def stop_scheduler():
    """Stops the scheduler cleanly on server shutdown."""
    if scheduler.running:
        scheduler.shutdown()


# ============================================================
# JOB IMPLEMENTATIONS
# All imports are INSIDE the functions (lazy imports).
# This prevents any startup import errors.
# ============================================================

async def send_daily_admin_report():
    """
    Sends the founder a comprehensive WhatsApp report every morning at 7 AM.
    Includes key stats, revenue, AI cost, and today's daily promo code.
    """
    from database.client import supabase, redis_client
    from whatsapp.sender import send_admin_whatsapp
    from config.settings import settings
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"📊 Generating daily admin report for {today}...")

    try:
        total_result = supabase.table('students').select('id', count='exact').execute()
        total_students = total_result.count or 0

        new_result = supabase.table('students').select('id', count='exact')\
            .gte('created_at', yesterday).lt('created_at', today).execute()
        new_yesterday = new_result.count or 0

        active_result = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', yesterday).execute()
        active_yesterday = active_result.count or 0

        paying_result = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()
        paying_count = paying_result.count or 0

        trial_result = supabase.table('students').select('id', count='exact')\
            .eq('is_trial_active', True).execute()
        on_trial = trial_result.count or 0

        payments_result = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', yesterday)\
            .lt('completed_at', today)\
            .eq('status', 'completed').execute()
        revenue_yesterday = sum(p.get('amount_naira', 0) for p in (payments_result.data or []))

        monthly_payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', (now - timedelta(days=30)).strftime('%Y-%m-%d'))\
            .eq('status', 'completed').execute()
        revenue_30_days = sum(p.get('amount_naira', 0) for p in (monthly_payments.data or []))

        ai_key = f"ai_cost:{today}"
        ai_cost_raw = redis_client.get(ai_key)
        ai_cost_today = float(ai_cost_raw) if ai_cost_raw else 0.0

        flags_result = supabase.table('question_flags').select('id', count='exact')\
            .eq('status', 'pending').execute()
        pending_flags = flags_result.count or 0

        questions_result = supabase.table('questions').select('id', count='exact').execute()
        total_questions = questions_result.count or 0

        # Generate today's founder promo code
        import random
        import string
        chars = string.ascii_uppercase + string.digits
        daily_code = "DAY" + ''.join(random.choices(chars, k=4))

        tomorrow = now + timedelta(days=1)
        expires_str = tomorrow.replace(hour=7, minute=0, second=0).isoformat()

        try:
            supabase.table('promo_codes').insert({
                'code': daily_code,
                'code_type': 'full_trial',
                'bonus_days': 3,
                'max_uses': 50,
                'is_daily_code': True,
                'description': f"Daily founder code for {today}",
                'expires_at': expires_str,
                'is_active': True,
            }).execute()
        except Exception as e:
            print(f"Daily code creation error: {e}")

        report = (
            f"📊 *WaxPrep Morning Report*\n"
            f"_{today}_\n\n"

            f"👥 *Students*\n"
            f"Total: {total_students:,}\n"
            f"New Yesterday: +{new_yesterday}\n"
            f"Active Yesterday: {active_yesterday:,}\n"
            f"Paying Now: {paying_count:,}\n"
            f"On Trial: {on_trial:,}\n\n"

            f"💰 *Revenue*\n"
            f"Yesterday: ₦{revenue_yesterday:,}\n"
            f"Last 30 Days: ₦{revenue_30_days:,}\n\n"

            f"🤖 *AI Cost Today*\n"
            f"Used: ${ai_cost_today:.4f} / ${settings.DAILY_AI_BUDGET_USD:.2f}\n\n"

            f"📚 *Content*\n"
            f"Questions in Bank: {total_questions:,}\n"
        )

        if pending_flags > 0:
            report += f"\n🚩 *Needs Review*\n{pending_flags} flagged question{'s' if pending_flags != 1 else ''}\n"

        report += (
            f"\n🎁 *Today's Founder Code*\n"
            f"*{daily_code}*\n"
            f"• 3 extra trial days\n"
            f"• Max 50 uses\n"
            f"• Expires tomorrow 7 AM\n\n"
            f"Share this on your WhatsApp status!\n\n"
            f"Type *ADMIN HELP* for admin commands."
        )

        await send_admin_whatsapp(report)
        print("✅ Daily admin report sent")

    except Exception as e:
        print(f"❌ Admin report error: {e}")
        try:
            from whatsapp.sender import send_admin_whatsapp as saa
            await saa(f"⚠️ Error generating daily report:\n{str(e)[:200]}")
        except Exception:
            pass


async def generate_daily_challenge():
    """Generates a new daily challenge question at 8 AM."""
    from database.client import supabase
    from ai.gemini_client import generate_questions_with_gemini
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    print(f"📝 Generating daily challenge for {today}...")

    existing = supabase.table('daily_challenges').select('id').eq('challenge_date', today).execute()
    if existing.data:
        print("Daily challenge already exists for today")
        return

    challenge_rotation = [
        ('Mathematics', 'Algebra and Equations', 'JAMB'),
        ('Physics', 'Mechanics and Motion', 'JAMB'),
        ('Chemistry', 'Chemical Bonding', 'WAEC'),
        ('Biology', 'Cell Biology and Genetics', 'WAEC'),
        ('English Language', 'Comprehension and Grammar', 'JAMB'),
        ('Mathematics', 'Statistics and Probability', 'WAEC'),
        ('Physics', 'Electricity and Magnetism', 'JAMB'),
    ]

    day_of_year = datetime.now().timetuple().tm_yday
    subject, topic, exam_type = challenge_rotation[day_of_year % len(challenge_rotation)]

    try:
        questions = await generate_questions_with_gemini(
            subject=subject,
            topic=topic,
            exam_type=exam_type,
            difficulty=8,
            count=1
        )

        if not questions:
            print("❌ Question generation returned empty — challenge not created")
            return

        q = questions[0]

        supabase.table('daily_challenges').insert({
            'challenge_date': today,
            'exam_type': exam_type,
            'subject': subject,
            'question_text': q.get('question_text', ''),
            'option_a': q.get('option_a', ''),
            'option_b': q.get('option_b', ''),
            'option_c': q.get('option_c', ''),
            'option_d': q.get('option_d', ''),
            'correct_answer': q.get('correct_answer', 'A'),
            'explanation': q.get('explanation_correct', ''),
            'total_attempts': 0,
            'total_correct': 0,
        }).execute()

        print(f"✅ Daily challenge created: {subject} — {topic}")

    except Exception as e:
        print(f"❌ Challenge generation error: {e}")


async def send_spaced_repetition_reminders():
    """
    Finds students whose topics are due for review and sends them a nudge.
    Only sends if the student hasn't studied yet today.
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = now.strftime('%Y-%m-%d')

    print("📚 Checking spaced repetition reminders...")

    try:
        due_reviews = supabase.table('mastery_scores')\
            .select('student_id, subject, topic, mastery_score')\
            .lte('next_review_at', now.isoformat())\
            .gte('mastery_score', 20)\
            .lt('mastery_score', 90)\
            .limit(300)\
            .execute()

        if not due_reviews.data:
            return

        student_topics: dict = {}
        for record in due_reviews.data:
            sid = record['student_id']
            if sid not in student_topics:
                student_topics[sid] = []
            student_topics[sid].append(record)

        sent_count = 0
        for student_id, topics in list(student_topics.items())[:100]:
            try:
                phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                    .eq('student_id', student_id).eq('platform', 'whatsapp').execute()

                if not phone_result.data:
                    continue

                phone = phone_result.data[0]['platform_user_id']

                student_result = supabase.table('students')\
                    .select('name, last_study_date, is_active')\
                    .eq('id', student_id).execute()

                if not student_result.data:
                    continue

                student = student_result.data[0]

                if not student.get('is_active'):
                    continue

                if student.get('last_study_date') == today:
                    continue

                name = student['name'].split()[0]
                topics_text = '\n'.join([
                    f"• {t['subject']}: {t['topic']} ({t['mastery_score']:.0f}% mastery)"
                    for t in topics[:3]
                ])

                msg = (
                    f"📚 *Time to Review, {name}!*\n\n"
                    f"These topics are ready for a quick revision — "
                    f"reviewing now locks them in before you forget:\n\n"
                    f"{topics_text}\n\n"
                    f"Type *REVISION* to start now! 🎯"
                )

                await send_whatsapp_message(phone, msg)
                sent_count += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Spaced repetition error for student {student_id}: {e}")
                continue

        print(f"✅ Sent {sent_count} spaced repetition reminders")

    except Exception as e:
        print(f"❌ Spaced repetition job error: {e}")


async def check_subscription_expirations():
    """Sends renewal reminders for subscriptions expiring in 5 days."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    five_days_out = (now + timedelta(days=5)).isoformat()

    print("🔔 Checking subscription expirations...")

    try:
        expiring = supabase.table('students')\
            .select('id, name, subscription_tier')\
            .neq('subscription_tier', 'free')\
            .gte('subscription_expires_at', now.isoformat())\
            .lt('subscription_expires_at', five_days_out)\
            .execute()

        sent = 0
        for student in (expiring.data or []):
            try:
                phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                    .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

                if not phone_result.data:
                    continue

                phone = phone_result.data[0]['platform_user_id']
                name = student['name'].split()[0]
                tier = student['subscription_tier'].capitalize()

                msg = (
                    f"🔔 *{name}, your {tier} Plan is expiring soon!*\n\n"
                    f"Don't lose your streak, your progress, or your premium features.\n\n"
                    f"Type *SUBSCRIBE* to renew before it expires. ✅"
                )

                await send_whatsapp_message(phone, msg)
                sent += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Subscription reminder error: {e}")

        print(f"✅ Sent {sent} subscription expiry reminders")

    except Exception as e:
        print(f"❌ Subscription check error: {e}")


async def check_trial_expirations():
    """Sends trial expiry warnings at Day 5 and Day 7."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))

    try:
        # Day 5 warning: trial expires in ~48 hours
        two_days_start = (now + timedelta(hours=47)).isoformat()
        two_days_end = (now + timedelta(hours=49)).isoformat()

        day5_students = supabase.table('students')\
            .select('id, name, total_questions_answered, total_questions_correct, current_streak')\
            .eq('is_trial_active', True)\
            .gte('trial_expires_at', two_days_start)\
            .lt('trial_expires_at', two_days_end)\
            .execute()

        for student in (day5_students.data or []):
            try:
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
                    f"⏰ *{name}, 2 days of free trial left!*\n\n"
                    f"Look what you've built in {settings.TRIAL_DURATION_DAYS - 2} days:\n"
                    f"✅ {answered:,} questions answered\n"
                    f"🎯 {accuracy}% accuracy rate\n"
                    f"🔥 {streak}-day streak\n\n"
                    f"Don't let this go to waste.\n\n"
                    f"*Scholar Plan — ₦1,500/month*\n"
                    f"That's ₦50/day. Less than one sachet of pure water.\n\n"
                    f"Type *SUBSCRIBE* to keep everything. ⚡"
                )

                await send_whatsapp_message(phone, msg)
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Day-5 trial reminder error: {e}")

        # Day 7: trial expires in the next hour
        one_hour_end = (now + timedelta(hours=1)).isoformat()

        day7_students = supabase.table('students')\
            .select('id, name, total_questions_answered, current_streak')\
            .eq('is_trial_active', True)\
            .gte('trial_expires_at', now.isoformat())\
            .lt('trial_expires_at', one_hour_end)\
            .execute()

        for student in (day7_students.data or []):
            try:
                phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                    .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

                if not phone_result.data:
                    continue

                phone = phone_result.data[0]['platform_user_id']
                name = student['name'].split()[0]

                msg = (
                    f"⚠️ *{name} — your trial ends in less than 1 hour!*\n\n"
                    f"After your trial, you'll keep:\n"
                    f"✅ Your WAX ID and progress\n"
                    f"✅ 20 free questions per day\n\n"
                    f"You'll lose:\n"
                    f"❌ Unlimited questions\n"
                    f"❌ Image analysis\n"
                    f"❌ Full mock exams\n"
                    f"❌ Personalized study plan\n\n"
                    f"Type *SUBSCRIBE* to keep everything right now! 🚀"
                )

                await send_whatsapp_message(phone, msg)
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Day-7 trial reminder error: {e}")

    except Exception as e:
        print(f"❌ Trial expiry check error: {e}")


async def check_ai_budget():
    """Checks AI spending and alerts admin if thresholds are crossed."""
    try:
        from ai.cost_tracker import check_budget_and_notify
        await check_budget_and_notify()
    except Exception as e:
        print(f"Budget check error: {e}")


async def midnight_tasks():
    """Tasks that run at midnight Lagos time."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    print(f"🌙 Midnight tasks running for {today}...")

    try:
        # Ensure today's daily challenge will be ready
        await generate_daily_challenge()
    except Exception as e:
        print(f"Midnight challenge prep error: {e}")


async def send_weekly_report():
    """Sends a comprehensive weekly report every Monday morning."""
    from database.client import supabase
    from whatsapp.sender import send_admin_whatsapp
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    today = now.strftime('%Y-%m-%d')

    print("📊 Generating weekly report...")

    try:
        total = supabase.table('students').select('id', count='exact').execute()

        new_this_week = supabase.table('students').select('id', count='exact')\
            .gte('created_at', week_ago).execute()

        active_this_week = supabase.table('students').select('id', count='exact')\
            .gte('last_study_date', week_ago).execute()

        paying = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()

        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', week_ago)\
            .eq('status', 'completed').execute()
        weekly_revenue = sum(p.get('amount_naira', 0) for p in (payments.data or []))

        # Retention: of students from 14 days ago, how many studied in past 7 days
        two_weeks_ago = (now - timedelta(days=14)).strftime('%Y-%m-%d')

        cohort = supabase.table('students').select('id', count='exact')\
            .gte('created_at', two_weeks_ago)\
            .lt('created_at', week_ago).execute()

        retained = supabase.table('students').select('id', count='exact')\
            .gte('created_at', two_weeks_ago)\
            .lt('created_at', week_ago)\
            .gte('last_study_date', week_ago).execute()

        cohort_count = cohort.count or 0
        retained_count = retained.count or 0
        retention_rate = round((retained_count / cohort_count * 100) if cohort_count > 0 else 0)

        report = (
            f"📊 *WaxPrep Weekly Report*\n"
            f"_Week ending {today}_\n\n"

            f"👥 *Students*\n"
            f"Total: {total.count or 0:,}\n"
            f"New This Week: +{new_this_week.count or 0}\n"
            f"Active This Week: {active_this_week.count or 0:,}\n"
            f"Paying Subscribers: {paying.count or 0:,}\n"
            f"7-Day Retention: {retention_rate}%\n\n"

            f"💰 *Revenue This Week*\n"
            f"₦{weekly_revenue:,}\n\n"

            f"_Build WaxPrep. Build Nigeria._ 🇳🇬"
        )

        await send_admin_whatsapp(report)
        print("✅ Weekly report sent")

    except Exception as e:
        print(f"❌ Weekly report error: {e}")


async def send_weekly_exam_countdown():
    """
    Every Sunday evening, sends exam countdown messages to students
    within 90 days of their exam. Motivational and data-driven.
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    ninety_days = (now + timedelta(days=90)).strftime('%Y-%m-%d')
    today = now.strftime('%Y-%m-%d')

    print("⏰ Sending weekly exam countdown messages...")

    try:
        upcoming_students = supabase.table('students')\
            .select('id, name, exam_date, target_exam, total_questions_answered, current_streak')\
            .gte('exam_date', today)\
            .lte('exam_date', ninety_days)\
            .eq('is_active', True)\
            .limit(500)\
            .execute()

        sent = 0
        for student in (upcoming_students.data or []):
            try:
                exam_date_str = student.get('exam_date')
                if not exam_date_str:
                    continue

                exam_dt = datetime.strptime(exam_date_str, '%Y-%m-%d')
                days_left = (exam_dt - now.replace(tzinfo=None)).days

                if days_left < 1:
                    continue

                phone_result = supabase.table('platform_sessions').select('platform_user_id')\
                    .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()

                if not phone_result.data:
                    continue

                phone = phone_result.data[0]['platform_user_id']
                name = student['name'].split()[0]
                exam = student.get('target_exam', 'your exam')
                answered = student.get('total_questions_answered', 0)
                streak = student.get('current_streak', 0)

                # Calculate daily average needed
                if days_left > 0 and answered > 0:
                    daily_avg = round(answered / max(1, (90 - days_left)))
                    needed_for_600 = max(0, 600 - answered)
                    days_to_reach = round(needed_for_600 / max(1, daily_avg)) if daily_avg > 0 else days_left
                else:
                    daily_avg = 0
                    needed_for_600 = 600

                msg = (
                    f"⏰ *{days_left} days to {exam}, {name}!*\n\n"
                    f"Your stats this week:\n"
                    f"📊 Total questions: {answered:,}\n"
                    f"🔥 Current streak: {streak} day{'s' if streak != 1 else ''}\n"
                    f"📅 Daily average: {daily_avg} questions\n\n"
                )

                if days_left <= 30:
                    msg += (
                        f"*FINAL MONTH.* Every day matters now.\n"
                        f"Aim for at least 30 questions per day.\n\n"
                        f"You have everything you need. Use it. 💪"
                    )
                elif days_left <= 60:
                    msg += (
                        f"*60 days left.* This is crunch time.\n"
                        f"Focus on your weak areas this week.\n\n"
                        f"Type *PLAN* to see your focus topics. 📚"
                    )
                else:
                    msg += (
                        f"*You have time — but not unlimited time.*\n"
                        f"The students who win in {days_left} days are studying now.\n\n"
                        f"Start today. Type anything to begin. 🚀"
                    )

                await send_whatsapp_message(phone, msg)
                sent += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Countdown message error for student: {e}")

        print(f"✅ Sent {sent} exam countdown messages")

    except Exception as e:
        print(f"❌ Weekly countdown error: {e}")

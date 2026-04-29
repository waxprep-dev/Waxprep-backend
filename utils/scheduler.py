"""
WaxPrep Scheduler

All time-based automatic tasks.
ALL imports are inside functions (lazy imports) to prevent startup errors.
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

NIGERIA_TZ = ZoneInfo("Africa/Lagos")
scheduler = AsyncIOScheduler(timezone=NIGERIA_TZ)


def start_scheduler():
    scheduler.add_job(
        send_daily_admin_report,
        CronTrigger(hour=7, minute=0, timezone=NIGERIA_TZ),
        id='admin_report', replace_existing=True, name='Daily Admin Report'
    )

    scheduler.add_job(
        generate_daily_challenge,
        CronTrigger(hour=8, minute=0, timezone=NIGERIA_TZ),
        id='daily_challenge', replace_existing=True, name='Generate Daily Challenge'
    )

    scheduler.add_job(
        send_spaced_repetition_reminders,
        CronTrigger(hour='9,18', minute=0, timezone=NIGERIA_TZ),
        id='spaced_repetition', replace_existing=True, name='Spaced Repetition Reminders'
    )

    scheduler.add_job(
        check_subscription_expirations,
        CronTrigger(hour=10, minute=0, timezone=NIGERIA_TZ),
        id='subscription_checks', replace_existing=True, name='Subscription Expiry Checks'
    )

    scheduler.add_job(
        check_trial_expirations,
        CronTrigger(minute=0, timezone=NIGERIA_TZ),
        id='trial_checks', replace_existing=True, name='Trial Expiry Checks'
    )

    scheduler.add_job(
        check_ai_budget,
        CronTrigger(minute='*/30', timezone=NIGERIA_TZ),
        id='budget_check', replace_existing=True, name='AI Budget Check'
    )

    scheduler.add_job(
        midnight_tasks,
        CronTrigger(hour=0, minute=5, timezone=NIGERIA_TZ),
        id='midnight_tasks', replace_existing=True, name='Midnight Cleanup Tasks'
    )

    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week='mon', hour=8, minute=30, timezone=NIGERIA_TZ),
        id='weekly_report', replace_existing=True, name='Weekly Admin Report'
    )

    scheduler.add_job(
        send_weekly_exam_countdown,
        CronTrigger(day_of_week='sun', hour=20, minute=0, timezone=NIGERIA_TZ),
        id='weekly_countdown', replace_existing=True, name='Weekly Exam Countdown'
    )

    scheduler.start()
    print("All scheduled tasks registered")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()


async def send_daily_admin_report():
    from database.client import supabase, redis_client
    from whatsapp.sender import send_admin_whatsapp
    from config.settings import settings
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = now.strftime('%Y-%m-%d')
    yesterday = (now - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"Generating daily admin report for {today}...")

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
            f"WaxPrep Morning Report\n"
            f"{today}\n\n"

            f"Students\n"
            f"Total: {total_students:,}\n"
            f"New Yesterday: +{new_yesterday}\n"
            f"Active Yesterday: {active_yesterday:,}\n"
            f"Paying Now: {paying_count:,}\n"
            f"On Trial: {on_trial:,}\n\n"

            f"Revenue\n"
            f"Yesterday: N{revenue_yesterday:,}\n"
            f"Last 30 Days: N{revenue_30_days:,}\n\n"

            f"AI Cost Today\n"
            f"Used: ${ai_cost_today:.4f} / ${settings.DAILY_AI_BUDGET_USD:.2f}\n\n"
        )

        if pending_flags > 0:
            report += f"Needs Review\n{pending_flags} flagged question{'s' if pending_flags != 1 else ''}\n\n"

        report += (
            f"Today's Founder Code\n"
            f"{daily_code}\n"
            f"3 extra trial days | Max 50 uses | Expires tomorrow 7 AM\n\n"
            f"Share on your WhatsApp status!\n\n"
            f"Type ADMIN HELP for admin commands."
        )

        await send_admin_whatsapp(report)
        print("Daily admin report sent")

    except Exception as e:
        print(f"Admin report error: {e}")
        try:
            await send_admin_whatsapp(f"Error generating daily report:\n{str(e)[:200]}")
        except Exception:
            pass


async def generate_daily_challenge():
    from database.client import supabase
    from ai.gemini_client import generate_questions_with_gemini
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    print(f"Generating daily challenge for {today}...")

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
            subject=subject, topic=topic, exam_type=exam_type,
            difficulty=8, count=1
        )

        if not questions:
            print("Question generation returned empty — challenge not created")
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

        print(f"Daily challenge created: {subject} — {topic}")

    except Exception as e:
        print(f"Challenge generation error: {e}")


async def send_spaced_repetition_reminders():
    """
    Finds students whose topics are due for review and sends personal nudges.
    Only sends if the student has not studied today yet.
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = now.strftime('%Y-%m-%d')

    print("Checking spaced repetition reminders...")

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

                # Do not remind students who already studied today
                if student.get('last_study_date') == today:
                    continue

                name = student['name'].split()[0]
                top_topic = topics[0]
                subject = top_topic['subject']
                topic_name = top_topic['topic']
                mastery = round(top_topic.get('mastery_score', 0))

                # Make the reminder feel personal, not robotic
                messages = [
                    (
                        f"Hey {name}! Quick one — you studied {topic_name} in {subject} "
                        f"a few days ago and now is actually the *best time* to review it. "
                        f"That is how spaced repetition works — your brain is ready to lock it in permanently. "
                        f"Just send me a message and we will pick up from there."
                    ),
                    (
                        f"{name}, your brain has been processing {topic_name} since you last studied it. "
                        f"Right now is the optimal time for a quick review — you are at {mastery}% mastery "
                        f"and one session could push that over 80%. "
                        f"Want to try a few questions on it?"
                    ),
                    (
                        f"Psst, {name}. {topic_name} ({subject}) is calling you. "
                        f"You studied it {3 if mastery > 60 else 2} days ago, "
                        f"and if you review it now it will stick for weeks. "
                        f"5 minutes is all it takes."
                    ),
                ]

                import random
                msg = random.choice(messages)

                await send_whatsapp_message(phone, msg)
                sent_count += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Spaced repetition error for student {student_id}: {e}")
                continue

        print(f"Sent {sent_count} spaced repetition reminders")

    except Exception as e:
        print(f"Spaced repetition job error: {e}")


async def check_subscription_expirations():
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings
    from helpers import format_naira
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    five_days_out = (now + timedelta(days=5)).isoformat()

    try:
        expiring = supabase.table('students')\
            .select('id, name, subscription_tier')\
            .neq('subscription_tier', 'free')\
            .gte('subscription_expires_at', now.isoformat())\
            .lt('subscription_expires_at', five_days_out)\
            .execute()

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
                    f"Hey {name}, your {tier} Plan expires in less than 5 days.\n\n"
                    f"Renew now and you will not miss a single day with Wax.\n\n"
                    f"Type *SUBSCRIBE* to renew."
                )

                await send_whatsapp_message(phone, msg)
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Subscription reminder error: {e}")

    except Exception as e:
        print(f"Subscription check error: {e}")


async def check_trial_expirations():
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings
    from helpers import format_naira
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
                    f"Hey {name}, 2 days of your free trial left.\n\n"
                    f"Look what you have built in {settings.TRIAL_DURATION_DAYS - 2} days:\n"
                    f"{answered:,} conversations with Wax\n"
                    f"{accuracy}% accuracy\n"
                    f"{streak}-day streak\n\n"
                    f"Do not let this go.\n\n"
                    f"*Scholar Plan — {format_naira(settings.SCHOLAR_MONTHLY)}/month*\n"
                    f"That is {format_naira(settings.SCHOLAR_MONTHLY // 30)}/day. "
                    f"Less than a sachet of pure water.\n\n"
                    f"Type *SUBSCRIBE* to keep everything."
                )

                await send_whatsapp_message(phone, msg)
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Day-5 trial reminder error: {e}")

        # Day 7: expires in the next hour
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
                    f"{name} — your trial ends in less than 1 hour.\n\n"
                    f"After your trial you keep:\n"
                    f"Your WAX ID and all your progress\n"
                    f"25 free conversations with Wax per day\n\n"
                    f"You lose:\n"
                    f"Unlimited conversations\n"
                    f"Voice note learning\n"
                    f"Textbook photo analysis\n"
                    f"Full personalized coaching\n\n"
                    f"Type *SUBSCRIBE* right now to keep everything."
                )

                await send_whatsapp_message(phone, msg)
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Day-7 trial reminder error: {e}")

    except Exception as e:
        print(f"Trial expiry check error: {e}")


async def check_ai_budget():
    try:
        from ai.cost_tracker import check_budget_and_notify
        await check_budget_and_notify()
    except Exception as e:
        print(f"Budget check error: {e}")


async def midnight_tasks():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    print(f"Midnight tasks running for {today}...")

    try:
        await generate_daily_challenge()
    except Exception as e:
        print(f"Midnight challenge prep error: {e}")


async def send_weekly_report():
    from database.client import supabase
    from whatsapp.sender import send_admin_whatsapp
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    today = now.strftime('%Y-%m-%d')

    try:
        total = supabase.table('students').select('id', count='exact').execute()
        new_this_week = supabase.table('students').select('id', count='exact')\
            .gte('created_at', week_ago).execute()
        active_this_week = supabase.table('students').select('id', count='exact')\
            .gte('last_study_date', week_ago).execute()
        paying = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()

        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', week_ago).eq('status', 'completed').execute()
        weekly_revenue = sum(p.get('amount_naira', 0) for p in (payments.data or []))

        two_weeks_ago = (now - timedelta(days=14)).strftime('%Y-%m-%d')
        cohort = supabase.table('students').select('id', count='exact')\
            .gte('created_at', two_weeks_ago).lt('created_at', week_ago).execute()
        retained = supabase.table('students').select('id', count='exact')\
            .gte('created_at', two_weeks_ago).lt('created_at', week_ago)\
            .gte('last_study_date', week_ago).execute()

        cohort_count = cohort.count or 0
        retained_count = retained.count or 0
        retention_rate = round((retained_count / cohort_count * 100) if cohort_count > 0 else 0)

        report = (
            f"WaxPrep Weekly Report\n"
            f"Week ending {today}\n\n"
            f"Students\n"
            f"Total: {total.count or 0:,}\n"
            f"New This Week: +{new_this_week.count or 0}\n"
            f"Active This Week: {active_this_week.count or 0:,}\n"
            f"Paying Subscribers: {paying.count or 0:,}\n"
            f"7-Day Retention: {retention_rate}%\n\n"
            f"Revenue This Week\n"
            f"N{weekly_revenue:,}\n\n"
            f"Build WaxPrep. Build Nigeria."
        )

        await send_admin_whatsapp(report)
        print("Weekly report sent")

    except Exception as e:
        print(f"Weekly report error: {e}")


async def send_weekly_exam_countdown():
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    ninety_days = (now + timedelta(days=90)).strftime('%Y-%m-%d')
    today = now.strftime('%Y-%m-%d')

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

                if days_left <= 30:
                    msg = (
                        f"{days_left} days to {exam}, {name}.\n\n"
                        f"Final month. This is where it counts.\n\n"
                        f"You have answered {answered:,} questions total. "
                        f"Your streak is {streak} day{'s' if streak != 1 else ''}.\n\n"
                        f"Aim for 30 questions every single day from here. "
                        f"That is how you walk into that exam confident."
                    )
                elif days_left <= 60:
                    msg = (
                        f"{days_left} days to {exam}, {name}.\n\n"
                        f"Two months. Enough time to completely transform your preparation.\n\n"
                        f"Your {streak}-day streak shows you are serious. "
                        f"This week, focus on your weakest topics. "
                        f"Send me a message and I will tell you exactly what to work on."
                    )
                else:
                    msg = (
                        f"{days_left} days to {exam}, {name}.\n\n"
                        f"You have more time than most students think they need — "
                        f"but the ones who win start now and stay consistent.\n\n"
                        f"You have already put in {answered:,} interactions with Wax. "
                        f"Keep that energy going every day."
                    )

                await send_whatsapp_message(phone, msg)
                sent += 1
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"Countdown message error: {e}")

        print(f"Sent {sent} exam countdown messages")

    except Exception as e:
        print(f"Weekly countdown error: {e}")

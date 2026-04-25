"""
Centralized Notification System

Handles all real-time notifications:
- Admin notifications for new student registrations
- Admin alerts for payments
- Admin alerts for bugs and system events
- Student notifications (upgrades, achievements, warnings)

All notification sends are fire-and-forget to avoid slowing down
the main request flow.
"""

import asyncio
from config.settings import settings


async def notify_admin_new_student(student: dict, phone: str):
    """
    Sends admin an immediate WhatsApp notification when a new student registers.
    Called at the end of onboarding completion.
    """
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    now = nigeria_now()
    name = student.get('name', 'Unknown')
    wax_id = student.get('wax_id', 'Unknown')
    target_exam = student.get('target_exam', 'Unknown')
    subjects = ', '.join(student.get('subjects', [])[:4]) or 'None set'
    state = student.get('state', 'Unknown')
    class_level = student.get('class_level', 'Unknown')
    exam_date = student.get('exam_date', 'Not set')
    referred_by = student.get('referred_by_wax_id', None)

    try:
        from database.client import supabase
        total_result = supabase.table('students').select('id', count='exact').execute()
        total_students = total_result.count or 0
    except Exception:
        total_students = 0

    referral_note = f"\nReferred By: {referred_by}" if referred_by else ""

    message = (
        f"New Student Registered!\n\n"
        f"Name: {name}\n"
        f"WAX ID: {wax_id}\n"
        f"Phone: +{phone}\n"
        f"State: {state}\n"
        f"Class: {class_level}\n"
        f"Exam: {target_exam}\n"
        f"Subjects: {subjects}\n"
        f"Exam Date: {exam_date}"
        f"{referral_note}\n\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}\n"
        f"Total Students Now: {total_students:,}\n\n"
        f"Reply: ADMIN MSG {wax_id} [message] to contact them directly."
    )

    try:
        await send_admin_whatsapp(message)
    except Exception as e:
        print(f"New student notification error: {e}")


async def notify_admin_payment(student_name: str, wax_id: str,
                                tier: str, billing_period: str,
                                amount_naira: int, reference: str):
    """Notifies admin of a successful payment."""
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now, format_naira

    now = nigeria_now()
    message = (
        f"Payment Received!\n\n"
        f"Student: {student_name} ({wax_id})\n"
        f"Plan: {tier.capitalize()} {billing_period.capitalize()}\n"
        f"Amount: {format_naira(amount_naira)}\n"
        f"Reference: {reference}\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}"
    )

    try:
        await send_admin_whatsapp(message)
    except Exception as e:
        print(f"Payment notification error: {e}")


async def notify_admin_bug(student_name: str, wax_id: str, description: str):
    """Forwards a bug report to admin immediately."""
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    now = nigeria_now()
    message = (
        f"Bug Report\n\n"
        f"Student: {student_name} ({wax_id})\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}\n\n"
        f"Issue:\n{description}\n\n"
        f"Reply: ADMIN MSG {wax_id} [your response]"
    )

    try:
        await send_admin_whatsapp(message)
    except Exception as e:
        print(f"Bug notification error: {e}")


async def notify_admin_suggestion(student_name: str, wax_id: str, suggestion: str):
    """Forwards a student suggestion to admin."""
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    now = nigeria_now()
    message = (
        f"Student Suggestion\n\n"
        f"Student: {student_name} ({wax_id})\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}\n\n"
        f"Idea:\n{suggestion}"
    )

    try:
        await send_admin_whatsapp(message)
    except Exception as e:
        print(f"Suggestion notification error: {e}")


async def notify_admin_alert(alert_type: str, details: str):
    """Generic admin alert."""
    from whatsapp.sender import send_admin_whatsapp

    labels = {
        'budget_warning': 'AI Budget Warning',
        'budget_exceeded': 'AI Budget EXCEEDED',
        'system_error': 'System Error',
        'milestone': 'Platform Milestone',
        'fraud': 'FRAUD ALERT',
        'question_quality': 'Question Quality Issue',
    }

    label = labels.get(alert_type, alert_type.upper())
    message = f"WaxPrep Alert: {label}\n\n{details}"

    try:
        await send_admin_whatsapp(message)
    except Exception as e:
        print(f"Alert notification error: {e}")


async def notify_student_upgrade(phone: str, student_name: str,
                                  tier: str, expires_str: str):
    """Sends a celebration message to a student after upgrade."""
    from whatsapp.sender import send_whatsapp_message

    first_name = student_name.split()[0]
    message = (
        f"You're in, {first_name}!\n\n"
        f"Welcome to {tier.capitalize()} Plan!\n"
        f"Active until {expires_str}.\n\n"
        f"Everything is unlocked. Go crush it!\n\n"
        f"Type any question to start studying right now."
    )

    try:
        await send_whatsapp_message(phone, message)
    except Exception as e:
        print(f"Student upgrade notification error: {e}")


async def notify_student_trial_ending(phone: str, student_name: str, days_left: int):
    """Warns a student their trial is ending."""
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings
    from helpers import format_naira

    first_name = student_name.split()[0]
    message = (
        f"Hey {first_name}, your free trial ends in {days_left} day{'s' if days_left != 1 else ''}!\n\n"
        f"Scholar Plan is {format_naira(settings.SCHOLAR_MONTHLY)}/month.\n"
        f"That is less than one plate of food a day.\n\n"
        f"Type SUBSCRIBE to keep your full access. Do not let it lapse!"
    )

    try:
        await send_whatsapp_message(phone, message)
    except Exception as e:
        print(f"Trial ending notification error: {e}")


def fire_and_forget(coro):
    """
    Schedules a coroutine to run in the background without awaiting it.
    Used to send notifications without slowing down the main response flow.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        print(f"fire_and_forget error: {e}")

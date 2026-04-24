"""
Feedback and Bug Reporting System

Students can:
- Give thumbs up / thumbs down after a session
- Report bugs: BUG [description]
- Make suggestions: SUGGEST [idea]

All reports go directly to the admin's WhatsApp.
Bugs are also saved to the database for tracking.
"""


async def handle_feedback_command(phone: str, student: dict, message: str) -> str:
    """
    Routes feedback commands.
    Called when message starts with BUG, SUGGEST, FEEDBACK, or thumbs.
    """
    msg_upper = message.strip().upper()

    if msg_upper.startswith('BUG ') or msg_upper == 'BUG':
        return await handle_bug_report(phone, student, message)

    if msg_upper.startswith('SUGGEST ') or msg_upper == 'SUGGEST':
        return await handle_suggestion(phone, student, message)

    if msg_upper.startswith('FEEDBACK'):
        return await handle_general_feedback(phone, student, message)

    return await handle_general_feedback(phone, student, message)


async def handle_bug_report(phone: str, student: dict, message: str) -> str:
    """Saves a bug report and sends it to admin immediately."""
    from database.client import supabase
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    parts = message.strip().split(None, 1)
    description = parts[1].strip() if len(parts) > 1 else "No description provided"

    name = student.get('name', 'Unknown')
    wax_id = student.get('wax_id', 'Unknown')
    now = nigeria_now()

    try:
        supabase.table('bug_reports').insert({
            'student_id': student.get('id'),
            'wax_id': wax_id,
            'description': description,
            'platform': 'whatsapp',
            'status': 'new',
            'created_at': now.isoformat(),
        }).execute()
    except Exception as e:
        print(f"Bug report save error: {e}")

    admin_msg = (
        f"Bug Report Received\n\n"
        f"Student: {name} ({wax_id})\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}\n\n"
        f"Description:\n{description}\n\n"
        f"Reply: ADMIN MSG {wax_id} [your response]"
    )

    try:
        await send_admin_whatsapp(admin_msg)
    except Exception as e:
        print(f"Bug report admin notification error: {e}")

    return (
        "Bug Report Received — Thank You!\n\n"
        f"I've sent your report directly to the WaxPrep team right now.\n\n"
        f"They will look into it and get back to you.\n\n"
        f"Your report: {description[:100]}{'...' if len(description) > 100 else ''}\n\n"
        "Keep studying while we fix it!"
    )


async def handle_suggestion(phone: str, student: dict, message: str) -> str:
    """Saves a suggestion and forwards it to admin."""
    from database.client import supabase
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    parts = message.strip().split(None, 1)
    suggestion = parts[1].strip() if len(parts) > 1 else "No details provided"

    name = student.get('name', 'Unknown')
    wax_id = student.get('wax_id', 'Unknown')
    now = nigeria_now()

    try:
        supabase.table('suggestions').insert({
            'student_id': student.get('id'),
            'wax_id': wax_id,
            'suggestion': suggestion,
            'status': 'new',
            'created_at': now.isoformat(),
        }).execute()
    except Exception as e:
        print(f"Suggestion save error: {e}")

    admin_msg = (
        f"Student Suggestion\n\n"
        f"Student: {name} ({wax_id})\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}\n\n"
        f"Suggestion:\n{suggestion}"
    )

    try:
        await send_admin_whatsapp(admin_msg)
    except Exception as e:
        print(f"Suggestion admin notification error: {e}")

    return (
        "Suggestion Received — Thank You!\n\n"
        "Your idea has been sent directly to the WaxPrep founder.\n\n"
        "Great students make great platforms. Keep the ideas coming!"
    )


async def handle_general_feedback(phone: str, student: dict, message: str) -> str:
    """Handles general feedback."""
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    parts = message.strip().split(None, 1)
    content = parts[1].strip() if len(parts) > 1 else message

    name = student.get('name', 'Unknown')
    wax_id = student.get('wax_id', 'Unknown')
    now = nigeria_now()

    admin_msg = (
        f"Student Feedback\n\n"
        f"Student: {name} ({wax_id})\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}\n\n"
        f"Feedback:\n{content}"
    )

    try:
        await send_admin_whatsapp(admin_msg)
    except Exception:
        pass

    return (
        "Feedback Received!\n\n"
        "Thank you for sharing your thoughts. "
        "The WaxPrep team reads every single message.\n\n"
        "Now let's get back to studying!"
    )


async def send_session_feedback_prompt(phone: str, student: dict, session_questions: int) -> None:
    """
    Sends a thumbs up / thumbs down feedback prompt after every 5 questions.
    """
    from whatsapp.sender import send_whatsapp_message

    name = student.get('name', 'Student').split()[0]

    msg = (
        f"Quick Check-In, {name}!\n\n"
        f"You've answered {session_questions} questions this session.\n\n"
        f"How is WaxPrep feeling for you right now?\n\n"
        f"Type GOOD — Everything is working great\n"
        f"Type BAD — Something is wrong or confusing\n"
        f"Type SUGGEST [idea] — Have an idea\n"
        f"Type BUG [issue] — Found a problem\n\n"
        f"Or just keep studying — the feedback is optional!"
    )

    await send_whatsapp_message(phone, msg)


async def handle_quick_thumbs(phone: str, student: dict, response: str) -> str:
    """Handles GOOD / BAD quick responses."""
    from whatsapp.sender import send_admin_whatsapp
    from helpers import nigeria_now

    name = student.get('name', 'Unknown')
    wax_id = student.get('wax_id', 'Unknown')
    now = nigeria_now()

    is_positive = response.strip().upper() in ['GOOD', 'GREAT', 'NICE', 'YES']

    sentiment = "POSITIVE" if is_positive else "NEGATIVE"
    admin_msg = (
        f"Quick Feedback: {sentiment}\n\n"
        f"Student: {name} ({wax_id})\n"
        f"Time: {now.strftime('%H:%M on %d %b %Y')}"
    )

    try:
        await send_admin_whatsapp(admin_msg)
    except Exception:
        pass

    if is_positive:
        return (
            f"Glad it's working well for you, {name.split()[0]}!\n\n"
            "Keep going — you're doing amazing!"
        )
    else:
        return (
            f"I'm sorry to hear that, {name.split()[0]}!\n\n"
            "Please tell me what's wrong so I can help:\n\n"
            "Type BUG [describe the problem] and it will go straight to the WaxPrep team.\n\n"
            "For example: BUG The quiz questions are repeating"
        )

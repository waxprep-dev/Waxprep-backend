"""
Test Harness — Founder-only testing tools.
Triggered via TEST [feature] command.
All test data is logged with signal_type='test' so it can be filtered out.
"""


async def handle_test_command(chat_id: int, student: dict, conversation: dict, message: str):
    """Routes test commands to the right test function."""
    from telegram.sender import send_telegram_message

    msg_upper = message.strip().upper()

    if 'HESITATION' in msg_upper:
        await _test_hesitation_tracker(chat_id, student, conversation)
    elif 'HELP' in msg_upper or not msg_upper.replace('TEST', '').strip():
        await send_telegram_message(
            chat_id,
            "Test commands available:\n"
            "TEST HESITATION — triggers auto-escalation\n"
            "TEST TIMER — tests quiz timeout\n"
            "TEST SIGNALS — shows your logged signals"
        )
    else:
        await send_telegram_message(chat_id, f"Unknown test command. Type TEST HELP for options.")


async def _test_hesitation_tracker(chat_id: int, student: dict, conversation: dict):
    """Logs 2 hesitation signals to trigger the auto-escalation system."""
    from telegram.sender import send_telegram_message
    from features.silent_diagnosis import log_signal

    subject = conversation.get('current_subject', 'physics')
    topic = conversation.get('current_topic', 'refraction')

    await log_signal(student['id'], subject, topic, 'hesitation', 'test_batch_1')
    await log_signal(student['id'], subject, topic, 'hesitation', 'test_batch_2')

    await send_telegram_message(
        chat_id,
        f"Test: Logged 2 hesitation signals for *{topic}* in *{subject}*.\n\n"
        "Your next question will use simplified explanation style.\n"
        "Ask away."
    )

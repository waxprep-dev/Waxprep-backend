"""
Mock Exam Flow — Coming in the WaxPrep App

Full timed mock exams (100 questions, JAMB simulation, detailed analysis)
are being built into the native WaxPrep app for the best experience.

On WhatsApp, Wax can run practice sessions on any subject naturally
through conversation. Just ask.
"""

from whatsapp.sender import send_whatsapp_message


async def start_mock_exam(phone: str, student: dict, conversation: dict,
                           exam_type: str = None, subjects: list = None,
                           num_questions: int = None):
    """
    Full mock exams are coming in the WaxPrep app.
    For now, redirect to natural practice session with Wax.
    """
    name = student.get('name', 'Student').split()[0]
    target_exam = student.get('target_exam', 'JAMB')
    student_subjects = student.get('subjects', ['Mathematics', 'English Language'])
    subjects_display = ', '.join(student_subjects[:3]) if student_subjects else 'your subjects'

    await send_whatsapp_message(
        phone,
        f"Full mock exams are coming in the WaxPrep app very soon, {name}!\n\n"
        f"The app will give you a proper {target_exam} simulation experience — "
        f"timed, all questions, complete score analysis.\n\n"
        f"*Right now on WhatsApp*, I can put you through an intensive practice session "
        f"on {subjects_display}. It will feel like revision with your toughest teacher.\n\n"
        f"Want to do that? Just say which subject and I will start."
    )


async def handle_exam_answer(phone: str, student: dict, conversation: dict, answer: str):
    """Placeholder — redirects to natural conversation."""
    from database.conversations import update_conversation_state
    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'current_mode': 'default',
        'conversation_state': {}
    })
    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(
        phone,
        f"Let us continue in conversation mode, {name}. "
        "Ask me any question or tell me what subject you want to practice."
    )


async def handle_exam_setup_choice(phone: str, student: dict, conversation: dict,
                                    message: str, state: dict):
    await start_mock_exam(phone, student, conversation)

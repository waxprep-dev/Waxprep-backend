"""
Telegram Message Handler
Reuses the same AI brain, database, and flows as WhatsApp.
Messages arrive via webhook, are normalised, and then follow the same paths.
"""

import asyncio
from config.settings import settings
from helpers import sanitize_input


async def process_telegram_update(update: dict) -> None:
    """
    Handles a single Telegram update (message or callback query).
    """
    from telegram.sender import send_telegram_message

    # 1. Callback query (inline button press)
    callback_query = update.get('callback_query')
    if callback_query:
        await _handle_callback_query(callback_query)
        return

    # 2. Text message
    message_data = update.get('message')
    if not message_data:
        return

    chat = message_data.get('chat', {})
    chat_id = chat.get('id')
    if not chat_id:
        return

    user = message_data.get('from', {})
    name = user.get('first_name', 'Student')
    text = message_data.get('text', '')

    if text:
        text = sanitize_input(text)

    if not text:
        return

    try:
        # Get the student
        from database.students import get_student_by_platform_id
        student = await get_student_by_platform_id('telegram', str(chat_id))
    except Exception as e:
        print(f"Telegram student lookup error: {e}")
        await send_telegram_message(chat_id, "Something went wrong. Please try again.")
        return

    # Route the message using the same core handler logic.
    # We'll build a small wrapper that calls the existing route_message,
    # but adapted for Telegram's chat_id instead of phone.
    from whatsapp.handler import route_message as whatsapp_route_message
    try:
        # We can reuse the same function, passing chat_id as 'phone'.
        # The function needs a phone-like identifier; we'll use "telegram:" prefix.
        await whatsapp_route_message(
            phone=f"telegram:{chat_id}",
            name=name,
            message=text,
            message_type='text',
            media_id=None
        )
    except Exception as e:
        print(f"Telegram route error: {e}")
        await send_telegram_message(chat_id, "Something went wrong. Please send your message again.")


async def _handle_callback_query(callback_query: dict):
    """
    Handles inline button presses (e.g., quiz answers A/B/C/D).
    """
    from telegram.sender import send_telegram_message

    query_id = callback_query.get('id')
    data = callback_query.get('data', '')
    message = callback_query.get('message', {})
    chat = message.get('chat', {})
    chat_id = chat.get('id')

    if not chat_id or not data:
        return

    # Answer the callback query to remove loading state on the button
    from config.settings import settings
    import httpx
    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"callback_query_id": query_id})
    except Exception:
        pass

    # The callback data will be the answer letter (A, B, C, D)
    # We'll process it exactly like a text answer using the handler route.
    from whatsapp.handler import route_message as whatsapp_route_message
    try:
        await whatsapp_route_message(
            phone=f"telegram:{chat_id}",
            name="Student",
            message=data,
            message_type='text',
            media_id=None
        )
    except Exception as e:
        print(f"Telegram callback error: {e}")
        await send_telegram_message(chat_id, "Something went wrong. Please try again.")

"""
Telegram Message Sender
Uses the Telegram Bot API to send text messages, with optional inline keyboards.
"""

import httpx
from config.settings import settings


TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """
    Sends a text message to a Telegram chat.
    If reply_markup is provided, it will be attached as an inline keyboard.
    Returns True if successful, False otherwise.
    """
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                print(f"Telegram send error: {response.text[:200]}")
                return False
            return True
    except Exception as e:
        print(f"Telegram send exception: {e}")
        return False


def build_quiz_keyboard(question: dict) -> dict | None:
    """
    Given a quiz question dict with keys 'a','b','c','d' (or 'option_a','option_b',...),
    returns a Telegram inline keyboard markup.
    Returns None if the question is not a valid multiple‑choice.
    """
    opt_a = question.get('a', question.get('option_a', ''))
    opt_b = question.get('b', question.get('option_b', ''))
    opt_c = question.get('c', question.get('option_c', ''))
    opt_d = question.get('d', question.get('option_d', ''))

    # Only build the keyboard if we have at least two options
    if not opt_a or not opt_b:
        return None

    keyboard = {
        "inline_keyboard": [
            [
                {"text": f"A) {opt_a}", "callback_data": "A"},
                {"text": f"B) {opt_b}", "callback_data": "B"},
            ],
            [
                {"text": f"C) {opt_c}", "callback_data": "C"},
                {"text": f"D) {opt_d}", "callback_data": "D"},
            ],
        ]
    }
    return keyboard


async def set_telegram_webhook(base_url: str) -> bool:
    """
    Registers the Telegram webhook URL so Telegram sends updates to our app.
    Call this after deployment with your Railway public URL.
    """
    url = f"{TELEGRAM_API_URL}/setWebhook"
    webhook_url = f"{base_url}/webhook/telegram"
    payload = {"url": webhook_url}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            print(f"Telegram webhook set response: {response.text}")
            return response.status_code == 200
    except Exception as e:
        print(f"Telegram webhook set error: {e}")
        return False

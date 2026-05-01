"""
Telegram Message Sender
Uses the Telegram Bot API to send text messages, with optional inline keyboards.
Features: Markdown fallback, auto-splitting long messages, quiz keyboard builder.
"""

import asyncio
import httpx
from config.settings import settings


TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_telegram_message(chat_id: int, text: str, reply_markup: dict = None) -> bool:
    """
    Sends a text message to a Telegram chat, automatically splitting
    messages longer than 3900 characters to avoid API rejection.
    If reply_markup is provided, it's only attached to the first chunk.
    Includes a fallback mechanism for Markdown parsing errors.
    Returns True if all chunks were sent successfully.
    """
    url = f"{TELEGRAM_API_URL}/sendMessage"
    MAX_LENGTH = 3900  # safe margin under Telegram's 4096 limit

    # Split long text into chunks at paragraph boundaries when possible
    chunks = []
    if len(text) <= MAX_LENGTH:
        chunks = [text]
    else:
        paragraphs = text.split('\n')
        current = ""
        for para in paragraphs:
            test = current + ('\n' if current else '') + para
            if len(test) <= MAX_LENGTH:
                current = test
            else:
                if current:
                    chunks.append(current)
                # If a single paragraph is still too long, hard-split it
                if len(para) > MAX_LENGTH:
                    current = para[:MAX_LENGTH]
                    chunks.append(current)
                    current = para[MAX_LENGTH:]
                else:
                    current = para
        if current:
            chunks.append(current)

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        # Only attach inline keyboard to the first chunk
        if i == 0 and reply_markup is not None:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    await asyncio.sleep(0.3)  # ensure chunks arrive in order
                    continue

                # If Markdown parsing failed, retry without formatting
                error_data = response.json()
                if response.status_code == 400 and "parse" in str(error_data).lower():
                    payload["parse_mode"] = None
                    retry = await client.post(url, json=payload)
                    if retry.status_code != 200:
                        print(f"Telegram send error (plain): {retry.text[:200]}")
                        return False
                else:
                    print(f"Telegram send error: {response.text[:200]}")
                    return False
        except Exception as e:
            print(f"Telegram send exception: {e}")
            return False

    return True


def build_quiz_keyboard(question: dict) -> dict | None:
    """
    Given a quiz question dict with keys 'a','b','c','d' (or 'option_a','option_b',...),
    returns a Telegram inline keyboard markup.
    Returns None if the question is not a valid multiple‑choice or if all options are identical.
    """
    opt_a = question.get('a', question.get('option_a', ''))
    opt_b = question.get('b', question.get('option_b', ''))
    opt_c = question.get('c', question.get('option_c', ''))
    opt_d = question.get('d', question.get('option_d', ''))

    # Only build the keyboard if we have at least two options with content
    if not opt_a or not opt_b:
        return None
    
    # Check that not all options are identical (AI hallucination guard)
    options = [opt_a.strip(), opt_b.strip(), opt_c.strip(), opt_d.strip()]
    unique_non_empty = list(set(o for o in options if o))
    if len(unique_non_empty) < 2:
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

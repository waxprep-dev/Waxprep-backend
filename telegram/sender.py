"""
Telegram Message Sender
Uses the Telegram Bot API to send text messages.
"""

import httpx
from config.settings import settings


TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """
    Sends a text message to a Telegram chat.
    Returns True if successful, False otherwise.
    """
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
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

"""
WhatsApp Message Sender

All imports that touch other WaxPrep modules are done INSIDE functions.
This is called lazy importing. It prevents module-not-found errors
at startup because the import only happens when the function is called,
not when the file is first loaded.
"""

import httpx
import asyncio
from config.settings import settings

WHATSAPP_BASE_URL = (
    f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"
    f"/{settings.WHATSAPP_PHONE_NUMBER_ID}"
)


def _normalize_phone(phone: str) -> str:
    """Converts any phone format to WhatsApp-compatible format (no + prefix)."""
    phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    if phone.startswith('0') and len(phone) == 11:
        phone = '234' + phone[1:]
    elif not phone.startswith('234'):
        phone = '234' + phone
    return phone


def _split_message(text: str, max_length: int = 4000) -> list:
    """
    Splits a long message into chunks that fit within WhatsApp limits.
    Tries to split at paragraph breaks so messages feel natural.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            sentences = paragraph.split('. ')
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 2 <= max_length:
                    current_chunk += sentence + '. '
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence + '. '
        elif len(current_chunk) + len(paragraph) + 2 <= max_length:
            current_chunk += paragraph + '\n\n'
        else:
            chunks.append(current_chunk.strip())
            current_chunk = paragraph + '\n\n'

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    for i in range(len(chunks) - 1):
        chunks[i] += "\n\n_(continued...)_"

    return chunks


async def send_whatsapp_message(to: str, message: str):
    """
    Sends a text message to a WhatsApp number.
    Handles long messages by splitting automatically.
    """
    if not to or not message:
        return

    to = _normalize_phone(to)
    chunks = _split_message(message)

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, chunk in enumerate(chunks):
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {
                    "preview_url": False,
                    "body": chunk
                }
            }

            try:
                response = await client.post(
                    f"{WHATSAPP_BASE_URL}/messages",
                    headers=headers,
                    json=payload
                )
                if response.status_code != 200:
                    print(f"WhatsApp send error {response.status_code}: {response.text[:200]}")
            except Exception as e:
                print(f"WhatsApp send exception: {e}")

            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)


async def send_admin_whatsapp(message: str):
    """Sends a message to the admin's personal WhatsApp number."""
    admin_number = settings.ADMIN_WHATSAPP
    if admin_number:
        await send_whatsapp_message(admin_number, message)


async def mark_as_read(message_id: str):
    """Marks a received message as read (shows blue double tick)."""
    if not message_id or not settings.WHATSAPP_TOKEN:
        return

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                f"{WHATSAPP_BASE_URL}/messages",
                headers=headers,
                json=payload
            )
        except Exception as e:
            print(f"Mark as read error (non-critical): {e}")


async def send_reaction(to: str, message_id: str, emoji: str):
    """Sends an emoji reaction to a specific message."""
    to = _normalize_phone(to)

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "reaction",
        "reaction": {
            "message_id": message_id,
            "emoji": emoji
        }
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                f"{WHATSAPP_BASE_URL}/messages",
                headers=headers,
                json=payload
            )
        except Exception as e:
            print(f"Reaction send error (non-critical): {e}")

"""
WhatsApp Message Sender — Optimized
"""

import httpx
import asyncio
from config.settings import settings

WHATSAPP_BASE_URL = (
    f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}"
    f"/{settings.WHATSAPP_PHONE_NUMBER_ID}"
)

# Shared HTTP client for connection pooling — reuse connections for speed
_http_client = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _http_client


def _normalize_phone(phone: str) -> str:
    phone = phone.replace('+', '').replace(' ', '').replace('-', '')
    if phone.startswith('0') and len(phone) == 11:
        phone = '234' + phone[1:]
    elif not phone.startswith('234'):
        phone = '234' + phone
    return phone


def _split_message(text: str, max_length: int = 4000) -> list:
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
    if not to or not message:
        return

    to = _normalize_phone(to)
    chunks = _split_message(message)

    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    client = get_http_client()

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
        except httpx.TimeoutException:
            print(f"WhatsApp send timeout for {to}")
        except Exception as e:
            print(f"WhatsApp send exception: {e}")

        if i < len(chunks) - 1:
            await asyncio.sleep(0.5)


async def send_admin_whatsapp(message: str):
    admin_number = settings.ADMIN_WHATSAPP
    if admin_number:
        await send_whatsapp_message(admin_number, message)


async def mark_as_read(message_id: str):
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

    try:
        client = get_http_client()
        await client.post(f"{WHATSAPP_BASE_URL}/messages", headers=headers, json=payload)
    except Exception as e:
        print(f"Mark as read error (non-critical): {e}")

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
=== FILE: features/wax_id.py ===
"""WAX ID System — Lazy imports throughout."""


async def create_new_wax_id() -> str:
    from database.client import supabase
    from helpers import generate_wax_id

    for _ in range(10):
        candidate = generate_wax_id()
        result = supabase.table('students').select('wax_id').eq('wax_id', candidate).execute()
        if not result.data:
            return candidate

    raise Exception("Could not generate unique WAX ID after 10 attempts")


async def create_new_recovery_code() -> str:
    from database.client import supabase
    from helpers import generate_recovery_code

    for _ in range(10):
        candidate = generate_recovery_code()
        result = supabase.table('students').select('recovery_code').eq('recovery_code', candidate).execute()
        if not result.data:
            return candidate

    raise Exception("Could not generate unique recovery code")


async def get_student_by_wax_id(wax_id: str) -> dict | None:
    from database.client import supabase
    result = supabase.table('students').select('*').eq('wax_id', wax_id.upper().strip()).execute()
    return result.data[0] if result.data else None


async def get_student_by_phone_hash(phone_hash: str) -> dict | None:
    from database.client import supabase
    result = supabase.table('students').select('*').eq('phone_hash', phone_hash).execute()
    return result.data[0] if result.data else None


async def student_exists_in_platform(platform: str, platform_user_id: str) -> dict | None:
    """Alias kept for backward compatibility. Use get_student_by_phone instead."""
    from database.students import get_student_by_phone
    return await get_student_by_phone(platform_user_id)


async def link_platform_to_student(student_id: str, platform: str, platform_user_id: str):
    from database.client import supabase
    from helpers import nigeria_now

    try:
        existing = supabase.table('platform_sessions')\
            .select('id, message_count')\
            .eq('platform', platform)\
            .eq('platform_user_id', platform_user_id)\
            .execute()

        now = nigeria_now().isoformat()

        if existing.data:
            current_count = existing.data[0].get('message_count', 0) or 0
            supabase.table('platform_sessions').update({
                'student_id': student_id,
                'last_active': now,
                'message_count': current_count + 1,
            }).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('platform_sessions').insert({
                'student_id': student_id,
                'platform': platform,
                'platform_user_id': platform_user_id,
                'is_primary_platform': platform == 'whatsapp',
                'last_active': now,
                'message_count': 1,
            }).execute()

    except Exception as e:
        print(f"link_platform_to_student error: {e}")

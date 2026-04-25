"""
Conversation State Management — Cache-First
"""

import json
from helpers import nigeria_now
from database.cache import (
    cache_conversation, get_cached_conversation, invalidate_conversation
)

CONVERSATION_CACHE_TTL = 7200


async def get_or_create_conversation(
    student_id: str,
    platform: str,
    platform_user_id: str
) -> dict:
    from database.client import supabase

    cached = get_cached_conversation(platform, platform_user_id)
    if cached:
        return cached

    try:
        result = supabase.table('conversations')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('platform', platform)\
            .eq('platform_user_id', platform_user_id)\
            .execute()

        if result.data:
            conversation = result.data[0]
        else:
            now = nigeria_now()
            insert_result = supabase.table('conversations').insert({
                'student_id': student_id,
                'platform': platform,
                'platform_user_id': platform_user_id,
                'current_mode': 'default',
                'conversation_state': {},
                'session_started_at': now.isoformat(),
                'last_message_at': now.isoformat(),
            }).execute()
            conversation = insert_result.data[0] if insert_result.data else {
                'id': f'temp_{student_id}',
                'student_id': student_id,
                'platform': platform,
                'platform_user_id': platform_user_id,
                'current_mode': 'default',
                'conversation_state': {},
            }

        cache_conversation(platform, platform_user_id, conversation)
        return conversation

    except Exception as e:
        print(f"get_or_create_conversation error: {e}")
        return {
            'id': f'temp_{student_id}',
            'student_id': student_id,
            'platform': platform,
            'platform_user_id': platform_user_id,
            'current_mode': 'default',
            'conversation_state': {},
        }


async def update_conversation_state(
    conversation_id: str,
    platform: str,
    platform_user_id: str,
    updates: dict
):
    from database.client import supabase

    if str(conversation_id).startswith('temp_'):
        return None

    try:
        now = nigeria_now()
        updates['last_message_at'] = now.isoformat()
        updates['updated_at'] = now.isoformat()

        result = supabase.table('conversations')\
            .update(updates)\
            .eq('id', conversation_id)\
            .execute()

        if result.data:
            cache_conversation(platform, platform_user_id, result.data[0])
            return result.data[0]

    except Exception as e:
        print(f"update_conversation_state error: {e}")

    return None


async def clear_conversation_state(
    conversation_id: str,
    platform: str,
    platform_user_id: str
):
    await update_conversation_state(
        conversation_id, platform, platform_user_id,
        {
            'current_mode': 'default',
            'current_subject': None,
            'current_topic': None,
            'conversation_state': {},
            'is_paused': False,
            'session_started_at': nigeria_now().isoformat(),
        }
    )


async def save_message(
    conversation_id: str,
    student_id: str,
    platform: str,
    role: str,
    content: str,
    message_type: str = 'text',
    ai_model: str = None
):
    from database.client import supabase

    if str(conversation_id).startswith('temp_'):
        return

    try:
        supabase.table('messages').insert({
            'conversation_id': conversation_id,
            'student_id': student_id,
            'platform': platform,
            'role': role,
            'content': content[:4000],
            'message_type': message_type,
            'ai_model_used': ai_model,
        }).execute()
    except Exception as e:
        print(f"save_message error: {e}")


async def get_conversation_history(conversation_id: str, limit: int = 20) -> list:
    from database.client import supabase

    if str(conversation_id).startswith('temp_'):
        return []

    try:
        result = supabase.table('messages')\
            .select('role, content')\
            .eq('conversation_id', conversation_id)\
            .order('created_at', desc=True)\
            .limit(limit)\
            .execute()

        if not result.data:
            return []

        messages = list(reversed(result.data))
        return [{"role": m['role'], "content": m['content']} for m in messages]

    except Exception as e:
        print(f"get_conversation_history error: {e}")
        return []

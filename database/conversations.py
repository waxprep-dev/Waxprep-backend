"""
Conversation State Management — Cache-First with Redis temp sessions for anonymous users.
"""

import json
from helpers import nigeria_now
from database.cache import (
    cache_conversation, get_cached_conversation, invalidate_conversation
)
from database.client import redis_client

CONVERSATION_CACHE_TTL = 7200        # 2 hours for real conversations
TEMP_CONVERSATION_CACHE_TTL = 1800   # 30 minutes for anonymous users


def _temp_key(platform: str, platform_user_id: str) -> str:
    return f"temp_conv:{platform}:{platform_user_id}"


async def get_or_create_conversation(
    student_id: str,
    platform: str,
    platform_user_id: str
) -> dict:
    from database.client import supabase

    # 1. If anonymous, use Redis‑backed temporary session
    if not student_id or student_id == 'anonymous':
        # Try to get existing temp session
        try:
            raw = redis_client.get(_temp_key(platform, platform_user_id))
            if raw:
                return json.loads(raw)
        except Exception as e:
            print(f"Redis temp get error: {e}")

        # Create new temp session
        temp = {
            'id': f'temp_{platform}_{platform_user_id}',
            'student_id': 'anonymous',
            'platform': platform,
            'platform_user_id': platform_user_id,
            'current_mode': 'default',
            'conversation_state': {},
        }
        # Save it immediately
        try:
            redis_client.setex(
                _temp_key(platform, platform_user_id),
                TEMP_CONVERSATION_CACHE_TTL,
                json.dumps(temp)
            )
        except Exception as e:
            print(f"Redis temp set error: {e}")
        return temp

    # 2. Registered student – normal flow
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

    # Temp conversations – update Redis, not database
    if str(conversation_id).startswith('temp_'):
        try:
            raw = redis_client.get(_temp_key(platform, platform_user_id))
            if raw:
                conv = json.loads(raw)
            else:
                conv = {
                    'id': conversation_id,
                    'student_id': 'anonymous',
                    'platform': platform,
                    'platform_user_id': platform_user_id,
                }
            # Merge updates
            for key, value in updates.items():
                if key == 'conversation_state' and isinstance(value, dict):
                    conv.setdefault('conversation_state', {}).update(value)
                else:
                    conv[key] = value
            redis_client.setex(
                _temp_key(platform, platform_user_id),
                TEMP_CONVERSATION_CACHE_TTL,
                json.dumps(conv)
            )
            return conv
        except Exception as e:
            print(f"Temp conversation update error: {e}")
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

    # Don't save messages for temp sessions
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


# Additional helper: when a student is created, we can migrate temp session to a real one.
async def migrate_temp_to_real(
    platform: str,
    platform_user_id: str,
    real_student_id: str
):
    """Call this after a student registers to convert their temp session into a real DB conversation."""
    try:
        raw = redis_client.get(_temp_key(platform, platform_user_id))
        if not raw:
            return None
        temp = json.loads(raw)
        # Delete the temp key
        redis_client.delete(_temp_key(platform, platform_user_id))
        # Create real conversation using the state from temp
        from database.client import supabase
        now = nigeria_now()
        result = supabase.table('conversations').insert({
            'student_id': real_student_id,
            'platform': platform,
            'platform_user_id': platform_user_id,
            'current_mode': temp.get('current_mode', 'default'),
            'current_subject': temp.get('current_subject'),
            'current_topic': temp.get('current_topic'),
            'conversation_state': temp.get('conversation_state', {}),
            'session_started_at': now.isoformat(),
            'last_message_at': now.isoformat(),
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"migrate_temp_to_real error: {e}")
        return None

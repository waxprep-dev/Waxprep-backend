"""
Conversation State Management

Tracks what each student is doing mid-conversation.
All imports are lazy to prevent startup errors.
"""

import json


CONVERSATION_CACHE_TTL = 7200  # 2 hours


async def get_or_create_conversation(
    student_id: str,
    platform: str,
    platform_user_id: str
) -> dict:
    """Gets the current conversation for a student, creating one if needed."""
    from database.client import supabase, redis_client
    from helpers import nigeria_now

    cache_key = f"conv:{platform}:{platform_user_id}"

    # Try cache first
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    # Check database
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
            insert_result = supabase.table('conversations').insert({
                'student_id': student_id,
                'platform': platform,
                'platform_user_id': platform_user_id,
                'current_mode': 'default',
                'conversation_state': {},
                'session_started_at': nigeria_now().isoformat(),
            }).execute()
            conversation = insert_result.data[0] if insert_result.data else {}

        try:
            redis_client.setex(cache_key, CONVERSATION_CACHE_TTL, json.dumps(conversation, default=str))
        except Exception:
            pass

        return conversation

    except Exception as e:
        print(f"get_or_create_conversation error: {e}")
        return {
            'id': f'temp_{student_id}_{platform}',
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
    """Updates conversation state in both database and cache."""
    from database.client import supabase, redis_client
    from helpers import nigeria_now

    if conversation_id.startswith('temp_'):
        return None

    try:
        updates['last_message_at'] = nigeria_now().isoformat()
        updates['updated_at'] = nigeria_now().isoformat()

        result = supabase.table('conversations')\
            .update(updates)\
            .eq('id', conversation_id)\
            .execute()

        if result.data:
            cache_key = f"conv:{platform}:{platform_user_id}"
            try:
                redis_client.setex(
                    cache_key,
                    CONVERSATION_CACHE_TTL,
                    json.dumps(result.data[0], default=str)
                )
            except Exception:
                pass
            return result.data[0]

    except Exception as e:
        print(f"update_conversation_state error: {e}")

    return None


async def set_awaiting_response(
    conversation_id: str,
    platform: str,
    platform_user_id: str,
    awaiting_for: str,
    extra_state: dict = None
):
    """Marks conversation as waiting for a specific type of response."""
    state = extra_state or {}
    state['awaiting_response_for'] = awaiting_for

    await update_conversation_state(
        conversation_id,
        platform,
        platform_user_id,
        {'conversation_state': state}
    )


async def clear_conversation_state(
    conversation_id: str,
    platform: str,
    platform_user_id: str
):
    """Clears conversation state — used when a new session starts."""
    from helpers import nigeria_now

    await update_conversation_state(
        conversation_id,
        platform,
        platform_user_id,
        {
            'current_mode': 'default',
            'current_subject': None,
            'current_topic': None,
            'conversation_state': {},
            'awaiting_response_for': None,
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
    """Saves a message to the conversation history."""
    from database.client import supabase

    if conversation_id.startswith('temp_'):
        return

    try:
        supabase.table('messages').insert({
            'conversation_id': conversation_id,
            'student_id': student_id,
            'platform': platform,
            'role': role,
            'content': content,
            'message_type': message_type,
            'ai_model_used': ai_model,
        }).execute()
    except Exception as e:
        print(f"save_message error: {e}")


async def get_conversation_history(conversation_id: str, limit: int = 15) -> list:
    """
    Gets recent message history for a conversation.
    Returns in format needed by AI: [{"role": "user", "content": "..."}]
    """
    from database.client import supabase

    if conversation_id.startswith('temp_'):
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
        return [{"role": msg['role'], "content": msg['content']} for msg in messages]

    except Exception as e:
        print(f"get_conversation_history error: {e}")
        return []

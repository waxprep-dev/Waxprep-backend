"""
Conversation State Management

Every active conversation has a "state" — this tracks:
- What mode the student is in (learn, quiz, exam, etc.)
- What subject/topic they're studying
- What WaxPrep is waiting for them to respond to
- Any temporary data needed for the current flow

State is stored in:
1. Redis (for fast access during active conversations)
2. Supabase (for persistence — state survives server restarts)

The Redis key for a conversation expires after 2 hours of inactivity.
If it expires, the next message loads it from Supabase.
"""

from database.client import supabase, redis_client
from utils.helpers import nigeria_now
import json

CONVERSATION_CACHE_TTL = 7200  # 2 hours in seconds

async def get_or_create_conversation(
    student_id: str,
    platform: str,
    platform_user_id: str
) -> dict:
    """
    Gets the current conversation state for a student on a platform.
    Creates one if it doesn't exist.
    
    Returns the conversation dict.
    """
    # Try Redis first (fast)
    cache_key = f"conv:{platform}:{platform_user_id}"
    cached = redis_client.get(cache_key)
    
    if cached:
        return json.loads(cached)
    
    # Not in cache — check database
    result = supabase.table('conversations')\
        .select('*')\
        .eq('student_id', student_id)\
        .eq('platform', platform)\
        .eq('platform_user_id', platform_user_id)\
        .execute()
    
    if result.data:
        conversation = result.data[0]
    else:
        # Create new conversation
        conversation = supabase.table('conversations').insert({
            'student_id': student_id,
            'platform': platform,
            'platform_user_id': platform_user_id,
            'current_mode': 'default',
            'conversation_state': {},
            'session_started_at': nigeria_now().isoformat()
        }).execute().data[0]
    
    # Cache it
    redis_client.setex(cache_key, CONVERSATION_CACHE_TTL, json.dumps(conversation, default=str))
    
    return conversation

async def update_conversation_state(
    conversation_id: str,
    platform: str,
    platform_user_id: str,
    updates: dict
):
    """
    Updates the conversation state.
    Updates both Redis cache and Supabase for persistence.
    """
    # Update in database
    updates['last_message_at'] = nigeria_now().isoformat()
    updates['updated_at'] = nigeria_now().isoformat()
    
    result = supabase.table('conversations')\
        .update(updates)\
        .eq('id', conversation_id)\
        .execute()
    
    if result.data:
        # Update cache
        cache_key = f"conv:{platform}:{platform_user_id}"
        redis_client.setex(
            cache_key, 
            CONVERSATION_CACHE_TTL, 
            json.dumps(result.data[0], default=str)
        )
    
    return result.data[0] if result.data else None

async def set_awaiting_response(
    conversation_id: str,
    platform: str,
    platform_user_id: str,
    awaiting_for: str,
    extra_state: dict = None
):
    """
    Marks the conversation as waiting for a specific type of response.
    
    For example, after asking "What is your name?", we set:
    awaiting_for = 'name'
    
    When the next message comes in, the system knows it's the student's name.
    """
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
    """
    Clears the conversation state — used when a new session starts.
    """
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
            'session_started_at': nigeria_now().isoformat()
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
    """
    Saves a message to the conversation history.
    Both student messages and AI responses are saved.
    """
    supabase.table('messages').insert({
        'conversation_id': conversation_id,
        'student_id': student_id,
        'platform': platform,
        'role': role,
        'content': content,
        'message_type': message_type,
        'ai_model_used': ai_model,
    }).execute()

async def get_conversation_history(conversation_id: str, limit: int = 20) -> list:
    """
    Gets recent message history for a conversation.
    Returns in the format needed by AI models: [{"role": "user", "content": "..."}]
    """
    result = supabase.table('messages')\
        .select('role, content')\
        .eq('conversation_id', conversation_id)\
        .order('created_at', desc=True)\
        .limit(limit)\
        .execute()
    
    if not result.data:
        return []
    
    # Reverse to get chronological order
    messages = list(reversed(result.data))
    
    # Format for AI models
    return [{"role": msg['role'], "content": msg['content']} for msg in messages]

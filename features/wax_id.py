"""
WAX ID System

All imports are lazy (inside functions) to prevent startup errors.
This file does NOT import from utils or helpers at the top level.
"""


async def create_new_wax_id() -> str:
    """Creates a unique WAX ID, retrying if collision occurs."""
    from database.client import supabase
    from helpers import generate_wax_id

    for _ in range(10):
        candidate = generate_wax_id()
        result = supabase.table('students').select('wax_id').eq('wax_id', candidate).execute()
        if not result.data:
            return candidate

    raise Exception("Could not generate unique WAX ID after 10 attempts")


async def create_new_recovery_code() -> str:
    """Creates a unique recovery code."""
    from database.client import supabase
    from helpers import generate_recovery_code

    for _ in range(10):
        candidate = generate_recovery_code()
        result = supabase.table('students').select('recovery_code').eq('recovery_code', candidate).execute()
        if not result.data:
            return candidate

    raise Exception("Could not generate unique recovery code")


async def get_student_by_wax_id(wax_id: str) -> dict | None:
    """Fetches a student by their WAX ID. Returns None if not found."""
    from database.client import supabase

    result = supabase.table('students').select('*').eq('wax_id', wax_id.upper().strip()).execute()
    return result.data[0] if result.data else None


async def get_student_by_phone_hash(phone_hash: str) -> dict | None:
    """Fetches a student by their hashed phone number."""
    from database.client import supabase

    result = supabase.table('students').select('*').eq('phone_hash', phone_hash).execute()
    return result.data[0] if result.data else None


async def student_exists_in_platform(platform: str, platform_user_id: str) -> dict | None:
    """
    Checks if a user from a specific platform is linked to a student account.
    Returns the full student record if found, None if not.

    For WhatsApp: platform='whatsapp', platform_user_id='2348012345678'
    """
    from database.client import supabase

    try:
        result = supabase.table('platform_sessions')\
            .select('student_id')\
            .eq('platform', platform)\
            .eq('platform_user_id', platform_user_id)\
            .execute()

        if not result.data:
            return None

        student_id = result.data[0]['student_id']

        student_result = supabase.table('students')\
            .select('*')\
            .eq('id', student_id)\
            .execute()

        return student_result.data[0] if student_result.data else None

    except Exception as e:
        print(f"student_exists_in_platform error: {e}")
        return None


async def link_platform_to_student(student_id: str, platform: str, platform_user_id: str):
    """
    Links a platform session to a student account.
    This is what makes cross-platform sync work.
    If link already exists, updates the last_active time.
    """
    from database.client import supabase
    from helpers import nigeria_now

    try:
        existing = supabase.table('platform_sessions')\
            .select('id')\
            .eq('platform', platform)\
            .eq('platform_user_id', platform_user_id)\
            .execute()

        if existing.data:
            supabase.table('platform_sessions').update({
                'student_id': student_id,
                'last_active': nigeria_now().isoformat(),
                'message_count': supabase.table('platform_sessions')
                    .select('message_count').eq('id', existing.data[0]['id'])
                    .execute().data[0].get('message_count', 0) + 1
            }).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('platform_sessions').insert({
                'student_id': student_id,
                'platform': platform,
                'platform_user_id': platform_user_id,
                'is_primary_platform': platform == 'whatsapp',
                'last_active': nigeria_now().isoformat(),
            }).execute()

    except Exception as e:
        print(f"link_platform_to_student error: {e}")

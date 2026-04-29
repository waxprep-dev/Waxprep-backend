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

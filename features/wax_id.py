import bcrypt
from database.client import supabase
from utils.helpers import generate_wax_id, generate_recovery_code, generate_referral_code

async def create_new_wax_id() -> str:
    """
    Creates a new unique WAX ID.
    Keeps trying until it generates one that doesn't already exist in the database.
    The chance of collision is astronomically low, but we check to be absolutely sure.
    """
    max_attempts = 10
    
    for attempt in range(max_attempts):
        candidate = generate_wax_id()
        
        # Check if this WAX ID already exists
        result = supabase.table('students').select('wax_id').eq('wax_id', candidate).execute()
        
        if not result.data:  # If no existing student has this WAX ID, it's safe to use
            return candidate
    
    # If after 10 attempts we still haven't found a unique one (essentially impossible),
    # something is very wrong and we should know about it
    raise Exception("Could not generate unique WAX ID after 10 attempts — this should never happen")

async def create_new_recovery_code() -> str:
    """Creates a unique recovery code."""
    max_attempts = 10
    
    for attempt in range(max_attempts):
        candidate = generate_recovery_code()
        result = supabase.table('students').select('recovery_code').eq('recovery_code', candidate).execute()
        
        if not result.data:
            return candidate
    
    raise Exception("Could not generate unique recovery code")

async def get_student_by_wax_id(wax_id: str) -> dict | None:
    """
    Fetches a student's complete profile from the database using their WAX ID.
    Returns None if no student found with that WAX ID.
    """
    result = supabase.table('students').select('*').eq('wax_id', wax_id.upper()).execute()
    return result.data[0] if result.data else None

async def get_student_by_phone_hash(phone_hash: str) -> dict | None:
    """
    Fetches a student by their hashed phone number.
    Used when someone messages WhatsApp — we hash their number and look them up.
    """
    result = supabase.table('students').select('*').eq('phone_hash', phone_hash).execute()
    return result.data[0] if result.data else None

async def is_student_registered(phone_hash: str) -> bool:
    """
    Checks if a phone number is already registered.
    Returns True if registered, False if new.
    """
    student = await get_student_by_phone_hash(phone_hash)
    return student is not None and student.get('onboarding_complete', False)

async def student_exists_in_platform(platform: str, platform_user_id: str) -> dict | None:
    """
    Checks if a user from a specific platform is linked to a student account.
    For WhatsApp: platform='whatsapp', platform_user_id=their WhatsApp number
    Returns the student data if found.
    """
    result = supabase.table('platform_sessions')\
        .select('*, students(*)')\
        .eq('platform', platform)\
        .eq('platform_user_id', platform_user_id)\
        .execute()
    
    if result.data:
        # Return the student data nested inside
        session = result.data[0]
        return session.get('students')
    return None

async def link_platform_to_student(student_id: str, platform: str, platform_user_id: str):
    """
    Links a platform session (like a WhatsApp number) to a student account.
    This is what makes cross-platform sync work.
    When we know Amaka's WhatsApp number maps to WAX-A74892, we store that here.
    """
    # Check if this platform session already exists
    existing = supabase.table('platform_sessions')\
        .select('id')\
        .eq('platform', platform)\
        .eq('platform_user_id', platform_user_id)\
        .execute()
    
    if existing.data:
        # Update last active time
        supabase.table('platform_sessions')\
            .update({'last_active': 'NOW()', 'student_id': student_id})\
            .eq('platform', platform)\
            .eq('platform_user_id', platform_user_id)\
            .execute()
    else:
        # Create new platform session
        supabase.table('platform_sessions').insert({
            'student_id': student_id,
            'platform': platform,
            'platform_user_id': platform_user_id,
            'is_primary_platform': platform == 'whatsapp',  # WhatsApp is primary by default
        }).execute()

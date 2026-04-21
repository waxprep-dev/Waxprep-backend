"""
PIN Security System

All imports are lazy to prevent startup errors.
"""


async def record_failed_pin_attempt(student_id: str) -> int:
    """Records a failed PIN attempt. Returns total failed attempts today."""
    from database.client import redis_client

    key = f"failed_pin:{student_id}"
    attempts = redis_client.incr(key)
    if attempts == 1:
        redis_client.expire(key, 1800)  # Lock for 30 minutes after first failure
    return int(attempts)


async def is_account_locked(student_id: str) -> bool:
    """Returns True if account is locked due to too many failed PIN attempts."""
    from database.client import redis_client

    key = f"failed_pin:{student_id}"
    attempts = redis_client.get(key)
    return attempts is not None and int(attempts) >= 5


async def clear_failed_attempts(student_id: str):
    """Clears failed PIN attempt counter after successful login."""
    from database.client import redis_client

    redis_client.delete(f"failed_pin:{student_id}")


async def change_pin(student_id: str, old_pin: str, new_pin: str) -> tuple:
    """
    Changes a student's PIN.
    Returns (success: bool, message: str)
    """
    from database.client import supabase
    from helpers import verify_pin, hash_pin, is_valid_pin

    result = supabase.table('students').select('pin_hash').eq('id', student_id).execute()
    if not result.data:
        return False, "Student not found"

    current_hash = result.data[0]['pin_hash']

    if not verify_pin(old_pin, current_hash):
        return False, "Current PIN is incorrect"

    if not is_valid_pin(new_pin):
        return False, "New PIN must be exactly 4 digits"

    new_hash = hash_pin(new_pin)
    supabase.table('students').update({'pin_hash': new_hash}).eq('id', student_id).execute()

    return True, "PIN changed successfully"

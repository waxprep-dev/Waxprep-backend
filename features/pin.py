import bcrypt
from database.client import supabase

def hash_pin(pin: str) -> str:
    """
    Creates a secure hash of a 4-digit PIN.
    
    bcrypt is a hashing algorithm designed specifically for passwords.
    Even if someone gets access to our database, they cannot reverse the hash
    to find the original PIN.
    
    The "12" is the "cost factor" — it makes the hashing slow enough that
    brute force attacks take too long, but fast enough that real users
    don't notice a delay.
    """
    pin_bytes = str(pin).encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pin_bytes, salt)
    return hashed.decode('utf-8')

def verify_pin(pin: str, pin_hash: str) -> bool:
    """
    Checks if a PIN matches its stored hash.
    Returns True if correct, False if wrong.
    
    This is how login works — we hash the entered PIN and compare
    to the stored hash. We never store the actual PIN.
    """
    try:
        pin_bytes = str(pin).encode('utf-8')
        hash_bytes = pin_hash.encode('utf-8')
        return bcrypt.checkpw(pin_bytes, hash_bytes)
    except Exception:
        return False

async def record_failed_pin_attempt(student_id: str) -> int:
    """
    Records a failed PIN attempt and returns how many failed attempts today.
    After 5 failed attempts, the account is locked for 30 minutes.
    """
    from database.client import redis_client
    
    key = f"failed_pin:{student_id}"
    attempts = redis_client.incr(key)
    
    if attempts == 1:
        # Set expiry of 30 minutes on first failure
        redis_client.expire(key, 1800)
    
    return attempts

async def is_account_locked(student_id: str) -> bool:
    """
    Checks if an account is locked due to too many failed PIN attempts.
    Returns True if locked, False if not.
    """
    from database.client import redis_client
    
    key = f"failed_pin:{student_id}"
    attempts = redis_client.get(key)
    
    return attempts is not None and int(attempts) >= 5

async def clear_failed_attempts(student_id: str):
    """
    Clears the failed PIN attempt counter after a successful login.
    """
    from database.client import redis_client
    redis_client.delete(f"failed_pin:{student_id}")

async def change_pin(student_id: str, old_pin: str, new_pin: str) -> tuple[bool, str]:
    """
    Changes a student's PIN.
    Returns (success: bool, message: str)
    """
    # Get current student
    result = supabase.table('students').select('pin_hash').eq('id', student_id).execute()
    
    if not result.data:
        return False, "Student not found"
    
    current_hash = result.data[0]['pin_hash']
    
    # Verify old PIN
    if not verify_pin(old_pin, current_hash):
        return False, "Current PIN is incorrect"
    
    # Validate new PIN
    from utils.helpers import is_valid_pin
    if not is_valid_pin(new_pin):
        return False, "New PIN must be exactly 4 digits"
    
    # Save new PIN
    new_hash = hash_pin(new_pin)
    supabase.table('students').update({'pin_hash': new_hash}).eq('id', student_id).execute()
    
    return True, "PIN changed successfully"

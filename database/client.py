from supabase import create_client, Client
from config.settings import settings
import redis
from functools import lru_cache

# ===================================================
# SUPABASE CONNECTION
# This connects to your Supabase database.
# We use the "service key" which has full admin access.
# This key is kept secret and only used on the server.
# ===================================================

@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """
    Returns the Supabase client.
    lru_cache means this function only creates the client ONCE,
    then returns the same connection every time it's called.
    This is efficient and saves resources.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables"
        )
    
    return create_client(
        settings.SUPABASE_URL,
        settings.SUPABASE_SERVICE_KEY
    )

# ===================================================
# REDIS CONNECTION
# Redis is our fast cache.
# We store temporary data here that we need to access quickly.
# Things like: current conversation state, session data, daily AI spending.
# ===================================================

@lru_cache(maxsize=1)
def get_redis():
    """
    Returns the Redis client.
    Again, only created once and reused.
    """
    if not settings.REDIS_URL:
        raise ValueError("REDIS_URL must be set in environment variables")
    
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,    # Returns strings instead of bytes
        socket_timeout=5,         # Give up after 5 seconds if Redis is slow
        socket_connect_timeout=5
    )

# Create global instances that all other files import
supabase = get_supabase()
redis_client = get_redis()

def test_connections():
    """
    Tests that both database connections work.
    Called when the app starts up.
    """
    try:
        # Test Supabase
        result = supabase.table('system_config').select('config_key').limit(1).execute()
        print("✅ Supabase connection successful")
    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
        raise
    
    try:
        # Test Redis
        redis_client.ping()
        print("✅ Redis connection successful")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        raise

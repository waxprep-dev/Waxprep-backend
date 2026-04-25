from supabase import create_client, Client
from config.settings import settings
import redis
from functools import lru_cache


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@lru_cache(maxsize=1)
def get_redis():
    if not settings.REDIS_URL:
        raise ValueError("REDIS_URL must be set")
    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )


supabase = get_supabase()
redis_client = get_redis()


def test_connections():
    try:
        supabase.table('system_config').select('config_key').limit(1).execute()
        print("Supabase connection successful")
    except Exception as e:
        print(f"Supabase connection failed: {e}")
        raise

    try:
        redis_client.ping()
        print("Redis connection successful")
    except Exception as e:
        print(f"Redis connection failed: {e}")
        raise

"""
AI Cost Tracker

Tracks every API call to AI models and the associated cost.
This is how you stay in control of spending.

The system has automatic protections:
- At 70% of daily budget: admin is notified
- At 85% of daily budget: free users get lighter models
- At 100% of daily budget: AI responses pause for the day

IMPORTANT NOTE ABOUT IMPORTS:
All imports that could cause circular dependencies are placed INSIDE
the functions that need them, not at the top of the file.
This prevents circular import errors at startup.
"""

# Approximate cost per 1000 tokens in USD
COST_PER_1K_TOKENS = {
    'llama3-8b-8192': 0.00005,
    'llama3-70b-8192': 0.00079,
    'gemini-1.5-flash': 0.000075,
    'gemini-1.5-pro': 0.00125,
    'gpt-4o-mini': 0.000150,
    'gpt-4o': 0.005,
}

async def track_ai_cost(
    student_id: str,
    model: str,
    tokens_input: int,
    tokens_output: int,
    query_type: str
):
    """
    Records an AI API call and its cost.
    Imports are inside the function to prevent circular imports.
    """
    # Import here, not at top of file
    from database.client import supabase, redis_client
    from config.settings import settings
    
    total_tokens = tokens_input + tokens_output
    cost_per_1k = COST_PER_1K_TOKENS.get(model, 0.001)
    estimated_cost = (total_tokens / 1000) * cost_per_1k
    
    # Get today's date in Nigerian timezone
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    
    # Update daily spending in Redis
    daily_key = f"ai_cost:{today}"
    try:
        redis_client.incrbyfloat(daily_key, estimated_cost)
        redis_client.expire(daily_key, 86400 * 2)
    except Exception as e:
        print(f"Redis cost tracking error (non-critical): {e}")
    
    # Log to database for history
    try:
        supabase.table('ai_cost_logs').insert({
            'student_id': student_id,
            'model_used': model,
            'tokens_input': tokens_input,
            'tokens_output': tokens_output,
            'estimated_cost_usd': round(estimated_cost, 6),
            'query_type': query_type,
        }).execute()
    except Exception as e:
        print(f"Cost log database error (non-critical): {e}")

async def get_daily_ai_spending() -> float:
    """Returns total AI spending for today in USD."""
    from database.client import redis_client
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    daily_key = f"ai_cost:{today}"
    
    try:
        value = redis_client.get(daily_key)
        return float(value) if value else 0.0
    except Exception:
        return 0.0

async def should_use_cheaper_model() -> bool:
    """Returns True if we should use cheaper models due to budget constraints."""
    from config.settings import settings
    
    spending = await get_daily_ai_spending()
    threshold = settings.DAILY_AI_BUDGET_USD * settings.AI_BUDGET_SHIFT_THRESHOLD
    return spending >= threshold

async def is_ai_budget_exceeded() -> bool:
    """Returns True if the daily AI budget has been completely used."""
    from config.settings import settings
    
    spending = await get_daily_ai_spending()
    return spending >= settings.DAILY_AI_BUDGET_USD

async def check_budget_and_notify():
    """
    Checks the current budget and notifies admin if thresholds are crossed.
    Called every 30 minutes by the scheduler.
    """
    from config.settings import settings
    
    try:
        spending = await get_daily_ai_spending()
        budget = settings.DAILY_AI_BUDGET_USD
        
        if budget <= 0:
            return
            
        fraction = spending / budget
        
        if fraction >= 1.0:
            message = (
                f"🚨 *CRITICAL: AI Budget Exceeded!*\n\n"
                f"Spent: ${spending:.4f}\n"
                f"Budget: ${budget:.2f}\n\n"
                f"AI responses are now paused for free tier students.\n"
                f"Check Railway logs for details."
            )
            await _send_admin_alert(message)
        elif fraction >= settings.AI_BUDGET_WARNING_THRESHOLD:
            message = (
                f"⚠️ *AI Budget Warning*\n\n"
                f"Spent: ${spending:.4f} ({fraction*100:.0f}% of daily budget)\n"
                f"Budget: ${budget:.2f}\n\n"
                f"Switching to cheaper models for free tier."
            )
            await _send_admin_alert(message)
    except Exception as e:
        print(f"Budget check error: {e}")

async def _send_admin_alert(message: str):
    """Internal function to send admin alerts. Avoids circular imports."""
    try:
        from config.settings import settings
        if settings.ADMIN_WHATSAPP:
            from whatsapp.sender import send_admin_whatsapp
            await send_admin_whatsapp(message)
    except Exception as e:
        print(f"Admin alert error: {e}")

def get_cost_summary_today() -> dict:
    """Returns a synchronous cost summary for use in reports."""
    from database.client import redis_client
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')
    daily_key = f"ai_cost:{today}"
    
    try:
        value = redis_client.get(daily_key)
        cost = float(value) if value else 0.0
    except Exception:
        cost = 0.0
    
    return {
        'date': today,
        'total_cost_usd': round(cost, 6),
        'total_cost_naira_estimate': round(cost * 1600, 2),
    }

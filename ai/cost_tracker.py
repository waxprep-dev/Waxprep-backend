"""
AI Cost Tracker

Tracks every API call to AI models and the associated cost.
This is how you stay in control of spending.

The system has automatic protections:
- At 70% of daily budget: admin is notified
- At 85% of daily budget: free users get lighter models
- At 100% of daily budget: AI responses pause for the day

Costs are logged in both Redis (for real-time tracking) and Supabase (for history).
"""

from database.client import supabase, redis_client
from config.settings import settings
from utils.helpers import nigeria_today

# Approximate cost per 1000 tokens in USD
# These are estimates — actual costs vary
COST_PER_1K_TOKENS = {
    'llama3-8b-8192': 0.00005,       # Groq — very cheap
    'llama3-70b-8192': 0.00079,      # Groq — cheap
    'gemini-1.5-flash': 0.000075,    # Gemini Flash — cheap
    'gemini-1.5-pro': 0.00125,       # Gemini Pro — moderate
    'gpt-4o-mini': 0.000150,         # OpenAI mini — moderate
    'gpt-4o': 0.005,                 # OpenAI — expensive (avoid unless vision needed)
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
    Updates both the daily spending counter and the historical log.
    """
    total_tokens = tokens_input + tokens_output
    cost_per_1k = COST_PER_1K_TOKENS.get(model, 0.001)  # Default if model unknown
    estimated_cost = (total_tokens / 1000) * cost_per_1k
    
    today = nigeria_today()
    
    # Update daily spending in Redis (fast, real-time)
    daily_key = f"ai_cost:{today}"
    redis_client.incrbyfloat(daily_key, estimated_cost)
    redis_client.expire(daily_key, 86400 * 2)  # Keep for 2 days
    
    # Log to database for history (slower, but permanent)
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
        print(f"Cost log error (non-critical): {e}")

async def get_daily_ai_spending() -> float:
    """Returns total AI spending for today in USD."""
    today = nigeria_today()
    daily_key = f"ai_cost:{today}"
    value = redis_client.get(daily_key)
    return float(value) if value else 0.0

async def should_use_cheaper_model() -> bool:
    """
    Returns True if we should use cheaper models due to budget constraints.
    This is triggered at 85% of daily budget.
    """
    spending = await get_daily_ai_spending()
    threshold = settings.DAILY_AI_BUDGET_USD * settings.AI_BUDGET_SHIFT_THRESHOLD
    return spending >= threshold

async def is_ai_budget_exceeded() -> bool:
    """
    Returns True if the daily AI budget has been completely used.
    """
    spending = await get_daily_ai_spending()
    return spending >= settings.DAILY_AI_BUDGET_USD

async def check_budget_and_notify():
    """
    Checks the current budget and notifies admin if thresholds are crossed.
    Called periodically by the scheduler.
    """
    spending = await get_daily_ai_spending()
    budget = settings.DAILY_AI_BUDGET_USD
    fraction = spending / budget
    
    if fraction >= 1.0:
        await notify_admin_budget(spending, budget, "CRITICAL: Daily AI budget EXCEEDED")
    elif fraction >= settings.AI_BUDGET_WARNING_THRESHOLD:
        await notify_admin_budget(spending, budget, f"WARNING: AI budget at {fraction*100:.0f}%")

async def notify_admin_budget(spending: float, budget: float, title: str):
    """Sends the admin a WhatsApp message about budget status."""
    # This will be implemented once WhatsApp sender is ready
    pass

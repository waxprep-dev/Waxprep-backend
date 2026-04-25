"""
AI Cost Tracker
Tracks spending per day and enforces budget limits.
"""

from helpers import nigeria_now

COST_PER_1K_TOKENS = {
    'llama-3.1-8b-instant': 0.00005,
    'llama-3.3-70b-versatile': 0.00079,
    'gemini-1.5-flash-latest': 0.000075,
    'gemini-1.5-pro-latest': 0.00125,
    'gpt-4o-mini': 0.000150,
    'gpt-4o': 0.005,
}


async def track_ai_cost(student_id: str, model: str,
                         tokens_input: int, tokens_output: int, query_type: str):
    from database.client import supabase
    from database.cache import increment_ai_cost

    total_tokens = tokens_input + tokens_output
    cost_per_1k = COST_PER_1K_TOKENS.get(model, 0.001)
    estimated_cost = (total_tokens / 1000) * cost_per_1k

    today = nigeria_now().strftime('%Y-%m-%d')
    increment_ai_cost(estimated_cost, today)

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
        print(f"Cost log DB error (non-critical): {e}")


async def get_daily_ai_spending() -> float:
    from database.cache import get_ai_cost
    today = nigeria_now().strftime('%Y-%m-%d')
    return get_ai_cost(today)


async def should_use_cheaper_model() -> bool:
    from config.settings import settings
    spending = await get_daily_ai_spending()
    return spending >= settings.DAILY_AI_BUDGET_USD * settings.AI_BUDGET_SHIFT_THRESHOLD


async def is_ai_budget_exceeded() -> bool:
    from config.settings import settings
    spending = await get_daily_ai_spending()
    return spending >= settings.DAILY_AI_BUDGET_USD


async def check_budget_and_notify():
    from config.settings import settings
    from features.notifications import notify_admin_alert

    try:
        spending = await get_daily_ai_spending()
        budget = settings.DAILY_AI_BUDGET_USD
        if budget <= 0:
            return

        fraction = spending / budget

        if fraction >= 1.0:
            await notify_admin_alert(
                'budget_exceeded',
                f"Spent: ${spending:.4f}\nBudget: ${budget:.2f}\n\nAI paused for free tier students."
            )
        elif fraction >= settings.AI_BUDGET_WARNING_THRESHOLD:
            await notify_admin_alert(
                'budget_warning',
                f"Spent: ${spending:.4f} ({fraction*100:.0f}% of daily budget)\nBudget: ${budget:.2f}"
            )
    except Exception as e:
        print(f"Budget check error: {e}")

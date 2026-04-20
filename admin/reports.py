"""
Admin Reports

Generates and sends detailed reports to the founder via WhatsApp.
These reports give you complete visibility into how WaxPrep is performing
without needing to log into any dashboard.

Reports are:
1. Daily morning report (automated at 7 AM)
2. Weekly summary (every Monday at 8 AM)
3. Real-time alerts for important events
"""

from database.client import supabase
from whatsapp.sender import send_admin_whatsapp
from utils.helpers import nigeria_now, nigeria_today
from config.settings import settings

async def send_weekly_report():
    """Sends a comprehensive weekly report every Monday morning."""
    from datetime import timedelta
    
    today = nigeria_today()
    week_ago = (nigeria_now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    # Gather 7-day metrics
    new_students = supabase.table('students').select('id', count='exact')\
        .gte('created_at', week_ago).execute()
    
    active_students = supabase.table('students').select('id', count='exact')\
        .gte('last_study_date', week_ago).execute()
    
    payments = supabase.table('payments').select('amount_naira')\
        .gte('completed_at', week_ago)\
        .eq('status', 'completed').execute()
    
    weekly_revenue = sum(p['amount_naira'] for p in (payments.data or []))
    
    total_students = supabase.table('students').select('id', count='exact').execute()
    
    paying = supabase.table('students').select('id', count='exact')\
        .neq('subscription_tier', 'free').execute()
    
    report = (
        f"📊 *WaxPrep Weekly Report*\n"
        f"_Week ending {today}_\n\n"
        
        f"👥 *Students*\n"
        f"Total: {total_students.count or 0:,}\n"
        f"New this week: +{new_students.count or 0}\n"
        f"Active this week: {active_students.count or 0:,}\n"
        f"Paying subscribers: {paying.count or 0:,}\n\n"
        
        f"💰 *Revenue*\n"
        f"This week: ₦{weekly_revenue:,}\n\n"
        
        f"_Great work! Keep going — Nigeria needs WaxPrep._ 🇳🇬"
    )
    
    await send_admin_whatsapp(report)

async def send_alert(alert_type: str, details: str):
    """
    Sends an immediate alert to the admin for important events.
    
    Alert types:
    - new_subscriber: Someone just subscribed
    - payment_failed: A payment failed
    - budget_warning: AI budget getting high
    - error: System error
    """
    icons = {
        'new_subscriber': '💰',
        'payment_failed': '⚠️',
        'budget_warning': '🤖',
        'error': '🚨',
        'milestone': '🎉',
    }
    
    icon = icons.get(alert_type, '📢')
    
    message = f"{icon} *WaxPrep Alert: {alert_type.replace('_', ' ').title()}*\n\n{details}"
    
    await send_admin_whatsapp(message)

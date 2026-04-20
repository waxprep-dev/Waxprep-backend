"""
Subscription Database Operations

Handles all subscription-related database operations.
Creating subscriptions, checking status, handling renewals, cancellations.
"""

from database.client import supabase
from utils.helpers import nigeria_now
from datetime import timedelta
from config.settings import settings

async def create_subscription(
    student_id: str,
    tier: str,
    billing_period: str,
    amount_naira: int,
    paystack_reference: str = None,
    promo_code: str = None,
    discount_applied: int = 0
) -> dict:
    """
    Creates a new subscription record for a student.
    Called after successful payment confirmation from Paystack.
    """
    now = nigeria_now()
    
    if billing_period == 'yearly':
        duration_days = 365
    else:
        duration_days = 30
    
    expires_at = now + timedelta(days=duration_days)
    grace_period_end = expires_at + timedelta(days=settings.GRACE_PERIOD_DAYS)
    
    subscription_data = {
        'student_id': student_id,
        'tier': tier,
        'billing_period': billing_period,
        'amount_naira': amount_naira,
        'started_at': now.isoformat(),
        'expires_at': expires_at.isoformat(),
        'is_active': True,
        'promo_code_used': promo_code,
        'discount_applied': discount_applied,
        'grace_period_ends_at': grace_period_end.isoformat(),
    }
    
    # Deactivate any previous active subscriptions
    supabase.table('subscriptions')\
        .update({'is_active': False})\
        .eq('student_id', student_id)\
        .eq('is_active', True)\
        .execute()
    
    # Create the new subscription
    result = supabase.table('subscriptions').insert(subscription_data).execute()
    
    if result.data:
        # Update the student record
        supabase.table('students').update({
            'subscription_tier': tier,
            'subscription_expires_at': expires_at.isoformat(),
            'is_trial_active': False,
            'updated_at': now.isoformat(),
        }).eq('id', student_id).execute()
    
    return result.data[0] if result.data else None

async def get_active_subscription(student_id: str) -> dict | None:
    """Gets the currently active subscription for a student."""
    result = supabase.table('subscriptions')\
        .select('*')\
        .eq('student_id', student_id)\
        .eq('is_active', True)\
        .order('created_at', desc=True)\
        .limit(1)\
        .execute()
    
    return result.data[0] if result.data else None

async def cancel_subscription(student_id: str, reason: str = None) -> bool:
    """Cancels a student's active subscription."""
    now = nigeria_now()
    
    result = supabase.table('subscriptions')\
        .update({
            'is_active': False,
            'auto_renew': False,
            'cancelled_at': now.isoformat(),
            'cancel_reason': reason,
        })\
        .eq('student_id', student_id)\
        .eq('is_active', True)\
        .execute()
    
    return bool(result.data)

async def get_subscription_history(student_id: str) -> list:
    """Gets all past subscriptions for a student."""
    result = supabase.table('subscriptions')\
        .select('*')\
        .eq('student_id', student_id)\
        .order('created_at', desc=True)\
        .execute()
    
    return result.data or []

async def generate_paystack_payment_link(
    student: dict,
    tier: str,
    billing_period: str
) -> str:
    """
    Generates a Paystack payment link for a student to pay for their subscription.
    
    Returns the payment URL that the student can tap to pay.
    """
    import httpx
    
    price_map = {
        ('scholar', 'monthly'): settings.SCHOLAR_MONTHLY,
        ('scholar', 'yearly'): settings.SCHOLAR_YEARLY,
        ('pro', 'monthly'): settings.PRO_MONTHLY,
        ('pro', 'yearly'): settings.PRO_YEARLY,
        ('elite', 'monthly'): settings.ELITE_MONTHLY,
        ('elite', 'yearly'): settings.ELITE_YEARLY,
    }
    
    amount_naira = price_map.get((tier.lower(), billing_period.lower()))
    if not amount_naira:
        raise ValueError(f"Invalid tier/billing combination: {tier}/{billing_period}")
    
    # Get student's phone for reference
    phone_result = supabase.table('platform_sessions').select('platform_user_id')\
        .eq('student_id', student['id'])\
        .eq('platform', 'whatsapp')\
        .execute()
    
    phone = phone_result.data[0]['platform_user_id'] if phone_result.data else ''
    
    # Create unique reference
    import time
    reference = f"WAX-{student['wax_id']}-{int(time.time())}"
    
    payload = {
        "email": f"{student['wax_id'].lower().replace('-', '')}@waxprep.ng",
        "amount": amount_naira * 100,  # Paystack uses kobo (100 kobo = 1 Naira)
        "reference": reference,
        "callback_url": "https://waxprep.ng/payment/success",
        "metadata": {
            "student_id": student['id'],
            "wax_id": student['wax_id'],
            "plan": tier,
            "billing_period": billing_period,
            "phone": phone,
            "student_name": student.get('name', ''),
        },
        "channels": ["card", "bank", "ussd", "qr", "mobile_money", "bank_transfer"],
    }
    
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.PAYSTACK_API_URL}/transaction/initialize",
            headers=headers,
            json=payload
        )
        
        data = response.json()
        
        if data.get('status'):
            return data['data']['authorization_url']
        else:
            raise Exception(f"Paystack initialization failed: {data.get('message', 'Unknown error')}")

async def verify_paystack_payment(reference: str) -> dict:
    """
    Verifies a payment with Paystack.
    Used to confirm a payment actually went through.
    """
    import httpx
    
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.PAYSTACK_API_URL}/transaction/verify/{reference}",
            headers=headers
        )
        
        return response.json()

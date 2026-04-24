"""
Subscription Database Operations
Fixes: proper email handling, PAYG support, better error messages
"""
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
"""Creates a new subscription record for a student."""
from database.client import supabase
from helpers import nigeria_now
from datetime import timedelta
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

supabase.table('subscriptions')\
    .update({'is_active': False})\
    .eq('student_id', student_id)\
    .eq('is_active', True)\
    .execute()

result = supabase.table('subscriptions').insert(subscription_data).execute()

if result.data:
    supabase.table('students').update({
        'subscription_tier': tier,
        'subscription_expires_at': expires_at.isoformat(),
        'is_trial_active': False,
        'updated_at': now.isoformat(),
    }).eq('id', student_id).execute()

return result.data[0] if result.data else None
async def get_active_subscription(student_id: str) -> dict | None:
"""Gets the currently active subscription for a student."""
from database.client import supabase
result = supabase.table('subscriptions')
.select('*')
.eq('student_id', student_id)
.eq('is_active', True)
.order('created_at', desc=True)
.limit(1)
.execute()
return result.data[0] if result.data else None
async def generate_paystack_payment_link(
student: dict,
tier: str,
billing_period: str
) -> str:
"""
Generates a Paystack payment link for a student.
FIXED: Uses WAX ID as email prefix to avoid Paystack email issues.
"""
import httpx
import time
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

from database.client import supabase
phone_result = supabase.table('platform_sessions').select('platform_user_id')\
    .eq('student_id', student['id'])\
    .eq('platform', 'whatsapp')\
    .execute()

phone = phone_result.data[0]['platform_user_id'] if phone_result.data else ''

clean_wax = student['wax_id'].lower().replace('-', '')
student_email = f"{clean_wax}@students.waxprep.ng"

reference = f"WAX-{student['wax_id']}-{int(time.time())}"

payload = {
    "email": student_email,
    "amount": amount_naira * 100,
    "reference": reference,
    "callback_url": f"https://waxprep.ng/payment/success?ref={reference}",
    "metadata": {
        "student_id": student['id'],
        "wax_id": student['wax_id'],
        "plan": tier,
        "billing_period": billing_period,
        "phone": phone,
        "student_name": student.get('name', ''),
        "custom_fields": [
            {
                "display_name": "Student Name",
                "variable_name": "student_name",
                "value": student.get('name', '')
            },
            {
                "display_name": "WAX ID",
                "variable_name": "wax_id",
                "value": student['wax_id']
            }
        ]
    },
    "channels": ["card", "bank", "ussd", "qr", "mobile_money", "bank_transfer"],
    "currency": "NGN",
}

headers = {
    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
    "Content-Type": "application/json",
}

if not settings.PAYSTACK_SECRET_KEY:
    raise Exception("Paystack secret key not configured. Please set PAYSTACK_SECRET_KEY in environment variables.")

async with httpx.AsyncClient(timeout=30.0) as client:
    response = await client.post(
        f"{settings.PAYSTACK_API_URL}/transaction/initialize",
        headers=headers,
        json=payload
    )

    if response.status_code != 200:
        error_text = response.text[:200]
        print(f"Paystack API error {response.status_code}: {error_text}")
        raise Exception(f"Paystack API returned {response.status_code}. Check your PAYSTACK_SECRET_KEY.")

    data = response.json()

    if data.get('status'):
        return data['data']['authorization_url']
    else:
        raise Exception(f"Paystack initialization failed: {data.get('message', 'Unknown error')}")
async def generate_payg_payment_link(
student: dict,
package: str
) -> str:
"""
Generates a Pay-As-You-Go payment link for question credits.
Packages: '100', '250', '500'
"""
import httpx
import time
package_map = {
    '100': settings.PAYG_100_QUESTIONS,
    '250': settings.PAYG_250_QUESTIONS,
    '500': settings.PAYG_500_QUESTIONS,
}

amount_naira = package_map.get(package)
if not amount_naira:
    raise ValueError(f"Invalid PAYG package: {package}")

clean_wax = student['wax_id'].lower().replace('-', '')
student_email = f"{clean_wax}@students.waxprep.ng"

reference = f"PAYG-{student['wax_id']}-{package}-{int(time.time())}"

payload = {
    "email": student_email,
    "amount": amount_naira * 100,
    "reference": reference,
    "metadata": {
        "student_id": student['id'],
        "wax_id": student['wax_id'],
        "plan": 'payg',
        "payg_questions": int(package),
        "billing_period": 'one_time',
    },
    "channels": ["card", "bank", "ussd", "qr", "mobile_money", "bank_transfer"],
    "currency": "NGN",
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
        raise Exception(f"PAYG link failed: {data.get('message', 'Unknown error')}")
async def verify_paystack_payment(reference: str) -> dict:
"""Verifies a payment with Paystack."""
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

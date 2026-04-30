"""
Subscription Database Operations
Includes full discount code validation before payment link generation.
"""

from config.settings import settings


async def validate_promo_code_for_payment(
    code: str,
    student: dict,
    tier: str,
    billing_period: str,
) -> dict:
    """
    Validates a promo code and calculates the discounted price.
    Returns dict with: valid, discount_percent, final_amount, original_amount,
                       promo_id, error_message, code_type, bonus_days.
    """
    from database.client import supabase
    from helpers import nigeria_now
    from datetime import datetime

    original_amount = settings.get_price_for_tier(tier, billing_period)
    base_result = {
        'valid': False,
        'discount_percent': 0,
        'final_amount': original_amount,
        'original_amount': original_amount,
        'promo_id': None,
        'error_message': None,
        'code_type': None,
        'bonus_days': 0,
    }

    if not code or not code.strip():
        return base_result

    code = code.strip().upper()

    try:
        result = supabase.table('promo_codes')\
            .select('*')\
            .eq('code', code)\
            .eq('is_active', True)\
            .execute()

        if not result.data:
            return {**base_result, 'error_message': f"Code *{code}* is not valid or has expired."}

        promo = result.data[0]
        now = nigeria_now()

        # Check expiry
        if promo.get('expires_at'):
            try:
                exp = datetime.fromisoformat(str(promo['expires_at']).replace('Z', '+00:00'))
                if exp < now:
                    return {**base_result, 'error_message': f"Code *{code}* has expired."}
            except Exception:
                pass

        # Check usage limit
        if promo.get('max_uses') and promo.get('current_uses', 0) >= promo['max_uses']:
            return {**base_result, 'error_message': f"Code *{code}* has reached its usage limit."}

        # Check if already used by this student
        existing = supabase.table('promo_code_uses')\
            .select('id')\
            .eq('promo_code_id', promo['id'])\
            .eq('student_id', student['id'])\
            .execute()

        if existing.data:
            return {**base_result, 'error_message': f"You have already used code *{code}*."}

        code_type = promo.get('code_type', '')

        # Calculate discount for subscription payments
        discount_percent = 0
        final_amount = original_amount
        bonus_days = promo.get('bonus_days', 0) or 0

        if code_type == 'discount_percent':
            discount_percent = promo.get('discount_percent', 0) or 0
            discount_amount = int(original_amount * discount_percent / 100)
            final_amount = max(100, original_amount - discount_amount)

        elif code_type == 'full_trial':
            # No discount on subscription, just trial extension
            discount_percent = 0
            final_amount = original_amount

        elif code_type == 'tier_upgrade':
            # If upgrading to a specific tier and the code unlocks it free
            if promo.get('tier_to_unlock', '').lower() == tier.lower():
                discount_percent = 100
                final_amount = 0
            else:
                discount_percent = 0

        return {
            'valid': True,
            'discount_percent': discount_percent,
            'final_amount': final_amount,
            'original_amount': original_amount,
            'promo_id': promo['id'],
            'promo_data': promo,
            'code_type': code_type,
            'bonus_days': bonus_days,
            'error_message': None,
        }

    except Exception as e:
        print(f"Promo validation error: {e}")
        return {**base_result, 'error_message': "Could not validate that code right now. Try again."}


async def mark_promo_used(promo_id: str, student_id: str, context: dict = None):
    """Marks a promo code as used by a student."""
    from database.client import supabase
    try:
        supabase.table('promo_code_uses').insert({
            'promo_code_id': promo_id,
            'student_id': student_id,
            'benefit_applied': context or {},
        }).execute()

        supabase.table('promo_codes').update({
            'current_uses': supabase.table('promo_codes')\
                .select('current_uses').eq('id', promo_id).execute().data[0].get('current_uses', 0) + 1
        }).eq('id', promo_id).execute()
    except Exception as e:
        print(f"Mark promo used error: {e}")


async def apply_trial_extension(student: dict, validation: dict) -> bool:
    """Extends the student's trial by the bonus days specified in the promo code."""
    from database.client import supabase
    from helpers import nigeria_now
    from datetime import timedelta

    bonus_days = validation.get('bonus_days', 3)
    try:
        # Get current trial expiry
        result = supabase.table('students').select('trial_expires_at')\
            .eq('id', student['id']).execute()
        if not result.data:
            return False

        current_exp = result.data[0].get('trial_expires_at')
        if current_exp:
            from datetime import datetime
            exp_dt = datetime.fromisoformat(current_exp.replace('Z', '+00:00'))
            new_exp = max(exp_dt, nigeria_now()) + timedelta(days=bonus_days)
        else:
            new_exp = nigeria_now() + timedelta(days=bonus_days)

        supabase.table('students').update({
            'is_trial_active': True,
            'trial_expires_at': new_exp.isoformat(),
        }).eq('id', student['id']).execute()

        # Mark promo used
        promo_id = validation.get('promo_id')
        if promo_id:
            await mark_promo_used(promo_id, student['id'], {'action': 'trial_extension', 'days': bonus_days})

        return True
    except Exception as e:
        print(f"Trial extension error: {e}")
        return False


async def generate_paystack_payment_link(
    student: dict,
    tier: str,
    billing_period: str,
    discount_percent: int = 0,
    promo_code: str = None,
) -> tuple[str, int]:
    """
    Generates a Paystack payment link.
    Returns (url, final_amount_naira).
    Discount is already calculated and passed in.
    """
    import httpx
    import time

    original_amount = settings.get_price_for_tier(tier, billing_period)
    if original_amount == 0:
        raise ValueError(f"Invalid tier/billing combination: {tier}/{billing_period}")

    if discount_percent > 0:
        discount = int(original_amount * discount_percent / 100)
        amount_naira = max(100, original_amount - discount)
    else:
        amount_naira = original_amount

    from database.client import supabase
    phone_result = supabase.table('platform_sessions').select('platform_user_id')\
        .eq('student_id', student['id']).eq('platform', 'whatsapp').execute()
    phone = phone_result.data[0]['platform_user_id'] if phone_result.data else ''

    clean_wax = student['wax_id'].lower().replace('-', '')
    student_email = f"{clean_wax}@students.waxprep.ng"
    reference = f"WAX-{student['wax_id']}-{int(time.time())}"

    metadata = {
        "student_id": student['id'],
        "wax_id": student['wax_id'],
        "plan": tier,
        "billing_period": billing_period,
        "phone": phone,
        "student_name": student.get('name', ''),
        "amount_naira": amount_naira,
        "original_amount": original_amount,
        "discount_percent": discount_percent,
        "promo_code_applied": promo_code or '',
        "custom_fields": [
            {"display_name": "Student Name", "variable_name": "student_name", "value": student.get('name', '')},
            {"display_name": "WAX ID", "variable_name": "wax_id", "value": student['wax_id']},
        ]
    }

    payload = {
        "email": student_email,
        "amount": amount_naira * 100,
        "reference": reference,
        "callback_url": f"{settings.PAYMENT_SUCCESS_URL}?ref={reference}",
        "metadata": metadata,
        "channels": ["card", "bank", "ussd", "qr", "mobile_money", "bank_transfer"],
        "currency": "NGN",
    }

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    if not settings.PAYSTACK_SECRET_KEY:
        raise Exception("Paystack secret key not configured. Set PAYSTACK_SECRET_KEY in environment variables.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.PAYSTACK_API_URL}/transaction/initialize",
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            raise Exception(f"Paystack API returned {response.status_code}: {response.text[:200]}")

        data = response.json()
        if data.get('status'):
            return data['data']['authorization_url'], amount_naira
        else:
            raise Exception(f"Paystack initialization failed: {data.get('message', 'Unknown error')}")


async def generate_payg_payment_link(student: dict, package: str) -> tuple[str, int]:
    """Generates a Pay-As-You-Go payment link. Returns (url, amount)."""
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
        "callback_url": f"{settings.PAYMENT_SUCCESS_URL}?ref={reference}",
        "metadata": {
            "student_id": student['id'],
            "wax_id": student['wax_id'],
            "plan": 'payg',
            "payg_questions": int(package),
            "billing_period": 'one_time',
            "amount_naira": amount_naira,
        },
        "channels": ["card", "bank", "ussd", "qr", "mobile_money", "bank_transfer"],
        "currency": "NGN",
    }

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    if not settings.PAYSTACK_SECRET_KEY:
        raise Exception("Paystack secret key not configured.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.PAYSTACK_API_URL}/transaction/initialize",
            headers=headers,
            json=payload
        )
        data = response.json()
        if data.get('status'):
            return data['data']['authorization_url'], amount_naira
        else:
            raise Exception(f"PAYG link failed: {data.get('message', 'Unknown error')}")


async def verify_paystack_payment(reference: str) -> dict:
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

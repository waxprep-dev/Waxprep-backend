"""
Command Handlers — Minimal Set

Only the commands that genuinely need specific non-AI handling.
Everything else is handled naturally by Wax in conversation.

Remaining hard commands:
- SUBSCRIBE: initiates payment flow
- PAYG: buy question credits
- PROMO: apply promo code
- MYID: show WAX ID (also handled in handler.py)
"""


async def handle_payg(phone: str, student: dict, conversation: dict, message: str):
    from whatsapp.sender import send_whatsapp_message
    from config.settings import settings
    from helpers import format_naira

    parts = message.strip().upper().split()
    package = parts[1] if len(parts) > 1 else None

    if not package or package not in ['100', '250', '500']:
        await send_whatsapp_message(
            phone,
            "*Buy Extra Question Credits*\n\n"
            "Credits never expire and work alongside your daily limit.\n\n"
            f"*PAYG 100* — {format_naira(settings.PAYG_100_QUESTIONS)} — 100 extra credits\n"
            f"*PAYG 250* — {format_naira(settings.PAYG_250_QUESTIONS)} — 250 extra credits\n"
            f"*PAYG 500* — {format_naira(settings.PAYG_500_QUESTIONS)} — 500 extra credits\n\n"
            "Example: type *PAYG 100* to buy 100 credits now."
        )
        return

    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(phone, f"Generating your payment link, {name}...")

    try:
        from database.subscriptions import generate_payg_payment_link
        payment_url, amount = await generate_payg_payment_link(student, package)

        await send_whatsapp_message(
            phone,
            f"*Payment Link Ready*\n\n"
            f"Package: {package} question credits\n"
            f"Amount: {format_naira(amount)}\n\n"
            f"Tap to pay securely:\n{payment_url}\n\n"
            "Credits are added automatically the moment payment confirms."
        )

    except Exception as e:
        print(f"PAYG link error: {e}")
        await send_whatsapp_message(
            phone,
            "Could not generate your payment link right now. Please try again in a few minutes."
        )


async def handle_promo_code(phone: str, student: dict, conversation: dict, message: str):
    """Handles promo codes applied outside of checkout."""
    from whatsapp.sender import send_whatsapp_message
    from database.client import supabase
    from helpers import nigeria_now
    from datetime import datetime

    parts = message.strip().upper().split()
    code = parts[1] if len(parts) >= 2 else None

    if not code:
        await send_whatsapp_message(
            phone,
            "To apply a promo code, type:\n*PROMO [YOUR CODE]*\n\nExample: *PROMO DAYXK2P*"
        )
        return

    result = supabase.table('promo_codes').select('*')\
        .eq('code', code).eq('is_active', True).execute()

    if not result.data:
        await send_whatsapp_message(
            phone,
            f"Code *{code}* is not valid or has expired.\n\n"
            "Double check the code and try again."
        )
        return

    promo = result.data[0]
    now = nigeria_now()

    if promo.get('expires_at'):
        try:
            exp = datetime.fromisoformat(str(promo['expires_at']).replace('Z', '+00:00'))
            if exp < now:
                await send_whatsapp_message(phone, f"Code *{code}* has expired.")
                return
        except Exception:
            pass

    if promo.get('max_uses') and promo.get('current_uses', 0) >= promo['max_uses']:
        await send_whatsapp_message(phone, f"Code *{code}* has reached its usage limit.")
        return

    existing = supabase.table('promo_code_uses').select('id')\
        .eq('promo_code_id', promo['id']).eq('student_id', student['id']).execute()

    if existing.data:
        await send_whatsapp_message(phone, f"You have already used code *{code}*.")
        return

    benefit_msg = await _apply_promo_benefit(student, promo)

    supabase.table('promo_code_uses').insert({
        'promo_code_id': promo['id'],
        'student_id': student['id'],
        'benefit_applied': {'code': code, 'type': promo['code_type']}
    }).execute()

    try:
        current = supabase.table('promo_codes').select('current_uses').eq('id', promo['id']).execute()
        current_count = current.data[0].get('current_uses', 0) if current.data else 0
        supabase.table('promo_codes').update({
            'current_uses': current_count + 1
        }).eq('id', promo['id']).execute()
    except Exception:
        pass

    await send_whatsapp_message(phone, f"*Code Applied: {code}*\n\n{benefit_msg}")


async def _apply_promo_benefit(student: dict, promo: dict) -> str:
    from database.students import update_student
    from helpers import nigeria_now
    from datetime import timedelta, datetime
    from database.cache import set_bonus_questions

    code_type = promo['code_type']
    student_id = student['id']

    if code_type == 'full_trial':
        bonus_days = promo.get('bonus_days', 3)
        trial_exp_str = student.get('trial_expires_at')
        if trial_exp_str:
            try:
                current_end = datetime.fromisoformat(str(trial_exp_str).replace('Z', '+00:00'))
                new_end = max(current_end, nigeria_now()) + timedelta(days=bonus_days)
            except Exception:
                new_end = nigeria_now() + timedelta(days=bonus_days)
        else:
            new_end = nigeria_now() + timedelta(days=bonus_days)

        await update_student(student_id, {
            'trial_expires_at': new_end.isoformat(),
            'is_trial_active': True
        })
        return (
            f"+{bonus_days} extra trial days!\n\n"
            f"Your trial now expires: {new_end.strftime('%d %B %Y')}\n\n"
            "Full access to everything extended. Keep studying!"
        )

    elif code_type == 'discount_percent':
        discount = promo.get('discount_percent', 10)
        return (
            f"{discount}% discount saved!\n\n"
            "This discount will be applied when you type *SUBSCRIBE* and pick a plan.\n"
            "Enter this same code during checkout."
        )

    elif code_type == 'tier_upgrade':
        tier = promo.get('tier_to_unlock', 'scholar')
        days = promo.get('bonus_days', 30)
        new_expires = nigeria_now() + timedelta(days=days)
        await update_student(student_id, {
            'subscription_tier': tier,
            'subscription_expires_at': new_expires.isoformat()
        })
        return (
            f"Upgraded to {tier.capitalize()} Plan for {days} days!\n\n"
            f"Expires: {new_expires.strftime('%d %B %Y')}\n\n"
            "All features unlocked. Go learn something!"
        )

    elif code_type == 'bonus_questions':
        bonus = promo.get('bonus_questions_per_day', 20)
        days = promo.get('bonus_days', 7)
        set_bonus_questions(student_id, bonus, days)
        return f"+{bonus} extra conversation turns per day for {days} days!"

    return "Promo code applied!"

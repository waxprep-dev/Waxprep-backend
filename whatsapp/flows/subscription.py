"""
Subscription Flow — Complete with Discount Code Step

Flow:
1. Student types SUBSCRIBE → show plans
2. Student picks plan → ask for discount code
3. Student enters code or types SKIP → validate, calculate price
4. Show final price with/without discount → generate payment link
5. Send payment link
6. Paystack webhook confirms → activate subscription
"""

from whatsapp.sender import send_whatsapp_message
from database.conversations import update_conversation_state
from helpers import format_naira
from config.settings import settings


async def handle_subscription_flow(
    phone: str,
    student: dict,
    conversation: dict,
    message: str
):
    """Main entry point for all subscription interactions."""
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)
    msg_upper = message.strip().upper()

    # Direct plan selection with billing period
    if 'SCHOLAR' in msg_upper and 'MONTHLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'scholar', 'monthly')
        return

    if 'SCHOLAR' in msg_upper and 'YEARLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'scholar', 'yearly')
        return

    if 'PRO' in msg_upper and 'MONTHLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'pro', 'monthly')
        return

    if 'PRO' in msg_upper and 'YEARLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'pro', 'yearly')
        return

    # Otherwise show the menu
    await show_plans_menu(phone, student, status)


async def show_plans_menu(phone: str, student: dict, status: dict):
    """Displays available subscription plans."""
    name = student.get('name', 'Student').split()[0]
    current_tier = status.get('display_tier', 'Free')

    trial_note = ""
    if status.get('is_trial'):
        days_left = status.get('days_remaining', 0)
        trial_note = (
            f"You have *{days_left} day{'s' if days_left != 1 else ''}* left on your trial.\n"
            f"Subscribe now to keep everything after your trial ends.\n\n"
        )

    msg = (
        f"*WaxPrep Plans*\n\n"
        f"Current Plan: *{current_tier}*\n\n"
        f"{trial_note}"
        f"*Scholar Plan* — For every serious student\n\n"
        f"100 AI questions per day\n"
        f"Send textbook photos for analysis\n"
        f"Full mock exams (JAMB, WAEC, NECO)\n"
        f"Personalized weekly study plan\n"
        f"Spaced repetition revision system\n"
        f"Weak area focus mode\n"
        f"30-day conversation history\n\n"
        f"*{format_naira(settings.SCHOLAR_MONTHLY)}/month*\n"
        f"*{format_naira(settings.SCHOLAR_YEARLY)}/year* (save 17%)\n\n"
        f"To subscribe, reply with:\n"
        f"*SCHOLAR MONTHLY* — {format_naira(settings.SCHOLAR_MONTHLY)}/month\n"
        f"*SCHOLAR YEARLY* — {format_naira(settings.SCHOLAR_YEARLY)}/year\n\n"
        f"Have a discount code? You will get the chance to enter it after picking your plan.\n\n"
        f"All payments are secure via Paystack. Accepts cards, bank transfer, USSD, and mobile money."
    )

    await send_whatsapp_message(phone, msg)


async def ask_for_promo_code(
    phone: str,
    student: dict,
    conversation: dict,
    tier: str,
    billing_period: str
):
    """
    After plan selection, ask if the student has a discount code.
    This is the critical step that was missing before.
    """
    from whatsapp.handler import _get_state

    original_amount = settings.get_price_for_tier(tier, billing_period)
    period_display = "month" if billing_period == "monthly" else "year"

    msg = (
        f"*{tier.capitalize()} Plan — {format_naira(original_amount)}/{period_display}*\n\n"
        f"Do you have a discount or promo code?\n\n"
        f"Type your code now (e.g. *LAGOS50*) and I will apply it before generating your payment link.\n\n"
        f"Or type *SKIP* to proceed at the full price.\n\n"
        f"_Your code will be validated immediately._"
    )

    await send_whatsapp_message(phone, msg)

    state = _get_state(conversation)
    await update_conversation_state(
        conversation['id'], 'whatsapp', phone,
        {
            'conversation_state': {
                **state,
                'awaiting_response_for': 'subscription_promo_code',
                'pending_tier': tier,
                'pending_billing_period': billing_period,
            }
        }
    )


async def handle_promo_code_during_checkout(
    phone: str,
    student: dict,
    conversation: dict,
    message: str,
    state: dict
):
    """
    Handles the promo code input during the subscription checkout flow.
    Called when awaiting_response_for == 'subscription_promo_code'.
    """
    from database.subscriptions import validate_promo_code_for_payment, mark_promo_used

    tier = state.get('pending_tier', 'scholar')
    billing_period = state.get('pending_billing_period', 'monthly')
    msg_clean = message.strip().upper()

    if msg_clean == 'SKIP':
        # No code — proceed at full price
        await initiate_payment(phone, student, conversation, tier, billing_period,
                               discount_percent=0, promo_code=None, state=state)
        return

    # Validate the code
    code = msg_clean
    validation = await validate_promo_code_for_payment(code, student, tier, billing_period)

    if not validation['valid']:
        error = validation.get('error_message', 'Code not valid.')
        await send_whatsapp_message(
            phone,
            f"{error}\n\n"
            f"Enter another code, or type *SKIP* to proceed without a discount."
        )
        return

    discount_percent = validation.get('discount_percent', 0)
    final_amount = validation.get('final_amount', 0)
    original_amount = validation.get('original_amount', 0)

    if discount_percent > 0:
        await send_whatsapp_message(
            phone,
            f"Code *{code}* applied!\n\n"
            f"Original price: {format_naira(original_amount)}\n"
            f"Discount: {discount_percent}% off\n"
            f"*Your price: {format_naira(final_amount)}*\n\n"
            f"Generating your payment link..."
        )
    elif validation.get('code_type') == 'full_trial':
        await send_whatsapp_message(
            phone,
            f"Code *{code}* noted! This is a trial extension code.\n\n"
            f"Your trial days will be extended after payment.\n\n"
            f"Generating your payment link at the standard price..."
        )
    else:
        await send_whatsapp_message(
            phone,
            f"Code *{code}* applied! Generating your payment link..."
        )

    await initiate_payment(
        phone, student, conversation, tier, billing_period,
        discount_percent=discount_percent,
        promo_code=code,
        promo_id=validation.get('promo_id'),
        state=state
    )


async def initiate_payment(
    phone: str,
    student: dict,
    conversation: dict,
    tier: str,
    billing_period: str,
    discount_percent: int = 0,
    promo_code: str = None,
    promo_id: str = None,
    state: dict = None
):
    """Generates payment link and sends it to the student."""
    from database.subscriptions import generate_paystack_payment_link, mark_promo_used
    from database.conversations import update_conversation_state as ucs
    from whatsapp.handler import _get_state

    name = student.get('name', 'Student').split()[0]

    try:
        payment_url, final_amount = await generate_paystack_payment_link(
            student, tier, billing_period,
            discount_percent=discount_percent,
            promo_code=promo_code,
        )

        period_display = "month" if billing_period == "monthly" else "year"

        msg = (
            f"*Your Payment Link is Ready, {name}!*\n\n"
            f"Plan: *{tier.capitalize()} — {billing_period.capitalize()}*\n"
            f"Amount: *{format_naira(final_amount)}/{period_display}*\n"
        )

        if discount_percent > 0 and promo_code:
            msg += f"Discount Applied: {discount_percent}% ({promo_code})\n"

        msg += (
            f"\nTap to pay securely:\n"
            f"{payment_url}\n\n"
            f"Accepts: Cards (Verve, Mastercard, Visa), Bank Transfer, USSD, Mobile Wallets\n\n"
            f"Your plan activates automatically within 10 seconds of payment.\n"
            f"Link expires in 30 minutes. Type *SUBSCRIBE* to generate a new one."
        )

        await send_whatsapp_message(phone, msg)

        # Mark promo as used (will be confirmed after actual payment)
        if promo_id and promo_code:
            try:
                from database.subscriptions import mark_promo_used
                await mark_promo_used(promo_id, student['id'], {
                    'code': promo_code,
                    'tier': tier,
                    'billing_period': billing_period,
                    'discount_percent': discount_percent,
                })
            except Exception as e:
                print(f"Mark promo used error: {e}")

        # Clear awaiting state
        current_state = state or _get_state(conversation)
        clean_state = {k: v for k, v in current_state.items()
                      if k not in ['awaiting_response_for', 'pending_tier',
                                   'pending_billing_period']}
        await ucs(conversation['id'], 'whatsapp', phone, {'conversation_state': clean_state})

    except Exception as e:
        print(f"Payment link generation error: {e}")
        await send_whatsapp_message(
            phone,
            "Sorry, I could not generate your payment link right now.\n\n"
            "Please try again in a few minutes, or contact support if this continues.\n\n"
            "Type *SUBSCRIBE* to try again."
        )

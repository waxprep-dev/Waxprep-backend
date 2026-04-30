"""
Subscription Flow

Clean version — no more Scholar/Premium naming confusion.
Consistent: Free tier and Scholar tier only (Elite is available but secondary).
Auto-debit via Paystack Subscriptions is supported.
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
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)
    msg_upper = message.strip().upper()

    # Direct plan selection
    if 'SCHOLAR' in msg_upper and 'MONTHLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'scholar', 'monthly')
        return

    if 'SCHOLAR' in msg_upper and 'YEARLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'scholar', 'yearly')
        return

    if 'ELITE' in msg_upper and 'MONTHLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'elite', 'monthly')
        return

    if 'ELITE' in msg_upper and 'YEARLY' in msg_upper:
        await ask_for_promo_code(phone, student, conversation, 'elite', 'yearly')
        return

    # Show plans menu
    await show_plans_menu(phone, student, status)


async def show_plans_menu(phone: str, student: dict, status: dict):
    name = student.get('name', 'Student').split()[0]
    current_tier = status.get('display_tier', 'Free')

    trial_note = ""
    if status.get('is_trial'):
        days_left = status.get('days_remaining', 0)
        trial_note = (
            f"You have *{days_left} day{'s' if days_left != 1 else ''}* left on your free trial.\n"
            "Subscribe now and your trial seamlessly converts — no gap in access.\n\n"
        )

    msg = (
        f"*WaxPrep Plans, {name}*\n\n"
        f"Current Plan: *{current_tier}*\n\n"
        f"{trial_note}"

        f"*Free Plan* — Always available\n"
        f"Unlimited text questions\n"
        f"Standard AI model\n"
        f"Basic progress tracking\n"
        f"Daily challenge\n\n"

        f"*Scholar Plan — {format_naira(settings.SCHOLAR_MONTHLY)}/month*\n"
        f"Everything in Free, plus:\n"
        f"Premium AI model (smarter, deeper explanations)\n"
        f"Send textbook photos for analysis\n"
        f"Voice note learning (send voice, I respond)\n"
        f"Full mock exams (JAMB, WAEC, NECO)\n"
        f"Personalized study plan\n"
        f"Spaced repetition system\n"
        f"Priority response speed\n\n"

        f"*{format_naira(settings.SCHOLAR_MONTHLY)}/month* or "
        f"*{format_naira(settings.SCHOLAR_YEARLY)}/year* (save 17%)\n\n"

        f"To subscribe, reply with:\n"
        f"*SCHOLAR MONTHLY* or *SCHOLAR YEARLY*\n\n"

        f"Payments are secure via Paystack.\n"
        f"Accepts: Cards, bank transfer, USSD, mobile money."
    )

    await send_whatsapp_message(phone, msg)


async def ask_for_promo_code(
    phone: str,
    student: dict,
    conversation: dict,
    tier: str,
    billing_period: str
):
    from whatsapp.handler import _get_state

    original_amount = settings.get_price_for_tier(tier, billing_period)
    period_display = "month" if billing_period == "monthly" else "year"

    msg = (
        f"*{tier.capitalize()} Plan — {format_naira(original_amount)}/{period_display}*\n\n"
        "Do you have a discount or promo code?\n\n"
        "Type your code and I will apply it before generating your payment link.\n\n"
        "Or type *SKIP* to proceed at the full price."
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
    from database.subscriptions import validate_promo_code_for_payment

    tier = state.get('pending_tier', 'scholar')
    billing_period = state.get('pending_billing_period', 'monthly')
    msg_clean = message.strip().upper()

    if msg_clean == 'SKIP':
        await initiate_payment(
            phone, student, conversation, tier, billing_period,
            discount_percent=0, promo_code=None, state=state
        )
        return

    code = msg_clean
    validation = await validate_promo_code_for_payment(code, student, tier, billing_period)

    if not validation['valid']:
        error = validation.get('error_message', 'That code is not valid.')
        await send_whatsapp_message(
            phone,
            f"{error}\n\n"
            "Enter another code, or type *SKIP* to proceed without a discount."
        )
        return

    discount_percent = validation.get('discount_percent', 0)
    final_amount = validation.get('final_amount', 0)
    original_amount = validation.get('original_amount', 0)

    if discount_percent > 0:
        await send_whatsapp_message(
            phone,
            f"Code *{code}* applied!\n\n"
            f"Original: {format_naira(original_amount)}\n"
            f"Discount: {discount_percent}% off\n"
            f"*Your price: {format_naira(final_amount)}*\n\n"
            "Generating your payment link..."
        )
    else:
        await send_whatsapp_message(
            phone,
            f"Code *{code}* noted! Generating your payment link..."
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
            f"*Payment Link Ready, {name}!*\n\n"
            f"Plan: *{tier.capitalize()} — {billing_period.capitalize()}*\n"
            f"Amount: *{format_naira(final_amount)}/{period_display}*\n"
        )

        if discount_percent > 0 and promo_code:
            msg += f"Discount: {discount_percent}% ({promo_code})\n"

        msg += (
            f"\nTap to pay securely:\n"
            f"{payment_url}\n\n"
            f"Accepts: Verve, Mastercard, Visa, Bank Transfer, USSD, Mobile Wallets\n\n"
            f"Your plan activates automatically within seconds of payment.\n"
            "Link expires in 30 minutes. Type *SUBSCRIBE* to generate a new one."
        )

        await send_whatsapp_message(phone, msg)

        if promo_id and promo_code:
            try:
                await mark_promo_used(promo_id, student['id'], {
                    'code': promo_code,
                    'tier': tier,
                    'billing_period': billing_period,
                    'discount_percent': discount_percent,
                })
            except Exception as e:
                print(f"Mark promo used error: {e}")

        current_state = state or _get_state(conversation)
        clean_state = {
            k: v for k, v in current_state.items()
            if k not in ['awaiting_response_for', 'pending_tier', 'pending_billing_period']
        }
        await ucs(conversation['id'], 'whatsapp', phone, {'conversation_state': clean_state})

    except Exception as e:
        print(f"Payment link generation error: {e}")
        await send_whatsapp_message(
            phone,
            "Could not generate your payment link right now.\n\n"
            "Please try again in a few minutes. Type *SUBSCRIBE* to retry."
        )

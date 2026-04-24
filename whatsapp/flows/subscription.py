"""
Subscription Flow

Handles the complete payment and subscription process over WhatsApp.

When a student types SUBSCRIBE:
1. Show them the plans
2. They pick a plan (SCHOLAR MONTHLY, SCHOLAR YEARLY, etc.)
3. Generate a Paystack payment link
4. Send them the link
5. Wait for Paystack webhook to confirm payment
6. Activate their subscription automatically
7. Send them a celebration message
"""

from whatsapp.sender import send_whatsapp_message
from database.subscriptions import generate_paystack_payment_link
from database.conversations import update_conversation_state, set_awaiting_response
from helpers import format_naira
from config.settings import settings


async def handle_subscription_flow(
    phone: str,
    student: dict,
    conversation: dict,
    message: str
):
    """Main entry point for subscription handling."""

    from database.students import get_student_subscription_status
    status = await get_student_subscription_status(student)

    msg_upper = message.strip().upper()

    if 'SCHOLAR' in msg_upper and 'MONTHLY' in msg_upper:
        await initiate_payment(phone, student, conversation, 'scholar', 'monthly')
        return

    if 'SCHOLAR' in msg_upper and 'YEARLY' in msg_upper:
        await initiate_payment(phone, student, conversation, 'scholar', 'yearly')
        return

    await show_plans_menu(phone, student, status)


async def show_plans_menu(phone: str, student: dict, status: dict):
    """Shows the subscription plans menu."""

    name = student.get('name', 'Student').split()[0]
    current_tier = status.get('display_tier', 'Free')

    scholar_monthly = format_naira(settings.SCHOLAR_MONTHLY)
    scholar_yearly = format_naira(settings.SCHOLAR_YEARLY)

    trial_note = ""
    if status.get('is_trial'):
        days_left = status.get('days_remaining', 0)
        trial_note = (
            f"You have *{days_left} day{'s' if days_left != 1 else ''}* left on your trial.\n"
            f"Subscribe now to keep everything after your trial ends.\n\n"
        )

    msg = (
        f"WaxPrep Plans\n\n"
        f"Current Plan: *{current_tier}*\n\n"
        f"{trial_note}"
        f"Scholar Plan\n"
        f"The essential plan for every serious student.\n\n"
        f"100 AI questions per day\n"
        f"Image upload (send textbook photos)\n"
        f"Voice note input\n"
        f"Full mock exams (2x weekly)\n"
        f"Personalized study plan\n"
        f"Spaced repetition system\n"
        f"Weak area focus mode\n"
        f"30 days conversation history\n\n"
        f"*{scholar_monthly}/month*\n"
        f"*{scholar_yearly}/year* (save 17%)\n\n"
        f"To subscribe, reply with:\n"
        f"SCHOLAR MONTHLY — {scholar_monthly}/month\n"
        f"SCHOLAR YEARLY — {scholar_yearly}/year\n\n"
        f"Pro and Elite plans coming soon!\n\n"
        f"All payments are secure via Paystack.\n"
        f"Accepts cards, bank transfer, USSD, and mobile money."
    )

    await send_whatsapp_message(phone, msg)


async def initiate_payment(
    phone: str,
    student: dict,
    conversation: dict,
    tier: str,
    billing_period: str
):
    """Generates a payment link and sends it to the student."""
    name = student.get('name', 'Student').split()[0]

    await send_whatsapp_message(
        phone,
        f"Generating your secure payment link, {name}...\n\nOne moment!"
    )

    try:
        payment_url = await generate_paystack_payment_link(student, tier, billing_period)

        price_map = {
            ('scholar', 'monthly'): settings.SCHOLAR_MONTHLY,
            ('scholar', 'yearly'): settings.SCHOLAR_YEARLY,
        }
        amount = price_map.get((tier, billing_period), settings.SCHOLAR_MONTHLY)

        period_display = "month" if billing_period == "monthly" else "year"
        tier_display = tier.capitalize()

        msg = (
            f"Your Payment Link is Ready!\n\n"
            f"Plan: *{tier_display}*\n"
            f"Amount: *{format_naira(amount)}/{period_display}*\n\n"
            f"Tap this link to pay securely:\n"
            f"{payment_url}\n\n"
            f"Cards (Verve, Mastercard, Visa)\n"
            f"Bank Transfer\n"
            f"USSD (*737#, *770#, etc.)\n"
            f"Mobile Wallets\n\n"
            f"After payment, your plan activates automatically — usually within 10 seconds.\n\n"
            f"The link expires in 30 minutes. Generate a new one with SUBSCRIBE if needed."
        )

        await send_whatsapp_message(phone, msg)

    except Exception as e:
        print(f"Payment link generation error: {e}")
        await send_whatsapp_message(
            phone,
            "Sorry, I couldn't generate a payment link right now.\n\n"
            "Please try again in a few minutes, or contact support if this continues.\n\n"
            "Type SUBSCRIBE to try again."
        )

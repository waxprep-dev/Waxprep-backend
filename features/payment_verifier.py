"""
Payment Verifier — Manual payment confirmation.
Lets students check if their payment went through when the webhook was missed.
"""

import httpx
from config.settings import settings


async def verify_payment_from_paystack(reference: str) -> dict:
    """Calls Paystack to verify a transaction by reference."""
    url = f"{settings.PAYSTACK_API_URL}/transaction/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") and data.get("data", {}).get("status") == "success":
                    return {
                        "success": True,
                        "amount": data["data"]["amount"] // 100,
                        "reference": reference,
                        "plan": data["data"].get("metadata", {}).get("plan", "scholar"),
                        "billing_period": data["data"].get("metadata", {}).get("billing_period", "monthly"),
                    }
            return {"success": False, "error": "Payment not found or not successful"}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


async def handle_verify_payment(phone_or_chat_id: str, student: dict, platform: str = "whatsapp"):
    """Handles the VERIFY PAYMENT command from a student."""
    from database.client import supabase
    from helpers import format_naira

    name = student.get("name", "Student").split()[0]

    # Find their most recent pending payment
    try:
        recent = supabase.table("payments") \
            .select("paystack_reference, amount_naira") \
            .eq("student_id", student["id"]) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if not recent.data:
            await _send(phone_or_chat_id, platform,
                f"No recent payment found, {name}. Type *SUBSCRIBE* to start a new one."
            )
            return

        reference = recent.data[0]["paystack_reference"]
        result = await verify_payment_from_paystack(reference)

        if result["success"]:
            # Activate the subscription (same logic as the webhook)
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo("Africa/Lagos"))
            plan = result["plan"]
            billing_period = result["billing_period"]
            duration_days = 365 if billing_period == "yearly" else 30
            expires = now + timedelta(days=duration_days)

            # Update student
            supabase.table("students").update({
                "subscription_tier": plan,
                "subscription_expires_at": expires.isoformat(),
                "is_trial_active": False,
                "updated_at": now.isoformat(),
            }).eq("id", student["id"]).execute()

            # Mark payment as completed
            supabase.table("payments").update({
                "status": "completed",
                "completed_at": now.isoformat(),
            }).eq("paystack_reference", reference).execute()

            await _send(phone_or_chat_id, platform,
                f"Payment verified, {name}!\n\n"
                f"Your *{plan.capitalize()} Plan* is now active until {expires.strftime('%d %B %Y')}.\n"
                f"Everything is unlocked. What do you want to study first?"
            )
        else:
            await _send(phone_or_chat_id, platform,
                f"Payment not confirmed yet, {name}. {result.get('error', '')}\n\n"
                "If you just paid, wait a minute and try again. Type *SUBSCRIBE* to generate a new link."
            )
    except Exception as e:
        print(f"Verify payment error: {e}")
        await _send(phone_or_chat_id, platform,
            f"Couldn't verify your payment right now, {name}. Type *SUBSCRIBE* to try again."
        )


async def _send(to: str, platform: str, message: str):
    """Send a message via the correct platform."""
    if platform == "whatsapp":
        from whatsapp.sender import send_whatsapp_message
        await send_whatsapp_message(to, message)
    else:
        from telegram.sender import send_telegram_message
        await send_telegram_message(int(to), message)

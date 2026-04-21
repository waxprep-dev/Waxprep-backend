"""
WaxPrep Main Application

The entry point for the entire WaxPrep backend.

KEY FIX IN THIS VERSION:
The WhatsApp webhook now reads the request body BEFORE starting the
background task. Previously the body was passed as a stale Request object
which caused silent failures. Now the body is parsed first, then passed
as a plain dictionary to the background task. This is the fix for
"messages come in but no replies are sent."
"""

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager

from config.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    print("🚀 WaxPrep is starting up...")

    # Test database connections
    try:
        from database.client import test_connections
        test_connections()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        raise

    # Start the scheduler
    try:
        from utils.scheduler import start_scheduler
        start_scheduler()
        print("✅ Scheduler started")
    except Exception as e:
        print(f"⚠️ Scheduler failed to start: {e}")
        import traceback
        traceback.print_exc()

    print("✅ WaxPrep is ready to receive messages!")

    yield

    print("👋 WaxPrep is shutting down...")
    try:
        from utils.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


app = FastAPI(
    title="WaxPrep API",
    description="Nigeria's Most Advanced AI Educational Platform",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
async def root():
    return {
        "app": "WaxPrep",
        "version": settings.APP_VERSION,
        "status": "operational",
        "message": "Nigeria's Most Advanced AI Educational Platform 🇳🇬"
    }


@app.get("/health")
async def health_check():
    from database.client import supabase, redis_client

    db_ok = False
    redis_ok = False

    try:
        supabase.table('system_config').select('config_key').limit(1).execute()
        db_ok = True
    except Exception as e:
        print(f"DB health check failed: {e}")

    try:
        redis_client.ping()
        redis_ok = True
    except Exception as e:
        print(f"Redis health check failed: {e}")

    status = "healthy" if (db_ok and redis_ok) else "degraded"
    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "cache": "ok" if redis_ok else "error",
    }


# ============================================================
# WHATSAPP WEBHOOK
# ============================================================

@app.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    """
    WhatsApp webhook verification.
    Meta calls this once when you set up the webhook in their dashboard.
    """
    params = dict(request.query_params)

    verify_token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    mode = params.get("hub.mode", "")

    if mode == "subscribe" and verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        print(f"✅ WhatsApp webhook verified successfully")
        return PlainTextResponse(content=challenge)
    else:
        print(f"❌ WhatsApp webhook verification failed. Token: '{verify_token}' Expected: '{settings.WHATSAPP_VERIFY_TOKEN}'")
        raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """
    Receives all incoming WhatsApp messages.

    CRITICAL: We read the request body HERE, synchronously, before
    adding to background task. This is the fix for silent message failures.

    The Request object's body stream can only be read ONCE.
    If we pass the Request object to a background task, the body is
    already consumed when the task tries to read it, causing silent failure.

    Solution: Read and parse the body first. Pass the parsed dict.
    """
    try:
        # READ THE BODY NOW — before it gets consumed
        body_bytes = await request.body()
        
        if not body_bytes:
            print("⚠️ Received empty webhook body")
            return JSONResponse(content={"status": "empty"}, status_code=200)

        import json
        try:
            body_data = json.loads(body_bytes)
        except json.JSONDecodeError as e:
            print(f"⚠️ Invalid JSON in webhook: {e}")
            return JSONResponse(content={"status": "invalid_json"}, status_code=200)

        print(f"📨 Webhook received: {str(body_data)[:200]}")

        # NOW add to background task — pass the parsed dict, not the request
        background_tasks.add_task(process_whatsapp_message_data, body_data)

        # Return 200 immediately so WhatsApp doesn't retry
        return JSONResponse(content={"status": "received"}, status_code=200)

    except Exception as e:
        print(f"❌ Webhook receive error: {e}")
        import traceback
        traceback.print_exc()
        # Always return 200 to WhatsApp even on error
        # Otherwise WhatsApp will keep retrying
        return JSONResponse(content={"status": "error_logged"}, status_code=200)


async def process_whatsapp_message_data(body_data: dict):
    """
    Background task that processes WhatsApp message data.
    Called with already-parsed dictionary — no Request object needed.
    All errors are caught and logged so they don't silently fail.
    """
    try:
        print(f"🔄 Processing webhook data...")
        
        entries = body_data.get('entry', [])
        
        if not entries:
            print("⚠️ No entries in webhook data")
            return

        for entry in entries:
            changes = entry.get('changes', [])
            for change in changes:
                value = change.get('value', {})
                messages = value.get('messages', [])

                for message_data in messages:
                    try:
                        print(f"📩 Processing message from: {message_data.get('from', 'unknown')}")
                        from whatsapp.handler import process_single_message
                        await process_single_message(message_data, value)
                        print(f"✅ Message processed successfully")
                    except Exception as e:
                        print(f"❌ Error processing message: {e}")
                        import traceback
                        traceback.print_exc()

    except Exception as e:
        print(f"❌ Background task error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# PAYSTACK PAYMENT WEBHOOK
# ============================================================

@app.post("/webhook/paystack")
async def paystack_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives payment confirmations from Paystack.
    Same pattern: read body first, then process in background.
    """
    import hmac
    import hashlib
    import json

    try:
        body_bytes = await request.body()
        paystack_signature = request.headers.get("x-paystack-signature", "")

        if settings.PAYSTACK_SECRET_KEY and paystack_signature:
            computed = hmac.new(
                settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
                body_bytes,
                hashlib.sha512
            ).hexdigest()

            if paystack_signature != computed:
                print(f"❌ Invalid Paystack signature")
                raise HTTPException(status_code=400, detail="Invalid signature")

        try:
            body_data = json.loads(body_bytes)
        except json.JSONDecodeError:
            return JSONResponse(content={"status": "invalid_json"}, status_code=200)

        background_tasks.add_task(process_paystack_event, body_data)
        return JSONResponse(content={"status": "received"}, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Paystack webhook error: {e}")
        return JSONResponse(content={"status": "error_logged"}, status_code=200)


async def process_paystack_event(body_data: dict):
    """Processes Paystack payment events in background."""
    try:
        event = body_data.get('event', '')
        data = body_data.get('data', {})

        print(f"💳 Paystack event: {event}")

        if event == 'charge.success':
            await handle_successful_payment(data)
        elif event == 'subscription.disable':
            print(f"Subscription disabled: {data.get('subscription_code')}")
        else:
            print(f"Unhandled Paystack event: {event}")

    except Exception as e:
        print(f"❌ Paystack processing error: {e}")
        import traceback
        traceback.print_exc()


async def handle_successful_payment(payment_data: dict):
    """Activates subscription after successful Paystack payment."""
    from database.client import supabase
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    reference = payment_data.get('reference', '')
    amount_kobo = payment_data.get('amount', 0)
    amount_naira = amount_kobo // 100
    metadata = payment_data.get('metadata', {})

    student_id = metadata.get('student_id')
    plan = metadata.get('plan', 'scholar').lower()
    billing_period = metadata.get('billing_period', 'monthly').lower()

    print(f"💰 Payment confirmed: {reference} | ₦{amount_naira} | {plan} {billing_period}")

    if not student_id:
        print(f"❌ Payment {reference} has no student_id in metadata")
        return

    duration_days = 365 if billing_period == 'yearly' else 30

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    expires = now + timedelta(days=duration_days)

    try:
        # Update student subscription
        supabase.table('students').update({
            'subscription_tier': plan,
            'subscription_expires_at': expires.isoformat(),
            'is_trial_active': False,
            'updated_at': now.isoformat(),
        }).eq('id', student_id).execute()

        # Record subscription
        supabase.table('subscriptions').insert({
            'student_id': student_id,
            'tier': plan,
            'billing_period': billing_period,
            'amount_naira': amount_naira,
            'started_at': now.isoformat(),
            'expires_at': expires.isoformat(),
            'is_active': True,
        }).execute()

        # Record payment
        supabase.table('payments').insert({
            'student_id': student_id,
            'amount_naira': amount_naira,
            'paystack_reference': reference,
            'status': 'completed',
            'completed_at': now.isoformat(),
        }).execute()

        # Get student's phone to send congratulation
        student_result = supabase.table('students').select('name').eq('id', student_id).execute()
        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student_id).eq('platform', 'whatsapp').execute()

        if student_result.data and phone_result.data:
            name = student_result.data[0]['name'].split()[0]
            phone = phone_result.data[0]['platform_user_id']

            from whatsapp.sender import send_whatsapp_message
            await send_whatsapp_message(
                phone,
                f"🎉 *Payment Confirmed, {name}!*\n\n"
                f"Welcome to *{plan.capitalize()} Plan*!\n"
                f"Your subscription is active until {expires.strftime('%d %B %Y')}.\n\n"
                f"You now have full access to all {plan.capitalize()} features.\n\n"
                f"What do you want to study first? Just ask me anything! 🚀"
            )

        print(f"✅ Subscription activated for student {student_id}")

    except Exception as e:
        print(f"❌ Payment activation error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# ADMIN API ENDPOINTS
# These are HTTP endpoints for programmatic admin access.
# The WhatsApp admin commands are handled in admin/dashboard.py
# ============================================================

@app.get("/admin/stats")
async def get_admin_stats():
    """Returns platform statistics. Add authentication before going to production."""
    from database.client import supabase, redis_client
    from datetime import datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Africa/Lagos")).strftime('%Y-%m-%d')

    try:
        total = supabase.table('students').select('id', count='exact').execute()
        active_today = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', today).execute()
        new_today = supabase.table('students').select('id', count='exact')\
            .gte('created_at', today).execute()
        paying = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()

        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        revenue_today = sum(p.get('amount_naira', 0) for p in (payments.data or []))

        ai_key = f"ai_cost:{today}"
        ai_cost = float(redis_client.get(ai_key) or 0)

        return {
            "total_students": total.count or 0,
            "active_today": active_today.count or 0,
            "new_today": new_today.count or 0,
            "paying_subscribers": paying.count or 0,
            "revenue_today_naira": revenue_today,
            "ai_cost_today_usd": round(ai_cost, 4),
            "status": "operational"
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/admin/broadcast")
async def api_broadcast(request: Request, background_tasks: BackgroundTasks):
    """
    HTTP endpoint to send broadcast messages.
    Body: {"target": "ALL|FREE|SCHOLAR|TRIAL", "message": "your message here"}
    """
    try:
        data = await request.json()
        target = data.get('target', 'ALL')
        message = data.get('message', '')

        if not message:
            return {"success": False, "error": "message is required"}

        background_tasks.add_task(run_broadcast, target, message)
        return {"success": True, "message": f"Broadcast to {target} queued"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def run_broadcast(target: str, message: str):
    """Runs a broadcast in the background."""
    try:
        from admin.dashboard import admin_broadcast
        # We simulate being admin by calling the function directly
        from config.settings import settings
        if settings.ADMIN_WHATSAPP:
            await admin_broadcast(settings.ADMIN_WHATSAPP, f"{target} {message}")
    except Exception as e:
        print(f"❌ API broadcast error: {e}")


@app.post("/admin/create-promo")
async def api_create_promo(request: Request):
    """
    HTTP endpoint to create promo codes.
    Body: {"code": "WAX2024", "code_type": "full_trial", "bonus_days": 7, "max_uses": 100}
    """
    try:
        from database.client import supabase
        data = await request.json()

        result = supabase.table('promo_codes').insert({
            'code': data.get('code', '').upper(),
            'code_type': data.get('code_type', 'full_trial'),
            'bonus_days': data.get('bonus_days', 3),
            'discount_percent': data.get('discount_percent', 0),
            'tier_to_unlock': data.get('tier_to_unlock'),
            'max_uses': data.get('max_uses', 100),
            'description': data.get('description', ''),
            'expires_at': data.get('expires_at'),
            'is_active': True,
        }).execute()

        return {"success": True, "promo_code": result.data[0] if result.data else {}}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/admin/send-message")
async def api_send_message(request: Request):
    """
    HTTP endpoint to send a message to a specific student.
    Body: {"wax_id": "WAX-A74892", "message": "Hello!"}
    """
    try:
        from database.client import supabase
        from whatsapp.sender import send_whatsapp_message

        data = await request.json()
        wax_id = data.get('wax_id', '').upper()
        message = data.get('message', '')

        if not wax_id or not message:
            return {"success": False, "error": "wax_id and message are required"}

        student = supabase.table('students').select('id, name').eq('wax_id', wax_id).execute()
        if not student.data:
            return {"success": False, "error": "Student not found"}

        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student.data[0]['id']).eq('platform', 'whatsapp').execute()

        if not phone_result.data:
            return {"success": False, "error": "Student not on WhatsApp"}

        phone = phone_result.data[0]['platform_user_id']
        await send_whatsapp_message(phone, f"📢 *Message from WaxPrep:*\n\n{message}")

        return {"success": True, "sent_to": wax_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/admin/trigger-report")
async def trigger_daily_report(background_tasks: BackgroundTasks):
    """Manually triggers the daily admin report."""
    from utils.scheduler import send_daily_admin_report
    background_tasks.add_task(send_daily_admin_report)
    return {"success": True, "message": "Daily report triggered — check your WhatsApp"}


@app.get("/admin/trigger-challenge")
async def trigger_daily_challenge(background_tasks: BackgroundTasks):
    """Manually triggers daily challenge generation."""
    from utils.scheduler import generate_daily_challenge
    background_tasks.add_task(generate_daily_challenge)
    return {"success": True, "message": "Challenge generation triggered"}


@app.get("/admin/student/{wax_id}")
async def get_student_info(wax_id: str):
    """Returns information about a specific student."""
    try:
        from database.client import supabase

        wax_id = wax_id.upper()
        if not wax_id.startswith('WAX-'):
            wax_id = 'WAX-' + wax_id.replace('WAX', '')

        result = supabase.table('students').select('*').eq('wax_id', wax_id).execute()

        if not result.data:
            return {"found": False}

        s = result.data[0]
        # Remove sensitive fields
        s.pop('pin_hash', None)
        s.pop('phone_hash', None)
        s.pop('recovery_code', None)

        return {"found": True, "student": s}
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )

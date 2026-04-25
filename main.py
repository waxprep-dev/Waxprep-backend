"""
WaxPrep Main Application
FIXES:
- Webhook message deduplication using Redis (prevents same message being processed 3-4 times)
- Admin API endpoints protected by X-Admin-Key header
- Payment webhook checks for duplicate payments before processing
- Paystack HMAC verification hardened
- Amount verification added
"""

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager

from config.settings import settings


def verify_admin_key(request: Request):
    if not settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Admin API not configured. Set ADMIN_API_KEY in environment variables."
        )
    api_key = request.headers.get("X-Admin-Key", "")
    if not api_key or api_key != settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized. Include a valid X-Admin-Key header."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("WaxPrep is starting up...")

    try:
        from database.client import test_connections
        test_connections()
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise

    try:
        from utils.scheduler import start_scheduler
        start_scheduler()
        print("Scheduler started")
    except Exception as e:
        print(f"Scheduler failed to start: {e}")
        import traceback
        traceback.print_exc()

    print("WaxPrep is ready to receive messages!")

    yield

    print("WaxPrep is shutting down...")
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


@app.get("/")
async def root():
    return {
        "app": "WaxPrep",
        "version": settings.APP_VERSION,
        "status": "operational",
        "message": "Nigeria's Most Advanced AI Educational Platform"
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


@app.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    params = dict(request.query_params)

    verify_token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    mode = params.get("hub.mode", "")

    if mode == "subscribe" and verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        print(f"WhatsApp webhook verified successfully")
        return PlainTextResponse(content=challenge)
    else:
        print(f"WhatsApp webhook verification failed. Token: '{verify_token}'")
        raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    try:
        body_bytes = await request.body()

        if not body_bytes:
            print("Received empty webhook body")
            return JSONResponse(content={"status": "empty"}, status_code=200)

        import json
        try:
            body_data = json.loads(body_bytes)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON in webhook: {e}")
            return JSONResponse(content={"status": "invalid_json"}, status_code=200)

        print(f"Webhook received: {str(body_data)[:200]}")

        background_tasks.add_task(process_whatsapp_message_data, body_data)

        return JSONResponse(content={"status": "received"}, status_code=200)

    except Exception as e:
        print(f"Webhook receive error: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"status": "error_logged"}, status_code=200)


async def process_whatsapp_message_data(body_data: dict):
    """Background task that processes WhatsApp message data with deduplication."""
    try:
        print(f"Processing webhook data...")

        entries = body_data.get('entry', [])

        if not entries:
            print("No entries in webhook data")
            return

        for entry in entries:
            changes = entry.get('changes', [])
            for change in changes:
                value = change.get('value', {})
                messages = value.get('messages', [])

                for message_data in messages:
                    try:
                        message_id = message_data.get('id', '')

                        # DEDUPLICATION - WhatsApp retries webhooks causing the same
                        # message to be processed 3-4 times. We block duplicates here.
                        if message_id:
                            try:
                                from database.client import redis_client
                                dedup_key = f"processed_msg:{message_id}"
                                already_processed = redis_client.get(dedup_key)
                                if already_processed:
                                    print(f"Duplicate webhook for message {message_id} — skipping")
                                    continue
                                # Mark as processed for 5 minutes
                                redis_client.setex(dedup_key, 300, "1")
                            except Exception as redis_err:
                                print(f"Redis dedup error (non-critical): {redis_err}")

                        print(f"Processing message from: {message_data.get('from', 'unknown')}")
                        from whatsapp.handler import process_single_message
                        await process_single_message(message_data, value)
                        print(f"Message processed successfully")
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        import traceback
                        traceback.print_exc()

    except Exception as e:
        print(f"Background task error: {e}")
        import traceback
        traceback.print_exc()


@app.post("/webhook/paystack")
async def paystack_webhook(request: Request, background_tasks: BackgroundTasks):
    import hmac
    import hashlib
    import json

    try:
        body_bytes = await request.body()
        paystack_signature = request.headers.get("x-paystack-signature", "")

        if settings.PAYSTACK_SECRET_KEY:
            if not paystack_signature:
                print("Paystack webhook received without signature — rejecting")
                raise HTTPException(status_code=400, detail="Missing signature")

            computed = hmac.new(
                settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
                body_bytes,
                hashlib.sha512
            ).hexdigest()

            if paystack_signature != computed:
                print(f"Invalid Paystack signature — possible forgery attempt")
                raise HTTPException(status_code=400, detail="Invalid signature")
        else:
            print("WARNING: PAYSTACK_SECRET_KEY not set. Rejecting webhook for security.")
            raise HTTPException(status_code=503, detail="Payment webhook not configured")

        try:
            body_data = json.loads(body_bytes)
        except json.JSONDecodeError:
            return JSONResponse(content={"status": "invalid_json"}, status_code=200)

        background_tasks.add_task(process_paystack_event, body_data)
        return JSONResponse(content={"status": "received"}, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        print(f"Paystack webhook error: {e}")
        return JSONResponse(content={"status": "error_logged"}, status_code=200)


async def process_paystack_event(body_data: dict):
    try:
        event = body_data.get('event', '')
        data = body_data.get('data', {})

        print(f"Paystack event: {event}")

        if event == 'charge.success':
            await handle_successful_payment(data)
        elif event == 'subscription.disable':
            print(f"Subscription disabled: {data.get('subscription_code')}")
        else:
            print(f"Unhandled Paystack event: {event}")

    except Exception as e:
        print(f"Paystack processing error: {e}")
        import traceback
        traceback.print_exc()


async def handle_successful_payment(payment_data: dict):
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
    payg_questions = metadata.get('payg_questions', 0)

    print(f"Payment confirmed: {reference} | N{amount_naira} | {plan} {billing_period}")

    if not student_id:
        print(f"Payment {reference} has no student_id in metadata — cannot process")
        return

    try:
        existing_payment = supabase.table('payments')\
            .select('id')\
            .eq('paystack_reference', reference)\
            .execute()

        if existing_payment.data:
            print(f"Payment {reference} already processed — skipping duplicate webhook")
            return
    except Exception as e:
        print(f"Duplicate check error: {e}")

    if plan != 'payg':
        price_map = {
            ('scholar', 'monthly'): settings.SCHOLAR_MONTHLY,
            ('scholar', 'yearly'): settings.SCHOLAR_YEARLY,
            ('pro', 'monthly'): settings.PRO_MONTHLY,
            ('pro', 'yearly'): settings.PRO_YEARLY,
            ('elite', 'monthly'): settings.ELITE_MONTHLY,
            ('elite', 'yearly'): settings.ELITE_YEARLY,
        }
        expected_amount = price_map.get((plan, billing_period))
        if expected_amount and amount_naira < (expected_amount - 10):
            print(
                f"FRAUD ALERT: Payment {reference} paid N{amount_naira} "
                f"but {plan} {billing_period} costs N{expected_amount}. Rejecting."
            )
            return

    now = datetime.now(ZoneInfo("Africa/Lagos"))

    try:
        supabase.table('payments').insert({
            'student_id': student_id,
            'amount_naira': amount_naira,
            'paystack_reference': reference,
            'status': 'completed',
            'completed_at': now.isoformat(),
            'metadata': metadata,
        }).execute()
    except Exception as e:
        print(f"Payment record error: {e}")
        return

    student_result = supabase.table('students').select('name').eq('id', student_id).execute()
    phone_result = supabase.table('platform_sessions').select('platform_user_id')\
        .eq('student_id', student_id).eq('platform', 'whatsapp').execute()

    student_name = student_result.data[0]['name'].split()[0] if student_result.data else 'Student'
    student_phone = phone_result.data[0]['platform_user_id'] if phone_result.data else None

    if plan == 'payg' and payg_questions > 0:
        try:
            current = supabase.table('students')\
                .select('payg_questions_remaining')\
                .eq('id', student_id).execute()
            current_remaining = 0
            if current.data:
                current_remaining = current.data[0].get('payg_questions_remaining', 0) or 0

            supabase.table('students').update({
                'payg_questions_remaining': current_remaining + payg_questions,
                'updated_at': now.isoformat(),
            }).eq('id', student_id).execute()

            if student_phone:
                from whatsapp.sender import send_whatsapp_message
                await send_whatsapp_message(
                    student_phone,
                    f"Payment Confirmed, {student_name}!\n\n"
                    f"{payg_questions} question credits have been added to your account.\n\n"
                    f"You now have {current_remaining + payg_questions} credits available.\n\n"
                    "Ask me any question to use them!"
                )

            print(f"PAYG credits added: {payg_questions} for student {student_id}")

        except Exception as e:
            print(f"PAYG activation error: {e}")

    else:
        duration_days = 365 if billing_period == 'yearly' else 30
        expires = now + timedelta(days=duration_days)

        try:
            supabase.table('students').update({
                'subscription_tier': plan,
                'subscription_expires_at': expires.isoformat(),
                'is_trial_active': False,
                'updated_at': now.isoformat(),
            }).eq('id', student_id).execute()

            try:
                supabase.table('subscriptions').insert({
                    'student_id': student_id,
                    'tier': plan,
                    'billing_period': billing_period,
                    'amount_naira': amount_naira,
                    'started_at': now.isoformat(),
                    'expires_at': expires.isoformat(),
                    'is_active': True,
                }).execute()
            except Exception as sub_err:
                print(f"Subscription record error (non-critical): {sub_err}")

            if student_phone:
                from whatsapp.sender import send_whatsapp_message
                await send_whatsapp_message(
                    student_phone,
                    f"Payment Confirmed, {student_name}!\n\n"
                    f"Welcome to {plan.capitalize()} Plan!\n"
                    f"Active until {expires.strftime('%d %B %Y')}.\n\n"
                    "You now have full access to all features.\n\n"
                    "What do you want to study first?"
                )

            print(f"Subscription activated for student {student_id}")

        except Exception as e:
            print(f"Payment activation error: {e}")
            import traceback
            traceback.print_exc()


@app.get("/admin/stats", dependencies=[Depends(verify_admin_key)])
async def get_admin_stats():
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


@app.post("/admin/broadcast", dependencies=[Depends(verify_admin_key)])
async def api_broadcast(request: Request, background_tasks: BackgroundTasks):
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
    try:
        from admin.dashboard import admin_broadcast
        from config.settings import settings
        if settings.ADMIN_WHATSAPP:
            await admin_broadcast(settings.ADMIN_WHATSAPP, f"{target} {message}")
    except Exception as e:
        print(f"API broadcast error: {e}")


@app.post("/admin/create-promo", dependencies=[Depends(verify_admin_key)])
async def api_create_promo(request: Request):
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


@app.post("/admin/send-message", dependencies=[Depends(verify_admin_key)])
async def api_send_message(request: Request):
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
        await send_whatsapp_message(phone, f"Message from WaxPrep:\n\n{message}")

        return {"success": True, "sent_to": wax_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/admin/trigger-report", dependencies=[Depends(verify_admin_key)])
async def trigger_daily_report(background_tasks: BackgroundTasks):
    from utils.scheduler import send_daily_admin_report
    background_tasks.add_task(send_daily_admin_report)
    return {"success": True, "message": "Daily report triggered — check your WhatsApp"}


@app.get("/admin/trigger-challenge", dependencies=[Depends(verify_admin_key)])
async def trigger_daily_challenge(background_tasks: BackgroundTasks):
    from utils.scheduler import generate_daily_challenge
    background_tasks.add_task(generate_daily_challenge)
    return {"success": True, "message": "Challenge generation triggered"}


@app.get("/admin/student/{wax_id}", dependencies=[Depends(verify_admin_key)])
async def get_student_info(wax_id: str):
    try:
        from database.client import supabase

        wax_id = wax_id.upper()
        if not wax_id.startswith('WAX-'):
            wax_id = 'WAX-' + wax_id.replace('WAX', '')

        result = supabase.table('students').select('*').eq('wax_id', wax_id).execute()

        if not result.data:
            return {"found": False}

        s = result.data[0]
        s.pop('pin_hash', None)
        s.pop('phone_hash', None)
        s.pop('recovery_code', None)

        return {"found": True, "student": s}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )

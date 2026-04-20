"""
WaxPrep Main Application

This is the entry point for the entire WaxPrep backend.
When Railway starts the server, it runs this file.

What happens when this file runs:
1. FastAPI creates a web server
2. Routes are registered (URLs that accept incoming requests)
3. The scheduler starts (for daily challenges, reports, etc.)
4. Database connections are tested
5. The server begins listening for incoming requests from WhatsApp, Paystack, etc.
"""

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
from contextlib import asynccontextmanager

from config.settings import settings

# ============================================================
# STARTUP AND SHUTDOWN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code that runs when the server starts up and when it shuts down.
    
    The 'yield' is the dividing line:
    Everything before yield runs at startup.
    Everything after yield runs at shutdown.
    """
    
    print("🚀 WaxPrep is starting up...")
    
    # Test database connections
    try:
        from database.client import test_connections
        test_connections()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        raise
    
    # Start the scheduler (daily challenges, reports, etc.)
    try:
        from utils.scheduler import start_scheduler
        start_scheduler()
        print("✅ Scheduler started")
    except Exception as e:
        print(f"⚠️ Scheduler failed to start: {e}")
    
    print("✅ WaxPrep is ready to receive messages!")
    
    yield  # Server is running
    
    # Shutdown
    print("👋 WaxPrep is shutting down...")
    try:
        from utils.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass

# ============================================================
# CREATE THE FASTAPI APP
# ============================================================

app = FastAPI(
    title="WaxPrep API",
    description="Nigeria's Most Advanced AI Educational Platform",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# Allow cross-origin requests (needed for the website frontend to talk to this server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your actual website URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# WHATSAPP WEBHOOK ROUTES
# ============================================================

@app.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    """
    This route handles WhatsApp webhook verification.
    
    When you set up your WhatsApp webhook in Meta's dashboard,
    Meta sends a GET request to this URL to verify you own it.
    They send a 'hub.challenge' code and you must send it back.
    
    This only happens once when you first set up the webhook.
    """
    params = dict(request.query_params)
    
    verify_token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    mode = params.get("hub.mode")
    
    if mode == "subscribe" and verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        print("✅ WhatsApp webhook verified successfully")
        return PlainTextResponse(content=challenge)
    else:
        print(f"❌ WhatsApp webhook verification failed. Token received: {verify_token}")
        raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook/whatsapp")
async def whatsapp_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """
    This route receives all incoming WhatsApp messages.
    
    Every time a student sends WaxPrep a message on WhatsApp,
    Meta sends that message to this URL as a POST request.
    
    We immediately return a 200 OK response (so Meta knows we got it),
    then process the message in the background.
    
    This is important because WhatsApp expects a response within 5 seconds.
    Processing the message might take longer, so we do it in the background.
    """
    from whatsapp.handler import handle_whatsapp_webhook
    
    # Process in background so we can return 200 immediately
    background_tasks.add_task(handle_whatsapp_webhook, request)
    
    return JSONResponse(content={"status": "received"}, status_code=200)

# ============================================================
# PAYSTACK PAYMENT WEBHOOK
# ============================================================

@app.post("/webhook/paystack")
async def paystack_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives payment confirmation from Paystack.
    When a student pays, Paystack sends a notification here confirming payment.
    """
    import hmac
    import hashlib
    
    paystack_signature = request.headers.get("x-paystack-signature", "")
    body = await request.body()
    
    if settings.PAYSTACK_SECRET_KEY:
        computed_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
            body,
            hashlib.sha512
        ).hexdigest()
        
        if paystack_signature != computed_signature:
            raise HTTPException(status_code=400, detail="Invalid Paystack signature")
    
    background_tasks.add_task(process_paystack_webhook, body)
    return JSONResponse(content={"status": "received"}, status_code=200)

async def process_paystack_webhook(body: bytes):
    """Processes a Paystack payment webhook."""
    import json
    
    try:
        data = json.loads(body)
        event = data.get('event')
        
        if event == 'charge.success':
            await handle_successful_payment(data.get('data', {}))
    except Exception as e:
        print(f"Paystack webhook processing error: {e}")

async def handle_successful_payment(payment_data: dict):
    """
    Handles a successful payment from Paystack.
    Activates the student's subscription.
    """
    from database.client import supabase
    from database.students import update_student
    from utils.helpers import nigeria_now
    from datetime import timedelta
    
    reference = payment_data.get('reference')
    amount_kobo = payment_data.get('amount', 0)
    amount_naira = amount_kobo // 100
    
    metadata = payment_data.get('metadata', {})
    student_id = metadata.get('student_id')
    plan = metadata.get('plan', 'scholar')
    billing_period = metadata.get('billing_period', 'monthly')
    
    if not student_id:
        print(f"Payment {reference} has no student_id in metadata")
        return
    
    # Determine subscription duration
    if billing_period == 'yearly':
        duration_days = 365
    else:
        duration_days = 30
    
    now = nigeria_now()
    expires = now + timedelta(days=duration_days)
    
    # Update student subscription
    await update_student(student_id, {
        'subscription_tier': plan,
        'subscription_expires_at': expires.isoformat(),
        'is_trial_active': False,
    })
    
    # Record the subscription
    supabase.table('subscriptions').insert({
        'student_id': student_id,
        'tier': plan,
        'billing_period': billing_period,
        'amount_naira': amount_naira,
        'started_at': now.isoformat(),
        'expires_at': expires.isoformat(),
        'is_active': True,
    }).execute()
    
    # Record the payment
    supabase.table('payments').insert({
        'student_id': student_id,
        'amount_naira': amount_naira,
        'paystack_reference': reference,
        'status': 'completed',
        'completed_at': now.isoformat(),
    }).execute()
    
    # Get student info to send congratulation message
    result = supabase.table('students').select(
        'name, wax_id'
    ).eq('id', student_id).execute()
    
    if result.data:
        student = result.data[0]
        phone_result = supabase.table('platform_sessions').select(
            'platform_user_id'
        ).eq('student_id', student_id).eq('platform', 'whatsapp').execute()
        
        if phone_result.data:
            phone = phone_result.data[0]['platform_user_id']
            from whatsapp.sender import send_whatsapp_message
            
            name_first = student['name'].split()[0]
            plan_display = plan.capitalize()
            
            await send_whatsapp_message(
                phone,
                f"🎉 *Payment Successful!*\n\n"
                f"Welcome to *{plan_display} Plan*, {name_first}!\n\n"
                f"Your subscription is now active.\n"
                f"Expires: {expires.strftime('%B %d, %Y')}\n\n"
                f"You now have access to all {plan_display} features.\n\n"
                f"Let's get studying! What subject do you want to tackle first? 📚"
            )

# ============================================================
# ADMIN API ROUTES
# ============================================================

@app.get("/admin/stats")
async def get_admin_stats(request: Request):
    """
    Returns platform statistics for the admin dashboard.
    This endpoint will be protected with authentication in production.
    """
    from database.client import supabase
    from utils.helpers import nigeria_today
    
    today = nigeria_today()
    
    try:
        # Total students
        total = supabase.table('students').select('id', count='exact').execute()
        
        # Active today
        active_today = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', today).execute()
        
        # New today
        new_today = supabase.table('students').select('id', count='exact')\
            .gte('created_at', today).execute()
        
        # Revenue today
        payments_today = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today)\
            .eq('status', 'completed').execute()
        
        revenue_today = sum(p['amount_naira'] for p in (payments_today.data or []))
        
        # AI cost today
        from ai.cost_tracker import get_daily_ai_spending
        ai_cost = await get_daily_ai_spending()
        
        return {
            "total_students": total.count or 0,
            "active_today": active_today.count or 0,
            "new_today": new_today.count or 0,
            "revenue_today_naira": revenue_today,
            "ai_cost_today_usd": round(ai_cost, 4),
            "status": "operational"
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/admin/promo-codes")
async def create_promo_code(request: Request):
    """Creates a new promo code. Admin only."""
    from database.client import supabase
    from utils.helpers import nigeria_now
    
    try:
        data = await request.json()
        
        result = supabase.table('promo_codes').insert({
            'code': data['code'].upper(),
            'code_type': data['code_type'],
            'tier_to_unlock': data.get('tier_to_unlock'),
            'discount_percent': data.get('discount_percent', 0),
            'bonus_days': data.get('bonus_days', 0),
            'bonus_questions_per_day': data.get('bonus_questions_per_day', 0),
            'max_uses': data.get('max_uses'),
            'description': data.get('description', ''),
            'expires_at': data.get('expires_at'),
            'created_for': data.get('created_for', ''),
        }).execute()
        
        return {"success": True, "promo_code": result.data[0] if result.data else {}}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/admin/send-message")
async def admin_send_message(request: Request):
    """
    Admin can send a message to any student by WAX ID.
    Used for announcements, support, etc.
    """
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message
    
    try:
        data = await request.json()
        wax_id = data.get('wax_id')
        message = data.get('message')
        
        if not wax_id or not message:
            return {"success": False, "error": "wax_id and message are required"}
        
        # Find student's WhatsApp
        student_result = supabase.table('students').select('id').eq('wax_id', wax_id).execute()
        if not student_result.data:
            return {"success": False, "error": "Student not found"}
        
        student_id = student_result.data[0]['id']
        
        phone_result = supabase.table('platform_sessions').select('platform_user_id')\
            .eq('student_id', student_id).eq('platform', 'whatsapp').execute()
        
        if not phone_result.data:
            return {"success": False, "error": "Student not on WhatsApp"}
        
        phone = phone_result.data[0]['platform_user_id']
        await send_whatsapp_message(phone, f"📢 *Message from WaxPrep:*\n\n{message}")
        
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/admin/send-daily-report")
async def trigger_daily_report():
    """Manually triggers the daily admin report."""
    from utils.scheduler import send_daily_admin_report
    await send_daily_admin_report()
    return {"success": True}

# ============================================================
# HEALTH CHECK ROUTES
# ============================================================

@app.get("/")
async def root():
    """Health check — confirms the server is running."""
    return {
        "app": "WaxPrep",
        "version": settings.APP_VERSION,
        "status": "operational",
        "message": "Nigeria's Most Advanced AI Educational Platform 🇳🇬"
    }

@app.get("/health")
async def health_check():
    """Detailed health check for Railway's monitoring."""
    from database.client import supabase, redis_client
    
    db_ok = False
    redis_ok = False
    
    try:
        supabase.table('system_config').select('config_key').limit(1).execute()
        db_ok = True
    except Exception:
        pass
    
    try:
        redis_client.ping()
        redis_ok = True
    except Exception:
        pass
    
    status = "healthy" if (db_ok and redis_ok) else "degraded"
    
    return {
        "status": status,
        "database": "ok" if db_ok else "error",
        "cache": "ok" if redis_ok else "error",
    }

# ============================================================
# RUN THE SERVER
# ============================================================

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True  # Auto-restart when code changes (only in development)
    )

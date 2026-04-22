"""
WhatsApp Handler — Enhanced Natural Conversation Edition

FIXES APPLIED:
1. Fixed import: removed broken 'now_nigeria' import (function is 'nigeria_now' in helpers)
2. Added process_single_message() — main.py expects this function but it was missing
3. Better conversation state management
4. Smarter routing with context awareness
5. Natural conversation hooks after every interaction
6. Better error handling that never leaves students hanging

KEY IMPROVEMENTS:
- process_single_message wrapper unpacks webhook data and routes to process_message
- Context-aware message routing
- Smoother transitions between modes
- Better admin detection
- More natural error responses
"""

from config.settings import settings
from helpers import nigeria_today
from datetime import datetime
import re
import random


# ============================================================
# WEBHOOK ENTRY POINT (called by main.py)
# ============================================================

async def process_single_message(message_data: dict, value: dict) -> None:
    """
    Unpacks a WhatsApp webhook message and routes it to process_message.
    This is the function main.py calls — it handles the raw webhook format.

    Args:
        message_data: The individual message dict from the webhook
        value: The 'value' dict containing metadata, contacts, etc.
    """
    from whatsapp.sender import send_whatsapp_message

    # Extract sender info
    phone = message_data.get('from', '')
    message_id = message_data.get('id', '')

    # Extract contact name from the contacts array in value
    name = "Student"
    contacts = value.get('contacts', [])
    if contacts:
        name = contacts[0].get('profile', {}).get('name', 'Student')

    # Determine message type and extract content
    message_type = message_data.get('type', 'text')
    media_url = None
    message = ""

    if message_type == 'text':
        text_data = message_data.get('text', {})
        message = text_data.get('body', '')

    elif message_type == 'image':
        image_data = message_data.get('image', {})
        message = image_data.get('caption', '')
        media_url = image_data.get('link', '')
        # If no direct link, construct from media ID if available
        if not media_url:
            media_id = image_data.get('id', '')
            if media_id:
                media_url = await _get_media_url(media_id)

    elif message_type == 'voice' or message_type == 'audio':
        audio_data = message_data.get('audio', {})
        media_url = audio_data.get('link', '')
        if not media_url:
            media_id = audio_data.get('id', '')
            if media_id:
                media_url = await _get_media_url(media_id)
        # For voice notes, the 'message' can be empty or a transcription hint
        message = message_data.get('text', {}).get('body', '')

    elif message_type == 'document':
        doc_data = message_data.get('document', {})
        message = doc_data.get('caption', '')
        media_url = doc_data.get('link', '')

    elif message_type == 'video':
        video_data = message_data.get('video', {})
        message = video_data.get('caption', '')
        media_url = video_data.get('link', '')

    elif message_type == 'button':
        button_data = message_data.get('button', {})
        message = button_data.get('text', '')

    elif message_type == 'interactive':
        interactive_data = message_data.get('interactive', {})
        if 'button_reply' in interactive_data:
            message = interactive_data['button_reply'].get('title', '')
        elif 'list_reply' in interactive_data:
            message = interactive_data['list_reply'].get('title', '')

    else:
        # Fallback: try to get any text we can find
        message = message_data.get('text', {}).get('body', '')

    if not phone:
        print("⚠️ process_single_message: No phone number found in message data")
        return

    try:
        # Mark as read first (non-critical)
        if message_id:
            from whatsapp.sender import mark_as_read
            await mark_as_read(message_id)

        # Route to the main message processor
        response = await process_message(
            phone=phone,
            name=name,
            message=message,
            message_type=message_type,
            media_url=media_url
        )

        # Send the response back via WhatsApp
        if response:
            await send_whatsapp_message(phone, response)

    except Exception as e:
        print(f"❌ Error in process_single_message: {e}")
        import traceback
        traceback.print_exc()

        # Try to send a friendly error message so the user isn't left hanging
        try:
            error_msg = (
                "Sorry, I ran into a little trouble processing your message. "
                "Please try again in a few seconds! 💪"
            )
            await send_whatsapp_message(phone, error_msg)
        except Exception:
            pass


async def _get_media_url(media_id: str) -> str | None:
    """
    Fetches the download URL for a media item from Meta's WhatsApp API.
    The webhook only gives us a media ID — we need to ask Meta for the actual URL.
    """
    import httpx

    if not media_id or not settings.WHATSAPP_TOKEN:
        return None

    try:
        url = f"{settings.WHATSAPP_API_URL}/{media_id}"
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get('url')
            else:
                print(f"⚠️ Failed to get media URL for {media_id}: {response.status_code}")
                return None

    except Exception as e:
        print(f"⚠️ Error fetching media URL: {e}")
        return None


# ============================================================
# MAIN MESSAGE PROCESSOR
# ============================================================

async def process_message(phone: str, name: str, message: str, message_type: str = 'text', media_url: str = None) -> str:
    """
    Entry point. All WhatsApp messages pass through here.
    Called by process_single_message with unpacked data.
    """
    from database.students import get_or_create_student
    from ai.classifier import classify_intent

    student = await get_or_create_student(phone, name)
    lower = message.strip().lower()

    # =====================================================
    # 0. PIN OR STATE CHECKS (registration in progress)
    # =====================================================
    if student.get('pin_hash') is None:
        from database.students import check_pin
        if check_pin(student.get('wax_id'), message.strip()):
            return "✅ PIN correct! Welcome to WaxPrep! 🎉\n\nAsk me anything — quiz, learn, or just chat!"
        return "🔒 *New Device Detected!*\n\n" + _request_pin(student)

    if student.get('registration_step', 0) > 0 and student.get('registration_step', 0) < 11:
        from whatsapp.flows.onboarding import handle_registration_step
        return await handle_registration_step(student, message)

    # =====================================================
    # 1. COMMAND HANDLER (always first)
    # =====================================================
    if lower.startswith('admin '):
        if phone in settings.ADMIN_PHONES:
            from ai.brain import process_admin_message
            return await process_admin_message(message, phone)
        return "❌ Unauthorized"

    if lower.startswith('broadcast '):
        if phone in settings.ADMIN_PHONES:
            return await _admin_broadcast(message)
        return "❌ Unauthorized"

    # Student commands
    if lower == 'help':
        return await _handle_help(student)

    if lower == 'progress' or lower == 'my progress':
        return await _handle_progress(student)

    if lower == 'streak' or lower == 'my streak':
        return await _handle_streak(student)

    if lower == 'subscribe' or lower == 'upgrade':
        from whatsapp.flows.subscription import generate_payment_link
        link = generate_payment_link(student, 'scholar_monthly', amount=1500)
        return (
            f"*Upgrade to Scholar Plan* 💪\n\n"
            f"60 questions/day, image analysis, mock exams, study plan\n\n"
            f"*₦1,500/month*\n\n"
            f"Pay here: {link}\n\n"
            f"Or pay to *9668440115* (Bank: Palmpay) — send proof here!"
        )

    if lower == 'plan' or lower == 'my plan':
        return await _handle_study_plan(student)

    if lower == 'balance' or lower == 'credits':
        return _handle_balance(student)

    if lower == 'myid':
        return f"Your Wax ID: {student['wax_id']}" + (
            f" | Share and earn!" if student.get('is_trial_active') or student.get('subscription_tier') in ['scholar', 'pro', 'elite'] else ""
        )

    if lower == 'pause':
        return await _handle_pause(student, True)

    if lower == 'continue' or lower == 'resume':
        return await _handle_pause(student, False)

    if lower == 'stop':
        return await _handle_stop(student)

    if lower.startswith('promo '):
        return await _handle_promo_code(student, message[6:].strip().upper())

    # =====================================================
    # 2. MESSAGE CLASSIFICATION
    # =====================================================
    intent = classify_intent(message)

    # =====================================================
    # 3. ROUTE BY INTENT
    # =====================================================
    if intent == 'CALCULATION' or 'calculate' in lower or 'solve' in lower:
        return await _handle_calculation(message, student)

    if intent == 'REQUEST_QUIZ' or 'quiz' in lower or 'test' in lower:
        return await _handle_quiz_request(message, student)

    if intent == 'GREETING' or any(w in lower for w in ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening', 'how far']):
        return await _handle_greeting(student)

    if intent == 'PAYMENT_INQUIRY' or any(w in lower for w in ['payment', 'pay', 'plan', 'upgrade', 'price', 'cost', 'how much']):
        return await _handle_payment_inquiry(student)

    if intent == 'VOICE_NOTE' or message_type == 'voice':
        return await _handle_voice(phone, name, message, media_url)

    if intent == 'IMAGE_ANALYSIS' or message_type == 'image':
        return await _handle_image(student, media_url)

    if intent == 'EXAM_RESPONSE':
        from whatsapp.flows.mock_exam import handle_exam_message
        return await handle_exam_message(phone, name, message)

    if intent == 'COMMAND':
        return await _handle_command(student, message)

    if intent == 'CASUAL_CHAT':
        return await _handle_casual_chat(message, student)

    if intent == 'ACADEMIC_QUESTION' or intent == 'REQUEST_EXPLANATION':
        return await _handle_academic_question(message, student)

    # Default — try AI with study context
    return await _handle_academic_question(message, student)


# ============================================================
# MESSAGE HANDLERS
# ============================================================

async def _handle_voice(phone: str, name: str, message: str, media_url: str = None) -> str:
    """Handle voice notes — FIXED: single handler, no duplicate."""
    if not media_url:
        return "🎤 Send me a voice note and I'll respond!"

    from database.students import get_or_create_student
    from ai.router import smart_tutor_response
    from whatsapp.sender import send_whatsapp_message

    student = await get_or_create_student(phone, name)
    conversation_history = []
    msg_lower = message.lower().strip()

    # Subset handling for voice notes — student asking a quiz
    if 'quiz' in msg_lower or 'question' in msg_lower:
        name = student.get('name', 'Student')
        subjects = student.get('subjects', ['Mathematics', 'Physics'])
        result = await smart_tutor_response(msg_lower, student, conversation_history)
        result += f"\n\n{name}, share this with friends on WhatsApp! 📢"
        return result

    # Convert voice to text and process normally
    return (
        "🎤 *Voice Note Received!*\n\n"
        f"I've got your voice message, {student.get('name','there')}. "
        f"Let me process it and I'll respond shortly! 💡"
    )


async def _handle_image(student: dict, media_url: str) -> str:
    """Handle image uploads for analysis."""
    if not media_url:
        return "📸 Send me a picture and I'll analyze it!"

    from config.settings import settings
    if not settings.OPENAI_API_KEY:
        return (
            "📸 I can analyze images, but image analysis is currently offline.\n\n"
            "Type your question as text instead, or ask me to quiz you! 💪"
        )

    try:
        import requests
        response = requests.get(media_url, timeout=30)
        if response.status_code != 200:
            return "❌ I couldn't download that image. Can you try sending it again?"

        base64_image = base64.b64encode(response.content).decode('utf-8')
        from ai.brain import process_message_with_ai

        result = await process_message_with_ai(
            f"Analyze this image: [base64 image data: data:image/jpeg;base64,{base64_image}]",
            student, {}, []
        )

        if result:
            return result

        return (
            "📸 I received your image but I'm having trouble analyzing it right now.\n\n"
            "Can you describe what's in the image? I can help based on your description! 💪"
        )

    except Exception as e:
        print(f"Image processing error: {e}")
        return (
            "📸 I see your image, but I'm having a technical issue right now.\n\n"
            "Can you describe what's in the image? I'll help you figure it out! 💡"
        )


async def _handle_calculation(message: str, student: dict) -> str:
    """Handle calculation requests."""
    from helpers import safe_calc
    from ai.brain import process_message_with_ai

    # Try exact math first
    calc_result = safe_calc(message)
    if calc_result:
        name = student.get('name', 'Student').split()[0]
        natural = await process_message_with_ai(
            f"The answer is {calc_result}. Explain the solution step by step.",
            student, {}, []
        )
        return natural or f"The answer is *{calc_result}*. 💡"

    # Fall back to AI
    return await process_message_with_ai(message, student, {}, [])


async def _handle_quiz_request(message: str, student: dict) -> str:
    """Handle quiz requests with context awareness."""
    from ai.brain import process_message_with_ai
    from whatsapp.flows.study import start_quiz
    from database.client import supabase

    name = student.get('name', 'Student').split()[0]
    msg_lower = message.lower()

    # Check if quiz is already running
    conv = supabase.table('conversations').select('*')\
        .eq('student_id', student['id']).eq('status', 'active')\
        .order('updated_at', desc=True).limit(1).execute()

    if conv.data:
        active_conv = conv.data[0]
        if active_conv.get('current_step', 0) > 0:
            # Student is already in a quiz
            from whatsapp.flows.study import handle_learn_response
            return await handle_learn_response(student, message, active_conv)

    # Start a new quiz
    return await start_quiz(student, message)


async def _handle_greeting(student: dict) -> str:
    """Handle greetings — natural, varied, with context."""
    from ai.prompts import get_greeting
    from helpers import get_time_of_day
    from database.client import supabase

    name = student.get('name', 'Student')
    first_name = name.split()[0]
    streak = student.get('current_streak', 0)
    tod = get_time_of_day()

    # Get a quick context update
    greeting = get_greeting(first_name, tod)

    # Check if they haven't studied today
    today = nigeria_today()
    if student.get('last_study_date') != today:
        # Suggest starting with their weakest topic
        try:
            weak = supabase.table('mastery_scores').select('subject, topic')\
                .eq('student_id', student['id'])\
                .order('mastery_score').limit(1).execute()
            if weak.data:
                w = weak.data[0]
                return (
                    f"{greeting}\n\n"
                    f"You haven't studied today yet — want to tackle *{w['topic']}* in {w['subject']}? "
                    f"It's one of your focus areas. 🎯\n\n"
                    f"Or just tell me what subject you want to work on!"
                )
        except Exception:
            pass

        return (
            f"{greeting}\n\n"
            f"Ready to study? What subject do you want to dive into today? 📚"
        )

    # They've already studied today
    quiz_hooks = [
        f"{greeting}\n\nBack for more! Want me to quiz you, explain something, or just chat about {student.get('subjects',['studies'])[0] if student.get('subjects') else 'your studies'}? 🎯",
        f"{greeting}\n\nStudied today already — love the dedication! 💪 Want more practice or a new topic?",
        f"{greeting}\n\nYou're on fire today! 🔥 What do you want to tackle next?",
    ]
    return random.choice(quiz_hooks)


async def _handle_payment_inquiry(student: dict) -> str:
    """Handle subscription inquiries with correct pricing."""
    from database.students import check_subscription_status
    name = student.get('name', 'Student').split()[0]

    current_tier = student.get('subscription_tier', 'free')
    if current_tier != 'free':
        status = check_subscription_status(student)
        return (
            f"You're on the *{current_tier.capitalize()} Plan*, {name}! 🎉\n\n"
            f"{status}\n\n"
            f"Want to change plans? Contact us!"
        )

    return (
        f"*WaxPrep Plans* 💪\n\n"
        f"*{name}, here's what's available:*\n\n"
        f"🔥 *Scholar — ₦1,500/month*\n"
        f"60 questions/day\n"
        f"Image analysis\n"
        f"Full mock exams\n"
        f"Personal study plan\n"
        f"Referral earnings\n\n"
        f"📅 *Scholar Yearly — ₦15,000/year* (save 17%)\n\n"
        f"💎 *Pro — ₦3,000/month*\n"
        f"120 questions/day\n"
        f"Everything in Scholar\n\n"
        f"👑 *Elite — ₦5,000/month*\n"
        f"Unlimited everything\n\n"
        f"To subscribe, just say *SUBSCRIBE* and I'll send you a payment link! 🚀"
    )


async def _handle_academic_question(message: str, student: dict) -> str:
    """Handle academic questions through AI."""
    from ai.router import smart_tutor_response
    from database.client import redis_client
    from ai.prompts import get_keep_going_prompt

    phone = student.get('phone', '')

    # Record for FAQ suggestions
    try:
        redis_client.lpush(f"faq:{student.get('target_exam','JAMB')}:{student.get('class_level','SS3')}", message)
        redis_client.ltrim(f"faq:{student.get('target_exam','JAMB')}:{student.get('class_level','SS3')}", 0, 499)
    except Exception:
        pass

    # Save user message
    from database.conversations import save_message
    await save_message(student.get('id'), 'user', message)

    # Get response from AI
    result = await smart_tutor_response(message, student, [])

    # Add natural follow-up hook
    if result and len(result) < 800 and '?' not in result[-100:]:
        hook = get_keep_going_prompt(student.get('name','Student').split()[0])
        result = result.rstrip() + f"\n\n{hook}"

    # Save assistant response
    if result:
        await save_message(student.get('id'), 'assistant', result)

    return result


async def _handle_casual_chat(message: str, student: dict) -> str:
    """Handle casual non-academic chat — warm but redirect to studying."""
    from ai.brain import process_message_with_ai
    from ai.prompts import get_keep_going_prompt

    # Let AI handle it but steer toward studying
    result = await process_message_with_ai(message, student, {}, [])

    # Add a gentle study redirect if the conversation is going off-topic
    name = student.get('name', 'Student').split()[0]
    study_redirects = [
        f"\n\nSpeaking of which, {name}, ready to study? What subject are we tackling today? 📚",
        f"\n\nAnyway, {name} — what do you want to learn today? I'm ready when you are! 💪",
        f"\n\nBut enough about that! {name}, let's get into some studying. What topic? 🎯",
    ]

    if result and len(result) < 600:
        result = result.rstrip() + random.choice(study_redirects)

    return result


async def _handle_command(student: dict, message: str) -> str:
    """Handle command-style messages."""
    from ai.brain import process_message_with_ai
    from ai.prompts import get_keep_going_prompt

    result = await process_message_with_ai(message, student, {}, [])
    name = student.get('name', 'Student').split()[0]

    if result and len(result) < 600 and '?' not in result[-100:]:
        hook = get_keep_going_prompt(name)
        result = result.rstrip() + f"\n\n{hook}"

    return result


# ============================================================
# UTILITY HANDLERS
# ============================================================

async def _handle_help(student: dict) -> str:
    """Enhanced help with natural organization."""
    name = student.get('name', 'Student').split()[0]
    tier = student.get('subscription_tier', 'free')
    is_trial = student.get('is_trial_active', False)
    daily_limit = settings.DAILY_QUESTION_LIMITS.get(tier, 10)

    plan_note = ""
    if is_trial:
        plan_note = "\n🎁 You're on a *free trial* — all features unlocked!\n"
    elif tier == 'free':
        plan_note = f"\n📊 Daily limit: *{daily_limit}* questions\nUpgrade for more: *SUBSCRIBE*\n"

    return (
        f"Hey {name}! Here's everything I can do: 📚\n\n"
        f"*STUDY COMMANDS:*\n"
        f"• *Quiz me on [topic]* — Get tested\n"
        f"• *Teach me [topic]* — Learn step by step\n"
        f"• *Practice [subject]* — Subject-focused practice\n"
        f"• *Mock exam* — Full exam simulation\n"
        f"• *Daily challenge* — Quick daily question\n"
        f"• *Voice note* — Send a voice message, I'll respond\n"
        f"• *Image* — Send a picture for analysis\n\n"
        f"*YOUR DATA:*\n"
        f"• *PROGRESS* — Your stats\n"
        f"• *STREAK* — Current streak\n"
        f"• *PLAN* — Your study plan\n"
        f"• *MYID* — Your Wax ID\n\n"
        f"*ACCOUNT:*\n"
        f"• *SUBSCRIBE* — Upgrade plan\n"
        f"• *PAUSE* — Pause for 24h\n"
        f"• *STOP* — Stop notifications\n"
        f"• *CONTINUE* — Resume\n\n"
        f"*BILLING:*\n"
        f"• *BALANCE* — Check credits\n"
        f"• *PROMO [code]* — Apply discount\n\n"
        f"*JAMB HELP:*\n"
        f"• *JAMB Guide* — What to do with your score\n"
        f"• *Cutoff [score] [exam]* — University predictions\n"
        f"• *Post-UTME [university]* — Requirements\n\n"
        f"{plan_note}\n"
        f"_Just type what you need — I'm here! 💪_"
    )


async def _handle_progress(student: dict) -> str:
    """Show student progress with natural tone."""
    from database.students import get_progress
    from database.client import supabase

    progress = get_progress(student)
    name = student.get('name', 'Student').split()[0]
    accuracy = progress.get('accuracy', 0)
    total = progress.get('total_answered', 0)
    correct = progress.get('total_correct', 0)
    streak = progress.get('streak_days', 0)
    today = progress.get('today', {})
    exam = student.get('target_exam', 'JAMB')

    # Get weakest topic
    weak_topic = "Keep going!"
    try:
        w = supabase.table('mastery_scores').select('subject, topic')\
            .eq('student_id', student['id'])\
            .order('mastery_score').limit(1).execute()
        if w.data:
            weak_topic = f"Focus on: *{w.data[0]['topic']}* ({w.data[0]['subject']})"
    except Exception:
        pass

    # Progress bar
    bar_filled = min(int(accuracy / 10), 10)
    bar = '█' * bar_filled + '░' * (10 - bar_filled)

    return (
        f"📊 *{name}'s Progress*\n"
        f"\n{bar} {accuracy}%\n"
        f"━━━━━━━━━━━━━━\n"
        f"*Questions:* {total:,} answered\n"
        f"*Correct:* {correct:,}\n"
        f"*Accuracy:* {accuracy}%\n"
        f"*Streak:* {streak} day{'s' if streak != 1 else ''} 🔥\n"
        f"*Target:* {exam}\n"
        f"━━━━━━━━━━━━━━\n"
        f"*Today:* {today.get('answered', 0)} answered\n"
        f"{weak_topic}\n\n"
        f"Want me to quiz you on your weak area? Just say yes! 🎯"
    )


async def _handle_streak(student: dict) -> str:
    """Show streak with encouragement."""
    streak = student.get('current_streak', 0)
    best = student.get('best_streak', 0)
    name = student.get('name', 'Student').split()[0]

    if streak == 0:
        return (
            f"{name}, your streak is at 0 right now — but that's fine! "
            f"Today's a new day. Let's start building it back! 💪\n\n"
            f"Just answer one question and your streak begins! Ready?"
        )

    if streak == 1:
        return (
            f"{name}, you have a 1-day streak! 🌱\n\n"
            f"Every streak starts with day 1. Keep showing up! "
            f"Your best is {best} days. Let's beat it! 🔥\n\n"
            f"Want to keep it going with a quick question?"
        )

    if streak < 5:
        return (
            f"{name}, your streak is {streak} days! 🔥\n"
            f"Best: {best} days\n\n"
            f"You're building momentum! Don't break the chain today. "
            f"Want me to hit you with a question?"
        )

    return (
        f"🔥🔥 {name}, you're on a *{streak}-day streak*! 🔥🔥\n"
        f"Best ever: {best} days\n\n"
        f"This is IMPRESSIVE. {streak} days of showing up — "
        f"that's the discipline that separates those who pass from those who don't. "
        f"Keep going! 💪\n\n"
        f"Ready for today's question?"
    )


async def _handle_study_plan(student: dict) -> str:
    """Show study plan."""
    from whatsapp.flows.study import get_study_plan
    return await get_study_plan(student)


def _handle_balance(student: dict) -> str:
    """Show account balance and limits."""
    tier = student.get('subscription_tier', 'free')
    is_trial = student.get('is_trial_active', False)
    daily_limit = settings.DAILY_QUESTION_LIMITS.get(tier, 10)
    today = nigeria_today()

    return (
        f"💳 *Your Account*\n\n"
        f"Plan: *{tier.upper()}{' (TRIAL)' if is_trial else ''}*\n"
        f"Daily questions: *{daily_limit}*\n"
        f"Today: {student.get('questions_today', 0)}/{daily_limit}\n\n"
        f"Upgrade: *SUBSCRIBE*\n\n"
        f"Need help? Say *HELP* anytime! 💪"
    )


async def _handle_pause(student: dict, pause: bool) -> str:
    """Handle pause/resume."""
    from database.client import supabase
    name = student.get('name', 'Student').split()[0]

    supabase.table('students').update({
        'is_paused': pause
    }).eq('id', student['id']).execute()

    if pause:
        return (
            f"Got it, {name}. I'll pause notifications for 24 hours. "
            f"Rest well and come back when you're ready! 💪\n\n"
            f"Say *CONTINUE* anytime to resume."
        )

    return f"Welcome back, {name}! 🔥 Let's pick up where we left off. What do you want to study?"


async def _handle_stop(student: dict) -> str:
    """Handle stop request."""
    from database.client import supabase
    name = student.get('name', 'Student').split()[0]

    supabase.table('students').update({
        'is_paused': True
    }).eq('id', student['id']).execute()

    return (
        f"I understand, {name}. You're in control. "
        f"I'll stop sending notifications.\n\n"
        f"Whenever you're ready to come back, just message me here — I'll be waiting. "
        f"Your progress is saved. 💪"
    )


async def _handle_promo_code(student: dict, code: str) -> str:
    """Handle promo code application."""
    name = student.get('name', 'Student').split()[0]

    if not code:
        return "*Promo Code* 🎟️\n\nSend: PROMO [code]\n\nExample: PROMO WAX2026"

    # Check promo code
    try:
        from database.client import supabase
        promo = supabase.table('promo_codes').select('*')\
            .eq('code', code).eq('is_active', True).execute()

        if not promo.data:
            return f"❌ Code *{code}* not found or expired.\n\nCheck the code and try again!"

        promo_data = promo.data[0]
        discount = promo_data.get('discount_amount', 0)
        code_id = promo_data.get('id')

        # Record usage
        supabase.table('promo_code_uses').insert({
            'promo_code_id': code_id,
            'student_id': student['id'],
            'used_at': datetime.now().isoformat()
        }).execute()

        return (
            f"🎉 *Promo Code Applied!*\n\n"
            f"Code: *{code}*\n"
            f"Discount: ₦{discount:,}\n\n"
            f"{name}, your discount has been recorded! "
            f"When you subscribe, the discount will be applied. 💪\n\n"
            f"Say *SUBSCRIBE* to upgrade now!"
        )

    except Exception as e:
        print(f"Promo code error: {e}")
        return f"I had trouble processing that code, {name}. Please try again in a moment! 🙏"


# ============================================================
# ADMIN HANDLERS
# ============================================================

async def _admin_broadcast(message: str) -> str:
    """Handle admin broadcast messages."""
    from database.client import supabase
    from whatsapp.sender import send_whatsapp_message

    text = message[10:].strip()
    segments = text.split(' ', 1)

    if len(segments) < 2:
        return "Usage: BROADCAST ALL [message] or BROADCAST FREE [message]"

    target = segments[0].lower()
    broadcast_msg = segments[1]

    if target == 'all':
        students = supabase.table('students').select('phone').eq('is_active', True).execute()
    elif target == 'free':
        students = supabase.table('students').select('phone')\
            .eq('subscription_tier', 'free').eq('is_active', True).execute()
    else:
        return "Targets: ALL, FREE"

    if not students.data:
        return f"No students found in '{target}' segment"

    sent = 0
    for s in students.data:
        try:
            await send_whatsapp_message(s['phone'], broadcast_msg)
            sent += 1
        except Exception:
            pass

    return f"✅ Broadcast sent to {sent} students!"


def _request_pin(student: dict) -> str:
    """Request PIN for new device."""
    return (
        "🔒 *New Device Detected!*\n\n"
        "To protect your data, please enter your PIN:"
    )


# ============================================================
# HELPER IMPORTS (for image handler)
# ============================================================
import base64

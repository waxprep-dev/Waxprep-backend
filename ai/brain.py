"""
WaxPrep AI Brain

Every student message comes here.
Gemini reads it, understands it, responds naturally.
No commands. No menus. Just conversation.
"""

import json
import google.generativeai as genai
from config.settings import settings

genai.configure(api_key=settings.GEMINI_API_KEY)


async def process_message_with_ai(
    message: str,
    student: dict,
    conversation: dict,
    conversation_history: list
) -> str:
    """
    Main function. Every student message comes here.
    Uses Gemini to understand and respond naturally.
    Falls back to Groq if Gemini fails.
    """
    student_context = _build_student_context(student, conversation)
    system_prompt = _build_system_prompt(student, student_context)

    history = []
    for msg in conversation_history[-10:]:
        role = "user" if msg.get("role") == "user" else "model"
        history.append({
            "role": role,
            "parts": [{"text": msg.get("content", "")}]
        })

    try:
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.8,
                max_output_tokens=1200,
            )
        )

        chat = model.start_chat(history=history)
        response = chat.send_message(message)
        result = _extract_text(response)

        if result:
            return result

        return await _fallback_response(message, student, conversation_history)

    except Exception as e:
        print(f"Gemini error: {e}")
        return await _fallback_response(message, student, conversation_history)


def _extract_text(response) -> str:
    """Extracts text from a Gemini response object."""
    try:
        text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                text += part.text
        return text.strip()
    except Exception:
        return ""


def _build_student_context(student: dict, conversation: dict) -> str:
    """Builds a summary of the student for the AI system prompt."""
    from helpers import nigeria_today

    name = student.get('name', 'Student')
    wax_id = student.get('wax_id', '')
    class_level = student.get('class_level', '')
    target_exam = student.get('target_exam', '')
    subjects = student.get('subjects', [])
    exam_date = student.get('exam_date', '')
    state = student.get('state', '')
    streak = student.get('current_streak', 0)
    points = student.get('total_points', 0)
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0)
    tier = student.get('subscription_tier', 'free')
    is_trial = student.get('is_trial_active', False)
    level = student.get('current_level', 1)
    level_name = student.get('level_name', 'Scholar')
    language = student.get('language_preference', 'english')
    current_subject = conversation.get('current_subject', '')
    current_topic = conversation.get('current_topic', '')
    today = nigeria_today()
    studied_today = student.get('last_study_date', '') == today

    days_until_exam = ""
    if exam_date:
        try:
            from datetime import datetime
            exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
            days_left = (exam_dt - datetime.now()).days
            if days_left > 0:
                days_until_exam = f"{days_left} days until {target_exam}"
            else:
                days_until_exam = f"{target_exam} exam has passed"
        except Exception:
            pass

    plan_str = 'Full Trial Access (all features unlocked)' if is_trial else tier.capitalize()

    return (
        f"STUDENT: {name} | WAX ID: {wax_id}\n"
        f"Class: {class_level} | Exam: {target_exam} | State: {state}\n"
        f"Subjects: {', '.join(subjects)}\n"
        f"Countdown: {days_until_exam}\n"
        f"Plan: {plan_str}\n"
        f"Stats: {answered} questions answered | {accuracy}% accuracy | "
        f"{streak}-day streak | {points:,} points | Level {level} ({level_name})\n"
        f"Studied today: {'Yes' if studied_today else 'No'}\n"
        f"Currently on: {current_subject} - {current_topic}\n"
        f"Language preference: {language}"
    )


def _build_system_prompt(student: dict, student_context: str) -> str:
    """Builds the personality and instruction prompt for Wax."""
    name = student.get('name', 'Student').split()[0]
    target_exam = student.get('target_exam', 'JAMB')
    language = student.get('language_preference', 'english')

    language_note = ""
    if language == 'pidgin':
        language_note = (
            "\nLANGUAGE: Communicate naturally in Nigerian Pidgin English mixed with "
            "standard English for technical terms. Sound like a friendly older sibling."
        )

    return (
        f"You are Wax — the AI study companion inside WaxPrep, Nigeria's most advanced "
        f"exam preparation platform.\n\n"
        f"You are talking with {name}, preparing for {target_exam}.\n\n"
        f"{student_context}\n\n"
        f"YOUR CHARACTER:\n"
        f"You are warm, intelligent, and genuinely invested in {name}'s success. "
        f"You speak like a knowledgeable friend who has already passed these exams and wants to help. "
        f"You are never robotic. You never list numbered options unless specifically asked. "
        f"You take initiative like a real teacher.\n\n"
        f"HOW YOU RESPOND:\n"
        f"When asked about any subject topic: explain it thoroughly with at least one Nigerian "
        f"real-life example (NEPA for electricity, danfo for Newton's laws, egusi for osmosis, "
        f"palm oil for chemistry, suya for fractions, Lagos traffic for speed and distance).\n"
        f"When asked to quiz or test: generate a well-formed multiple choice question with 4 options.\n"
        f"When asked about progress/stats: share the numbers from the student context warmly.\n"
        f"When asked about subscription/payment: explain the Scholar plan is N1,500/month and "
        f"they can type ADMIN PAY or visit waxprep.ng to subscribe (be honest, payment link "
        f"generation is being set up).\n"
        f"When the student seems stressed: acknowledge it first, then gently redirect to studying.\n"
        f"When the student says something vague like 'hi' or 'hello': greet them warmly, "
        f"reference something personal from their profile (streak, exam countdown), and "
        f"proactively suggest what to study based on their subjects.\n\n"
        f"WHAT YOU NEVER DO:\n"
        f"Never say 'type X to do Y'. Just do it.\n"
        f"Never give a numbered menu of options unless asked.\n"
        f"Never say 'I am an AI' or break character.\n"
        f"Never ignore context — always reference their exam, subjects, and progress.\n\n"
        f"FORMAT FOR WHATSAPP:\n"
        f"Use *bold* for key terms. Use line breaks between ideas. "
        f"Keep responses focused — not too long. Use emojis warmly but sparingly.\n"
        f"{language_note}"
    )


async def _fallback_response(message: str, student: dict, history: list) -> str:
    """Uses Groq as backup when Gemini fails."""
    try:
        from groq import Groq
        from config.settings import settings

        client = Groq(api_key=settings.GROQ_API_KEY)
        name = student.get('name', 'Student').split()[0]
        target_exam = student.get('target_exam', 'JAMB')

        system = (
            f"You are Wax, a friendly AI study tutor for Nigerian secondary school students. "
            f"You are talking with {name} who is preparing for {target_exam}. "
            f"Be warm, helpful, and use Nigerian examples. Respond naturally, not robotically."
        )

        messages = [{"role": "system", "content": system}]
        for msg in history[-6:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": message})

        response = client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=messages,
            max_tokens=800,
            temperature=0.7,
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"Groq fallback error: {e}")
        name = student.get('name', 'Student').split()[0]
        return (
            f"Hey {name}! I'm here. 😊\n\n"
            f"What would you like to study? Just tell me the topic or subject "
            f"and I'll explain it right away."
        )


async def process_admin_message(message: str, admin_phone: str) -> str:
    """
    Handles admin messages with natural language understanding.
    Falls back to direct command parsing if AI is unavailable.
    """
    # First try direct command parsing (always works, no AI needed)
    direct_result = await _handle_admin_direct(message, admin_phone)
    if direct_result:
        return direct_result

    # Try Gemini for natural language admin queries
    try:
        context = await _get_admin_context()

        system = (
            "You are the WaxPrep admin assistant helping the founder manage the platform.\n"
            "Be concise and action-oriented. The admin is busy.\n\n"
            f"Current platform status:\n{context}\n\n"
            "You can answer questions about the platform stats from the context above. "
            "For actions like broadcasts, upgrades, or bans, tell the admin to use "
            "the specific ADMIN command and show them the exact syntax."
        )

        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system,
            generation_config=genai.types.GenerationConfig(
                temperature=0.5,
                max_output_tokens=600,
            )
        )

        response = model.generate_content(message)
        result = _extract_text(response)
        if result:
            return result

    except Exception as e:
        print(f"Admin Gemini error: {e}")

    return await _admin_fallback(message, admin_phone)


async def _handle_admin_direct(message: str, phone: str) -> str | None:
    """
    Handles admin requests directly without AI.
    Returns a response string if handled, None if not recognized.
    """
    msg = message.strip().lower()

    # Stats requests
    if any(w in msg for w in ['stats', 'how many student', 'how many user', 'numbers', 'overview']):
        return await _get_admin_context()

    # Revenue requests
    if any(w in msg for w in ['revenue', 'income', 'money', 'earnings', 'payment']):
        from database.client import supabase
        from helpers import nigeria_today
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Africa/Lagos"))
        today = nigeria_today()
        week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        month_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d')

        today_p = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        week_p = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', week_ago).eq('status', 'completed').execute()
        month_p = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', month_ago).eq('status', 'completed').execute()

        rev_today = sum(p.get('amount_naira', 0) for p in (today_p.data or []))
        rev_week = sum(p.get('amount_naira', 0) for p in (week_p.data or []))
        rev_month = sum(p.get('amount_naira', 0) for p in (month_p.data or []))

        return (
            f"💰 *Revenue Summary*\n\n"
            f"Today: ₦{rev_today:,}\n"
            f"This Week: ₦{rev_week:,}\n"
            f"This Month: ₦{rev_month:,}"
        )

    # Report request
    if any(w in msg for w in ['report', 'send report', 'daily report']):
        from utils.scheduler import send_daily_admin_report
        await send_daily_admin_report()
        return "✅ Daily report sent to your WhatsApp!"

    # Challenge generation
    if 'challenge' in msg and any(w in msg for w in ['generate', 'create', 'make', 'new']):
        from utils.scheduler import generate_daily_challenge
        await generate_daily_challenge()
        return "✅ Daily challenge generated!"

    # Top students
    if 'top' in msg and any(w in msg for w in ['student', 'user', 'performer']):
        from database.client import supabase
        result = supabase.table('students').select(
            'name, wax_id, total_points, current_streak, subscription_tier'
        ).eq('is_active', True).order('total_points', desc=True).limit(5).execute()

        if not result.data:
            return "No students yet!"

        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        lines = [f"🏆 *Top Students*\n"]
        for i, s in enumerate(result.data):
            medal = medals[i] if i < len(medals) else '•'
            lines.append(
                f"{medal} {s['name']}\n"
                f"   {s.get('wax_id', '')} | "
                f"{s.get('total_points', 0):,} pts | "
                f"{s.get('current_streak', 0)}🔥"
            )
        return "\n\n".join(lines)

    return None


async def _get_admin_context() -> str:
    """Gets current platform stats for admin."""
    from database.client import supabase, redis_client
    from helpers import nigeria_today
    from config.settings import settings
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = nigeria_today()

    try:
        total = supabase.table('students').select('id', count='exact').execute()
        active_today = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', today).execute()
        new_today = supabase.table('students').select('id', count='exact')\
            .gte('created_at', today).execute()
        paying = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()
        on_trial = supabase.table('students').select('id', count='exact')\
            .eq('is_trial_active', True).execute()

        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        revenue_today = sum(p.get('amount_naira', 0) for p in (payments.data or []))

        ai_cost = float(redis_client.get(f"ai_cost:{today}") or 0)

        q_count = supabase.table('questions').select('id', count='exact').execute()

        return (
            f"📊 *WaxPrep Stats — {now.strftime('%d %b %Y, %H:%M')} WAT*\n\n"
            f"👥 *Students*\n"
            f"Total: {total.count or 0:,}\n"
            f"New Today: +{new_today.count or 0}\n"
            f"Studying Today: {active_today.count or 0:,}\n"
            f"On Trial: {on_trial.count or 0:,}\n"
            f"Paying: {paying.count or 0:,}\n\n"
            f"💰 Revenue Today: ₦{revenue_today:,}\n"
            f"🤖 AI Cost Today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD}\n"
            f"📚 Questions in Bank: {q_count.count or 0:,}\n\n"
            f"Type *ADMIN HELP* for all admin commands."
        )

    except Exception as e:
        return f"Stats error: {str(e)[:100]}"


async def _admin_fallback(message: str, phone: str) -> str:
    """Final fallback for admin when everything else fails."""
    msg = message.strip().lower()

    # Try to be helpful based on keywords
    if any(w in msg for w in ['help', 'what can', 'commands', 'options']):
        return (
            "🛠️ *Admin Quick Reference*\n\n"
            "Just ask naturally:\n"
            "• 'How many students?' → stats\n"
            "• 'Revenue today?' → revenue\n"
            "• 'Top students' → leaderboard\n"
            "• 'Send report' → daily report\n\n"
            "Or use ADMIN commands:\n"
            "*ADMIN STATS* — full stats\n"
            "*ADMIN BROADCAST ALL [msg]* — message all\n"
            "*ADMIN STUDENT WAX-XXXXXX* — student profile\n"
            "*ADMIN UPGRADE WAX-XXXXXX scholar 30* — give plan\n"
            "*ADMIN CODE CREATE WAX50 trial 7 100* — promo code\n"
            "*ADMIN HELP* — complete command list"
        )

    return (
        "I got your message but couldn't process it right now.\n\n"
        "Try asking: 'How many students do I have?' or use *ADMIN STATS*\n\n"
        "Type *ADMIN HELP* for all commands."
    )

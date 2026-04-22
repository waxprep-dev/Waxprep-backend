"""
WaxPrep AI Brain — Groq-Primary Architecture

WHY GROQ IS NOW PRIMARY:
- Groq free tier: ~14,400 requests per day (very generous)
- Gemini free tier: 1,500 requests per day (exhausted quickly)
- During testing we hit Gemini's limit and both AI models failed
- Solution: Groq handles all conversations, Gemini handles complex tasks

ARCHITECTURE:
1. Every student message → Groq (fast, reliable, generous quota)
2. Quiz question generation → Groq (can do it, free)
3. Complex multi-topic explanations → Gemini (used sparingly)
4. Daily challenge generation → Gemini (once per day, fine)
5. Rate limit caching: if Gemini is rate limited, cache that for 60s

ADMIN ESCAPE:
ADMIN ADMIN_MODE always works even in student mode.
This is intercepted at the handler level before any mode check.
"""

from groq import Groq
import google.generativeai as genai
from config.settings import settings

# Initialize clients
_groq_client = None
_gemini_configured = False


def get_groq_client() -> Groq:
    """Returns the Groq client, creating it once."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


def setup_gemini():
    """Configures Gemini API once."""
    global _gemini_configured
    if not _gemini_configured and settings.GEMINI_API_KEY:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        _gemini_configured = True


def is_gemini_rate_limited() -> bool:
    """Checks if Gemini is currently rate limited (cached in Redis)."""
    try:
        from database.client import redis_client
        return redis_client.get("gemini_rate_limited") is not None
    except Exception:
        return False


def mark_gemini_rate_limited(seconds: int = 65):
    """Marks Gemini as rate limited for the specified seconds."""
    try:
        from database.client import redis_client
        redis_client.setex("gemini_rate_limited", seconds, "1")
        print(f"⏳ Gemini rate limited, cached for {seconds}s")
    except Exception:
        pass


async def process_message_with_ai(
    message: str,
    student: dict,
    conversation: dict,
    conversation_history: list
) -> str:
    """
    Main brain function. Every student message comes here.

    Primary: Groq (fast, free, 14,400 req/day)
    Secondary: Gemini (smarter but 1,500 req/day limit)

    Strategy:
    - Use Groq for all conversations
    - Groq with a smart system prompt handles 95% of cases well
    - Gemini only for complex scientific explanations when explicitly needed
    """
    system_prompt = _build_full_system_prompt(student, conversation)

    # Format history for Groq
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-10:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": message})

    # Try Groq first (primary)
    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model=settings.GROQ_SMART_MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.75,
        )
        result = response.choices[0].message.content
        if result and len(result.strip()) > 5:
            return result.strip()
    except Exception as e:
        print(f"Groq primary error: {e}")

    # Groq failed — try Gemini
    if not is_gemini_rate_limited():
        try:
            setup_gemini()
            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=system_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=1000,
                )
            )

            history = []
            for msg in conversation_history[-8:]:
                role = "user" if msg.get("role") == "user" else "model"
                history.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

            chat = model.start_chat(history=history)
            response = chat.send_message(message)

            text = ""
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    text += part.text

            if text.strip():
                return text.strip()

        except Exception as e:
            error_str = str(e)
            print(f"Gemini error: {error_str[:100]}")
            if "429" in error_str or "quota" in error_str.lower() or "rate" in error_str.lower():
                mark_gemini_rate_limited(65)

    # Both failed — use fast Groq with simpler prompt
    try:
        client = get_groq_client()
        name = student.get('name', 'Student').split()[0]
        exam = student.get('target_exam', 'JAMB')
        subjects = ', '.join(student.get('subjects', ['all subjects'])[:3])

        simple_system = (
            f"You are Wax, an AI tutor for {name} who is preparing for {exam}. "
            f"Their subjects are {subjects}. "
            f"Be warm, helpful, and use Nigerian examples (NEPA, danfo, suya, Lagos, etc.). "
            f"Never give the same generic reply — actually respond to what they said."
        )

        response = client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=[
                {"role": "system", "content": simple_system},
                {"role": "user", "content": message}
            ],
            max_tokens=600,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"Fast Groq also failed: {e}")

    # Total failure — context-aware message instead of generic one
    return _context_aware_fallback(message, student)


def _context_aware_fallback(message: str, student: dict) -> str:
    """
    Returns a context-aware response even when all AI fails.
    Never the same generic message — always responds to what was said.
    """
    name = student.get('name', 'Student').split()[0]
    msg_lower = message.lower()
    exam = student.get('target_exam', 'JAMB')
    subjects = student.get('subjects', [])

    if any(w in msg_lower for w in ['quiz', 'question', 'test', 'practice']):
        subject = subjects[0] if subjects else 'Mathematics'
        return (
            f"I want to quiz you, {name}! Give me just a second — "
            f"I'm putting together a {subject} question for you. 🎯\n\n"
            f"_(My AI brain is a tiny bit overloaded right now — "
            f"try again in 30 seconds and I'll have a question ready!)_"
        )

    if any(w in msg_lower for w in ['explain', 'what is', 'what are', 'how does', 'teach', 'help me with']):
        return (
            f"Great question, {name}! I'm thinking through the best way to explain this. 🤔\n\n"
            f"I'm temporarily at my limit — try again in about 30 seconds "
            f"and I'll give you a proper explanation. 💡"
        )

    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'good']):
        streak = student.get('current_streak', 0)
        answered = student.get('total_questions_answered', 0)
        streak_msg = f"Your {streak}-day streak is still going! 🔥" if streak > 0 else ""
        return (
            f"Hey {name}! Great to see you. 😊\n\n"
            f"{streak_msg}\n"
            f"You've answered {answered:,} questions so far. "
            f"What subject do you want to tackle today? "
            f"Just tell me and we'll dive in."
        )

    if any(w in msg_lower for w in ['progress', 'stats', 'how am i', 'my score']):
        answered = student.get('total_questions_answered', 0)
        correct = student.get('total_questions_correct', 0)
        accuracy = round((correct / answered * 100) if answered > 0 else 0)
        streak = student.get('current_streak', 0)
        return (
            f"📊 *Quick Stats, {name}*\n\n"
            f"Questions answered: {answered:,}\n"
            f"Accuracy: {accuracy}%\n"
            f"Streak: {streak} day{'s' if streak != 1 else ''}\n\n"
            f"Keep going — every question gets you closer to {exam}! 💪"
        )

    # Generic but still personal
    return (
        f"I'm here, {name}! My processing is a bit slow right now. 😅\n\n"
        f"Try asking me again in 30 seconds — I'll answer properly. "
        f"What subject would you like to study?"
    )


def _build_full_system_prompt(student: dict, conversation: dict) -> str:
    """Builds the complete system prompt with student context."""
    from helpers import nigeria_today

    name = student.get('name', 'Student').split()[0]
    class_level = student.get('class_level', 'SS3')
    target_exam = student.get('target_exam', 'JAMB')
    subjects = student.get('subjects', [])
    exam_date = student.get('exam_date', '')
    state = student.get('state', 'Nigeria')
    streak = student.get('current_streak', 0)
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0)
    tier = student.get('subscription_tier', 'free')
    is_trial = student.get('is_trial_active', False)
    language = student.get('language_preference', 'english')
    today = nigeria_today()
    studied_today = student.get('last_study_date', '') == today
    current_subject = conversation.get('current_subject', '')
    current_topic = conversation.get('current_topic', '')

    days_until_exam = ""
    if exam_date:
        try:
            from datetime import datetime
            exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
            days_left = (exam_dt - datetime.now()).days
            if days_left > 0:
                days_until_exam = f"{days_left} days until {target_exam}"
        except Exception:
            pass

    plan = "Full Trial (all features)" if is_trial else tier.capitalize()
    subjects_str = ', '.join(subjects) if subjects else 'not specified'

    lang_note = ""
    if language == 'pidgin':
        lang_note = "\nLANGUAGE: Respond in Nigerian Pidgin English naturally mixed with standard English for technical terms.\n"

    return (
        f"You are Wax — the AI study companion inside WaxPrep, Nigeria's most advanced exam prep platform.\n\n"

        f"STUDENT PROFILE:\n"
        f"Name: {name} | Class: {class_level} | Exam: {target_exam}\n"
        f"Subjects: {subjects_str}\n"
        f"State: {state} | Plan: {plan}\n"
        f"Exam countdown: {days_until_exam}\n\n"

        f"THEIR PERFORMANCE:\n"
        f"Questions answered: {answered:,} | Accuracy: {accuracy}%\n"
        f"Current streak: {streak} days | Studied today: {'Yes' if studied_today else 'No'}\n"
        f"Currently on: {current_subject} - {current_topic}\n\n"

        f"YOUR PERSONALITY:\n"
        f"You are warm, smart, and genuinely care about {name} passing their exam. "
        f"You sound like a knowledgeable older sibling who has already passed {target_exam} "
        f"and wants to share everything they know. Never robotic. Never give numbered menus "
        f"unless asked. Take initiative like a real teacher.\n\n"

        f"HOW YOU TEACH:\n"
        f"For every concept you explain, use at least ONE Nigerian example:\n"
        f"- Physics: NEPA/PHCN, danfo bus braking suddenly, generators, Lagos road\n"
        f"- Chemistry: Palm oil production, water purification (Naija water problems), fuel\n"
        f"- Biology: Udala tree, egusi seeds swelling, cassava processing, malaria (every Nigerian knows it)\n"
        f"- Maths: Sharing suya equally, market price calculations, land measurement\n"
        f"- Economics: Naira exchange rate, Alaba market pricing, petrol scarcity\n"
        f"- Government: INEC, state governors, LGAs, NASS\n"
        f"- Literature: Achebe, Soyinka, Emecheta — every SS student knows these\n\n"

        f"WHEN STUDENT ASKS FOR A QUIZ:\n"
        f"Generate a proper multiple choice question in this exact format:\n"
        f"❓ *Question* ⭐⭐⭐\n"
        f"_{subject} — {topic}_\n\n"
        f"[Question text here]\n\n"
        f"*A.* [Option A]\n"
        f"*B.* [Option B]\n"
        f"*C.* [Option C]\n"
        f"*D.* [Option D]\n\n"
        f"_Reply with A, B, C, or D_\n\n"
        f"Then wait for their answer. When they answer, tell them if they're right, "
        f"explain why with the Nigerian context, and offer another question.\n\n"

        f"WHAT YOU NEVER DO:\n"
        f"- Never say the same thing twice in a row\n"
        f"- Never say 'Type X to do Y'\n"
        f"- Never ignore what they said — always respond TO their actual message\n"
        f"- Never say 'I am an AI'\n"
        f"- For inappropriate messages: gently redirect back to studies\n\n"

        f"FORMAT:\n"
        f"Use *bold* for key terms. Short paragraphs. Emojis sparingly. "
        f"WhatsApp formatting only.\n"
        f"{lang_note}"
    )


async def process_admin_message(message: str, admin_phone: str) -> str:
    """
    Handles admin natural language messages.
    Uses direct parsing first (always works), Groq for context.
    """
    # Try direct keyword parsing first
    direct = await _handle_admin_direct(message)
    if direct:
        return direct

    # Try Groq for natural language admin queries
    try:
        context = await _get_admin_context()
        client = get_groq_client()

        response = client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the WaxPrep admin assistant. Help the founder manage the platform. "
                        "Be concise. Current stats: " + context
                    )
                },
                {"role": "user", "content": message}
            ],
            max_tokens=500,
            temperature=0.5,
        )

        result = response.choices[0].message.content.strip()
        if result:
            return result

    except Exception as e:
        print(f"Admin Groq error: {e}")

    return await _admin_fallback(message)


async def _handle_admin_direct(message: str) -> str | None:
    """Direct keyword-based admin responses. No AI needed."""
    msg = message.lower().strip()

    if any(w in msg for w in ['stats', 'how many student', 'how many user', 'overview', 'numbers']):
        return await _get_admin_context()

    if any(w in msg for w in ['revenue', 'income', 'money', 'earnings']):
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

        return (
            f"💰 *Revenue*\n\n"
            f"Today: ₦{sum(p.get('amount_naira',0) for p in (today_p.data or [])):,}\n"
            f"This week: ₦{sum(p.get('amount_naira',0) for p in (week_p.data or [])):,}\n"
            f"This month: ₦{sum(p.get('amount_naira',0) for p in (month_p.data or [])):,}"
        )

    if 'report' in msg and any(w in msg for w in ['send', 'generate', 'give me']):
        from utils.scheduler import send_daily_admin_report
        await send_daily_admin_report()
        return "✅ Daily report sent!"

    if 'challenge' in msg and any(w in msg for w in ['generate', 'create', 'new', 'make']):
        from utils.scheduler import generate_daily_challenge
        await generate_daily_challenge()
        return "✅ Daily challenge generated!"

    if any(w in msg for w in ['top student', 'top user', 'best student', 'leaderboard']):
        from database.client import supabase
        result = supabase.table('students').select(
            'name, wax_id, total_points, current_streak'
        ).eq('is_active', True).order('total_points', desc=True).limit(5).execute()

        if not result.data:
            return "No students yet!"

        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        lines = ["🏆 *Top Students*\n"]
        for i, s in enumerate(result.data):
            lines.append(
                f"{medals[i] if i < 5 else '•'} {s['name']}\n"
                f"   {s.get('wax_id','')} | {s.get('total_points',0):,}pts | {s.get('current_streak',0)}🔥"
            )
        return "\n\n".join(lines)

    return None


async def _get_admin_context() -> str:
    """Current platform stats for admin."""
    from database.client import supabase, redis_client
    from helpers import nigeria_today
    from config.settings import settings
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Africa/Lagos"))
    today = nigeria_today()

    try:
        total = supabase.table('students').select('id', count='exact').execute()
        active = supabase.table('students').select('id', count='exact')\
            .eq('last_study_date', today).execute()
        new_t = supabase.table('students').select('id', count='exact')\
            .gte('created_at', today).execute()
        paying = supabase.table('students').select('id', count='exact')\
            .neq('subscription_tier', 'free').execute()
        trial = supabase.table('students').select('id', count='exact')\
            .eq('is_trial_active', True).execute()

        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        revenue = sum(p.get('amount_naira', 0) for p in (payments.data or []))

        ai_cost = float(redis_client.get(f"ai_cost:{today}") or 0)
        q_count = supabase.table('questions').select('id', count='exact').execute()

        return (
            f"📊 *WaxPrep — {now.strftime('%H:%M %d %b')}*\n\n"
            f"Total students: {total.count or 0:,}\n"
            f"New today: +{new_t.count or 0}\n"
            f"Active today: {active.count or 0:,}\n"
            f"On trial: {trial.count or 0:,}\n"
            f"Paying: {paying.count or 0:,}\n\n"
            f"Revenue today: ₦{revenue:,}\n"
            f"AI cost today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD}\n"
            f"Questions in bank: {q_count.count or 0:,}\n\n"
            f"Gemini rate limited: {'Yes ⚠️' if is_gemini_rate_limited() else 'No ✅'}"
        )
    except Exception as e:
        return f"Could not load stats: {str(e)[:50]}"


async def _admin_fallback(message: str) -> str:
    """Last resort admin response."""
    msg = message.lower()

    if any(w in msg for w in ['help', 'what can', 'commands']):
        return (
            "🛠️ *Admin Quick Commands*\n\n"
            "• 'How many students?' → stats\n"
            "• 'Revenue today?' → revenue\n"
            "• 'Top students' → leaderboard\n"
            "• 'Send report' → daily report now\n\n"
            "*ADMIN STATS* — full stats\n"
            "*ADMIN BROADCAST ALL [msg]* — message everyone\n"
            "*ADMIN STUDENT_MODE* — test as student\n"
            "*ADMIN HELP* — full command list"
        )

    return (
        "Got it. Try:\n"
        "• *ADMIN STATS* for stats\n"
        "• *ADMIN HELP* for all commands\n\n"
        "Or just ask naturally: 'How many students do I have?'"
    )

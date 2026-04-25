"""
WaxPrep AI Brain

Groq primary (fast, free tier generous).
Gemini secondary (only when Groq fails completely).
FIXED: Uses updated model names from settings.
FIXED: Smarter quota detection.
"""

from groq import Groq
from config.settings import settings
import random

_groq = None


def get_groq():
    global _groq
    if _groq is None:
        _groq = Groq(api_key=settings.GROQ_API_KEY)
    return _groq


def is_gemini_available() -> bool:
    try:
        from database.client import redis_client
        return redis_client.get("gemini_rate_limited") is None
    except Exception:
        return True


def mark_gemini_limited(is_daily_limit: bool = False):
    try:
        from database.client import redis_client
        ttl = 3600 if is_daily_limit else 90
        redis_client.setex("gemini_rate_limited", ttl, "1")
        if is_daily_limit:
            print("Gemini daily quota exhausted — marked unavailable for 1 hour")
    except Exception:
        pass


async def get_student_deep_context(student: dict) -> dict:
    from database.client import supabase
    from helpers import nigeria_today

    student_id = student.get('id', '')

    context = {
        'weak_topics': [],
        'strong_topics': [],
        'days_until_exam': 0,
    }

    try:
        mastery = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score')\
            .eq('student_id', student_id)\
            .order('mastery_score', desc=False)\
            .limit(3).execute()

        if mastery.data:
            context['weak_topics'] = [
                f"{m['topic']} in {m['subject']} ({m['mastery_score']:.0f}%)"
                for m in mastery.data
            ]

        strong = supabase.table('mastery_scores')\
            .select('subject, topic, mastery_score')\
            .eq('student_id', student_id)\
            .order('mastery_score', desc=True)\
            .limit(2).execute()

        if strong.data:
            context['strong_topics'] = [
                f"{m['topic']} in {m['subject']} ({m['mastery_score']:.0f}%)"
                for m in strong.data
                if m['mastery_score'] > 60
            ]

        exam_date = student.get('exam_date', '')
        if exam_date:
            from datetime import datetime
            try:
                exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
                days = (exam_dt - datetime.now()).days
                context['days_until_exam'] = max(0, days)
            except Exception:
                pass

    except Exception as e:
        print(f"Context fetch error: {e}")

    return context


def build_system_prompt(student: dict, conversation: dict, deep_context: dict) -> str:
    from helpers import nigeria_today

    name = student.get('name', 'Student').split()[0]
    class_level = student.get('class_level', 'SS3')
    target_exam = student.get('target_exam', 'JAMB')
    subjects = student.get('subjects', [])
    state = student.get('state', 'Nigeria')
    streak = student.get('current_streak', 0)
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0)
    is_trial = student.get('is_trial_active', False)
    tier = student.get('subscription_tier', 'free')
    language = student.get('language_preference', 'english')
    today = nigeria_today()
    studied_today = student.get('last_study_date', '') == today
    subjects_str = ', '.join(subjects) if subjects else 'not set yet'
    days_left = deep_context.get('days_until_exam', 0)
    weak_topics = deep_context.get('weak_topics', [])
    strong_topics = deep_context.get('strong_topics', [])
    plan_str = "Full Trial Access" if is_trial else tier.capitalize()

    exam_urgency = ""
    if days_left > 0:
        if days_left <= 14:
            exam_urgency = f"CRITICAL: Only {days_left} days until {target_exam}. Be focused and specific."
        elif days_left <= 60:
            exam_urgency = f"IMPORTANT: {days_left} days until {target_exam}. Steady progress matters."
        else:
            exam_urgency = f"{days_left} days until {target_exam}. Build foundation now."

    weak_str = "\n".join([f"- {t}" for t in weak_topics]) if weak_topics else "Still learning their patterns"
    strong_str = "\n".join([f"- {t}" for t in strong_topics]) if strong_topics else "Still building"

    pidgin_note = ""
    if language == 'pidgin':
        pidgin_note = "\nLANGUAGE: Respond in Nigerian Pidgin mixed naturally with standard English for technical terms.\n"

    return f"""You are Wax — the AI study companion inside WaxPrep, Nigeria's most advanced exam preparation platform.

STUDENT YOU ARE TALKING WITH:
Name: {name}
Class: {class_level} | Exam: {target_exam} | State: {state}
Subjects: {subjects_str}
Plan: {plan_str}
{exam_urgency}

THEIR PERFORMANCE:
Questions answered: {answered:,} | Accuracy: {accuracy}%
Current streak: {streak} day{'s' if streak != 1 else ''} | Studied today: {'Yes' if studied_today else 'Not yet'}

WEAK AREAS (need most focus):
{weak_str}

STRONG AREAS:
{strong_str}

YOUR IDENTITY AND PERSONALITY:
You are Wax. You speak like a brilliant older sibling who has already passed these exams and wants to help. You are warm, direct, real. You never sound like a robot. You never give the same response twice. You take initiative.

CRITICAL PERSONALITY RULES:
1. Be conversational. Sound like a real person texting. Not a script.
2. When a student says "I have forgotten" or "I don't know" — EXPLAIN IT. Never show a help menu for academic questions.
3. When a student asks about a subject topic — explain it properly with a Nigerian example.
4. Only show commands/menu when the student explicitly asks "what can you do" or "help".
5. Never respond with just a list of commands to a genuine academic question.

WHAT YOU KNOW AND CAN DO:
1. Teach any topic in the Nigerian secondary school curriculum (JAMB, WAEC, NECO)
2. Generate quiz questions and evaluate answers
3. Explain concepts using Nigerian real-world examples
4. Help students understand their progress
5. Guide students on university admission processes in Nigeria

TEACHING STYLE:
For every concept, use at least one Nigerian example:
- Physics: NEPA cuts, danfo braking, generator sound waves
- Chemistry: Palm oil extraction, kerosene from crude oil
- Biology: Egusi seeds swelling (osmosis), malaria, cassava rotting
- Maths: Sharing suya equally, market profits
- Economics: Naira exchange rate, petrol subsidy

QUIZ FORMAT (use this EXACTLY every time):
*Question [number]* ⭐⭐⭐
_{{subject}} — {{topic}}_

[Question text here]

*A.* [Option A]
*B.* [Option B]
*C.* [Option C]
*D.* [Option D]

_Reply with A, B, C, or D_

WHEN EVALUATING ANSWERS:
If correct: Celebrate specifically. Explain WHY it's correct. Use a Nigerian example.
If wrong: NEVER say "Wrong" or "Incorrect". Vary encouragement. Explain the correct answer clearly.

CRITICAL RULES:
1. NEVER say you have processed a payment. You cannot process payments.
2. Prices: Scholar = N1,500/month, Pro = N3,000/month, Elite = N5,000/month. Scholar yearly = N15,000.
3. NEVER show admin data to students.
4. Use single asterisks (*bold*) not double.
5. Keep responses focused for WhatsApp — short paragraphs, line breaks.
{pidgin_note}"""


async def process_message_with_ai(
    message: str,
    student: dict,
    conversation: dict,
    conversation_history: list
) -> str:
    deep_context = await get_student_deep_context(student)
    system_prompt = build_system_prompt(student, conversation, deep_context)

    messages = [{"role": "system", "content": system_prompt}]

    for msg in conversation_history[-12:]:
        role = msg.get("role", "user")
        if role not in ["user", "assistant"]:
            role = "user"
        content = msg.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    # Try Groq smart model first
    try:
        client = get_groq()
        response = client.chat.completions.create(
            model=settings.GROQ_SMART_MODEL,
            messages=messages,
            max_tokens=900,
            temperature=0.75,
        )
        result = response.choices[0].message.content
        if result and len(result.strip()) > 10:
            return result.strip()
    except Exception as e:
        print(f"Groq smart error: {e}")

    # Try Groq fast model
    try:
        client = get_groq()
        response = client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=messages,
            max_tokens=700,
            temperature=0.7,
        )
        result = response.choices[0].message.content
        if result and len(result.strip()) > 10:
            return result.strip()
    except Exception as e:
        print(f"Groq fast error: {e}")

    # Try Gemini only as last resort
    if is_gemini_available():
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)

            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=system_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.8,
                    max_output_tokens=800,
                )
            )

            history = []
            for msg in conversation_history[-8:]:
                role = "user" if msg.get("role") == "user" else "model"
                history.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

            chat = model.start_chat(history=history)
            response = chat.send_message(message)

            text = ""
            try:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        text += part.text
            except Exception:
                pass

            if text.strip():
                return text.strip()

        except Exception as e:
            err = str(e)
            print(f"Gemini error: {err[:200]}")
            is_daily = (
                "GenerateRequestsPerDayPerProjectPerModel" in err or
                "quota_id" in err and "Day" in err or
                "limit: 0" in err
            )
            if "429" in err or "quota" in err.lower() or "exceeded" in err.lower():
                mark_gemini_limited(is_daily_limit=is_daily)

    return _smart_fallback(message, student, deep_context)


def _smart_fallback(message: str, student: dict, deep_context: dict) -> str:
    name = student.get('name', 'Student').split()[0]
    msg_lower = message.lower().strip()
    subjects = student.get('subjects', [])
    target_exam = student.get('target_exam', 'JAMB')
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0)
    streak = student.get('current_streak', 0)
    days_left = deep_context.get('days_until_exam', 0)
    weak_topics = deep_context.get('weak_topics', [])

    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'good morning', 'good evening', 'sup']):
        streak_line = f"Your {streak}-day streak is alive!" if streak > 1 else "Let's start a new streak today."
        days_line = f"{days_left} days to {target_exam}." if days_left > 0 else ""
        weak_line = f"Your weakest area right now is {weak_topics[0]}. That's our focus today." if weak_topics else f"Tell me which {target_exam} subject you want to tackle."
        return f"Hey {name}! {streak_line} {days_line}\n\n{weak_line}"

    if any(w in msg_lower for w in ['quiz', 'test', 'question', 'practice']):
        subject = subjects[0] if subjects else 'Mathematics'
        for s in subjects:
            if s.lower() in msg_lower:
                subject = s
                break
        return (
            f"On it, {name}! Getting a {subject} question ready.\n\n"
            f"_(Brief delay — ask again in 20 seconds if nothing comes)_"
        )

    if any(w in msg_lower for w in ['subscribe', 'upgrade', 'pay', 'plan', 'payment']):
        return (
            f"Great that you want to upgrade, {name}!\n\n"
            f"*Scholar Plan — N1,500/month*\n"
            f"100 questions/day, image analysis, full mock exams, study plan\n\n"
            f"*Scholar Yearly — N15,000/year* (save 17%)\n\n"
            f"Type *SUBSCRIBE* and then *SCHOLAR MONTHLY* to get your payment link."
        )

    if any(w in msg_lower for w in ['university', 'admission', 'cut off', 'jamb score', 'confused', 'what should i do']):
        return (
            f"{name}, I hear you. A lot of students are in this exact situation.\n\n"
            f"Tell me more about what happened and what you're considering. "
            f"I know the Nigerian university system well and can help you think through your options."
        )

    if any(w in msg_lower for w in ['progress', 'stats', 'how am i', 'score']):
        return (
            f"*{name}'s Progress*\n\n"
            f"Questions: {answered:,} answered | {accuracy}% accuracy\n"
            f"Streak: {streak} day{'s' if streak != 1 else ''}\n"
            f"Days to {target_exam}: {days_left if days_left > 0 else 'update your exam date'}\n\n"
            f"{'Focus: ' + weak_topics[0] if weak_topics else 'Keep going to identify patterns'}"
        )

    defaults = [
        f"I'm with you, {name}. My thinking is a bit slow right now — ask again in 30 seconds. What are we studying?",
        f"Got your message, {name}! Brief pause on my end. What subject do you want to tackle?",
        f"Hey {name}, I'm here. Give me 30 seconds and ask again — I'll give you a proper response.",
        f"Sorry about the delay, {name}. Ask me again and I'll respond properly. What subject?",
    ]
    return random.choice(defaults)


async def process_admin_message(message: str, admin_phone: str) -> str:
    direct = await _handle_admin_natural(message)
    if direct:
        return direct

    try:
        stats = await _get_admin_stats()
        client = get_groq()

        response = client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the WaxPrep admin assistant. Be brief and helpful. "
                        "Current platform: " + stats
                    )
                },
                {"role": "user", "content": message}
            ],
            max_tokens=400,
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"Admin Groq error: {e}")
        return "Use ADMIN STATS for stats or ADMIN HELP for all commands."


async def _handle_admin_natural(message: str):
    msg = message.lower().strip()

    if any(w in msg for w in ['stats', 'how many', 'numbers', 'overview']):
        return await _get_admin_stats()

    if any(w in msg for w in ['revenue', 'money', 'income', 'earnings']):
        from database.client import supabase
        from helpers import nigeria_today
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Africa/Lagos"))
        today = nigeria_today()
        week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')

        t = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        w = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', week_ago).eq('status', 'completed').execute()

        return (
            f"Revenue\n\n"
            f"Today: N{sum(p.get('amount_naira',0) for p in (t.data or [])):,}\n"
            f"This week: N{sum(p.get('amount_naira',0) for p in (w.data or [])):,}"
        )

    if 'report' in msg:
        from utils.scheduler import send_daily_admin_report
        await send_daily_admin_report()
        return "Daily report sent!"

    if 'top' in msg:
        from database.client import supabase
        r = supabase.table('students').select('name, wax_id, total_points, current_streak')\
            .eq('is_active', True).order('total_points', desc=True).limit(5).execute()
        if not r.data:
            return "No students yet!"
        medals = ['1st', '2nd', '3rd', '4th', '5th']
        lines = ["Top Students\n"]
        for i, s in enumerate(r.data):
            lines.append(f"{medals[i]} {s['name']} — {s.get('total_points',0):,}pts | {s.get('current_streak',0)} day streak")
        return "\n".join(lines)

    return None


async def _get_admin_stats() -> str:
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

        return (
            f"WaxPrep — {now.strftime('%H:%M, %d %b')}\n\n"
            f"Total students: {total.count or 0:,}\n"
            f"New today: +{new_t.count or 0}\n"
            f"Active today: {active.count or 0:,}\n"
            f"On trial: {trial.count or 0:,}\n"
            f"Paying: {paying.count or 0:,}\n\n"
            f"Revenue today: N{revenue:,}\n"
            f"AI cost: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD}"
        )
    except Exception as e:
        return f"Stats error: {str(e)[:80]}"

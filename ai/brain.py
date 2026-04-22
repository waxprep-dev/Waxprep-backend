"""
WaxPrep AI Brain — Rebuilt Simple Version

Architecture: Groq primary, Gemini secondary, context-aware fallback
No complex tool-calling. Just natural conversation.
Works on free tier of both APIs.
"""

from groq import Groq
from config.settings import settings

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


def mark_gemini_limited():
    try:
        from database.client import redis_client
        redis_client.setex("gemini_rate_limited", 70, "1")
    except Exception:
        pass


async def get_student_deep_context(student: dict) -> dict:
    """
    Gets rich context about a student for the AI to use.
    This is what makes responses feel personal and relevant.
    """
    from database.client import supabase
    from helpers import nigeria_today

    student_id = student.get('id', '')
    today = nigeria_today()

    context = {
        'weak_topics': [],
        'strong_topics': [],
        'recent_sessions': 0,
        'questions_this_week': 0,
        'last_topic_studied': '',
        'days_until_exam': 0,
    }

    try:
        # Get weak topics
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

        # Get strong topics
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

        # Days until exam
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
        print(f"Context fetch error (non-critical): {e}")

    return context


def build_system_prompt(student: dict, conversation: dict, deep_context: dict) -> str:
    """
    Builds a rich, personal system prompt for Wax.
    The more personal and specific this is, the more natural the conversation feels.
    """
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

    exam_urgency = ""
    if days_left > 0:
        if days_left <= 14:
            exam_urgency = f"CRITICAL: Only {days_left} days until {target_exam}. Be focused and urgent."
        elif days_left <= 60:
            exam_urgency = f"IMPORTANT: {days_left} days until {target_exam}. Every session counts."
        else:
            exam_urgency = f"There are {days_left} days until {target_exam}. Steady progress is the strategy."

    weak_str = "\n".join([f"- {t}" for t in weak_topics]) if weak_topics else "Not enough data yet"
    strong_str = "\n".join([f"- {t}" for t in strong_topics]) if strong_topics else "Still building"

    plan_str = "Full Trial Access" if is_trial else tier.capitalize()

    pidgin_note = ""
    if language == 'pidgin':
        pidgin_note = "\nLANGUAGE STYLE: Communicate in Nigerian Pidgin mixed with standard English for technical terms. Sound like a smart friend who grew up in Nigeria.\n"

    return f"""You are Wax — the AI study companion inside WaxPrep, Nigeria's most advanced exam preparation platform.

WHO YOU ARE TALKING TO RIGHT NOW:
Name: {name}
Class: {class_level} | Exam: {target_exam} | State: {state}
Subjects: {subjects_str}
Plan: {plan_str}
{exam_urgency}

THEIR LEARNING HISTORY:
Total questions answered: {answered:,}
Accuracy rate: {accuracy}%
Current streak: {streak} day{'s' if streak != 1 else ''}
Studied today: {'Yes' if studied_today else 'Not yet'}

WEAK AREAS (needs most attention):
{weak_str}

STRONG AREAS (doing well here):
{strong_str}

YOUR IDENTITY:
You are Wax. You are warm, direct, and genuinely invested in {name} passing their {target_exam} exam. You are not a chatbot — you are more like a brilliant older sibling who has already passed these exams and wants to share everything they know. You speak with confidence. You take initiative. You never say "I am an AI." You never give numbered menus unless specifically asked.

YOUR TEACHING STYLE:
You always make the abstract concrete using Nigerian real-world examples. This is not optional — every explanation must have at least one Nigerian reference:
- Physics concepts → NEPA current cuts, generator noise, danfo bus braking, okada weaving through traffic
- Chemistry → palm oil processing, egusi grinding, petrol (everyone knows fuel scarcity), water from the tap that may or may not be clean
- Biology → malaria (every Nigerian has had it), egusi seeds soaking in water for osmosis, udala tree and photosynthesis, cassava processing for respiration
- Mathematics → sharing money among siblings, market price calculations, land measurement in plots
- Economics → Naira exchange rate pain, Alaba International Market pricing, petrol subsidy removal
- Government → INEC elections, state governors, LGA chairmen, NASS members
- Literature → Chinua Achebe's Things Fall Apart (every SS student has read it), Wole Soyinka, Buchi Emecheta

HOW YOU RESPOND:
1. When they greet you: greet them back personally using their name, reference something specific about them (their streak, their exam countdown, something they studied before), and proactively suggest what to focus on based on their weak areas.

2. When they ask about a subject topic: explain it thoroughly. Start with what they probably already know. Build up from there. Use a Nigerian example. End with a check-in question.

3. When they want a quiz: generate a proper multiple choice question immediately. Format it exactly like this:
❓ *Question* ⭐⭐⭐
_{subject} — {topic}_

[Question text here]

*A.* [Option A]
*B.* [Option B]  
*C.* [Option C]
*D.* [Option D]

_Reply with A, B, C, or D_

4. When they answer A, B, C, or D: evaluate their answer. If correct, celebrate briefly, explain why it's correct, and immediately offer the next question. If wrong, use an encouraging phrase ("Almost!" "Close!" "Good thinking but...") — NEVER say "wrong" or "incorrect" — then explain the correct answer, explain why theirs was wrong, and offer another try.

5. When they seem stressed or mention difficulty: acknowledge it first. Then redirect to what they can control (studying this topic right now). Keep it brief — don't over-therapize.

6. When they say something inappropriate: respond calmly, note that WaxPrep is a study platform, and immediately pivot back to their studies.

WHAT YOU NEVER DO:
- Never give the same response twice in a row
- Never say "I cannot" or "I don't have access to"
- Never say "Type X to do Y" — just do it
- Never ignore what they actually said
- Never be robotic or list-heavy unless they ask for a list
- Never say you're an AI or break character

FORMAT:
WhatsApp formatting only. Use *bold* for key terms and important answers. Line breaks between ideas. Short paragraphs. Emojis used warmly but not excessively — maybe one or two per response maximum.
{pidgin_note}"""


async def process_message_with_ai(
    message: str,
    student: dict,
    conversation: dict,
    conversation_history: list
) -> str:
    """
    Main function. Every student message comes here.
    Groq is primary. Gemini is backup. Context-aware fallback is last resort.
    """
    deep_context = await get_student_deep_context(student)
    system_prompt = build_system_prompt(student, conversation, deep_context)

    # Build message history for Groq
    messages = [{"role": "system", "content": system_prompt}]

    for msg in conversation_history[-12:]:
        role = msg.get("role", "user")
        if role == "assistant":
            role = "assistant"
        else:
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

    # Try Gemini if not rate limited
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
            print(f"Gemini error: {err[:100]}")
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                mark_gemini_limited()

    # All AI failed — context-aware fallback
    return _smart_fallback(message, student, deep_context)


def _smart_fallback(message: str, student: dict, deep_context: dict) -> str:
    """
    When all AI fails, this responds intelligently based on what the student said.
    Never the same message twice.
    """
    name = student.get('name', 'Student').split()[0]
    msg_lower = message.lower().strip()
    subjects = student.get('subjects', [])
    target_exam = student.get('target_exam', 'JAMB')
    answered = student.get('total_questions_answered', 0)
    accuracy = round((student.get('total_questions_correct', 0) / answered * 100) if answered > 0 else 0)
    streak = student.get('current_streak', 0)
    days_left = deep_context.get('days_until_exam', 0)
    weak_topics = deep_context.get('weak_topics', [])

    # Greeting
    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'good morning', 'good evening', 'good afternoon', 'sup']):
        streak_line = f"Your {streak}-day streak is still alive 🔥 Don't let it die today." if streak > 1 else ""
        days_line = f"You have {days_left} days until {target_exam}." if days_left > 0 else ""
        weak_line = f"Your weakest area right now is {weak_topics[0]}. That's where we should focus." if weak_topics else ""

        return (
            f"Hey {name}! Good to see you. 😊\n\n"
            f"{streak_line}\n"
            f"{days_line}\n"
            f"{weak_line}\n\n"
            f"What subject are we tackling today?"
        ).replace("\n\n\n", "\n\n").strip()

    # Quiz request
    if any(w in msg_lower for w in ['quiz', 'test', 'question', 'practice', 'quizme', 'quiz me']):
        subject = subjects[0] if subjects else 'Mathematics'
        for s in subjects:
            if s.lower() in msg_lower:
                subject = s
                break
        return (
            f"Let's do it, {name}! Give me a second to pull up a {subject} question for you. 🎯\n\n"
            f"_(My thinking engine is a bit slow right now — ask again in 20 seconds and "
            f"I'll have a proper question ready for you!)_"
        )

    # Explanation request
    if any(w in msg_lower for w in ['explain', 'what is', 'what are', 'how does', 'how do', 'teach', 'help me', 'i don\'t understand', 'i dont understand']):
        return (
            f"Great question, {name}! Let me think through the best way to explain this. 🤔\n\n"
            f"I'm just a bit overloaded right now — try again in 30 seconds and I'll give you "
            f"a proper explanation with a Nigerian example you'll actually remember. 💡"
        )

    # Progress check
    if any(w in msg_lower for w in ['progress', 'stats', 'how am i doing', 'how am i', 'my score', 'my result']):
        return (
            f"📊 *{name}'s Progress*\n\n"
            f"Questions answered: {answered:,}\n"
            f"Accuracy: {accuracy}%\n"
            f"Current streak: {streak} day{'s' if streak != 1 else ''}\n"
            f"Days until {target_exam}: {days_left if days_left > 0 else 'update your exam date'}\n\n"
            f"{'Focus on: ' + weak_topics[0] if weak_topics else 'Keep practicing to identify your weak areas!'}"
        )

    # Default — never the same as "Hey David I'm here"
    import random
    options = [
        f"I'm with you, {name}. My processing is a tiny bit slow — ask again in 30 seconds. What subject?",
        f"Got your message, {name}! Just a brief delay on my end. What are we studying today?",
        f"Hey {name}, I'm here! Give me 30 seconds and ask again — I'll respond properly. What's the topic?",
    ]
    return random.choice(options)


async def process_admin_message(message: str, admin_phone: str) -> str:
    """Natural language admin interface using Groq."""
    from ai.brain import _get_admin_stats

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
                        "You are the WaxPrep admin assistant. The founder is asking you questions. "
                        "Be brief and helpful. Current platform status: " + stats
                    )
                },
                {"role": "user", "content": message}
            ],
            max_tokens=400,
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print(f"Admin AI error: {e}")
        return await _handle_admin_natural(message) or (
            "Got it. Use *ADMIN STATS* for stats or *ADMIN HELP* for all commands."
        )


async def _handle_admin_natural(message: str):
    """Keyword-based admin responses. Always works."""
    msg = message.lower().strip()

    if any(w in msg for w in ['stats', 'how many', 'numbers', 'overview', 'students']):
        return await _get_admin_stats()

    if any(w in msg for w in ['revenue', 'money', 'income', 'payment', 'earnings']):
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

        rev_t = sum(p.get('amount_naira', 0) for p in (t.data or []))
        rev_w = sum(p.get('amount_naira', 0) for p in (w.data or []))

        return f"💰 *Revenue*\nToday: ₦{rev_t:,}\nThis week: ₦{rev_w:,}"

    if 'report' in msg:
        from utils.scheduler import send_daily_admin_report
        await send_daily_admin_report()
        return "✅ Daily report sent!"

    if 'top' in msg and any(w in msg for w in ['student', 'user']):
        from database.client import supabase
        r = supabase.table('students').select('name, wax_id, total_points, current_streak')\
            .eq('is_active', True).order('total_points', desc=True).limit(5).execute()
        if not r.data:
            return "No students yet!"
        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        lines = ["🏆 *Top Students*\n"]
        for i, s in enumerate(r.data):
            lines.append(f"{medals[i]} {s['name']} — {s.get('total_points',0):,}pts | {s.get('current_streak',0)}🔥")
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
            f"📊 *WaxPrep — {now.strftime('%H:%M, %d %b')}*\n\n"
            f"Total students: {total.count or 0:,}\n"
            f"New today: +{new_t.count or 0}\n"
            f"Active today: {active.count or 0:,}\n"
            f"On trial: {trial.count or 0:,}\n"
            f"Paying: {paying.count or 0:,}\n\n"
            f"Revenue today: ₦{revenue:,}\n"
            f"AI cost: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD}"
        )
    except Exception as e:
        return f"Stats error: {str(e)[:80]}"

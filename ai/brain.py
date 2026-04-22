"""
WaxPrep AI Brain — Fixed Version

Fixes in this version:
1. AI can no longer hallucinate payment processing
2. Correct pricing in all responses
3. Admin data cannot leak to students
4. Encouragement is varied, never the same twice
5. Knowledge of university guidance for confused students
6. Single asterisk formatting for WhatsApp
7. Groq primary, Gemini secondary
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


def mark_gemini_limited():
    try:
        from database.client import redis_client
        redis_client.setex("gemini_rate_limited", 70, "1")
    except Exception:
        pass


async def get_student_deep_context(student: dict) -> dict:
    """Gets rich context about a student for personalised responses."""
    from database.client import supabase
    from helpers import nigeria_today

    student_id = student.get('id', '')
    today = nigeria_today()

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
    """Builds the complete system prompt for Wax."""
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
You are Wax. You speak like a brilliant older sibling who has already passed these exams. You are warm, direct, and genuinely invested in {name}'s success. You never sound like a robot. You never give the same response twice. You take initiative — you don't wait for the student to figure out what to ask.

WHAT YOU KNOW AND CAN DO:
1. Teach any topic in the Nigerian secondary school curriculum (JAMB, WAEC, NECO)
2. Generate quiz questions and evaluate answers
3. Explain concepts using Nigerian real-world examples
4. Help students understand their progress
5. Guide students on university admission processes in Nigeria
6. Help confused students figure out their next steps after JAMB

UNIVERSITY GUIDANCE — THIS IS IMPORTANT:
Many Nigerian students are confused about university admission. You understand this completely:
- Students who scored below their cut-off mark: Guide them on supplementary admission (Direct Entry, Post-UTME for other schools, Part-Time programmes, School of Preliminary Studies, change of institution or course)
- Students who want to change their course: Explain JAMB change of institution/course process, timelines, and which schools offer similar programmes
- Students who are confused whether to resit: Help them weigh options honestly — resitting JAMB vs. accepting a lower school vs. looking at polytechnics vs. waiting another year
- Students about to give up: Remind them that most great Nigerians did not get into their first choice university. Chinua Achebe. Fela. Dangote didn't even finish university. The path matters more than the starting point.
- JAMB supplementary admission: Guide them through CAPS, accepting offers, DE options
- Polytechnic vs. university: Honest comparison based on their field and goals
- Changing from science to social science or vice versa: Subject combination requirements, what to do

TEACHING STYLE:
For every concept you explain, always use at least one Nigerian example:
- Physics: NEPA cuts, danfo braking, generator sound waves, okada on a bumpy road
- Chemistry: Palm oil extraction, kerosene from crude oil, salt from the sea in Badagry
- Biology: Egusi seeds swelling (osmosis), malaria (vector transmission), cassava rotting (decay)
- Maths: Sharing suya equally, market profits, land in plots and hectares
- Economics: Naira exchange rate, petrol subsidy, Alaba market prices
- Government: INEC, governorship, National Assembly, NASS
- English: Achebe's Things Fall Apart, oral tradition in Yoruba culture, proverbs

QUIZ FORMAT (use this EXACTLY every time):
When asked for a quiz, generate a proper question in this format with SINGLE asterisks:

*Question [number]* ⭐⭐⭐
_{subject} — {topic}_

[Question text here]

*A.* [Option A]
*B.* [Option B]
*C.* [Option C]
*D.* [Option D]

_Reply with A, B, C, or D_

WHEN EVALUATING ANSWERS:
If correct: Celebrate specifically (not generically). Explain WHY it's correct. Use a Nigerian example. Then offer the next question or ask if they want to continue.
If wrong: NEVER say "Don't worry, you're still doing great!" — vary your encouragement completely. Say things like "Almost there!" or "Good attempt — let me show you the gap" or "You're thinking in the right direction" or "That's actually a very common mix-up." Then explain the correct answer clearly, explain why their answer was wrong, and offer to try again.

CRITICAL RULES — NEVER BREAK THESE:
1. NEVER say you have processed a payment. You cannot process payments. When a student wants to subscribe, tell them: "To subscribe to Scholar Plan for ₦1,500/month, tap this link: [payment link will be sent automatically] — or contact us directly." Do NOT say the payment was processed.
2. NEVER quote these prices: ₦2,000, ₦5,000, ₦10,000 for plans. The real prices are: Scholar = ₦1,500/month, Pro = ₦3,000/month, Elite = ₦5,000/month. Scholar yearly = ₦15,000.
3. NEVER show admin data to students (total students, revenue figures, AI costs).
4. NEVER use double asterisks (**bold**) — WhatsApp uses single asterisks (*bold*) for bold text.
5. NEVER give the same encouragement twice in one conversation. Vary it every time.
6. NEVER make up features that don't exist (video lessons, community forum, coaching).
7. NEVER say "I've processed" or "I've gone ahead and" — you cannot take backend actions without telling the student you're doing it.

WHEN STUDENT ASKS TO SUBSCRIBE OR UPGRADE:
Say exactly this structure:
"I'd love to get you on Scholar Plan, {name}! Here's what you get:
- 60 questions per day
- Image analysis (send photos of textbooks)
- Full mock exams
- Personalized study plan

Price: ₦1,500/month or ₦15,000/year (save 17%)

Tap here to pay securely: [I'm generating your payment link now]

Once you pay, your plan activates automatically within seconds."

Then try to generate the actual payment link. If it fails, say: "I'm having trouble with the payment link right now. Please message us at [your support contact] and we'll sort it out immediately."

WHEN STUDENT IS CONFUSED ABOUT LIFE, UNIVERSITY, OR THEIR FUTURE:
This is one of the most important things you do. Take it seriously.
Listen first. Don't jump to solutions. Then guide them through their actual options clearly. Use real Nigerian examples — people who took unconventional paths and succeeded. Be honest about difficult realities while being hopeful about possibilities.

FORMAT FOR WHATSAPP:
Single asterisks for bold: *bold text*
Line breaks between ideas
Short paragraphs — no walls of text
Use emojis warmly: one or two maximum per response
Never use code blocks (```text```) in regular conversation
{pidgin_note}"""


async def process_message_with_ai(
    message: str,
    student: dict,
    conversation: dict,
    conversation_history: list
) -> str:
    """
    Main function. Groq primary, Gemini secondary.
    All student messages come here — no admin data ever shown.
    """
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

    # Try Groq smart model
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

    # Try Gemini
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
            if "429" in err or "quota" in err.lower():
                mark_gemini_limited()

    return _smart_fallback(message, student, deep_context)


def _smart_fallback(message: str, student: dict, deep_context: dict) -> str:
    """Context-aware fallback when all AI fails. Never the same message."""
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

    # Greeting
    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'good morning', 'good evening', 'sup']):
        streak_line = f"Your {streak}-day streak is alive 🔥" if streak > 1 else "Let's start a new streak today."
        days_line = f"{days_left} days to {target_exam}." if days_left > 0 else ""
        weak_line = f"Your weakest area right now is {weak_topics[0]}. That's our focus today." if weak_topics else f"Tell me which {target_exam} subject you want to tackle."
        return f"Hey {name}! {streak_line} {days_line}\n\n{weak_line}"

    # Quiz
    if any(w in msg_lower for w in ['quiz', 'test', 'question', 'practice']):
        subject = subjects[0] if subjects else 'Mathematics'
        for s in subjects:
            if s.lower() in msg_lower:
                subject = s
                break
        return (
            f"On it, {name}! Getting a {subject} question ready. 🎯\n\n"
            f"_(Brief delay — ask again in 20 seconds if nothing comes)_"
        )

    # Subscription
    if any(w in msg_lower for w in ['subscribe', 'upgrade', 'pay', 'plan', 'payment']):
        return (
            f"Great that you want to upgrade, {name}!\n\n"
            f"*Scholar Plan — ₦1,500/month*\n"
            f"60 questions/day, image analysis, full mock exams, study plan\n\n"
            f"*Scholar Yearly — ₦15,000/year* (save 17%)\n\n"
            f"I'm having trouble generating your payment link right now. "
            f"Please try again in 30 seconds and I'll send it directly."
        )

    # University confusion
    if any(w in msg_lower for w in ['university', 'admission', 'cut off', 'jamb score', 'confused', 'what should i do', 'change course']):
        return (
            f"{name}, I hear you. A lot of students are in this exact situation — "
            f"and most of them figure it out.\n\n"
            f"Tell me more about what happened and what you're considering. "
            f"I know the Nigerian university system well and I can help you think through your options. "
            f"Whether it's supplementary admission, changing institution, poly vs. uni, "
            f"or resitting — we'll work through it together."
        )

    # Progress
    if any(w in msg_lower for w in ['progress', 'stats', 'how am i', 'score']):
        return (
            f"*{name}'s Progress*\n\n"
            f"Questions: {answered:,} answered | {accuracy}% accuracy\n"
            f"Streak: {streak} day{'s' if streak != 1 else ''}\n"
            f"Days to {target_exam}: {days_left if days_left > 0 else 'update your exam date'}\n\n"
            f"{'Focus: ' + weak_topics[0] if weak_topics else 'Keep going to identify patterns'}"
        )

    # Varied default responses — never the same twice
    defaults = [
        f"I'm with you, {name}. My thinking is a bit slow right now — ask again in 30 seconds. What are we studying?",
        f"Got your message, {name}! Brief pause on my end. What subject do you want to tackle?",
        f"Hey {name}, I'm here. Give me 30 seconds and ask again — I'll give you a proper response.",
        f"Sorry about the delay, {name}. Ask me again and I'll respond properly. What subject?",
    ]
    return random.choice(defaults)


async def process_admin_message(message: str, admin_phone: str) -> str:
    """Natural language admin interface using Groq."""
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
        return "Use *ADMIN STATS* for stats or *ADMIN HELP* for all commands."


async def _handle_admin_natural(message: str):
    """Direct keyword admin responses. No AI needed."""
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
            f"*Revenue*\n\n"
            f"Today: ₦{sum(p.get('amount_naira',0) for p in (t.data or [])):,}\n"
            f"This week: ₦{sum(p.get('amount_naira',0) for p in (w.data or [])):,}"
        )

    if 'report' in msg:
        from utils.scheduler import send_daily_admin_report
        await send_daily_admin_report()
        return "✅ Daily report sent!"

    if 'top' in msg:
        from database.client import supabase
        r = supabase.table('students').select('name, wax_id, total_points, current_streak')\
            .eq('is_active', True).order('total_points', desc=True).limit(5).execute()
        if not r.data:
            return "No students yet!"
        medals = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
        lines = ["*Top Students*\n"]
        for i, s in enumerate(r.data):
            lines.append(f"{medals[i]} {s['name']} — {s.get('total_points',0):,}pts | {s.get('current_streak',0)}🔥")
        return "\n".join(lines)

    return None


async def _get_admin_stats() -> str:
    """Current platform stats for admin only — never shown to students."""
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

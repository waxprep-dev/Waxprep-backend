"""
WaxPrep AI Brain — Natural Conversation Engine

This is how ChatGPT, Claude, and Gemini work:
Every message goes to an AI model. The AI decides what to do.
No commands. No numbered menus. No instructions to memorize.

The student just talks. Wax understands and responds.

Architecture:
- Student sends any message in any format
- Gemini reads the message + conversation history + student profile
- Gemini decides: should I explain something? Quiz them? Show progress? Generate a payment link?
- Gemini calls the right internal function (called "tools")
- The function runs and returns data
- Gemini writes a natural response using that data
- Student receives a human response, not a robotic one

This is called "function calling" or "tool use" — it's how all modern AI assistants work.
"""

import json
from typing import Optional
import google.generativeai as genai
from config.settings import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

# ============================================================
# TOOL DEFINITIONS
# These are the actions Wax can take.
# Gemini reads these descriptions and decides which to call.
# ============================================================

WAXPREP_TOOLS = [
    {
        "name": "get_student_progress",
        "description": "Get the student's learning progress, stats, streak, points, level, and subscription status. Use when student asks about their progress, stats, streak, how they're doing, their account, or their profile.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "generate_quiz_question",
        "description": "Generate and send a quiz question to the student. Use when student wants to be tested, quizzed, practice questions, or says things like 'quiz me', 'test me', 'give me a question', 'practice', 'let me try'. Extract subject and topic from context.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject (e.g. Physics, Chemistry, Mathematics, Biology, English Language, Economics, Government)"
                },
                "topic": {
                    "type": "string",
                    "description": "Specific topic within the subject, if mentioned. Leave empty if not specified."
                }
            },
            "required": ["subject"]
        }
    },
    {
        "name": "get_subscription_info",
        "description": "Get subscription plans and generate a payment link. Use when student asks about pricing, how to subscribe, upgrade, pay, plans, or cost.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "The plan they want: scholar, pro, or elite. Default to scholar if unclear.",
                    "enum": ["scholar", "pro", "elite"]
                },
                "billing": {
                    "type": "string",
                    "description": "monthly or yearly",
                    "enum": ["monthly", "yearly"]
                }
            },
            "required": []
        }
    },
    {
        "name": "get_daily_challenge",
        "description": "Get today's daily challenge question. Use when student asks about the daily challenge, wants to try the hard question of the day, or mentions the challenge.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "start_mock_exam",
        "description": "Start a mock exam simulation. Use when student says mock exam, practice test, simulation, wants to do a full exam, or mentions JAMB/WAEC/NECO simulation.",
        "parameters": {
            "type": "object",
            "properties": {
                "exam_type": {
                    "type": "string",
                    "description": "JAMB, WAEC, or NECO",
                    "enum": ["JAMB", "WAEC", "NECO"]
                },
                "num_questions": {
                    "type": "integer",
                    "description": "Number of questions. Use 20 for quick practice, 100 for full JAMB simulation."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_my_wax_id",
        "description": "Show the student their WAX ID and account details. Use when student asks for their ID, account number, WAX ID.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "apply_promo_code",
        "description": "Apply a promotional code to the student's account. Use when student mentions a promo code, discount code, or coupon.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The promo code the student mentioned"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "get_study_plan",
        "description": "Get or create the student's personalized study plan. Use when student asks about their plan, what to study, study schedule, or how to prepare.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "teach_topic",
        "description": "Explain and teach a specific topic in detail. Use when student asks you to explain something, teach them, help them understand a concept. This is the primary learning function.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject"
                },
                "topic": {
                    "type": "string",
                    "description": "What they want to learn about"
                },
                "question": {
                    "type": "string",
                    "description": "The student's exact question or what they said"
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "check_answer",
        "description": "Check if the student's answer to a quiz question is correct and explain. Use when student has answered a question (A, B, C, D or typed an answer to a question that was just asked).",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The student's answer"
                }
            },
            "required": ["answer"]
        }
    },
    {
        "name": "show_weak_areas",
        "description": "Show the student their weak topics that need more work. Use when student asks about weak areas, what to focus on, where they're struggling.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


async def process_message_with_ai(
    message: str,
    student: dict,
    conversation: dict,
    conversation_history: list
) -> str:
    """
    The main function. Every student message comes here.
    
    Gemini reads the message, understands context, decides what action to take,
    calls the right function, and returns a natural response.
    
    Returns the text response to send to the student.
    """
    
    student_context = _build_student_context(student, conversation)
    system_prompt = _build_system_prompt(student, student_context)
    
    # Format history for Gemini
    history = []
    for msg in conversation_history[-12:]:
        role = "user" if msg.get("role") == "user" else "model"
        history.append({
            "role": role,
            "parts": [{"text": msg.get("content", "")}]
        })
    
    try:
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system_prompt,
            tools=_build_gemini_tools(),
            generation_config=genai.types.GenerationConfig(
                temperature=0.8,
                max_output_tokens=1500,
            )
        )
        
        chat = model.start_chat(history=history)
        response = chat.send_message(message)
        
        # Check if Gemini wants to call a function
        if response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'function_call') and part.function_call:
                    fn_name = part.function_call.name
                    fn_args = dict(part.function_call.args) if part.function_call.args else {}
                    
                    # Execute the function
                    fn_result = await _execute_tool(fn_name, fn_args, student, conversation, message)
                    
                    # Send result back to Gemini for natural response
                    function_response = chat.send_message(
                        genai.protos.Content(
                            parts=[genai.protos.Part(
                                function_response=genai.protos.FunctionResponse(
                                    name=fn_name,
                                    response={"result": fn_result}
                                )
                            )]
                        )
                    )
                    
                    return _extract_text(function_response)
        
        # No function call — direct response
        return _extract_text(response)
    
    except Exception as e:
        print(f"Brain error: {e}")
        import traceback
        traceback.print_exc()
        
        # Fallback to simple Groq response
        return await _fallback_response(message, student, conversation_history)


def _extract_text(response) -> str:
    """Extracts text from Gemini response."""
    try:
        text = ""
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'text') and part.text:
                text += part.text
        return text.strip() if text.strip() else "I'm here! What would you like to study?"
    except Exception:
        return "I'm here! What would you like to study?"


def _build_gemini_tools():
    """
    Builds Gemini tools in a format that works with the free API.
    Simplified to avoid schema issues on the free tier.
    """
    declarations = []
    for tool in WAXPREP_TOOLS:
        props = {}
        for k, v in tool.get("parameters", {}).get("properties", {}).items():
            schema = genai.protos.Schema(
                type=genai.protos.Type.STRING,
                description=v.get("description", "")
            )
            props[k] = schema

        declarations.append(
            genai.protos.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties=props
                ) if props else None
            )
        )

    return [genai.protos.Tool(function_declarations=declarations)]

def _build_student_context(student: dict, conversation: dict) -> str:
    """Builds a context string about the student for the AI."""
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
    learning_style = student.get('learning_style', 'example_based')
    motivational_style = student.get('motivational_style', 'celebrations')
    current_subject = conversation.get('current_subject', '')
    current_topic = conversation.get('current_topic', '')
    
    from helpers import nigeria_today
    today = nigeria_today()
    last_study = student.get('last_study_date', '')
    studied_today = last_study == today
    
    # Days until exam
    days_until_exam = ""
    if exam_date:
        try:
            from datetime import datetime
            exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
            days_left = (exam_dt - datetime.now()).days
            days_until_exam = f"{days_left} days until {target_exam}"
        except Exception:
            pass
    
    return f"""
STUDENT PROFILE:
Name: {name}
WAX ID: {wax_id}
Class: {class_level}
Target Exam: {target_exam}
Subjects: {', '.join(subjects)}
State: {state}
Exam countdown: {days_until_exam}

PERFORMANCE:
Streak: {streak} days
Total Questions Answered: {answered}
Accuracy Rate: {accuracy}%
Points: {points:,}
Level: {level} ({level_name})
Studied Today: {'Yes' if studied_today else 'No'}

SUBSCRIPTION:
Plan: {'Trial (full access)' if is_trial else tier.capitalize()}

CURRENT SESSION:
Currently studying: {current_subject} - {current_topic if current_topic else 'nothing specific yet'}

PREFERENCES:
Language: {language}
Learning Style: {learning_style}
Motivation Style: {motivational_style}
"""


def _build_system_prompt(student: dict, student_context: str) -> str:
    """Builds the main system prompt for Wax."""
    name = student.get('name', 'Student').split()[0]
    target_exam = student.get('target_exam', 'JAMB')
    state = student.get('state', 'Nigeria')
    language = student.get('language_preference', 'english')
    
    language_note = ""
    if language == 'pidgin':
        language_note = """
LANGUAGE: Communicate in Nigerian Pidgin English naturally mixed with standard English for technical terms.
Sound like a knowledgeable, friendly older sibling who grew up in Nigeria."""
    
    return f"""You are Wax — the AI study companion inside WaxPrep, Nigeria's most advanced educational platform.

You are having a NATURAL CONVERSATION with {name}, a Nigerian secondary school student preparing for {target_exam}.

{student_context}

YOUR PERSONALITY:
- You are warm, intelligent, and genuinely care about {name}'s success
- You speak like a knowledgeable friend who has already passed these exams
- You are never robotic. You never list commands or give instructions like a manual
- You read what the student says and UNDERSTAND what they need
- You take initiative — like a real teacher, not a robot waiting for exact commands
- You know Nigerian culture deeply: NEPA, danfo, suya, Lagos traffic, generator, egusi — use these in examples
- You celebrate small wins. A student answering correctly is a big deal to you
- You notice when they seem stressed and respond with warmth before diving into academics

HOW YOU WORK:
- When the student asks ANYTHING related to their studies, you either explain it directly or call the right function
- When they say "quiz me" or anything like it, call generate_quiz_question
- When they answer a question, call check_answer
- When they ask about their progress, call get_student_progress
- When they ask about payment, call get_subscription_info
- When they just want to learn something, call teach_topic or explain directly
- When they seem lost or don't know what to do, SUGGEST something proactively

WHAT YOU NEVER DO:
- Never say "Type PROGRESS to see your stats" — just show them
- Never say "Please choose from the following options: 1, 2, 3" — just respond naturally
- Never give robotic instructions like "send QUIZ to start a quiz"
- Never say "I am an AI" or break character
- Never ask "What do you want to do?" when it's obvious from context

NIGERIAN CONTEXT FOR EXPLANATIONS:
Always use at least one Nigerian real-life example:
- Physics: NEPA/PHCN, generators, danfo buses, Lagos traffic
- Chemistry: palm oil production, water purification, fuel/petrol
- Biology: udala trees, cassava farming, malaria, egusi
- Mathematics: market pricing, sharing suya, land measurements
- Economics: Naira exchange rates, Lagos market
- Government: INEC, state governors, LGAs, Nigerian federal structure
- Literature: Chinua Achebe, Wole Soyinka, Buchi Emecheta

FORMATTING FOR WHATSAPP:
- Use *bold* for important terms
- Use line breaks between ideas
- Keep responses focused — not too long, not too short
- Use emojis warmly but not excessively 🎯🔥💡✅
- Don't write walls of text — break it up

{language_note}

Remember: {name} has {student.get('exam_date', 'an exam')} coming up. Every message you send could be the one that helps them pass. Take that seriously. Be the teacher they deserve."""


async def _execute_tool(
    tool_name: str,
    args: dict,
    student: dict,
    conversation: dict,
    original_message: str
) -> str:
    """
    Executes the function that Gemini decided to call.
    Returns a string result that Gemini uses to write a natural response.
    """
    
    student_id = student.get('id', '')
    
    if tool_name == "get_student_progress":
        return await _tool_get_progress(student)
    
    elif tool_name == "generate_quiz_question":
        subject = args.get('subject', '')
        topic = args.get('topic', '')
        if not subject:
            subjects = student.get('subjects', [])
            subject = subjects[0] if subjects else 'Mathematics'
        return await _tool_generate_quiz(student, conversation, subject, topic)
    
    elif tool_name == "get_subscription_info":
        plan = args.get('plan', 'scholar')
        billing = args.get('billing', 'monthly')
        return await _tool_get_subscription(student, plan, billing)
    
    elif tool_name == "get_daily_challenge":
        return await _tool_daily_challenge(student, conversation)
    
    elif tool_name == "start_mock_exam":
        exam_type = args.get('exam_type', student.get('target_exam', 'JAMB'))
        num_questions = args.get('num_questions', 20)
        return await _tool_start_exam(student, conversation, exam_type, num_questions)
    
    elif tool_name == "get_my_wax_id":
        return f"WAX ID: {student.get('wax_id', 'Not found')}. Recovery Code is stored securely. The student can use this WAX ID to log in on any device."
    
    elif tool_name == "apply_promo_code":
        code = args.get('code', '').upper()
        return await _tool_apply_promo(student, code)
    
    elif tool_name == "get_study_plan":
        return await _tool_get_study_plan(student)
    
    elif tool_name == "teach_topic":
        question = args.get('question', original_message)
        subject = args.get('subject', '')
        topic = args.get('topic', '')
        return f"TEACH THIS: Subject={subject}, Topic={topic}, Question={question}. Provide a thorough, engaging explanation using Nigerian examples."
    
    elif tool_name == "check_answer":
        answer = args.get('answer', original_message)
        return await _tool_check_answer(student, conversation, answer)
    
    elif tool_name == "show_weak_areas":
        return await _tool_weak_areas(student)
    
    return "I'm here and ready to help!"


async def _tool_get_progress(student: dict) -> str:
    """Returns student progress data as a string for Gemini to use."""
    from database.students import get_student_subscription_status
    from helpers import nigeria_today
    
    answered = student.get('total_questions_answered', 0)
    correct = student.get('total_questions_correct', 0)
    accuracy = round((correct / answered * 100) if answered > 0 else 0)
    streak = student.get('current_streak', 0)
    points = student.get('total_points', 0)
    level = student.get('current_level', 1)
    level_name = student.get('level_name', 'Scholar')
    
    status = await get_student_subscription_status(student)
    
    today = nigeria_today()
    last_study = student.get('last_study_date', '')
    studied_today = last_study == today
    
    return f"""
Student Progress Data:
- WAX ID: {student.get('wax_id')}
- Plan: {status['display_tier']}
- Questions Answered: {answered:,}
- Correct Answers: {correct:,}
- Accuracy: {accuracy}%
- Current Streak: {streak} days
- Longest Streak: {student.get('longest_streak', 0)} days
- Total Points: {points:,}
- Level: {level} - {level_name}
- Studied Today: {'Yes' if studied_today else 'No'}
- Trial Active: {student.get('is_trial_active', False)}
- Trial Expires: {str(student.get('trial_expires_at', ''))[:10]}
"""


async def _tool_generate_quiz(student: dict, conversation: dict, subject: str, topic: str) -> str:
    """Generates a quiz question and stores it in conversation state."""
    from features.quiz_engine import get_question_for_student, format_question_for_whatsapp, record_question_seen
    from database.conversations import update_conversation_state
    
    question = await get_question_for_student(
        student_id=student['id'],
        subject=subject,
        topic=topic if topic else None,
        exam_type=student.get('target_exam', 'JAMB')
    )
    
    if not question:
        return f"Could not find a question for {subject} - {topic}. Try a different subject or topic."
    
    # Store the question for answer checking
    state = conversation.get('conversation_state', {})
    if isinstance(state, str):
        import json
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    
    await update_conversation_state(
        conversation['id'], 'whatsapp', conversation.get('platform_user_id', ''),
        {
            'current_mode': 'quiz',
            'current_subject': subject,
            'current_topic': topic or question.get('topic', ''),
            'conversation_state': {
                **state,
                'awaiting_response_for': 'quiz_answer',
                'current_question': question,
            }
        }
    )
    
    if question.get('id'):
        await record_question_seen(student['id'], question['id'])
    
    q = format_question_for_whatsapp(question, 1)
    return f"Here is the question to show the student:\n{q}\n\nPresent this question naturally. Don't add instructions about how to answer — they'll know to reply with A, B, C, or D."


async def _tool_check_answer(student: dict, conversation: dict, answer: str) -> str:
    """Checks the student's answer to the current question."""
    import json
    from features.quiz_engine import evaluate_quiz_answer, update_mastery_after_answer, calculate_and_award_points
    from database.conversations import update_conversation_state
    from database.questions import update_question_stats
    
    state = conversation.get('conversation_state', {})
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    
    current_question = state.get('current_question')
    
    if not current_question:
        return "No active question to check. Generate a new quiz question."
    
    is_correct, feedback = evaluate_quiz_answer(
        answer,
        current_question.get('correct_answer', 'A'),
        current_question
    )
    
    if is_correct is None:
        return "Answer couldn't be parsed. Ask the student to reply with just A, B, C, or D."
    
    subject = current_question.get('subject', '')
    topic = current_question.get('topic', '')
    difficulty = current_question.get('difficulty_level', 5)
    
    await update_mastery_after_answer(student['id'], subject, topic, difficulty, is_correct)
    
    if current_question.get('id'):
        await update_question_stats(current_question['id'], is_correct)
    
    points, badge = await calculate_and_award_points(student['id'], is_correct, difficulty)
    
    from database.students import increment_questions_today
    await increment_questions_today(student['id'])
    
    # Clear question from state
    await update_conversation_state(
        conversation['id'], 'whatsapp', conversation.get('platform_user_id', ''),
        {
            'conversation_state': {
                **state,
                'awaiting_response_for': 'quiz_continue',
                'current_question': None,
                'last_was_correct': is_correct,
            }
        }
    )
    
    badge_info = f"\n\nNEW BADGE EARNED: {badge['name']} - {badge['description']}" if badge else ""
    
    return f"""
Answer result: {'CORRECT' if is_correct else 'WRONG'}
Points earned: {points}
{feedback}
{badge_info}

Now proactively offer to ask another question or move to a related topic. Be encouraging.
"""


async def _tool_get_subscription(student: dict, plan: str, billing: str) -> str:
    """Returns subscription info and generates a payment link."""
    from config.settings import settings
    from helpers import format_naira
    
    price_map = {
        ('scholar', 'monthly'): settings.SCHOLAR_MONTHLY,
        ('scholar', 'yearly'): settings.SCHOLAR_YEARLY,
        ('pro', 'monthly'): settings.PRO_MONTHLY,
        ('pro', 'yearly'): settings.PRO_YEARLY,
    }
    
    amount = price_map.get((plan.lower(), billing.lower()), settings.SCHOLAR_MONTHLY)
    
    # Try to generate payment link
    payment_url = None
    try:
        from database.subscriptions import generate_paystack_payment_link
        payment_url = await generate_paystack_payment_link(student, plan, billing)
    except Exception as e:
        print(f"Payment link error: {e}")
    
    trial_info = ""
    if student.get('is_trial_active'):
        trial_info = "Student is currently on trial with full access."
    
    return f"""
Subscription Information:
- Scholar Monthly: {format_naira(settings.SCHOLAR_MONTHLY)}/month
- Scholar Yearly: {format_naira(settings.SCHOLAR_YEARLY)}/year (save 17%)
- Scholar includes: 60 questions/day, image analysis, mock exams, personalized study plan
{trial_info}

Payment link for {plan} {billing}: {payment_url if payment_url else 'Could not generate link - tell student to try again'}
Amount: {format_naira(amount)}

Present this conversationally. Don't list everything robotically. 
Mention the payment link naturally: 'Here's your secure payment link: [url]'
"""


async def _tool_daily_challenge(student: dict, conversation: dict) -> str:
    """Gets and presents today's daily challenge."""
    from features.daily_challenge import get_todays_challenge, has_student_attempted_today, format_daily_challenge
    from database.conversations import update_conversation_state
    
    challenge = await get_todays_challenge()
    
    if not challenge:
        return "No daily challenge available yet today. Tell the student it goes live at 8 AM."
    
    already_tried = await has_student_attempted_today(student['id'])
    
    if already_tried:
        attempts = challenge.get('total_attempts', 0)
        correct = challenge.get('total_correct', 0)
        rate = round((correct / attempts * 100) if attempts > 0 else 0)
        return f"Student already attempted today's challenge. Show them stats: {attempts} students tried, {rate}% got it right. Tell them tomorrow's challenge comes at 8 AM."
    
    formatted = format_daily_challenge(challenge)
    
    state = conversation.get('conversation_state', {})
    if isinstance(state, str):
        import json
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    
    await update_conversation_state(
        conversation['id'], 'whatsapp', conversation.get('platform_user_id', ''),
        {
            'conversation_state': {
                **state,
                'awaiting_response_for': 'challenge_answer',
                'current_challenge': challenge,
            }
        }
    )
    
    return f"Present this daily challenge to the student:\n{formatted}\nBuild it up — make them excited about the challenge!"


async def _tool_start_exam(student: dict, conversation: dict, exam_type: str, num_questions: int) -> str:
    """Starts a mock exam."""
    from database.students import get_student_subscription_status
    from config.settings import settings
    from helpers import format_naira
    
    status = await get_student_subscription_status(student)
    
    if status['effective_tier'] == 'free' and not status['is_trial']:
        return f"Student is on free plan. Mock exams require Scholar plan ({format_naira(settings.SCHOLAR_MONTHLY)}/month). Tell them this warmly and offer to generate a 5-question practice instead."
    
    subjects = student.get('subjects', ['Mathematics', 'English Language'])
    
    from database.questions import get_questions_for_mock_exam
    from database.client import supabase
    from helpers import nigeria_now
    
    questions = await get_questions_for_mock_exam(exam_type, subjects, min(num_questions, 40))
    
    if not questions or len(questions) < 3:
        return "Could not get enough questions for a full exam. Tell the student the question bank is still being built and offer a quiz instead."
    
    exam_record = supabase.table('mock_exams').insert({
        'student_id': student['id'],
        'exam_type': exam_type,
        'total_questions': len(questions),
        'time_limit_minutes': 60,
        'max_score': len(questions),
        'status': 'in_progress',
        'questions_data': [q.get('id', '') for q in questions],
        'started_at': nigeria_now().isoformat(),
    }).execute()
    
    exam_id = exam_record.data[0]['id'] if exam_record.data else None
    
    from database.conversations import update_conversation_state
    import json
    
    state = conversation.get('conversation_state', {})
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    
    first_q = questions[0]
    
    await update_conversation_state(
        conversation['id'], 'whatsapp', conversation.get('platform_user_id', ''),
        {
            'current_mode': 'exam',
            'conversation_state': {
                **state,
                'exam_id': exam_id,
                'exam_type': exam_type,
                'questions': [q.get('id', '') for q in questions],
                'all_questions': questions,
                'current_question_index': 0,
                'answers': {},
                'correct_count': 0,
                'awaiting_response_for': 'exam_answer',
            }
        }
    )
    
    q_text = first_q.get('question_text', '')
    a = first_q.get('option_a', '')
    b = first_q.get('option_b', '')
    c = first_q.get('option_c', '')
    d = first_q.get('option_d', '')
    
    return f"""
Exam started successfully. {len(questions)} questions ready.
Exam type: {exam_type}

Tell the student: Exam is starting now! No hints allowed during the exam (just like the real thing).
Present Question 1 of {len(questions)}:
Subject: {first_q.get('subject', '')}

{q_text}

A. {a}
B. {b}
C. {c}
D. {d}

Tell them to reply A, B, C, or D. Sound like a real exam proctor - serious but encouraging.
"""


async def _tool_apply_promo(student: dict, code: str) -> str:
    """Applies a promo code."""
    from database.client import supabase
    from helpers import nigeria_now
    
    result = supabase.table('promo_codes').select('*').eq('code', code.upper()).eq('is_active', True).execute()
    
    if not result.data:
        return f"Promo code {code} is not valid or has expired. Tell the student this and suggest they check the code again."
    
    promo = result.data[0]
    
    # Check if already used
    used = supabase.table('promo_code_uses').select('id')\
        .eq('promo_code_id', promo['id']).eq('student_id', student['id']).execute()
    
    if used.data:
        return f"Student already used code {code}. Tell them each code can only be used once."
    
    # Apply benefit
    code_type = promo.get('code_type', '')
    bonus_days = promo.get('bonus_days', 3)
    
    from database.students import update_student
    from datetime import timedelta, datetime
    
    if code_type == 'full_trial':
        trial_exp_str = student.get('trial_expires_at', '')
        now = nigeria_now()
        try:
            current_end = datetime.fromisoformat(trial_exp_str.replace('Z', '+00:00')) if trial_exp_str else now
            new_end = max(current_end, now) + timedelta(days=bonus_days)
        except Exception:
            new_end = now + timedelta(days=bonus_days)
        
        await update_student(student['id'], {
            'trial_expires_at': new_end.isoformat(),
            'is_trial_active': True
        })
        
        benefit = f"{bonus_days} extra days of full access, expires {new_end.strftime('%d %B %Y')}"
    
    elif code_type == 'tier_upgrade':
        tier = promo.get('tier_to_unlock', 'scholar')
        new_expires = nigeria_now() + timedelta(days=bonus_days)
        await update_student(student['id'], {
            'subscription_tier': tier,
            'subscription_expires_at': new_expires.isoformat()
        })
        benefit = f"Upgraded to {tier.capitalize()} for {bonus_days} days"
    
    else:
        benefit = "Benefit applied to account"
    
    # Record use
    supabase.table('promo_code_uses').insert({
        'promo_code_id': promo['id'],
        'student_id': student['id'],
        'benefit_applied': {'code': code, 'type': code_type}
    }).execute()
    supabase.table('promo_codes').update({
        'current_uses': promo.get('current_uses', 0) + 1
    }).eq('id', promo['id']).execute()
    
    return f"Promo code {code} applied successfully! Benefit: {benefit}. Celebrate this with the student!"


async def _tool_get_study_plan(student: dict) -> str:
    """Gets or generates a study plan."""
    from database.client import supabase
    
    result = supabase.table('study_plans').select('*')\
        .eq('student_id', student['id']).eq('is_active', True)\
        .order('created_at', desc=True).limit(1).execute()
    
    subjects = student.get('subjects', [])
    exam_date = student.get('exam_date', '')
    target_exam = student.get('target_exam', 'JAMB')
    
    days_left = 180
    if exam_date:
        try:
            from datetime import datetime
            exam_dt = datetime.strptime(exam_date, '%Y-%m-%d')
            days_left = max(1, (exam_dt - datetime.now()).days)
        except Exception:
            pass
    
    if result.data:
        plan = result.data[0]
        return f"""
Study plan exists:
Daily target: {plan.get('daily_question_target', 20)} questions
Focus subjects: {', '.join(plan.get('focus_subjects', subjects[:3]))}
Weak topics: {', '.join(plan.get('weak_topics', [])[:3])}
Days until exam: {days_left}

Present this as a real teacher would — talk through their week with them, not as a list.
"""
    else:
        return f"""
No study plan yet. Generate one conversationally.
Student: {target_exam}, {days_left} days left, subjects: {', '.join(subjects)}
Tell them what they should focus on based on their exam and timeline.
Speak like a real teacher planning with a student, not generating a document.
"""


async def _tool_weak_areas(student: dict) -> str:
    """Gets weak areas for the student."""
    from database.client import supabase
    
    result = supabase.table('mastery_scores').select('subject, topic, mastery_score')\
        .eq('student_id', student['id'])\
        .lt('mastery_score', 60)\
        .order('mastery_score', desc=False)\
        .limit(5).execute()
    
    if not result.data:
        return "Student has no weak areas tracked yet — they haven't studied enough topics to identify patterns. Encourage them to start studying and the system will learn their weak spots."
    
    weak = [(f"{m['subject']}: {m['topic']} ({m['mastery_score']:.0f}% mastery)") for m in result.data]
    return f"Weak areas: {', '.join(weak)}. Present these warmly — frame it as 'here's where we'll focus to get your score up', not as failures."


async def _fallback_response(message: str, student: dict, history: list) -> str:
    """Simple fallback if Gemini function calling fails."""
    from ai.groq_client import ask_groq
    from ai.prompts import get_main_tutor_prompt
    
    system = get_main_tutor_prompt(student, 'default')
    return await ask_groq(
        system_prompt=system,
        user_message=message,
        conversation_history=history[-8:],
        student_id=student.get('id')
    )


# ============================================================
# ADMIN AI BRAIN
# Admin just talks naturally from their phone
# ============================================================

async def process_admin_message(message: str, admin_phone: str) -> str:
    """
    Natural conversation for admin.
    Admin just says what they want in plain English.
    No commands to memorize.
    """
    
    system_prompt = """You are the WaxPrep admin assistant. You help the founder manage WaxPrep.

The admin can ask you anything about the platform and you will:
1. Understand what they want naturally — no exact commands needed
2. Call the right function to get data or take action
3. Respond in a friendly, concise way

Examples of what admin might say and what they mean:
- "How many students do I have?" → get platform stats
- "Send a message to all free users saying X" → broadcast to free tier
- "What's today's revenue?" → get revenue data
- "Give Chidi a free month" → find student and upgrade
- "Create a promo code for 20% off" → create discount code
- "Who are my top students?" → show leaderboard
- "Block WAX-A74892" → ban student
- "Show me students in Lagos" → search by state
- "Generate today's challenge" → trigger challenge generation
- "What's my AI bill?" → show AI cost

Be conversational. The admin is the founder of WaxPrep — treat them with respect and get things done for them."""
    
    try:
        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction=system_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                max_output_tokens=1000,
            )
        )
        
        # Build admin context
        context = await _get_admin_context()
        full_message = f"{context}\n\nAdmin says: {message}"
        
        response = model.generate_content(full_message)
        
        # Check if we need to take action
        action = await _parse_admin_intent(message)
        if action:
            result = await _execute_admin_action(action, message)
            
            # Get Gemini to write a natural response about the action
            followup = model.generate_content(
                f"Action taken: {action}\nResult: {result}\n\nWrite a brief, natural response to the admin."
            )
            return _extract_text(followup)
        
        return _extract_text(response)
    
    except Exception as e:
        print(f"Admin brain error: {e}")
        return f"Sorry, something went wrong. Error: {str(e)[:100]}"


async def _get_admin_context() -> str:
    """Gets current platform stats for admin context."""
    from database.client import supabase, redis_client
    from helpers import nigeria_today
    from config.settings import settings
    
    today = nigeria_today()
    
    try:
        total = supabase.table('students').select('id', count='exact').execute()
        active = supabase.table('students').select('id', count='exact').eq('last_study_date', today).execute()
        paying = supabase.table('students').select('id', count='exact').neq('subscription_tier', 'free').execute()
        
        ai_cost = float(redis_client.get(f"ai_cost:{today}") or 0)
        
        payments = supabase.table('payments').select('amount_naira')\
            .gte('completed_at', today).eq('status', 'completed').execute()
        revenue = sum(p.get('amount_naira', 0) for p in (payments.data or []))
        
        return f"""
CURRENT PLATFORM STATUS ({today}):
Total students: {total.count or 0:,}
Active today: {active.count or 0:,}
Paying subscribers: {paying.count or 0:,}
Today's revenue: ₦{revenue:,}
AI cost today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD}
"""
    except Exception:
        return "Platform status: Could not load stats"


async def _parse_admin_intent(message: str) -> str | None:
    """Parses what action the admin wants to take."""
    msg = message.lower()
    
    if any(w in msg for w in ['stats', 'how many', 'numbers', 'overview', 'dashboard']):
        return 'get_stats'
    elif 'broadcast' in msg or 'send to all' in msg or 'message all' in msg or 'tell all' in msg:
        return 'broadcast'
    elif 'upgrade' in msg or 'give' in msg and ('plan' in msg or 'free' in msg or 'month' in msg):
        return 'upgrade_student'
    elif 'ban' in msg or 'block' in msg:
        return 'ban_student'
    elif 'promo' in msg and ('create' in msg or 'make' in msg or 'new' in msg):
        return 'create_promo'
    elif 'report' in msg and 'send' in msg:
        return 'send_report'
    elif 'challenge' in msg and ('generate' in msg or 'create' in msg or 'make' in msg):
        return 'generate_challenge'
    elif 'top' in msg and ('student' in msg or 'user' in msg):
        return 'top_students'
    
    return None


async def _execute_admin_action(action: str, message: str) -> str:
    """Executes an admin action and returns result string."""
    
    if action == 'get_stats':
        return await _get_admin_context()
    
    elif action == 'send_report':
        from utils.scheduler import send_daily_admin_report
        await send_daily_admin_report()
        return "Daily report sent to your WhatsApp"
    
    elif action == 'generate_challenge':
        from utils.scheduler import generate_daily_challenge
        await generate_daily_challenge()
        return "Daily challenge generated"
    
    elif action == 'top_students':
        from database.client import supabase
        result = supabase.table('students').select('name, wax_id, total_points, current_streak')\
            .eq('is_active', True).order('total_points', desc=True).limit(5).execute()
        if result.data:
            lines = [f"{i+1}. {s['name']} ({s['wax_id']}) — {s.get('total_points',0):,} pts, {s.get('current_streak',0)}🔥" 
                    for i, s in enumerate(result.data)]
            return "Top 5 students:\n" + "\n".join(lines)
        return "No students found"
    
    elif action == 'broadcast':
        import re
        # Try to extract the message and target
        # "send to all free users: you're missing out on..."
        # "broadcast to scholars: exam season is here"
        target = 'ALL'
        if 'free' in message.lower():
            target = 'FREE'
        elif 'scholar' in message.lower():
            target = 'SCHOLAR'
        elif 'trial' in message.lower():
            target = 'TRIAL'
        
        # Extract the message content after common separators
        separators = ['saying', 'message:', 'msg:', 'content:', ':', 'that', 'saying']
        broadcast_msg = message
        for sep in separators:
            if sep in message.lower():
                idx = message.lower().index(sep) + len(sep)
                broadcast_msg = message[idx:].strip().strip('"\'')
                break
        
        if len(broadcast_msg) < 5:
            return "Could not identify the message to broadcast. Please be more specific."
        
        # Execute broadcast
        from admin.dashboard import admin_broadcast
        from config.settings import settings
        if settings.ADMIN_WHATSAPP:
            await admin_broadcast(settings.ADMIN_WHATSAPP, f"{target} {broadcast_msg}")
            return f"Broadcast to {target} users: '{broadcast_msg[:50]}...'"
        return "Admin WhatsApp not configured"
    
    return f"Action {action} noted but not fully implemented yet"

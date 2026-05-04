"""
Telegram Message Handler
Uses the same AI brain, DB, and flows but sends replies via Telegram (not WhatsApp).
Includes quiz timer with subject‑based durations.
"""

import asyncio
from config.settings import settings
from helpers import sanitize_input, nigeria_now
from utils.background import bg_task

# ---------- Subject‑based quiz timer (seconds) ----------
QUIZ_TIMERS = {
    'physics': 50,
    'chemistry': 50,
    'mathematics': 60,
    'further mathematics': 70,
    'biology': 35,
    'economics': 35,
    'government': 35,
    'literature in english': 40,
    'english language': 40,
    'geography': 40,
    'commerce': 35,
    'agricultural science': 35,
    'computer studies': 40,
    'christian religious studies': 30,
    'islamic religious studies': 30,
}
DEFAULT_QUIZ_TIMER = 35   # fallback for any subject not listed


def _quiz_seconds(subject: str) -> int:
    """Return the quiz time limit for a given subject."""
    if not subject:
        return DEFAULT_QUIZ_TIMER
    return QUIZ_TIMERS.get(subject.strip().lower(), DEFAULT_QUIZ_TIMER)


async def process_telegram_update(update: dict) -> None:
    """Handles a single Telegram update (message or callback query)."""
    from telegram.sender import send_telegram_message

    # 1. Callback query (inline button press)
    callback_query = update.get('callback_query')
    if callback_query:
        await _handle_callback_query(callback_query)
        return

    # 2. Text message
    message_data = update.get('message')
    if not message_data:
        return

    chat = message_data.get('chat', {})
    chat_id = chat.get('id')
    if not chat_id:
        return

    user = message_data.get('from', {})
    name = user.get('first_name', 'Student')
    text = message_data.get('text', '')

    if text:
        text = sanitize_input(text)

    if not text:
        return

    # ----- Student lookup ------------------------------------------------
    from database.students import get_student_by_platform_id
    student = await get_student_by_platform_id('telegram', str(chat_id))

    # ----- Onboarding (no student yet) -----------------------------------
    if not student:
        # Use the NEW Redis-based onboarding state store instead of
        # the conversation system. Temp conversations lose state on every
        # message because they can't persist to Supabase.
        from database.conversations import get_onboarding_state
        from ai.classifier import ONBOARDING_STATES
        from telegram.onboarding import handle_onboarding_response as tg_onboarding_response
        from telegram.onboarding import handle_new_or_existing as tg_onboarding

        # Load onboarding state directly from Redis (keyed by platform + chat_id)
        onboarding_state = await get_onboarding_state('telegram', str(chat_id))
        awaiting = onboarding_state.get('awaiting_response_for', '')

        # Also get a conversation object (needed for function signatures)
        from database.conversations import get_or_create_conversation
        conversation = await get_or_create_conversation(
            student_id='anonymous',
            platform='telegram',
            platform_user_id=str(chat_id)
        )

        if awaiting and awaiting in ONBOARDING_STATES:
            # Continue from where they left off
            await tg_onboarding_response(chat_id, conversation, text, onboarding_state_override=onboarding_state)
        else:
            # Fresh start
            await tg_onboarding(chat_id, conversation, text)
        return

    if student.get('is_banned'):
        await send_telegram_message(
            chat_id,
            "Your account has been suspended. If you believe this is an error, contact WaxPrep support."
        )
        return

    if student.get('is_deleted'):
        await send_telegram_message(chat_id, "This account has been deleted. Create a new one anytime.")
        return

    # ----- Admin commands ------------------------------------------------
    from admin.dashboard import is_admin, handle_admin_command
    msg_upper = text.strip().upper() if text else ''

    if is_admin(f"telegram:{chat_id}") and msg_upper.startswith('ADMIN '):
        await handle_admin_command(f"telegram:{chat_id}", text)
        return

    if is_admin(f"telegram:{chat_id}") and msg_upper.startswith('$DIAG'):
        await _send_diagnostic_telegram(chat_id)
        return

    # ----- Hard trigger check -------------------------------------------
    from ai.classifier import classify_hard_trigger, ONBOARDING_STATES
    from database.conversations import get_or_create_conversation, update_conversation_state

    conversation = await get_or_create_conversation(
        student_id=student['id'],
        platform='telegram',
        platform_user_id=str(chat_id)
    )
    conv_state = conversation.get('conversation_state', {})
    if isinstance(conv_state, str):
        import json
        try:
            conv_state = json.loads(conv_state)
        except Exception:
            conv_state = {}

    awaiting = conv_state.get('awaiting_response_for', '')

    if awaiting and awaiting in ONBOARDING_STATES:
        from telegram.onboarding import handle_onboarding_response as tg_onboarding_response
        await tg_onboarding_response(chat_id, conversation, text)
        return

    # Account deletion PIN confirmation
    if awaiting == 'delete_confirm_pin':
        from helpers import verify_pin
        name = student.get('name', 'Student').split()[0]
        entered_pin = text.strip()
        if verify_pin(entered_pin, student['pin_hash']):
            try:
                from database.client import supabase
                from helpers import nigeria_now
                supabase.table('students').update({
                    'is_deleted': True,
                    'deleted_at': nigeria_now().isoformat(),
                    'is_active': False,
                }).eq('id', student['id']).execute()
                await send_telegram_message(
                    chat_id,
                    f"Account deleted, {name}.\n\n"
                    "Your data will be permanently erased in 30 days. "
                    "If you change your mind, message us within that time.\n\n"
                    "Thank you for using WaxPrep."
                )
            except Exception as e:
                print(f"Account deletion error (Telegram): {e}")
                await send_telegram_message(chat_id, "Something went wrong. Please try again.")
        else:
            await send_telegram_message(
                chat_id,
                f"PIN incorrect, {name}. Account not deleted."
            )
        # Clear the state regardless
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': {**conv_state, 'awaiting_response_for': None}
        })
        return

    if conv_state.get('current_question') and classify_hard_trigger(text, conv_state):
        conv_state['current_question'] = None

    trigger = classify_hard_trigger(text, conv_state)

    # --- Subscription flow ---
    if trigger == 'SUBSCRIBE':
        from whatsapp.flows.subscription import handle_subscription_flow
        await handle_subscription_flow(
            f"telegram:{chat_id}", student, conversation, text
        )
        return
    if trigger == 'SUBSCRIPTION_PROMO':
        from whatsapp.flows.subscription import handle_promo_code_during_checkout
        await handle_promo_code_during_checkout(
            f"telegram:{chat_id}", student, conversation, text, conv_state
        )
        return

    # --- Simple commands ---
    if trigger == 'MYID':
        await send_telegram_message(chat_id,
            f"Your WAX ID, {student.get('name', 'Student').split()[0]}\n\n"
            f"*{student.get('wax_id', 'Unknown')}*\n\n"
            "This is your permanent identity on WaxPrep. "
            "Use it to log in on any device.\n\n"
            "_Never share your PIN with anyone._"
        )
        return

    if trigger == 'MYPLAN' or trigger == 'MY PLAN':
        from database.students import get_student_subscription_status
        from helpers import format_naira
        status = await get_student_subscription_status(student)
        name = student.get('name', 'Student').split()[0]
        tier = status['display_tier']
        days = status.get('days_remaining')
        msg = f"*{name}'s Current Plan*\nPlan: *{tier}*\n"
        if days is not None:
            msg += f"Days remaining: {days}\n"
        if status['effective_tier'] == 'free':
            msg += f"\nUpgrade to Scholar for just {format_naira(settings.SCHOLAR_MONTHLY)}/month.\nType *SUBSCRIBE* when you are ready."
        elif status.get('is_in_grace_period'):
            msg += "\nYou are in your grace period. Type *SUBSCRIBE* to renew now."
        await send_telegram_message(chat_id, msg)
        return

    if trigger == 'PING':
        await send_telegram_message(chat_id, f"Pong! I'm here and ready, {student.get('name', 'Student').split()[0]}.")
        return

    if trigger == 'VERIFY PAYMENT' or trigger == 'I HAVE PAID':
        from features.payment_verifier import handle_verify_payment
        await handle_verify_payment(str(chat_id), student, 'telegram')
        return

    # If student asks for a quiz while another quiz is pending, remind them
    if conv_state.get('current_question') and any(kw in text.lower() for kw in ['quiz', 'test me', 'question me']):
        await send_telegram_message(chat_id, "You still have a question waiting. Answer that one first, then we'll keep going.")
        return

    if trigger == 'PROGRESS':
        from database.students import get_student_profile_summary
        summary = await get_student_profile_summary(student)
        await send_telegram_message(chat_id, summary)
        return

    if trigger == 'TEST':
        from features.test_harness import handle_test_command
        await handle_test_command(chat_id, student, conversation, text)
        return

    if msg_upper == 'DELETE ACCOUNT':
        name = student.get('name', 'Student').split()[0]
        await send_telegram_message(
            chat_id,
            f"Are you sure you want to permanently delete your account, {name}?\n\n"
            "This will erase your WAX ID, all progress, streaks, and badges.\n\n"
            "Type your *4‑digit PIN* to confirm, or just ignore this message to cancel."
        )
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': {**conv_state, 'awaiting_response_for': 'delete_confirm_pin'}
        })
        return

    # ----- Quiz answer evaluation ----------------------------------------
    from ai.classifier import looks_like_quiz_answer
    current_question = conv_state.get('current_question')
    if current_question and looks_like_quiz_answer(text):
        await _evaluate_and_respond_telegram(chat_id, student, conversation, text, conv_state)
        return

    # --- Bug/suggest ---
    if trigger == 'BUG':
        from features.feedback import handle_bug_report
        response = await handle_bug_report(f"telegram:{chat_id}", student, text)
        await send_telegram_message(chat_id, response)
        return
    if trigger == 'SUGGEST':
        from features.feedback import handle_suggestion
        response = await handle_suggestion(f"telegram:{chat_id}", student, text)
        await send_telegram_message(chat_id, response)
        return

    # ----- All other messages → AI brain --------------------------------
    await _think_and_respond_telegram(chat_id, student, conversation, text, conv_state)


async def _handle_callback_query(callback_query: dict):
    from telegram.sender import send_telegram_message
    data = callback_query.get('data', '')
    message = callback_query.get('message', {})
    chat = message.get('chat', {})
    chat_id = chat.get('id')
    if not chat_id or not data:
        return

    import httpx
    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={"callback_query_id": callback_query['id']})
    except Exception:
        pass

    fake_update = {
        "message": {
            "chat": {"id": chat_id},
            "from": message.get('from', {}),
            "text": data
        }
    }
    await process_telegram_update(fake_update)


async def _think_and_respond_telegram(chat_id: int, student: dict, conversation: dict,
                                      message: str, conv_state: dict):
    # ---- Race condition guard ----
    from database.conversations import acquire_student_lock, release_student_lock
    from telegram.sender import send_telegram_message

    locked = await acquire_student_lock(student['id'])
    if not locked:
        await send_telegram_message(chat_id, "I'm still processing your last message. One moment.")
        return

    try:
        from database.conversations import (get_conversation_history, update_conversation_state,
                                            save_message)
        from database.students import can_student_ask_question, increment_questions_today
        from ai.brain import think
        from ai.context_manager import get_full_student_context
        from helpers import nigeria_today

        can_ask, limit_msg = await can_student_ask_question(student)
        if not can_ask:
            await send_telegram_message(chat_id, limit_msg)
            return

        # ---- Long‑pause re‑entry ----
        from datetime import datetime, timedelta
        last_ts = conversation.get('last_message_at')
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(str(last_ts).replace('Z', '+00:00'))
                now_nig = nigeria_now()
                gap = (now_nig - last_dt.replace(tzinfo=now_nig.tzinfo)
                       if last_dt.tzinfo is None else now_nig - last_dt)
                if gap > timedelta(hours=1):
                    current_subject = conversation.get('current_subject', 'General Studies')
                    topic = conversation.get('current_topic', 'where we left off')
                    warm_greeting = (
                        f"It's been a while—welcome back! "
                        f"We were on {current_subject} – {topic}. "
                        f"Ready to keep going?"
                    )
                    await send_telegram_message(chat_id, warm_greeting)
                    await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
                        'last_message_at': now_nig.isoformat()
                    })
            except Exception as e:
                print(f"Pause re-entry error: {e}")

        today = nigeria_today()
        if conv_state.get('session_date', '') != today:
            conv_state['session_questions'] = 0
            conv_state['session_correct'] = 0
            conv_state['session_date'] = today

        history = await get_conversation_history(conversation['id'])
        context = await get_full_student_context(student)
        recent_subject = conversation.get('current_subject')

        bg_task(save_message(conversation['id'], student['id'], 'telegram', 'user', message))

        # Silent diagnosis: hesitation detection
        from features.silent_diagnosis import detect_hesitation, log_signal, count_recent_hesitations
        if detect_hesitation(message):
            current_subject = conversation.get('current_subject', 'general')
            current_topic = conversation.get('current_topic', 'general')
            bg_task(log_signal(
                student['id'], current_subject, current_topic, 'hesitation', 'rephrase_request'
            ))
            recent_count = await count_recent_hesitations(student['id'], current_subject, current_topic)
            if recent_count >= 2:
                message = (
                    f"[STUDENT IS REPEATEDLY CONFUSED ABOUT THIS TOPIC — USE SIMPLER LANGUAGE, "
                    f"SHORTER SENTENCES, A CONCRETE NIGERIAN EXAMPLE, AND CHECK FOR UNDERSTANDING "
                    f"AFTER EACH POINT. DO NOT INTRODUCE NEW CONCEPTS.]\n\n{message}"
                )

        try:
            response_text, question_data = await think(
                message=message, student=student, conversation_history=history,
                recent_subject=recent_subject, context=context
            )
        except Exception as e:
            print(f"AI think error (Telegram): {e}")
            response_text = f"Something went wrong on my end, {student.get('name', 'Student').split()[0]}. Please try again."
            question_data = None

        keyboard = None
        if question_data:
            from telegram.sender import build_quiz_keyboard
            keyboard = build_quiz_keyboard(question_data)

            subject = question_data.get('subject', recent_subject or '')
            seconds = _quiz_seconds(subject)
            timer_hint = f"\n\n⏳ _You have {seconds} seconds._"
            response_text += timer_hint

        await send_telegram_message(chat_id, response_text, reply_markup=keyboard)

        bg_task(save_message(conversation['id'], student['id'], 'telegram', 'assistant', response_text))
        bg_task(increment_questions_today(student['id']))

        if question_data:
            from features.recent_questions import add_recent_question
            add_recent_question(student['id'], question_data.get('question', ''))

        if question_data:
            new_state = {**conv_state, 'current_question': question_data, 'session_date': today}
            subject = question_data.get('subject', recent_subject or '')
            topic = question_data.get('topic', '')
            await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
                'conversation_state': new_state, 'current_subject': subject, 'current_topic': topic,
                'last_message_at': nigeria_now().isoformat()
            })

            seconds = _quiz_seconds(subject)
            student_id = student['id']
            conv_id = conversation['id']

            async def timeout_check():
                await asyncio.sleep(seconds + 2)
                from database.conversations import get_or_create_conversation, update_conversation_state as ucs
                fresh_conv = await get_or_create_conversation(student_id, 'telegram', str(chat_id))
                fresh_state = fresh_conv.get('conversation_state', {})
                if isinstance(fresh_state, str):
                    import json
                    try:
                        fresh_state = json.loads(fresh_state)
                    except Exception:
                        fresh_state = {}
                pending = fresh_state.get('current_question')
                if pending and pending.get('question') == question_data.get('question'):
                    correct = pending.get('correct', pending.get('correct_answer', '?'))
                    await send_telegram_message(
                        chat_id,
                        f"⏰ Time's up! The correct answer was *{correct}*. No worries — you can review it and we'll keep going. Want an explanation or the next question?"
                    )
                    await ucs(conv_id, 'telegram', str(chat_id), {
                        'conversation_state': {**fresh_state, 'current_question': None},
                        'last_message_at': nigeria_now().isoformat()
                    })

            asyncio.ensure_future(timeout_check())
        else:
            if conv_state.get('current_question'):
                await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
                    'conversation_state': {**conv_state, 'current_question': None},
                    'last_message_at': nigeria_now().isoformat()
                })
            else:
                await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
                    'last_message_at': nigeria_now().isoformat()
                })
    finally:
        release_student_lock(student['id'])


async def _evaluate_and_respond_telegram(chat_id: int, student: dict, conversation: dict,
                                         message: str, conv_state: dict):
    from telegram.sender import send_telegram_message
    from database.conversations import (update_conversation_state, save_message,
                                        get_conversation_history)
    from database.students import increment_questions_today
    from features.quiz_engine import calculate_and_award_points
    from features.badges import check_and_award_milestone_badges
    from ai.adaptive_engine import record_interaction_outcome
    from ai.brain import think
    from ai.context_manager import get_full_student_context
    from ai.classifier import extract_answer_letter
    from helpers import nigeria_today
    from database.client import supabase

    current_question = conv_state.get('current_question', {})
    if not current_question:
        await _think_and_respond_telegram(chat_id, student, conversation, message, conv_state)
        return

    q_text = current_question.get('question', current_question.get('question_text', ''))
    correct_answer = current_question.get('correct', current_question.get('correct_answer', 'A')).strip().upper()
    explanation = current_question.get('explanation', current_question.get('explanation_correct', ''))
    subject = current_question.get('subject', conversation.get('current_subject', ''))
    topic = current_question.get('topic', conversation.get('current_topic', ''))
    difficulty = current_question.get('difficulty_level', 5)

    student_letter = extract_answer_letter(message)
    if not student_letter:
        await send_telegram_message(chat_id, "Reply with just *A*, *B*, *C*, or *D* to answer.")
        return

    is_correct = student_letter == correct_answer

    # Increment total questions answered via RPC
    try:
        supabase.rpc('increment_questions_answered', {'student_id_param': student['id']}).execute()
    except Exception as e:
        print(f"total_questions_answered update error (Telegram): {e}")

    bg_task(record_interaction_outcome(student['id'], subject, topic, difficulty, is_correct))

    if is_correct:
        try:
            supabase.table('students').update({
                'total_questions_correct': student.get('total_questions_correct', 0) + 1
            }).eq('id', student['id']).execute()
        except Exception as e:
            print(f"Correct count update error (Telegram): {e}")

    points, _ = await calculate_and_award_points(student_id=student['id'], is_correct=is_correct,
                                                  question_difficulty=difficulty)
    badges = await check_and_award_milestone_badges(student['id'], student.get('total_questions_answered', 0) + 1)

    history = await get_conversation_history(conversation['id'])
    context = await get_full_student_context(student)

    opt_a = current_question.get('a', current_question.get('option_a', ''))
    opt_b = current_question.get('b', current_question.get('option_b', ''))
    opt_c = current_question.get('c', current_question.get('option_c', ''))
    opt_d = current_question.get('d', current_question.get('option_d', ''))
    option_map = {'A': opt_a, 'B': opt_b, 'C': opt_c, 'D': opt_d}
    student_answer_with_text = f"{student_letter}. {option_map.get(student_letter, message)}"
    correct_with_text = f"{correct_answer}. {option_map.get(correct_answer, '')}"

    extra_note = f"\n\n(The student earned {points} points for this answer."
    if badges:
        badge_names = ', '.join([b.get('name', '') for b in badges])
        extra_note += f" They also just earned a new badge: {badge_names}."
    extra_note += " Mention points and badge naturally only if it fits the flow — do not force it.)"

    quiz_ctx = {
        'question': q_text, 'student_answer': student_answer_with_text,
        'is_correct': is_correct, 'correct_answer': correct_with_text,
        'explanation': explanation, 'subject': subject, 'topic': topic
    }

    response_text, new_question_data = await think(
        message=message + extra_note, student=student, conversation_history=history,
        recent_subject=conversation.get('current_subject'), context=context, quiz_context=quiz_ctx
    )

    keyboard = None
    if new_question_data:
        from telegram.sender import build_quiz_keyboard
        keyboard = build_quiz_keyboard(new_question_data)

    await send_telegram_message(chat_id, response_text, reply_markup=keyboard)

    bg_task(save_message(conversation['id'], student['id'], 'telegram', 'user', message))
    bg_task(save_message(conversation['id'], student['id'], 'telegram', 'assistant', response_text))

    if new_question_data:
        from features.recent_questions import add_recent_question
        add_recent_question(student['id'], new_question_data.get('question', ''))

    today = nigeria_today()
    session_q = conv_state.get('session_questions', 0) + 1
    session_correct = conv_state.get('session_correct', 0) + (1 if is_correct else 0)

    if new_question_data:
        new_state = {**conv_state, 'current_question': new_question_data, 'session_questions': session_q,
                     'session_correct': session_correct, 'session_date': today}
        new_subject = new_question_data.get('subject', subject)
        new_topic = new_question_data.get('topic', topic)
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': new_state, 'current_subject': new_subject, 'current_topic': new_topic,
            'last_message_at': nigeria_now().isoformat()
        })
    else:
        new_state = {**conv_state, 'current_question': None, 'session_questions': session_q,
                     'session_correct': session_correct, 'session_date': today}
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': new_state,
            'last_message_at': nigeria_now().isoformat()
        })

    bg_task(increment_questions_today(student['id']))

    if badges:
        await asyncio.sleep(1.5)
        for badge in badges:
            try:
                badge_msg = (f"New badge unlocked!\n\n*{badge.get('name', '')}*\n"
                             f"{badge.get('description', '')}\n\n+{badge.get('points_awarded', 50)} bonus points")
                await send_telegram_message(chat_id, badge_msg)
            except Exception:
                pass


async def _send_diagnostic_telegram(chat_id: int):
    from telegram.sender import send_telegram_message
    from database.client import supabase, redis_client
    from helpers import nigeria_now
    from config.settings import settings

    now = nigeria_now()
    today = now.strftime('%Y-%m-%d')
    db_ok, redis_ok = False, False
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

    ai_cost = float(redis_client.get(f"ai_cost:{today}") or 0)
    total = supabase.table('students').select('id', count='exact').execute()

    msg = (f"WaxPrep Diagnostic\n{now.strftime('%H:%M:%S %d %b %Y')}\n\n"
           f"Database: {'OK' if db_ok else 'ERROR'}\n"
           f"Redis: {'OK' if redis_ok else 'ERROR'}\n"
           f"AI Cost Today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD:.2f}\n"
           f"Total Students: {total.count or 0:,}\n"
           f"Free Model: {settings.GROQ_FREE_MODEL}\n"
           f"Scholar Model: {settings.GROQ_SMART_MODEL}")
    await send_telegram_message(chat_id, msg)

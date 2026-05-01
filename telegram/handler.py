"""
Telegram Message Handler
Uses the same AI brain, DB, and flows but sends replies via Telegram (not WhatsApp).
"""

import asyncio
from config.settings import settings
from helpers import sanitize_input


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
        from database.conversations import get_or_create_conversation
        conversation = await get_or_create_conversation(
            student_id='anonymous',
            platform='telegram',
            platform_user_id=str(chat_id)
        )

        # Extract stored state (if any) from the temp conversation
        conv_state = conversation.get('conversation_state', {})
        if isinstance(conv_state, str):
            import json
            try:
                conv_state = json.loads(conv_state)
            except Exception:
                conv_state = {}

        awaiting = conv_state.get('awaiting_response_for', '')

        # If the user is already in an onboarding flow, continue it
        from ai.classifier import ONBOARDING_STATES
        if awaiting and awaiting in ONBOARDING_STATES:
            from telegram.onboarding import handle_onboarding_response as tg_onboarding_response
            await tg_onboarding_response(chat_id, conversation, text)
        else:
            # Otherwise, start fresh onboarding
            from telegram.onboarding import handle_new_or_existing as tg_onboarding
            await tg_onboarding(chat_id, conversation, text)
        return

    # ----- Student is banned --------------------------------------------
    if student.get('is_banned'):
        await send_telegram_message(
            chat_id,
            "Your account has been suspended. If you believe this is an error, contact WaxPrep support."
        )
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

    # ----- Hard trigger check (like SUBSCRIBE, MYID, etc.) -------------
    from ai.classifier import classify_hard_trigger, ONBOARDING_STATES
    from database.conversations import get_or_create_conversation

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

    # ----- Continue onboarding if the student is still in the flow ------
    if awaiting and awaiting in ONBOARDING_STATES:
        from telegram.onboarding import handle_onboarding_response as tg_onboarding_response
        await tg_onboarding_response(chat_id, conversation, text)
        return

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

    if trigger == 'PROGRESS':
        from database.students import get_student_profile_summary
        summary = await get_student_profile_summary(student)
        await send_telegram_message(chat_id, summary)
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
    """Inline button press – treat as normal text answer."""
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
    from telegram.sender import send_telegram_message
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

    today = nigeria_today()
    if conv_state.get('session_date', '') != today:
        conv_state['session_questions'] = 0
        conv_state['session_correct'] = 0
        conv_state['session_date'] = today

    history = await get_conversation_history(conversation['id'])
    context = await get_full_student_context(student)
    recent_subject = conversation.get('current_subject')

    asyncio.ensure_future(save_message(conversation['id'], student['id'], 'telegram', 'user', message))

    try:
        response_text, question_data = await think(
            message=message, student=student, conversation_history=history,
            recent_subject=recent_subject, context=context
        )
    except Exception as e:
        print(f"AI think error (Telegram): {e}")
        response_text = f"Something went wrong on my end, {student.get('name', 'Student').split()[0]}. Please try again."
        question_data = None

    await send_telegram_message(chat_id, response_text)
    asyncio.ensure_future(save_message(conversation['id'], student['id'], 'telegram', 'assistant', response_text))
    asyncio.ensure_future(increment_questions_today(student['id']))

    if question_data:
        new_state = {**conv_state, 'current_question': question_data, 'session_date': today}
        subject = question_data.get('subject', recent_subject or '')
        topic = question_data.get('topic', '')
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': new_state, 'current_subject': subject, 'current_topic': topic
        })
    else:
        if conv_state.get('current_question'):
            await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
                'conversation_state': {**conv_state, 'current_question': None}
            })


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

    # Background mastery update (async, can be fire-and-forget)
    asyncio.ensure_future(record_interaction_outcome(student['id'], subject, topic, difficulty, is_correct))
    
    # Sync DB update for correct count – must be direct, not wrapped in asyncio.ensure_future
    if is_correct:
        from database.client import supabase
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

    await send_telegram_message(chat_id, response_text)
    asyncio.ensure_future(save_message(conversation['id'], student['id'], 'telegram', 'user', message))
    asyncio.ensure_future(save_message(conversation['id'], student['id'], 'telegram', 'assistant', response_text))

    today = nigeria_today()
    session_q = conv_state.get('session_questions', 0) + 1
    session_correct = conv_state.get('session_correct', 0) + (1 if is_correct else 0)

    if new_question_data:
        new_state = {**conv_state, 'current_question': new_question_data, 'session_questions': session_q,
                     'session_correct': session_correct, 'session_date': today}
        new_subject = new_question_data.get('subject', subject)
        new_topic = new_question_data.get('topic', topic)
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': new_state, 'current_subject': new_subject, 'current_topic': new_topic
        })
    else:
        new_state = {**conv_state, 'current_question': None, 'session_questions': session_q,
                     'session_correct': session_correct, 'session_date': today}
        await update_conversation_state(conversation['id'], 'telegram', str(chat_id), {
            'conversation_state': new_state
        })

    asyncio.ensure_future(increment_questions_today(student['id']))

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

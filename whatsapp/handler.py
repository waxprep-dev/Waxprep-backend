"""
WhatsApp Message Handler

Teaching-first architecture.
Key fix from test conversation: quiz state persistence and evaluation.
The "sorry something went wrong" bug was caused by the evaluate_and_respond
function throwing unhandled exceptions. Now fully wrapped with error handling.
"""

import asyncio
import re
from config.settings import settings
from helpers import nigeria_today, nigeria_now, get_time_of_day, sanitize_input
from utils.background import bg_task


def _get_state(conversation: dict) -> dict:
    import json
    raw = conversation.get('conversation_state', {})
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


async def process_single_message(message_data: dict, value: dict) -> None:
    from whatsapp.sender import send_whatsapp_message
    from database.cache import is_message_processed

    phone = message_data.get('from', '')
    message_id = message_data.get('id', '')

    if message_id and is_message_processed(message_id):
        print(f"Duplicate message {message_id} — skipped")
        return

    name = "Student"
    contacts = value.get('contacts', [])
    if contacts:
        name = contacts[0].get('profile', {}).get('name', 'Student')

    message_type = message_data.get('type', 'text')
    media_id = None
    message = ""

    if message_type == 'text':
        message = message_data.get('text', {}).get('body', '')
    elif message_type == 'image':
        image_data = message_data.get('image', {})
        message = image_data.get('caption', '')
        media_id = image_data.get('id', '')
    elif message_type in ['voice', 'audio']:
        audio_data = message_data.get('audio', message_data.get('voice', {}))
        media_id = audio_data.get('id', '')
        message = ''
    elif message_type == 'button':
        message = message_data.get('button', {}).get('text', '')
    elif message_type == 'interactive':
        interactive = message_data.get('interactive', {})
        if 'button_reply' in interactive:
            message = interactive['button_reply'].get('title', '')
        elif 'list_reply' in interactive:
            message = interactive['list_reply'].get('title', '')
    else:
        message = message_data.get('text', {}).get('body', '')

    if not phone:
        return

    if not message and message_type not in ['image', 'voice', 'audio']:
        return

    if message:
        message = sanitize_input(message)

    try:
        if message_id:
            bg_task(_mark_read(message_id))

        await route_message(
            phone=phone,
            name=name,
            message=message,
            message_type=message_type,
            media_id=media_id
        )

    except Exception as e:
        print(f"Error in process_single_message: {e}")
        import traceback
        traceback.print_exc()
        try:
            name_for_error = name.split()[0] if name else "there"
            await send_whatsapp_message(
                phone,
                f"Something went wrong on my end, {name_for_error}. Please send your message again."
            )
        except Exception:
            pass


async def _mark_read(message_id: str):
    try:
        from whatsapp.sender import mark_as_read
        await mark_as_read(message_id)
    except Exception:
        pass


CRISIS_KEYWORDS = [
    "suicidal", "suicide", "kill myself", "end my life", "want to die",
    "self-harm", "self harm", "hurt myself", "cutting myself",
    "don't want to live", "no reason to live", "feel like dying"
]

CRISIS_RESPONSE = (
    "I hear you, and I'm really glad you told me. You are not alone.\n\n"
    "Please reach out to someone who can help right now:\n"
    "• Nigeria Suicide Prevention Hotline: 09090002999\n"
    "• Lagos Mental Health Helpline: 09090002999\n"
    "• Mentally Aware Nigeria Initiative: 08091116264\n\n"
    "If you're in immediate danger, please call 112 or go to the nearest hospital.\n\n"
    "I'm here to talk, but I'm not a replacement for professional support. You matter, and things can get better."
)


def _is_crisis_message(text: str) -> bool:
    """Returns True if the message contains crisis keywords."""
    lower = text.lower()
    return any(kw in lower for kw in CRISIS_KEYWORDS)


async def route_message(phone: str, name: str, message: str,
                         message_type: str = 'text', media_id: str = None) -> None:
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_by_phone
    from database.conversations import get_or_create_conversation, update_conversation_state
    from admin.dashboard import is_admin, handle_admin_command
    from ai.classifier import classify_hard_trigger, ONBOARDING_STATES

    msg_upper = message.strip().upper() if message else ''

    # 0. CRISIS CHECK – hardcoded and immediate, regardless of state
    if message and _is_crisis_message(message):
        await send_whatsapp_message(phone, CRISIS_RESPONSE)
        try:
            from database.client import supabase
            supabase.table('crisis_events').insert({
                'phone_hash': phone,
                'message_preview': message[:100],
                'detected_at': 'now()'
            }).execute()
        except Exception:
            pass
        return

    # 1. Admin commands
    if is_admin(phone) and msg_upper.startswith('ADMIN '):
        await handle_admin_command(phone, message)
        return

    if is_admin(phone) and msg_upper.startswith('$DIAG'):
        await _send_diagnostic(phone)
        return

    # 2. Load student
    student = await get_student_by_phone(phone)

    if student and student.get('is_banned'):
        await send_whatsapp_message(
            phone,
            "Your account has been suspended. If you believe this is an error, contact WaxPrep support."
        )
        return

    student_id = student['id'] if student else 'anonymous'
    conversation = await get_or_create_conversation(
        student_id=student_id,
        platform='whatsapp',
        platform_user_id=phone
    )

    conv_state = _get_state(conversation)

    # 3. No student — onboarding
    if not student:
        from whatsapp.flows.onboarding import handle_new_or_existing, handle_onboarding_response

        awaiting = conv_state.get('awaiting_response_for', '')
        if awaiting in ONBOARDING_STATES:
            await handle_onboarding_response(phone, conversation, message)
        else:
            await handle_new_or_existing(phone, conversation, message)
        return

    # 4. Remaining onboarding for registered students
    awaiting = conv_state.get('awaiting_response_for', '')
    if awaiting in ONBOARDING_STATES:
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message)
        return

    # Account deletion PIN confirmation
    if awaiting == 'delete_confirm_pin':
        from helpers import verify_pin
        name_first = student.get('name', 'Student').split()[0]
        entered_pin = message.strip()
        if verify_pin(entered_pin, student['pin_hash']):
            # Soft-delete the account
            try:
                from database.client import supabase
                from helpers import nigeria_now
                supabase.table('students').update({
                    'is_deleted': True,
                    'deleted_at': nigeria_now().isoformat(),
                    'is_active': False,
                }).eq('id', student['id']).execute()
                await send_whatsapp_message(
                    phone,
                    f"Account deleted, {name_first}.\n\n"
                    "Your data will be permanently erased in 30 days. "
                    "If you change your mind, message us within that time.\n\n"
                    "Thank you for using WaxPrep."
                )
            except Exception as e:
                print(f"Account deletion error: {e}")
                await send_whatsapp_message(phone, "Something went wrong. Please try again.")
        else:
            await send_whatsapp_message(
                phone,
                f"PIN incorrect, {name_first}. Account not deleted."
            )
        # Clear the state regardless
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {**conv_state, 'awaiting_response_for': None}
        })
        return

    # 5. Media handling
    if message_type == 'image':
        await _handle_image(phone, student, media_id, message)
        return

    if message_type in ['voice', 'audio']:
        await _handle_voice(phone, student, conversation, media_id, conv_state)
        return

    # 6. Hard-coded trigger check & Clear pending quiz if command is used
    if conv_state.get('current_question') and classify_hard_trigger(message, conv_state):
        conv_state['current_question'] = None

    trigger = classify_hard_trigger(message, conv_state)

    if trigger == 'ONBOARDING':
        from whatsapp.flows.onboarding import handle_onboarding_response
        await handle_onboarding_response(phone, conversation, message)
        return

    if trigger == 'SUBSCRIPTION_PROMO':
        from whatsapp.flows.subscription import handle_promo_code_during_checkout
        await handle_promo_code_during_checkout(phone, student, conversation, message, conv_state)
        return

    if trigger == 'CHALLENGE_ANSWER':
        from whatsapp.flows.study import handle_challenge_answer
        await handle_challenge_answer(phone, student, conversation, message, conv_state)
        return

    if trigger == 'CHALLENGE':
        from whatsapp.flows.study import handle_daily_challenge
        await handle_daily_challenge(phone, student, conversation)
        return

    if trigger == 'SUBSCRIBE':
        from whatsapp.flows.subscription import handle_subscription_flow
        await handle_subscription_flow(phone, student, conversation, message)
        return

    if trigger == 'MYID':
        await _send_wax_id(phone, student)
        return

    if trigger == 'MYPLAN' or trigger == 'MY PLAN':
        await _send_plan_info(phone, student)
        return

    if trigger == 'BILLING':
        await _send_billing_history(phone, student)
        return

    if trigger == 'PAYG':
        from whatsapp.flows.commands import handle_payg
        await handle_payg(phone, student, conversation, message)
        return

    if trigger == 'PROMO':
        from whatsapp.flows.commands import handle_promo_code
        await handle_promo_code(phone, student, conversation, message)
        return

    if trigger == 'BUG':
        from features.feedback import handle_bug_report
        response = await handle_bug_report(phone, student, message)
        await send_whatsapp_message(phone, response)
        return

    if trigger == 'SUGGEST':
        from features.feedback import handle_suggestion
        response = await handle_suggestion(phone, student, message)
        await send_whatsapp_message(phone, response)
        return

    if trigger == 'PING':
        name_first = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(phone, f"Pong! I'm here and ready, {name_first}.")
        return

    if trigger == 'VERIFY PAYMENT' or trigger == 'I HAVE PAID':
        from features.payment_verifier import handle_verify_payment
        await handle_verify_payment(phone, student, 'whatsapp')
        return

    if trigger == 'CANCEL':
        await _handle_cancel_subscription(phone, student, conversation, conv_state)
        return

    if trigger == 'CANCEL_CONFIRM':
        await _confirm_cancel(phone, student, conversation, message, conv_state)
        return

    if msg_upper == 'DELETE ACCOUNT':
        name_first = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Are you sure you want to permanently delete your account, {name_first}?\n\n"
            "This will erase your WAX ID, all progress, streaks, and badges.\n\n"
            "Type your *4‑digit PIN* to confirm, or just ignore this message to cancel."
        )
        await update_conversation_state(conversation['id'], 'whatsapp', phone, {
            'conversation_state': {**conv_state, 'awaiting_response_for': 'delete_confirm_pin'}
        })
        return

    if trigger == 'PROGRESS':
        from database.students import get_student_profile_summary
        summary = await get_student_profile_summary(student)
        await send_whatsapp_message(phone, summary)
        return

    # 7. Quiz answer (moved after commands)
    from ai.classifier import looks_like_quiz_answer
    current_question = conv_state.get('current_question')
    if current_question and looks_like_quiz_answer(message):
        await _evaluate_and_respond(phone, student, conversation, message, conv_state)
        return

    # 8. Everything else → AI brain
    await _think_and_respond(phone, student, conversation, message, conv_state)


async def _send_wax_id(phone: str, student: dict):
    from whatsapp.sender import send_whatsapp_message
    wax_id = student.get('wax_id', 'Unknown')
    name = student.get('name', 'Student').split()[0]
    await send_whatsapp_message(
        phone,
        f"Your WAX ID, {name}\n\n"
        f"*{wax_id}*\n\n"
        "This is your permanent identity on WaxPrep. "
        "Use it to log in on any device.\n\n"
        "_Never share your PIN with anyone._"
    )


async def _send_plan_info(phone: str, student: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status
    from helpers import format_naira
    from config.settings import settings

    status = await get_student_subscription_status(student)
    name = student.get('name', 'Student').split()[0]
    tier = status['display_tier']
    days = status.get('days_remaining')

    msg = f"*{name}'s Current Plan*\n\nPlan: *{tier}*\n"
    if days is not None:
        msg += f"Days remaining: {days}\n"

    credits = student.get('credits_balance', 0) or 0
    if credits > 0:
        msg += f"Credits balance: {credits}\n"

    if status['effective_tier'] == 'free':
        msg += (
            f"\nUpgrade to Scholar for just {format_naira(settings.SCHOLAR_MONTHLY)}/month.\n"
            "Type *SUBSCRIBE* when you are ready."
        )
    elif status.get('is_in_grace_period'):
        msg += "\nYou are in your grace period. Type *SUBSCRIBE* to renew now."

    await send_whatsapp_message(phone, msg)


async def _send_billing_history(phone: str, student: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.client import supabase
    from helpers import format_naira

    name = student.get('name', 'Student').split()[0]

    try:
        payments = supabase.table('payments')\
            .select('amount_naira, completed_at, metadata')\
            .eq('student_id', student['id'])\
            .eq('status', 'completed')\
            .order('completed_at', desc=True)\
            .limit(5)\
            .execute()

        if not payments.data:
            await send_whatsapp_message(
                phone,
                f"No payment history yet, {name}.\n\nType *SUBSCRIBE* to upgrade your plan."
            )
            return

        lines = [f"*{name}'s Billing History*\n"]
        for p in payments.data:
            amount = format_naira(p.get('amount_naira', 0))
            date = str(p.get('completed_at', ''))[:10]
            meta = p.get('metadata', {}) or {}
            plan = meta.get('plan', 'subscription').capitalize()
            lines.append(f"{date} — {amount} — {plan}")

        await send_whatsapp_message(phone, '\n'.join(lines))

    except Exception as e:
        print(f"Billing history error: {e}")
        await send_whatsapp_message(phone, "Could not load billing history right now. Try again in a moment.")


async def _handle_cancel_subscription(phone: str, student: dict,
                                        conversation: dict, conv_state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)

    if status['effective_tier'] == 'free':
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"You are on the free plan, {name} — nothing to cancel.\n\n"
            "Type *SUBSCRIBE* if you want to upgrade."
        )
        return

    name = student.get('name', 'Student').split()[0]
    tier = status['display_tier']
    days = status.get('days_remaining', 0)

    await send_whatsapp_message(
        phone,
        f"Are you sure you want to cancel your {tier} plan, {name}?\n\n"
        f"You will keep access for {days} more day{'s' if days != 1 else ''} until it expires.\n"
        "Your progress and WAX ID are kept forever.\n\n"
        "Type *YES CANCEL* to confirm, or just continue studying to keep your plan."
    )

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {**conv_state, 'awaiting_response_for': 'cancel_confirm'}
    })


async def _confirm_cancel(phone: str, student: dict, conversation: dict,
                           message: str, conv_state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import update_conversation_state

    if message.strip().upper() in ('YES CANCEL', 'YES', 'CONFIRM', 'CANCEL PLAN'):
        try:
            from database.client import supabase
            from helpers import nigeria_now
            supabase.table('subscription_cancellations').insert({
                'student_id': student['id'],
                'wax_id': student.get('wax_id', ''),
                'cancelled_at': nigeria_now().isoformat(),
                'reason': 'Student requested via bot'
            }).execute()
        except Exception as e:
            print(f"Cancel log error: {e}")

        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"Cancellation noted, {name} (ID: {student.get('wax_id')}). Your plan access continues until it expires.\n\n"
            "Your progress, WAX ID, and streak are all kept. "
            "Come back anytime — type *SUBSCRIBE* to reactivate."
        )
    else:
        name = student.get('name', 'Student').split()[0]
        await send_whatsapp_message(
            phone,
            f"No problem, {name} — your plan stays active. Let's get back to studying."
        )

    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
        'conversation_state': {**conv_state, 'awaiting_response_for': None}
    })


async def _think_and_respond(phone: str, student: dict, conversation: dict,
                              message: str, conv_state: dict) -> None:
    # ---- Race condition guard ----
    from database.conversations import acquire_student_lock, release_student_lock
    from whatsapp.sender import send_whatsapp_message

    locked = await acquire_student_lock(student['id'])
    if not locked:
        await send_whatsapp_message(phone, "I'm still processing your last message. One moment.")
        return

    try:
        from database.conversations import (
            get_conversation_history, update_conversation_state, save_message
        )
        from database.students import can_student_ask_question, increment_questions_today
        from ai.brain import think
        from ai.context_manager import get_full_student_context
        from features.quiz_engine import extract_subject_from_message
        from helpers import nigeria_today

        can_ask, limit_msg = await can_student_ask_question(student)
        if not can_ask:
            await send_whatsapp_message(phone, limit_msg)
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
                    await send_whatsapp_message(phone, warm_greeting)
                    await update_conversation_state(conversation['id'], 'whatsapp', phone, {
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

        bg_task(save_message(
            conversation['id'], student['id'], 'whatsapp', 'user', message
        ))

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

        # Call AI brain
        try:
            response_text, question_data = await think(
                message=message,
                student=student,
                conversation_history=history,
                recent_subject=recent_subject,
                context=context,
            )
        except Exception as e:
            print(f"AI brain error in _think_and_respond: {e}")
            import traceback
            traceback.print_exc()
            name = student.get('name', 'Student').split()[0]
            response_text = f"I had a brief technical issue, {name}. Send your message again and I will answer properly."
            question_data = None

        await send_whatsapp_message(phone, response_text)

        bg_task(save_message(
            conversation['id'], student['id'], 'whatsapp', 'assistant', response_text
        ))

        bg_task(increment_questions_today(student['id']))

        if question_data:
            # Log the question to prevent repetition
            from features.recent_questions import add_recent_question
            add_recent_question(student['id'], question_data.get('question', ''))

        bg_task(_update_stats(student, phone, conv_state))

        if question_data:
            new_state = {
                **conv_state,
                'current_question': question_data,
                'session_date': today,
            }
            subject = question_data.get('subject', recent_subject or '')
            topic = question_data.get('topic', '')
            await update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {
                    'conversation_state': new_state,
                    'current_subject': subject,
                    'current_topic': topic,
                    'last_message_at': nigeria_now().isoformat()
                }
            )
        else:
            if conv_state.get('current_question'):
                new_state = {**conv_state, 'current_question': None}
                asyncio.ensure_future(update_conversation_state(
                    conversation['id'], 'whatsapp', phone,
                    {'conversation_state': new_state, 'last_message_at': nigeria_now().isoformat()}
                ))
            else:
                asyncio.ensure_future(update_conversation_state(
                    conversation['id'], 'whatsapp', phone,
                    {'last_message_at': nigeria_now().isoformat()}
                ))

            detected_subject = extract_subject_from_message(message)
            if detected_subject:
                asyncio.ensure_future(update_conversation_state(
                    conversation['id'], 'whatsapp', phone,
                    {'current_subject': detected_subject}
                ))
    finally:
        release_student_lock(student['id'])


async def _evaluate_and_respond(phone: str, student: dict, conversation: dict,
                                  message: str, conv_state: dict) -> None:
    from whatsapp.sender import send_whatsapp_message
    from database.conversations import (
        update_conversation_state, save_message, get_conversation_history
    )
    from database.students import increment_questions_today
    from database.client import supabase
    from features.quiz_engine import calculate_and_award_points
    from features.badges import check_and_award_milestone_badges
    from ai.adaptive_engine import record_interaction_outcome
    from ai.brain import think
    from ai.context_manager import get_full_student_context
    from ai.classifier import extract_answer_letter
    from helpers import nigeria_today

    try:
        current_question = conv_state.get('current_question', {})
        if not current_question:
            await _think_and_respond(phone, student, conversation, message, conv_state)
            return

        q_text = current_question.get('question', current_question.get('question_text', ''))
        opt_a = current_question.get('a', current_question.get('option_a', ''))
        opt_b = current_question.get('b', current_question.get('option_b', ''))
        opt_c = current_question.get('c', current_question.get('option_c', ''))
        opt_d = current_question.get('d', current_question.get('option_d', ''))
        correct_answer = current_question.get('correct', current_question.get('correct_answer', 'A'))
        explanation = current_question.get('explanation', current_question.get('explanation_correct', ''))
        subject = current_question.get('subject', conversation.get('current_subject', ''))
        topic = current_question.get('topic', conversation.get('current_topic', ''))
        difficulty = current_question.get('difficulty_level', 5)

        student_letter = extract_answer_letter(message)
        if not student_letter:
            await send_whatsapp_message(phone, "Reply with just *A*, *B*, *C*, or *D* to answer.")
            return

        correct_answer = correct_answer.strip().upper()
        is_correct = student_letter == correct_answer

        # Increment total questions answered via Database RPC
        try:
            supabase.rpc('increment_questions_answered', {'student_id_param': student['id']}).execute()
        except Exception as e:
            print(f"total_questions_answered update error: {e}")

        bg_task(record_interaction_outcome(
            student['id'], subject, topic, difficulty, is_correct
        ))

        if is_correct:
            try:
                bg_task(supabase.rpc('increment_correct_answers', {'student_id_param': student['id']}).execute())
            except Exception as e:
                print(f"Correct count update error (WhatsApp): {e}")

        points, _ = await calculate_and_award_points(
            student_id=student['id'],
            is_correct=is_correct,
            question_difficulty=difficulty
        )

        new_total = student.get('total_questions_answered', 0) + 1
        badges = await check_and_award_milestone_badges(student['id'], new_total)

        history = await get_conversation_history(conversation['id'])
        context = await get_full_student_context(student)

        option_map = {'A': opt_a, 'B': opt_b, 'C': opt_c, 'D': opt_d}
        student_answer_with_text = f"{student_letter}. {option_map.get(student_letter, message)}"
        correct_with_text = f"{correct_answer}. {option_map.get(correct_answer, '')}"

        extra_note = f"\n\n(The student earned {points} points for this answer."
        if badges:
            badge_names = ', '.join([b.get('name', '') for b in badges])
            extra_note += f" They also just earned a new badge: {badge_names}."
        extra_note += " Mention points and badge naturally only if it fits the flow — do not force it.)"

        quiz_ctx = {
            'question': q_text,
            'student_answer': student_answer_with_text,
            'is_correct': is_correct,
            'correct_answer': correct_with_text,
            'explanation': explanation,
            'subject': subject,
            'topic': topic,
        }

        response_text, new_question_data = await think(
            message=message + extra_note,
            student=student,
            conversation_history=history,
            recent_subject=conversation.get('current_subject'),
            context=context,
            quiz_context=quiz_ctx,
        )

        await send_whatsapp_message(phone, response_text)

        bg_task(save_message(
            conversation['id'], student['id'], 'whatsapp', 'user', message
        ))
        
        bg_task(save_message(
            conversation['id'], student['id'], 'whatsapp', 'assistant', response_text
        ))

        if new_question_data:
            from features.recent_questions import add_recent_question
            add_recent_question(student['id'], new_question_data.get('question', ''))

        today = nigeria_today()
        session_q = conv_state.get('session_questions', 0) + 1
        session_correct = conv_state.get('session_correct', 0) + (1 if is_correct else 0)

        if new_question_data:
            new_state = {
                **conv_state,
                'current_question': new_question_data,
                'session_questions': session_q,
                'session_correct': session_correct,
                'session_date': today,
            }
            new_subject = new_question_data.get('subject', subject)
            new_topic = new_question_data.get('topic', topic)
            await update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {
                    'conversation_state': new_state,
                    'current_subject': new_subject,
                    'current_topic': new_topic,
                    'last_message_at': nigeria_now().isoformat()
                }
            )
        else:
            new_state = {
                **conv_state,
                'current_question': None,
                'session_questions': session_q,
                'session_correct': session_correct,
                'session_date': today,
            }
            await update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {'conversation_state': new_state, 'last_message_at': nigeria_now().isoformat()}
            )

        bg_task(increment_questions_today(student['id']))
        bg_task(_update_stats(student, phone, conv_state))

        if badges:
            await asyncio.sleep(1.5)
            for badge in badges:
                try:
                    from whatsapp.sender import send_whatsapp_message as swm
                    badge_msg = (
                        f"New badge unlocked!\n\n"
                        f"*{badge.get('name', '')}*\n"
                        f"{badge.get('description', '')}\n\n"
                        f"+{badge.get('points_awarded', 50)} bonus points"
                    )
                    await swm(phone, badge_msg)
                except Exception:
                    pass

    except Exception as e:
        print(f"Error in _evaluate_and_respond: {e}")
        try:
            name = student.get('name', 'Student').split()[0]
            broken_state = {**conv_state, 'current_question': None}
            await update_conversation_state(
                conversation['id'], 'whatsapp', phone,
                {'conversation_state': broken_state, 'last_message_at': nigeria_now().isoformat()}
            )
            await _think_and_respond(phone, student, conversation, message, broken_state)
        except Exception:
            pass


async def _handle_image(phone: str, student: dict, media_id: str, caption: str):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)
    tier = status['effective_tier']
    is_trial = status.get('is_trial', False)
    name = student.get('name', 'Student').split()[0]

    if not settings.has_feature('image_analysis', tier, is_trial):
        await send_whatsapp_message(
            phone,
            f"Image analysis is available on Scholar Plan, {name}.\n\n"
            "Upgrade for N1,500/month and you can send me photos of textbook pages, "
            "past question papers, diagrams — I will read them and explain everything.\n\n"
            "Type *SUBSCRIBE* to upgrade."
        )
        return

    if not settings.OPENAI_API_KEY:
        await send_whatsapp_message(
            phone,
            "Image analysis is temporarily unavailable. Type your question and I will help immediately."
        )
        return

    await send_whatsapp_message(phone, f"Got your photo, {name}! Reading it now...")

    try:
        from ai.openai_client import download_whatsapp_image, analyze_image
        image_b64 = await download_whatsapp_image(media_id)
        if not image_b64:
            await send_whatsapp_message(phone, "Could not download that image. Please try again.")
            return
        result = await analyze_image(image_base64=image_b64, prompt=caption or None, student=student)
        await send_whatsapp_message(phone, result)
    except Exception as e:
        print(f"Image analysis error: {e}")
        await send_whatsapp_message(
            phone,
            "Had trouble reading that image. Try a clearer photo, or type your question instead."
        )


async def _handle_voice(phone: str, student: dict, conversation: dict,
                         media_id: str, conv_state: dict):
    from whatsapp.sender import send_whatsapp_message
    from database.students import get_student_subscription_status

    status = await get_student_subscription_status(student)
    tier = status['effective_tier']
    is_trial = status.get('is_trial', False)
    name = student.get('name', 'Student').split()[0]

    if not settings.has_feature('voice_input', tier, is_trial):
        await send_whatsapp_message(
            phone,
            f"Voice notes are available on Scholar Plan, {name}.\n\n"
            "Upgrade for N1,500/month — send me voice notes and I will transcribe and respond.\n\n"
            "Type *SUBSCRIBE* to upgrade, or just type your question."
        )
        return

    if not media_id:
        await send_whatsapp_message(
            phone,
            f"I received a voice note, {name}, but could not access it. Please try again."
        )
        return

    try:
        from ai.openai_client import transcribe_voice_note
        transcribed_text = await transcribe_voice_note(media_id)
    except Exception as e:
        print(f"Voice transcription error: {e}")
        transcribed_text = None

    if not transcribed_text or len(transcribed_text.strip()) < 2:
        await send_whatsapp_message(
            phone,
            f"Could not make out your voice note clearly, {name}. "
            "Try sending it again or type your question."
        )
        return

    await _think_and_respond(
        phone=phone,
        student=student,
        conversation=conversation,
        message=f"[Voice note transcribed]: {transcribed_text}",
        conv_state=conv_state
    )


async def _update_stats(student: dict, phone: str, conv_state: dict) -> None:
    from database.client import supabase
    from helpers import nigeria_today
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    try:
        today = nigeria_today()
        yesterday = (
            datetime.now(ZoneInfo("Africa/Lagos")) - timedelta(days=1)
        ).strftime('%Y-%m-%d')

        fresh = supabase.table('students').select(
            'last_study_date, current_streak, longest_streak'
        ).eq('id', student['id']).execute()

        if fresh.data:
            s = fresh.data[0]
            last_date = s.get('last_study_date')
            current_streak = s.get('current_streak', 0)
            longest_streak = s.get('longest_streak', 0)
            updates = {}
            new_streak = current_streak

            if last_date == today:
                pass
            elif last_date == yesterday:
                new_streak = current_streak + 1
                updates = {
                    'current_streak': new_streak,
                    'longest_streak': max(longest_streak, new_streak),
                    'last_study_date': today
                }
            else:
                new_streak = 1
                updates = {'current_streak': 1, 'last_study_date': today}

            if updates:
                supabase.table('students').update(updates).eq('id', student['id']).execute()

            streak_milestones = {3, 7, 14, 30, 60, 100}
            if new_streak in streak_milestones and last_date != today and last_date != yesterday:
                try:
                    from features.badges import check_streak_badges
                    from whatsapp.sender import send_whatsapp_message
                    new_badges = await check_streak_badges(student['id'], new_streak)
                    for badge in new_badges:
                        name = student.get('name', 'Student').split()[0]
                        await send_whatsapp_message(
                            phone,
                            f"*{new_streak}-Day Streak!*\n\n"
                            f"*{badge['name']}* badge earned!\n"
                            f"{badge.get('description', '')}\n\n"
                            f"You have been consistent, {name}. That is how exams are won."
                        )
                except Exception:
                    pass
    except Exception as e:
        print(f"Streak update error: {e}")

    try:
        await _check_level(student['id'], phone, student.get('name', 'Student'))
    except Exception:
        pass


async def _check_level(student_id: str, phone: str, student_name: str):
    from database.client import supabase
    from config.settings import settings
    from whatsapp.sender import send_whatsapp_message

    result = supabase.table('students').select('total_points, current_level')\
        .eq('id', student_id).execute()
    if not result.data:
        return

    s = result.data[0]
    points = s.get('total_points', 0)
    current_level = s.get('current_level', 1)
    new_level = 1

    for level, threshold in sorted(settings.LEVEL_THRESHOLDS.items()):
        if points >= threshold:
            new_level = level

    if new_level > current_level:
        new_level_name = settings.get_level_name(new_level)
        supabase.table('students').update({
            'current_level': new_level,
            'level_name': new_level_name,
        }).eq('id', student_id).execute()
        name = student_name.split()[0]
        await send_whatsapp_message(
            phone,
            f"Level Up, *{name}!*\n\n"
            f"You reached Level {new_level} — *{new_level_name}*\n\n"
            f"{points:,} total points. You are building something real."
        )


async def _send_diagnostic(phone: str):
    from whatsapp.sender import send_whatsapp_message
    from database.client import supabase, redis_client
    from helpers import nigeria_now
    from config.settings import settings

    try:
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

        ai_cost_raw = redis_client.get(f"ai_cost:{today}")
        ai_cost = float(ai_cost_raw) if ai_cost_raw else 0.0
        total_students = supabase.table('students').select('id', count='exact').execute()

        msg = (
            f"WaxPrep Diagnostic\n"
            f"{now.strftime('%H:%M:%S %d %b %Y')}\n\n"
            f"Database: {'OK' if db_ok else 'ERROR'}\n"
            f"Redis: {'OK' if redis_ok else 'ERROR'}\n"
            f"AI Cost Today: ${ai_cost:.4f} / ${settings.DAILY_AI_BUDGET_USD:.2f}\n"
            f"Total Students: {total_students.count or 0:,}\n"
            f"Free Model: {settings.GROQ_FREE_MODEL}\n"
            f"Scholar Model: {settings.GROQ_SMART_MODEL}\n"
        )
        await send_whatsapp_message(phone, msg)
    except Exception as e:
        await send_whatsapp_message(phone, f"Diagnostic error: {str(e)[:200]}")

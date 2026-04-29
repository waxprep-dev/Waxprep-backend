"""
Intent Classification — Simplified

The old AI-powered classifier is gone. We no longer route messages to
specialized handlers based on intent. Almost everything goes to the AI brain.

This module only identifies the very small set of hard-coded triggers
that need specific non-AI handling: payment initiation, media files,
admin commands, onboarding state continuation.

Everything else is CONVERSATIONAL and goes directly to the AI brain.
"""

import re

# Commands that need specific non-AI handling
HARD_COMMANDS = {
    'SUBSCRIBE', 'MYID', 'MY ID', 'PAYG',
}

# Promo code triggers
PROMO_TRIGGERS = {'PROMO', 'CODE'}

# Onboarding states that need the onboarding handler
ONBOARDING_STATES = {
    'new_or_existing', 'terms_acceptance', 'wax_id_entry', 'pin_entry',
    'name', 'class_level', 'target_exam', 'subjects', 'exam_date',
    'state', 'language_pref', 'pin_setup', 'pin_confirm'
}


def classify_hard_trigger(message: str, conversation_state: dict = None) -> str | None:
    """
    Returns a trigger type if the message matches a hard-coded trigger.
    Returns None if the message should go to the AI brain.

    Trigger types returned:
    - 'SUBSCRIBE': payment flow
    - 'MYID': show WAX ID
    - 'PAYG': pay as you go
    - 'PROMO': promo code application
    - 'ONBOARDING': onboarding state continuation
    - 'SUBSCRIPTION_PROMO': promo code during checkout
    - None: everything else goes to AI brain
    """
    if not message:
        return None

    msg_upper = message.strip().upper()
    first_word = msg_upper.split()[0] if msg_upper.split() else ''

    # Check onboarding state first
    if conversation_state:
        awaiting = conversation_state.get('awaiting_response_for', '')
        if awaiting in ONBOARDING_STATES:
            return 'ONBOARDING'
        if awaiting == 'subscription_promo_code':
            return 'SUBSCRIPTION_PROMO'

    # Hard commands
    if first_word in HARD_COMMANDS:
        return first_word

    if first_word in PROMO_TRIGGERS:
        return 'PROMO'

    # Plan keywords that go to subscription flow
    plan_keywords = [
        'SCHOLAR MONTHLY', 'SCHOLAR YEARLY',
        'ELITE MONTHLY', 'ELITE YEARLY',
        'PRO MONTHLY', 'PRO YEARLY'
    ]
    if any(kw in msg_upper for kw in plan_keywords):
        return 'SUBSCRIBE'

    return None


def looks_like_quiz_answer(message: str) -> bool:
    """
    Returns True if the message looks like a student answering A/B/C/D.
    Used to detect quiz answer context before passing to AI brain.
    """
    msg = message.strip().upper()

    # Single letter
    if msg in ('A', 'B', 'C', 'D'):
        return True

    # Letter with punctuation
    if re.match(r'^[ABCD][.\):]?\s*$', msg):
        return True

    # "I think it's B" style
    patterns = [
        r'\b(think|answer|choose|pick|go with|say)\s+(is\s+)?[ABCD]\b',
        r'\bit[\'s]?\s+[ABCD]\b',
        r'\b[ABCD]\s+(is correct|is right|is the answer)\b',
    ]
    for pattern in patterns:
        if re.search(pattern, msg, re.IGNORECASE):
            return True

    return False

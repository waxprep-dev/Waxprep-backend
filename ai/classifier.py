"""
Intent Classification — Minimal

We do not AI-classify messages anymore.
Almost everything goes to the brain.
This module identifies only hard-coded triggers.
"""

import re

# Commands that need specific non-AI handling
HARD_COMMANDS = {
    'SUBSCRIBE', 'MYID', 'MY ID', 'PAYG', 'BILLING', 'MYPLAN', 'MY PLAN',
    'CANCEL', 'PING', 'SUBSCRIBE MONTHLY', 'SUBSCRIBE YEARLY', 'TEST',
    'VERIFY PAYMENT', 'I HAVE PAID', 'DELETE ACCOUNT',
}

# Promo code triggers
PROMO_TRIGGERS = {'PROMO', 'CODE'}

# Onboarding states
ONBOARDING_STATES = {
    'new_or_existing', 'terms_acceptance', 'wax_id_entry', 'pin_entry',
    'name', 'class_level', 'target_exam', 'subjects', 'exam_date',
    'state', 'language_pref', 'pin_setup', 'pin_confirm',
    'exam_year_confirm',
}


def classify_hard_trigger(message: str, conversation_state: dict = None) -> str | None:
    """
    Returns a trigger type if the message is a hard-coded command.
    Returns None if the message should go to the AI brain.
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
        if awaiting == 'challenge_answer':
            return 'CHALLENGE_ANSWER'
        if awaiting == 'cancel_confirm':
            return 'CANCEL_CONFIRM'

    # Hard commands
    if first_word in HARD_COMMANDS:
        return first_word

    if first_word in PROMO_TRIGGERS:
        return 'PROMO'

    # Plan keywords
    plan_keywords = [
        'SCHOLAR MONTHLY', 'SCHOLAR YEARLY',
        'ELITE MONTHLY', 'ELITE YEARLY',
    ]
    if any(kw in msg_upper for kw in plan_keywords):
        return 'SUBSCRIBE'

    # Bug/suggest reports
    if msg_upper.startswith('BUG ') or msg_upper == 'BUG':
        return 'BUG'
    if msg_upper.startswith('SUGGEST ') or msg_upper == 'SUGGEST':
        return 'SUGGEST'

    # Challenge trigger
    if msg_upper in ('CHALLENGE', 'DAILY CHALLENGE'):
        return 'CHALLENGE'

    return None


def looks_like_quiz_answer(message: str) -> bool:
    """
    Returns True if the message looks like a student answering A/B/C/D.
    This is checked ONLY when there is an active current_question in state.
    """
    if not message:
        return False

    msg = message.strip().upper()

    # Single letter — most common case
    if msg in ('A', 'B', 'C', 'D'):
        return True

    # Letter with punctuation: A. A) A:
    if re.match(r'^[ABCD][.\):\s]*$', msg):
        return True

    # "I think it's B" / "my answer is C" / "it's D" / "option A"
    patterns = [
        r'\b(think|answer|choose|pick|go with|say|option)\s*(is\s+)?[ABCD]\b',
        r'\bit[\'s]?\s+[ABCD]\b',
        r'\b[ABCD]\s+(is correct|is right|is the answer)\b',
        r'^(its?|i think|i say|my answer is|the answer is|i choose|i pick)\s+[ABCD]',
    ]
    for pattern in patterns:
        if re.search(pattern, msg, re.IGNORECASE):
            return True

    # "A or B" type response — ambiguous answer
    if re.match(r'^[ABCD]\s+(or|and)\s+[ABCD]$', msg):
        return True

    return False


def extract_answer_letter(message: str) -> str | None:
    """
    Extracts the actual A/B/C/D letter from a quiz answer message.
    Returns the letter or None if extraction fails.
    """
    if not message:
        return None

    msg = message.strip().upper()

    # Direct single letter
    if msg in ('A', 'B', 'C', 'D'):
        return msg

    # First character if it is a valid option
    if msg[0] in ('A', 'B', 'C', 'D') and (len(msg) == 1 or msg[1] in ('.', ')', ':', ' ')):
        return msg[0]

    # Search for a letter in the message
    for pattern in [
        r'\b([ABCD])\s+is\s+(correct|right|the answer)',
        r'\b(my answer is|i choose|i pick|i say|i think|option)\s+([ABCD])\b',
        r'\bit[\'s]?\s+([ABCD])\b',
    ]:
        match = re.search(pattern, msg, re.IGNORECASE)
        if match:
            # Get the last group which should be the letter
            groups = match.groups()
            for g in reversed(groups):
                if g and g.upper() in ('A', 'B', 'C', 'D'):
                    return g.upper()

    # Last resort: find any isolated A/B/C/D in the message
    letters_found = re.findall(r'\b([ABCD])\b', msg)
    if letters_found:
        return letters_found[0]

    return None

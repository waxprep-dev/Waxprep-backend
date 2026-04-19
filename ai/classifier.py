"""
Intent Classification Engine

Every message a student sends gets classified before anything else happens.
Classification determines:
1. Which AI model handles the message
2. Which conversation handler processes it
3. What database lookups are needed
4. What response format to use

Classification takes less than 100ms because it uses the fastest AI model available.
"""

from groq import Groq
from config.settings import settings

# Create the Groq client once and reuse it
groq_client = Groq(api_key=settings.GROQ_API_KEY)

VALID_INTENTS = {
    'ACADEMIC_QUESTION', 'CALCULATION', 'REQUEST_QUIZ', 'REQUEST_EXPLANATION',
    'COMMAND', 'GREETING', 'CASUAL_CHAT', 'PAYMENT_INQUIRY', 'IMAGE_ANALYSIS',
    'VOICE_NOTE', 'WRONG_RESPONSE', 'ONBOARDING_RESPONSE', 'EXAM_RESPONSE',
    'REFERRAL_CODE', 'PROMO_CODE', 'HELP_REQUEST', 'UNKNOWN'
}

COMMAND_LIST = {
    'PROGRESS', 'HELP', 'SUBSCRIBE', 'STREAK', 'PLAN', 'BALANCE', 
    'MYID', 'PROMO', 'PAUSE', 'CONTINUE', 'STOP', 'MODES',
    'SUBJECTS', 'QUIZ', 'LEARN', 'EXAM', 'REVISION', 'CHALLENGE',
    'PROFILE', 'BADGES', 'REFERRAL', 'PARENT'
}

def classify_message_fast(message: str, conversation_state: dict = None) -> str:
    """
    Fast classification using rule-based logic first, then AI if needed.
    
    Rule-based classification handles obvious cases instantly (no API call needed).
    AI classification handles ambiguous cases.
    
    Returns the intent category as a string.
    """
    message_upper = message.strip().upper()
    message_words = message_upper.split()
    
    # Check for exact commands first (fastest, no AI needed)
    if message_words and message_words[0] in COMMAND_LIST:
        return 'COMMAND'
    
    # Check for promo code pattern
    if message_upper.startswith('PROMO ') or message_upper.startswith('CODE '):
        return 'PROMO_CODE'
    
    # Check for WAX ID
    import re
    if re.search(r'WAX-[A-Z][A-Z0-9]{5}', message_upper):
        return 'REFERRAL_CODE'
    
    # If in exam mode, any text response is an exam answer
    if conversation_state and conversation_state.get('current_mode') == 'exam':
        return 'EXAM_RESPONSE'
    
    # If awaiting a specific response, use that context
    awaiting = conversation_state.get('awaiting_response_for') if conversation_state else None
    if awaiting:
        if awaiting in ['new_or_existing', 'wax_id_entry', 'pin_entry', 'name', 
                        'class_level', 'target_exam', 'subjects', 'exam_date', 
                        'language_pref', 'pin_setup', 'pin_confirm']:
            return 'ONBOARDING_RESPONSE'
        if awaiting == 'quiz_answer':
            return 'WRONG_RESPONSE'
    
    # Check for simple greetings
    greetings = ['hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening', 
                 'good night', 'sup', 'howdy', 'oya', 'abeg', 'bro']
    if any(message.lower().strip().startswith(g) for g in greetings) and len(message) < 30:
        return 'GREETING'
    
    # For everything else, use AI classification
    return classify_message_with_ai(message, conversation_state)

def classify_message_with_ai(message: str, conversation_state: dict = None) -> str:
    """
    Uses Groq's fast AI model to classify the message intent.
    Only called when rule-based classification can't determine the intent.
    """
    from ai.prompts import get_intent_classifier_prompt
    
    # Add conversation context to help classification
    context = ""
    if conversation_state:
        mode = conversation_state.get('current_mode', 'default')
        subject = conversation_state.get('current_subject', '')
        if mode != 'default' and mode:
            context = f"\nContext: Student is currently in {mode} mode studying {subject}."
    
    try:
        response = groq_client.chat.completions.create(
            model=settings.GROQ_FAST_MODEL,
            messages=[
                {"role": "system", "content": get_intent_classifier_prompt()},
                {"role": "user", "content": message + context}
            ],
            max_tokens=20,         # We only need one word
            temperature=0.1,       # Low temperature = more consistent/predictable
        )
        
        intent = response.choices[0].message.content.strip().upper()
        
        # Validate the response
        if intent in VALID_INTENTS:
            return intent
        else:
            # AI returned something unexpected — default to academic question
            # Better to try to answer academically than to fail silently
            return 'ACADEMIC_QUESTION'
            
    except Exception as e:
        print(f"Classification error: {e}")
        # If classification fails, treat as academic question
        return 'ACADEMIC_QUESTION'

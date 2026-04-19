import hashlib
import random
import string
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import phonenumbers

NIGERIA_TZ = ZoneInfo("Africa/Lagos")

# ===================================================
# PHONE NUMBER UTILITIES
# ===================================================

def normalize_phone(phone: str) -> str:
    """
    Converts any Nigerian phone number format to international format.
    
    Examples:
    08012345678 → +2348012345678
    2348012345678 → +2348012345678
    +2348012345678 → +2348012345678
    
    We normalize all numbers so they're stored consistently.
    """
    phone = re.sub(r'\D', '', phone)  # Remove everything that's not a digit
    
    if phone.startswith('0') and len(phone) == 11:
        phone = '234' + phone[1:]
    elif phone.startswith('234') and len(phone) == 13:
        pass
    elif len(phone) == 10:
        phone = '234' + phone
    
    return '+' + phone

def hash_phone(phone: str) -> str:
    """
    Creates a one-way hash of a phone number.
    We store the hash, not the real number.
    If someone hacks our database, they can't recover phone numbers.
    But we can still check: "does this hash match this phone number?"
    """
    normalized = normalize_phone(phone)
    return hashlib.sha256(normalized.encode()).hexdigest()

def validate_phone(phone: str) -> bool:
    """
    Checks if a phone number looks like a real Nigerian number.
    Returns True if valid, False if not.
    """
    try:
        normalized = normalize_phone(phone)
        parsed = phonenumbers.parse(normalized)
        return phonenumbers.is_valid_number(parsed)
    except Exception:
        return False

# ===================================================
# WAX ID GENERATION
# ===================================================

def generate_wax_id() -> str:
    """
    Generates a new WAX ID in the format WAX-A74892.
    
    WAX = Always starts with this
    A = A random letter (A-Z)
    74892 = Five random alphanumeric characters
    
    Total unique combinations: 26 * 36^5 = over 1.1 billion
    More than enough for every Nigerian student who will ever use WaxPrep.
    """
    letter = random.choice(string.ascii_uppercase)
    characters = string.ascii_uppercase + string.digits
    suffix = ''.join(random.choices(characters, k=5))
    return f"WAX-{letter}{suffix}"

def generate_recovery_code() -> str:
    """
    Generates a recovery code like WAXBRAVE77.
    Students save this during onboarding.
    If they lose their phone, they can use this + WAX ID to get back in.
    """
    words = [
        'BRAVE', 'SMART', 'BOLD', 'KEEN', 'SWIFT', 'SHARP', 'BRIGHT', 'WISE',
        'GREAT', 'PURE', 'GOLD', 'STAR', 'FIRE', 'IRON', 'ROCK', 'WIND',
        'LION', 'EAGLE', 'HAWK', 'OWL', 'TIGER', 'SWIFT', 'APEX', 'PRIME',
        'NOVA', 'FLUX', 'BEAM', 'GLOW', 'RISE', 'SHINE', 'ACE', 'TOP'
    ]
    word = random.choice(words)
    numbers = ''.join(random.choices(string.digits, k=2))
    return f"WAX{word}{numbers}"

def generate_referral_code(wax_id: str) -> str:
    """
    Generates a referral code based on the student's WAX ID.
    Example: WAX-A74892 → WAXA74
    Short, memorable, and unique.
    """
    clean = wax_id.replace('WAX-', '').replace('-', '')
    return f"WAX{clean[:4].upper()}"

def generate_promo_code(code_type: str = None) -> str:
    """
    Generates a random promo code.
    Used for daily founder codes.
    Example: WAXDAY7K2P
    """
    characters = string.ascii_uppercase + string.digits
    suffix = ''.join(random.choices(characters, k=4))
    prefix = {
        'daily': 'DAY',
        'trial': 'TRY',
        'discount': 'OFF',
        'free': 'FREE',
    }.get(code_type, 'WAX')
    return f"{prefix}{suffix}"

# ===================================================
# DATE AND TIME UTILITIES
# ===================================================

def nigeria_now() -> datetime:
    """Returns the current time in Nigerian timezone."""
    return datetime.now(NIGERIA_TZ)

def nigeria_today() -> str:
    """Returns today's date as a string in Nigerian timezone. Format: YYYY-MM-DD"""
    return nigeria_now().strftime('%Y-%m-%d')

def time_until(future_dt: datetime) -> str:
    """
    Returns a human-readable string for how long until a date.
    Example: "2 days and 3 hours" or "45 minutes"
    """
    if not future_dt:
        return "unknown"
    
    now = nigeria_now()
    if future_dt.tzinfo is None:
        future_dt = future_dt.replace(tzinfo=NIGERIA_TZ)
    
    diff = future_dt - now
    
    if diff.total_seconds() < 0:
        return "expired"
    
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    
    if days > 0:
        return f"{days} day{'s' if days > 1 else ''} and {hours} hour{'s' if hours != 1 else ''}"
    elif hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''} and {minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"

def days_since(past_dt: datetime) -> int:
    """Returns how many days have passed since a given datetime."""
    if not past_dt:
        return 0
    now = nigeria_now()
    if past_dt.tzinfo is None:
        past_dt = past_dt.replace(tzinfo=NIGERIA_TZ)
    return (now - past_dt).days

# ===================================================
# TEXT FORMATTING
# ===================================================

def clean_name(name: str) -> str:
    """
    Cleans a student's name.
    Removes extra spaces, capitalizes properly.
    "  chidi OKONKWO  " → "Chidi Okonkwo"
    """
    return ' '.join(word.capitalize() for word in name.strip().split())

def format_naira(amount: int) -> str:
    """
    Formats a Naira amount with the symbol and comma separators.
    1500 → "₦1,500"
    """
    return f"₦{amount:,}"

def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncates text to a maximum length, adding ... if truncated."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def split_for_whatsapp(text: str, max_length: int = 4000) -> list:
    """
    WhatsApp messages have a character limit.
    This splits long responses into appropriate chunks.
    We try to split at paragraph breaks so the message feels natural.
    
    Returns a list of message chunks, each under max_length characters.
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""
    
    for paragraph in paragraphs:
        # If this single paragraph is too long, we must split it
        if len(paragraph) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            # Split by sentence
            sentences = paragraph.split('. ')
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 2 <= max_length:
                    current_chunk += sentence + '. '
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence + '. '
        elif len(current_chunk) + len(paragraph) + 2 <= max_length:
            current_chunk += paragraph + '\n\n'
        else:
            chunks.append(current_chunk.strip())
            current_chunk = paragraph + '\n\n'
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    # Add "continued..." markers
    for i in range(len(chunks) - 1):
        chunks[i] += f"\n\n_(continued...)_"
    
    return chunks

# ===================================================
# VALIDATION UTILITIES
# ===================================================

def is_valid_pin(pin: str) -> bool:
    """Checks if a PIN is exactly 4 digits."""
    return bool(re.match(r'^\d{4}$', str(pin)))

def is_valid_wax_id(wax_id: str) -> bool:
    """Checks if a string looks like a valid WAX ID."""
    return bool(re.match(r'^WAX-[A-Z][A-Z0-9]{5}$', wax_id.upper()))

def extract_wax_id(text: str) -> str | None:
    """
    Tries to find a WAX ID in a message.
    Handles cases where students type their WAX ID in different ways.
    "my id is WAX-A74892" → "WAX-A74892"
    """
    text = text.upper()
    match = re.search(r'WAX-[A-Z][A-Z0-9]{5}', text)
    return match.group(0) if match else None

def sanitize_input(text: str) -> str:
    """
    Removes potentially dangerous characters from user input.
    This is a security measure.
    """
    # Remove null bytes and control characters
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    # Trim whitespace
    text = text.strip()
    # Maximum length
    return text[:2000]

# ===================================================
# MOTIVATIONAL CONTENT
# ===================================================

ENCOURAGEMENT_MESSAGES = {
    'almost': [
        "Almost! You were right about part of it 💪",
        "Close — you're thinking about it the right way, just one piece shifted",
        "Good thinking — let me show you where it went a slightly different direction",
        "You're on the right track! Small adjustment needed 🎯",
        "Nearly there! Let me show you the slight difference",
    ],
    'wrong': [
        "You attempted to apply the formula, which is exactly the right approach. The formula itself needs a small adjustment.",
        "I can see your reasoning — let me show you a cleaner approach to this one",
        "Good effort! Here's a different angle on this question",
        "No worries — this is actually one of the trickier ones. Let's break it down",
    ],
    'correct': [
        "Excellent! That's exactly right! 🎉",
        "Perfect! You nailed it! ⭐",
        "Correct! That's the right answer! 🏆",
        "Outstanding! You got it! 💫",
        "That's exactly it! Well done! 🌟",
    ],
    'streak_encouragement': [
        "Your consistency is your superpower 🔥",
        "Day {streak}! You're building something real here",
        "Imagine where you'll be in 30 more days at this pace 🚀",
        "Chidi studies every day. That's why Chidi passes. Keep going.",
        "The student who shows up daily wins. You're showing up.",
    ]
}

def get_almost_message() -> str:
    """Returns a random 'almost right' encouragement message."""
    return random.choice(ENCOURAGEMENT_MESSAGES['almost'])

def get_correct_message() -> str:
    """Returns a random 'correct answer' celebration message."""
    return random.choice(ENCOURAGEMENT_MESSAGES['correct'])

def get_wrong_message() -> str:
    """Returns a random message for completely wrong answers."""
    return random.choice(ENCOURAGEMENT_MESSAGES['wrong'])

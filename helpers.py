"""
WaxPrep Helper Functions — Root Level

This file is at the ROOT of the project (same level as main.py).
It requires NO __init__.py and NO package structure.
Python always finds root-level files automatically.

All imports here are from standard library or pip packages only.
No WaxPrep internal imports — this file has zero dependencies.
"""

import hashlib
import random
import string
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import bcrypt

NIGERIA_TZ = ZoneInfo("Africa/Lagos")


# ============================================================
# PHONE NUMBER UTILITIES
# ============================================================

def normalize_phone(phone: str) -> str:
    """
    Converts any Nigerian phone number to the format 2348012345678
    (no + prefix, starts with 234).

    Examples:
      08012345678     -> 2348012345678
      +2348012345678  -> 2348012345678
      2348012345678   -> 2348012345678
    """
    phone = re.sub(r'\D', '', phone)  # Remove non-digits
    if phone.startswith('0') and len(phone) == 11:
        phone = '234' + phone[1:]
    elif phone.startswith('234') and len(phone) == 13:
        pass  # Already correct
    elif len(phone) == 10:
        phone = '234' + phone
    return phone


def hash_phone(phone: str) -> str:
    """
    Creates a one-way SHA-256 hash of a phone number.
    We store the hash, not the real number.
    Even if database is accessed, actual numbers cannot be recovered.
    """
    normalized = normalize_phone(phone)
    return hashlib.sha256(normalized.encode()).hexdigest()


def validate_phone(phone: str) -> bool:
    """Returns True if the string looks like a valid Nigerian phone number."""
    try:
        import phonenumbers
        normalized = '+' + normalize_phone(phone)
        parsed = phonenumbers.parse(normalized)
        return phonenumbers.is_valid_number(parsed)
    except Exception:
        # If phonenumbers package not available or invalid, do basic check
        digits = re.sub(r'\D', '', phone)
        return len(digits) in [10, 11, 13]


# ============================================================
# WAX ID AND CODE GENERATION
# ============================================================

def generate_wax_id() -> str:
    """
    Generates a WAX ID in format WAX-A74892.
    WAX = prefix
    A   = random uppercase letter
    74892 = 5 random uppercase letters or digits
    Over 1.1 billion possible combinations.
    """
    letter = random.choice(string.ascii_uppercase)
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(random.choices(chars, k=5))
    return f"WAX-{letter}{suffix}"


def generate_recovery_code() -> str:
    """
    Generates a memorable recovery code like WAXBRAVE77.
    Students save this during onboarding for account recovery.
    """
    words = [
        'BRAVE', 'SMART', 'BOLD', 'KEEN', 'SWIFT', 'SHARP', 'BRIGHT', 'WISE',
        'GREAT', 'PURE', 'GOLD', 'STAR', 'FIRE', 'IRON', 'LION', 'EAGLE',
        'HAWK', 'APEX', 'NOVA', 'BEAM', 'RISE', 'SHINE', 'ACE', 'TOP',
        'PRIME', 'CORE', 'PEAK', 'FLUX', 'GLOW', 'ROCK'
    ]
    word = random.choice(words)
    numbers = ''.join(random.choices(string.digits, k=2))
    return f"WAX{word}{numbers}"


def generate_referral_code(wax_id: str) -> str:
    """
    Generates a short referral code from a WAX ID.
    WAX-A74892 -> WAXA74
    """
    clean = wax_id.replace('WAX-', '').replace('-', '')
    return f"WAX{clean[:4].upper()}"


def generate_promo_code(code_type: str = 'daily') -> str:
    """
    Generates a random promo code for admin use.
    Example: DAYXK2P4
    """
    chars = string.ascii_uppercase + string.digits
    suffix = ''.join(random.choices(chars, k=4))
    prefix_map = {
        'daily': 'DAY',
        'trial': 'TRY',
        'discount': 'OFF',
        'free': 'FREE',
        'vip': 'VIP',
    }
    prefix = prefix_map.get(code_type, 'WAX')
    return f"{prefix}{suffix}"


# ============================================================
# DATE AND TIME
# ============================================================

def nigeria_now() -> datetime:
    """Returns the current datetime in Nigerian timezone (WAT = UTC+1)."""
    return datetime.now(NIGERIA_TZ)


def nigeria_today() -> str:
    """Returns today's date as YYYY-MM-DD string in Nigerian timezone."""
    return nigeria_now().strftime('%Y-%m-%d')


def time_until(future_dt: datetime) -> str:
    """
    Returns a human-readable string for time remaining.
    Example: '2 days and 3 hours' or '45 minutes'
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
        return f"{days} day{'s' if days != 1 else ''} and {hours} hour{'s' if hours != 1 else ''}"
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
    return max(0, (now - past_dt).days)


# ============================================================
# TEXT AND FORMATTING
# ============================================================

def clean_name(name: str) -> str:
    """
    Cleans and properly capitalizes a name.
    '  chidi OKONKWO  ' -> 'Chidi Okonkwo'
    """
    return ' '.join(word.capitalize() for word in name.strip().split() if word)


def format_naira(amount: int) -> str:
    """
    Formats a Naira amount with symbol and comma separators.
    1500 -> '₦1,500'
    """
    return f"₦{amount:,}"


def truncate_text(text: str, max_length: int = 200) -> str:
    """Truncates text to max_length, adding ... if truncated."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def split_for_whatsapp(text: str, max_length: int = 4000) -> list:
    """
    Splits long text into chunks that fit within WhatsApp's character limit.
    Tries to split at paragraph breaks for natural-feeling messages.
    Returns a list of strings.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
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

    # Add continuation markers
    for i in range(len(chunks) - 1):
        chunks[i] += "\n\n_(continued...)_"

    return chunks if chunks else [text]


# ============================================================
# VALIDATION
# ============================================================

def is_valid_pin(pin: str) -> bool:
    """Returns True if pin is exactly 4 digits."""
    return bool(re.match(r'^\d{4}$', str(pin).strip()))


def is_valid_wax_id(wax_id: str) -> bool:
    """Returns True if string matches WAX ID format WAX-XXXXXX."""
    return bool(re.match(r'^WAX-[A-Z][A-Z0-9]{5}$', str(wax_id).strip().upper()))


def extract_wax_id(text: str) -> str | None:
    """
    Finds a WAX ID anywhere in a message.
    Handles formats: WAX-A74892, WAXA74892, wax-a74892
    Returns the WAX ID in standard format or None.
    """
    text_upper = text.strip().upper()

    # Standard format: WAX-A74892
    match = re.search(r'WAX-[A-Z][A-Z0-9]{5}', text_upper)
    if match:
        return match.group(0)

    # Without dash: WAXA74892
    match = re.search(r'WAX([A-Z][A-Z0-9]{5})', text_upper)
    if match:
        return f"WAX-{match.group(1)}"

    return None


def sanitize_input(text: str) -> str:
    """Removes potentially dangerous characters from user input."""
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return text.strip()[:2000]


# ============================================================
# PIN SECURITY
# ============================================================

def hash_pin(pin: str) -> str:
    """
    Creates a secure bcrypt hash of a 4-digit PIN.
    The hash cannot be reversed — even we can't see the original PIN.
    """
    pin_bytes = str(pin).encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pin_bytes, salt)
    return hashed.decode('utf-8')


def verify_pin(pin: str, pin_hash: str) -> bool:
    """
    Checks if a PIN matches its stored hash.
    Returns True if correct, False if wrong.
    """
    try:
        pin_bytes = str(pin).encode('utf-8')
        hash_bytes = pin_hash.encode('utf-8')
        return bcrypt.checkpw(pin_bytes, hash_bytes)
    except Exception:
        return False


# ============================================================
# ENCOURAGEMENT MESSAGES
# ============================================================

_ALMOST_MESSAGES = [
    "Almost! You were right about part of it 💪",
    "Close — you're thinking about it the right way, just one piece shifted",
    "Good thinking — let me show you where it went a slightly different direction",
    "You're on the right track! Small adjustment needed 🎯",
    "Nearly there! Let me show you the slight difference",
]

_CORRECT_MESSAGES = [
    "Excellent! That's exactly right! 🎉",
    "Perfect! You nailed it! ⭐",
    "Correct! Outstanding! 🏆",
    "That's exactly it! Well done! 🌟",
    "Great job! You got it! 💫",
]

_WRONG_MESSAGES = [
    "You attempted to apply the formula, which is exactly the right approach. Let me show you a small adjustment.",
    "I can see your reasoning — let me show you a cleaner angle on this one",
    "Good effort! Here's a different perspective on this question",
    "No worries — this is actually one of the trickier ones. Let's break it down",
]


def get_almost_message() -> str:
    return random.choice(_ALMOST_MESSAGES)


def get_correct_message() -> str:
    return random.choice(_CORRECT_MESSAGES)


def get_wrong_message() -> str:
    return random.choice(_WRONG_MESSAGES)

import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    APP_NAME = "WaxPrep"
    APP_VERSION = "1.0.0"
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "waxprep-change-this")
    ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP")
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
    TIMEZONE = "Africa/Lagos"
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    REDIS_URL = os.getenv("REDIS_URL")

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    GROQ_FAST_MODEL = "llama-3.1-8b-instant"
    GROQ_SMART_MODEL = "llama-3.3-70b-versatile"
    GEMINI_MODEL = "gemini-2.0-flash"
    GEMINI_PRO_MODEL = "gemini-1.5-pro"
    OPENAI_VISION_MODEL = "gpt-4o-mini"

    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "waxprep_verify_2024")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_API_VERSION = "v19.0"
    WHATSAPP_API_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"

    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
    PAYSTACK_API_URL = "https://api.paystack.co"

    TERMII_API_KEY = os.getenv("TERMII_API_KEY")
    TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "WaxPrep")

    SCHOLAR_MONTHLY = 1500
    SCHOLAR_YEARLY = 15000
    PRO_MONTHLY = 3000
    PRO_YEARLY = 28800
    ELITE_MONTHLY = 5000
    ELITE_YEARLY = 48000

    PAYG_100_QUESTIONS = 500
    PAYG_250_QUESTIONS = 1000
    PAYG_500_QUESTIONS = 1800

    FREE_DAILY_QUESTIONS = 20
    SCHOLAR_DAILY_QUESTIONS = 100
    PRO_DAILY_QUESTIONS = 9999
    ELITE_DAILY_QUESTIONS = 9999
    TRIAL_DAILY_QUESTIONS = 9999

    DAILY_QUESTION_LIMITS = {
        'free': 20,
        'scholar': 100,
        'pro': 9999,
        'elite': 9999,
        'trial': 9999,
    }

    TRIAL_DURATION_DAYS = 7
    GRACE_PERIOD_DAYS = 3

    POINTS_CORRECT_ANSWER = 10
    POINTS_WRONG_ATTEMPT = 2
    POINTS_SESSION_COMPLETE = 25
    POINTS_STREAK_DAILY = 20
    POINTS_MOCK_EXAM = 75
    POINTS_DAILY_CHALLENGE_ATTEMPT = 50
    POINTS_DAILY_CHALLENGE_WIN = 100
    POINTS_BADGE_EARNED = 50
    POINTS_REFERRAL_SIGNUP = 100

    DAILY_AI_BUDGET_USD = 2.00
    AI_BUDGET_WARNING_THRESHOLD = 0.70
    AI_BUDGET_SHIFT_THRESHOLD = 0.85

    SESSION_TIMEOUT_MINUTES = 30
    SESSION_RESUME_WINDOW_HOURS = 6

    # FIXED: Changed from waxprep.ng (dead domain) to live GitHub Pages URL
    TERMS_URL = "https://waxprep-dev.github.io/Waxprep-backend/terms.html"
    PRIVACY_URL = "https://waxprep-dev.github.io/Waxprep-backend/terms.html"

    LEVEL_THRESHOLDS = {
        1: 0, 2: 500, 3: 1200, 4: 2500, 5: 4500,
        6: 7000, 7: 10000, 8: 14000, 9: 19000, 10: 25000,
    }

    @classmethod
    def get_daily_question_limit(cls, tier: str, is_trial: bool) -> int:
        if is_trial:
            return cls.TRIAL_DAILY_QUESTIONS
        return cls.DAILY_QUESTION_LIMITS.get(tier, cls.FREE_DAILY_QUESTIONS)

    @classmethod
    def get_level_name(cls, level: int) -> str:
        if level <= 10: return "Scholar"
        if level <= 20: return "Apprentice"
        if level <= 30: return "Adept"
        if level <= 40: return "Expert"
        if level <= 50: return "Master"
        if level <= 70: return "Elite"
        if level <= 90: return "Legendary"
        if level <= 99: return "Grandmaster"
        return "Wax Champion"

settings = Settings()

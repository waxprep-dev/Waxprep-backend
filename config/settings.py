import os
from dotenv import load_dotenv

# Load environment variables from .env file (for local testing)
# On Railway, these come from the Variables section
load_dotenv()

class Settings:
    """
    Central configuration for WaxPrep.
    All settings come from environment variables so that:
    1. No secrets are stored in the code
    2. Settings can be changed without redeploying
    3. Different environments (test vs production) can have different values
    """
    
    # ========================================
    # APPLICATION SETTINGS
    # ========================================
    APP_NAME = "WaxPrep"
    APP_VERSION = "1.0.0"
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
    
    # Your personal WhatsApp number (for admin reports)
    ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP")
    
    # Nigerian timezone
    TIMEZONE = "Africa/Lagos"
    
    # ========================================
    # DATABASE — SUPABASE
    # ========================================
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    
    # ========================================
    # CACHE — UPSTASH REDIS
    # ========================================
    REDIS_URL = os.getenv("REDIS_URL")
    
    # ========================================
    # AI MODELS
    # ========================================
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Which model to use for each tier
    GROQ_FAST_MODEL = "llama3-8b-8192"        # Free, very fast, good for simple stuff
    GROQ_SMART_MODEL = "llama3-70b-8192"       # Free, powerful, slower
    GEMINI_MODEL = "gemini-1.5-flash"           # Fast Gemini, good quality
    GEMINI_PRO_MODEL = "gemini-1.5-pro"         # Powerful Gemini, best quality
    OPENAI_VISION_MODEL = "gpt-4o-mini"         # Vision, image analysis
    
    # ========================================
    # WHATSAPP API (META)
    # ========================================
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "waxprep_verify_2024")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_API_VERSION = "v19.0"
    WHATSAPP_API_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
    
    # ========================================
    # PAYMENTS — PAYSTACK
    # ========================================
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
    PAYSTACK_API_URL = "https://api.paystack.co"
    
    # ========================================
    # SMS — TERMII
    # ========================================
    TERMII_API_KEY = os.getenv("TERMII_API_KEY")
    TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "WaxPrep")
    
    # ========================================
    # SUBSCRIPTION PRICING (in Naira)
    # ========================================
    SCHOLAR_MONTHLY = 1500
    SCHOLAR_YEARLY = 15000
    PRO_MONTHLY = 3000
    PRO_YEARLY = 28800
    ELITE_MONTHLY = 5000
    ELITE_YEARLY = 48000
    
    # ========================================
    # DAILY QUESTION LIMITS PER TIER
    # ========================================
    FREE_DAILY_QUESTIONS = 60
    SCHOLAR_DAILY_QUESTIONS = 100
    PRO_DAILY_QUESTIONS = 9999       # Effectively unlimited
    ELITE_DAILY_QUESTIONS = 9999     # Effectively unlimited
    TRIAL_DAILY_QUESTIONS = 9999     # Full access during trial
    
    # ========================================
    # TRIAL SETTINGS
    # ========================================
    TRIAL_DURATION_DAYS = 7
    GRACE_PERIOD_DAYS = 3            # Days of access after subscription expires
    
    # ========================================
    # GAMIFICATION — POINTS
    # ========================================
    POINTS_CORRECT_ANSWER = 10
    POINTS_WRONG_ATTEMPT = 2         # Points for trying even when wrong
    POINTS_SESSION_COMPLETE = 25
    POINTS_STREAK_DAILY = 20
    POINTS_MOCK_EXAM = 75
    POINTS_DAILY_CHALLENGE_ATTEMPT = 50
    POINTS_DAILY_CHALLENGE_WIN = 100
    POINTS_BADGE_EARNED = 50
    POINTS_REFERRAL_SIGNUP = 100    # Points when someone you referred signs up
    
    # ========================================
    # AI COST MANAGEMENT
    # ========================================
    DAILY_AI_BUDGET_USD = 5.00
    AI_BUDGET_WARNING_THRESHOLD = 0.70   # Warn at 70% of budget
    AI_BUDGET_SHIFT_THRESHOLD = 0.85     # Start using cheaper models at 85%
    
    # ========================================
    # SESSION SETTINGS
    # ========================================
    SESSION_TIMEOUT_MINUTES = 30
    SESSION_RESUME_WINDOW_HOURS = 6      # Window to offer to resume a session
    
    # ========================================
    # LEVEL THRESHOLDS
    # How many total points to reach each level
    # ========================================
    LEVEL_THRESHOLDS = {
        1: 0,
        2: 500,
        3: 1200,
        4: 2500,
        5: 4500,
        6: 7000,
        7: 10000,
        8: 14000,
        9: 19000,
        10: 25000,
        11: 32000,
        12: 40000,
        13: 50000,
        14: 62000,
        15: 76000,
        16: 92000,
        17: 110000,
        18: 130000,
        19: 152000,
        20: 176000,
    }
    
    LEVEL_NAMES = {
        range(1, 11): "Scholar",
        range(11, 21): "Apprentice",
        range(21, 31): "Adept",
        range(31, 41): "Expert",
        range(41, 51): "Master",
        range(51, 71): "Elite",
        range(71, 91): "Legendary",
        range(91, 100): "Grandmaster",
        range(100, 101): "Wax Champion",
    }
    
    @classmethod
    def get_daily_question_limit(cls, tier: str, is_trial: bool) -> int:
        """Returns how many questions a student can ask per day based on their tier."""
        if is_trial:
            return cls.TRIAL_DAILY_QUESTIONS
        limits = {
            'free': cls.FREE_DAILY_QUESTIONS,
            'scholar': cls.SCHOLAR_DAILY_QUESTIONS,
            'pro': cls.PRO_DAILY_QUESTIONS,
            'elite': cls.ELITE_DAILY_QUESTIONS,
        }
        return limits.get(tier, cls.FREE_DAILY_QUESTIONS)
    
    @classmethod
    def get_level_name(cls, level: int) -> str:
        """Returns the name for a given level number."""
        for level_range, name in cls.LEVEL_NAMES.items():
            if level in level_range:
                return name
        return "Scholar"

# Create a global instance of settings
settings = Settings()

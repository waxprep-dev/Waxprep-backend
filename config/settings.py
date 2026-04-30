import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME = "WaxPrep"
    APP_VERSION = "3.0.0"
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    SECRET_KEY = os.getenv("SECRET_KEY", "waxprep-change-this-in-production")
    ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP")
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
    TIMEZONE = "Africa/Lagos"

    # Database
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    REDIS_URL = os.getenv("REDIS_URL")

    # AI Models
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

    # Model names
    # Free tier uses the fast 8B model — still very good, noticeably different from 70B
    GROQ_FREE_MODEL = "llama-3.1-8b-instant"
    # Scholar tier uses the 70B model — dramatically better for complex explanations
    GROQ_SMART_MODEL = "llama-3.3-70b-versatile"
    GROQ_FAST_MODEL = "llama-3.1-8b-instant"
    GROQ_WHISPER_MODEL = "whisper-large-v3"
    GEMINI_MODEL = "gemini-1.5-flash-latest"
    GEMINI_PRO_MODEL = "gemini-1.5-pro-latest"
    OPENAI_VISION_MODEL = "gpt-4o-mini"
    OPENAI_TTS_MODEL = "tts-1"
    OPENAI_TTS_VOICE = "nova"

    # WhatsApp
    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "waxprep_verify_2024")
    WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_API_VERSION = "v19.0"
    WHATSAPP_API_URL = "https://graph.facebook.com/v19.0"
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    # Paystack
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
    PAYSTACK_API_URL = "https://api.paystack.co"
    # Plan codes from your Paystack dashboard
    PAYSTACK_SCHOLAR_MONTHLY_PLAN_CODE = os.getenv("PAYSTACK_SCHOLAR_MONTHLY_PLAN_CODE", "")
    PAYSTACK_SCHOLAR_YEARLY_PLAN_CODE = os.getenv("PAYSTACK_SCHOLAR_YEARLY_PLAN_CODE", "")

    # Termii
    TERMII_API_KEY = os.getenv("TERMII_API_KEY")
    TERMII_SENDER_ID = os.getenv("TERMII_SENDER_ID", "WaxPrep")

    # Pricing (Naira)
    SCHOLAR_MONTHLY = 1500
    SCHOLAR_YEARLY = 15000
    ELITE_MONTHLY = 3500
    ELITE_YEARLY = 35000

    # Pay-As-You-Go Credit packs
    # 1 credit = 1 naira equivalent
    CREDIT_PACK_1000 = 1000    # 1000 credits for N1000
    CREDIT_PACK_2500 = 2000    # 2500 credits for N2000
    CREDIT_PACK_5000 = 3500    # 5000 credits for N3500
    # Credit costs per action
    CREDIT_COST_TEXT_QUESTION = 1
    CREDIT_COST_IMAGE_ANALYSIS = 3
    CREDIT_COST_VOICE_NOTE = 2
    CREDIT_COST_MOCK_EXAM = 25

    # FREE TIER IS UNLIMITED TEXT — no question cap
    # The difference is MODEL QUALITY and FEATURES, not quantity
    # This is the core philosophy change
    FREE_DAILY_TURNS = 999999   # Effectively unlimited
    SCHOLAR_DAILY_TURNS = 999999
    ELITE_DAILY_TURNS = 999999
    TRIAL_DAILY_TURNS = 999999

    # Per-student daily AI cost cap to prevent abuse
    # Free students use cheap model so this is rarely hit
    FREE_DAILY_AI_COST_CAP_USD = 0.05   # ~50 cents max per free student per day
    SCHOLAR_DAILY_AI_COST_CAP_USD = 0.50

    # Feature flags by tier
    # These control what each tier can access
    FEATURES_BY_TIER = {
        'free': {
            'text_questions': True,
            'voice_input': False,
            'image_analysis': False,
            'mock_exams': False,
            'spaced_repetition': True,
            'study_plan': False,
            'progress_report': False,
            'battle_mode': False,
            'premium_ai_model': False,
            'priority_response': False,
            'pdf_reports': False,
            'daily_challenge': True,
            'credits_purchase': True,
        },
        'trial': {
            'text_questions': True,
            'voice_input': True,
            'image_analysis': True,
            'mock_exams': True,
            'spaced_repetition': True,
            'study_plan': True,
            'progress_report': True,
            'battle_mode': True,
            'premium_ai_model': True,
            'priority_response': True,
            'pdf_reports': True,
            'daily_challenge': True,
            'credits_purchase': True,
        },
        'scholar': {
            'text_questions': True,
            'voice_input': True,
            'image_analysis': True,
            'mock_exams': True,
            'spaced_repetition': True,
            'study_plan': True,
            'progress_report': True,
            'battle_mode': True,
            'premium_ai_model': True,
            'priority_response': True,
            'pdf_reports': True,
            'daily_challenge': True,
            'credits_purchase': True,
        },
        'elite': {
            'text_questions': True,
            'voice_input': True,
            'image_analysis': True,
            'mock_exams': True,
            'spaced_repetition': True,
            'study_plan': True,
            'progress_report': True,
            'battle_mode': True,
            'premium_ai_model': True,
            'priority_response': True,
            'pdf_reports': True,
            'daily_challenge': True,
            'credits_purchase': True,
            'voice_output': True,
            'audiobook': True,
        }
    }

    # Trial Settings
    TRIAL_DURATION_DAYS = 7
    GRACE_PERIOD_DAYS = 3

    # Points System
    POINTS_CORRECT_ANSWER = 10
    POINTS_WRONG_ATTEMPT = 2
    POINTS_SESSION_COMPLETE = 25
    POINTS_STREAK_DAILY = 20
    POINTS_MOCK_EXAM = 75
    POINTS_DAILY_CHALLENGE_ATTEMPT = 50
    POINTS_DAILY_CHALLENGE_WIN = 100
    POINTS_BADGE_EARNED = 50
    POINTS_REFERRAL_SIGNUP = 100
    POINTS_FIRST_PAYMENT = 200

    # AI Budget (platform-wide daily cap)
    DAILY_AI_BUDGET_USD = 10.00
    AI_BUDGET_WARNING_THRESHOLD = 0.70
    AI_BUDGET_SHIFT_THRESHOLD = 0.85

    # Cache TTLs (seconds)
    STUDENT_CACHE_TTL = 300
    CONVERSATION_CACHE_TTL = 7200
    SESSION_CACHE_TTL = 1800
    QUESTION_CACHE_TTL = 3600

    # Session Settings
    SESSION_TIMEOUT_MINUTES = 30
    SESSION_RESUME_WINDOW_HOURS = 6

    # Question Quality Thresholds
    QUESTION_MIN_ANSWERS_TO_EVALUATE = 15
    QUESTION_AUTO_DEACTIVATE_QUALITY_BELOW = 2.5
    QUESTION_SUSPICIOUS_CORRECT_RATE_MIN = 0.05
    QUESTION_SUSPICIOUS_CORRECT_RATE_MAX = 0.98

    # URLs
    TERMS_URL = "https://waxprep-dev.github.io/Waxprep-backend/terms.html"
    PRIVACY_URL = "https://waxprep-dev.github.io/Waxprep-backend/terms.html"
    PAYMENT_SUCCESS_URL = "https://waxprep-dev.github.io/Waxprep-backend/payment_success.html"

    # Level System
    LEVEL_THRESHOLDS = {
        1: 0, 2: 500, 3: 1200, 4: 2500, 5: 4500,
        6: 7000, 7: 10000, 8: 14000, 9: 19000, 10: 25000,
        11: 32000, 12: 40000, 13: 50000, 14: 62000, 15: 76000,
    }

    @classmethod
    def get_ai_model_for_tier(cls, tier: str, is_trial: bool) -> str:
        effective = 'trial' if is_trial else tier
        if effective in ('trial', 'scholar', 'elite'):
            return cls.GROQ_SMART_MODEL
        return cls.GROQ_FREE_MODEL

    @classmethod
    def has_feature(cls, feature: str, tier: str, is_trial: bool) -> bool:
        effective = 'trial' if is_trial else tier
        tier_features = cls.FEATURES_BY_TIER.get(effective, cls.FEATURES_BY_TIER['free'])
        return tier_features.get(feature, False)

    @classmethod
    def get_level_name(cls, level: int) -> str:
        if level <= 2: return "Freshman"
        if level <= 5: return "Scholar"
        if level <= 8: return "Apprentice"
        if level <= 11: return "Adept"
        if level <= 14: return "Expert"
        if level <= 17: return "Master"
        if level <= 20: return "Elite"
        if level <= 25: return "Grandmaster"
        return "Wax Champion"

    @classmethod
    def get_price_for_tier(cls, tier: str, billing_period: str) -> int:
        prices = {
            ('scholar', 'monthly'): cls.SCHOLAR_MONTHLY,
            ('scholar', 'yearly'): cls.SCHOLAR_YEARLY,
            ('elite', 'monthly'): cls.ELITE_MONTHLY,
            ('elite', 'yearly'): cls.ELITE_YEARLY,
        }
        return prices.get((tier.lower(), billing_period.lower()), 0)


settings = Settings()

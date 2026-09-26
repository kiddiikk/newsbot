import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GRAMKIT_DATABASE_URL = os.getenv("GRAMKIT_DATABASE_URL", DATABASE_URL)
CHANNEL_ID = os.getenv("CHANNEL_ID")

RSS_CHECK_INTERVAL = 3600
MAX_CHANNELS_PER_USER = 5
MAX_RSS_PER_CHANNEL = 10
DEFAULT_POST_INTERVAL = 7200
MAX_QUEUE_SIZE = 50

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
DEFAULT_AI_MODEL = "openai/gpt-oss-120b"
AI_MODELS = GROQ_MODELS
SUBSCRIPTION_PRICES = {
    "start": {
        "price": 250,
        "channels": 1,
        "posts_per_day": 5,
        "interval_hours": 4,
        "models": ["openai/gpt-oss-20b"],
        "custom_prompt": False,
        "moderation": False,
        "team_size": 0,
        "analytics": False,
        "priority_support": False,
        "name": "🚀 Старт",
    },
    "pro": {
        "price": 500,
        "channels": 3,
        "posts_per_day": 20,
        "interval_hours": 2,
        "models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        "custom_prompt": True,
        "moderation": True,
        "team_size": 2,
        "analytics": False,
        "priority_support": False,
        "name": "💎 Про",
    },
    "business": {
        "price": 1000,
        "channels": 10,
        "posts_per_day": 100,
        "interval_hours": 1,
        "models": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        "custom_prompt": True,
        "moderation": True,
        "team_size": 5,
        "extra_seat_price": 200,
        "analytics": True,
        "priority_support": True,
        "name": "🏢 Бизнес",
    },
}
TRIAL_DAYS = 1

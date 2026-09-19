import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bot.db")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

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
        "posts_per_day": 10,
        "name": "🚀 Старт",
    },
    "pro": {
        "price": 500,
        "channels": 2,
        "posts_per_day": 30,
        "name": "💎 Про",
    },
    "business": {
        "price": 1000,
        "channels": 5,
        "posts_per_day": 100,
        "name": "🏢 Бизнес",
    },
}
TRIAL_DAYS = 1

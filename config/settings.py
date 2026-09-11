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
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "qwen/qwen3-32b",
    "mistral-saba-24b",
    "meta-llama/llama-4-scout-17b-16e-instruct"
]
DEFAULT_AI_MODEL = "llama-3.1-8b-instant"
AI_MODELS = GROQ_MODELS

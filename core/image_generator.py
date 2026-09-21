import os
import logging
from pollinations import Pollinations

logger = logging.getLogger(__name__)

client = Pollinations()


def generate_image(prompt: str) -> str:
    try:
        filepath = f"/tmp/generated_{os.urandom(4).hex()}.png"

        client.download_image(
            prompt=prompt,
            output_path=filepath,
            model="flux",
            width=1024,
            height=1024,
            nologo=True,
            enhance=False,   # ← ВАЖНО
        )

        if os.path.exists(filepath):
            size_kb = os.path.getsize(filepath) / 1024
            logger.info(f"Картинка сгенерирована: {filepath} ({size_kb:.0f} KB)")
            return filepath
        return None
    except Exception as e:
        logger.error(f"Ошибка генерации картинки: {e}", exc_info=True)
        return None

import os
import logging
from pollinations import Pollinations

logger = logging.getLogger(__name__)

client = Pollinations()

def generate_image(prompt: str) -> str:
    """
    Генерирует картинку через Pollinations (бесплатно, без ключей)
    Возвращает путь к локальному файлу или None
    """
    try:
        filepath = f"/tmp/generated_{os.urandom(4).hex()}.png"
        
        client.download_image(
            prompt=prompt,
            output_path=filepath,
            model="flux",
            width=1024,
            height=1024,
            nologo=True,
            enhance=True
        )
        
        if os.path.exists(filepath):
            logger.info(f"Картинка сгенерирована: {filepath}")
            return filepath
        return None
    except Exception as e:
        logger.error(f"Ошибка генерации картинки: {e}")
        return None

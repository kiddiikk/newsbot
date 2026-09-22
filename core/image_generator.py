import os
import logging
import urllib.parse
import requests

logger = logging.getLogger(__name__)


def generate_image(prompt: str) -> str:
    """
    Генерирует картинку через Pollinations напрямую (без библиотеки-обёртки).
    Возвращает путь к файлу или None.
    """
    try:
        encoded = urllib.parse.quote(prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1024&height=1024"
            f"&model=flux"
            f"&nologo=true"
            f"&enhance=false"
            f"&safe=false"
            f"&seed={os.urandom(3).hex()}"
        )
        logger.info(f"Pollinations request: {url[:150]}")

        filepath = f"/tmp/generated_{os.urandom(4).hex()}.png"
        resp = requests.get(url, timeout=90, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "unknown")
        logger.info(f"Content-Type: {content_type}")

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        size_kb = os.path.getsize(filepath) / 1024
        from PIL import Image
        with Image.open(filepath) as img:
            logger.info(
                f"Картинка: {filepath}, {size_kb:.0f} KB, "
                f"{img.size[0]}x{img.size[1]}, {img.format}"
            )
        return filepath
    except Exception as e:
        logger.error(f"Ошибка генерации картинки: {e}", exc_info=True)
        return None

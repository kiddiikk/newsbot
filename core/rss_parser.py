import feedparser
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import hashlib


class RSSParser:
    def __init__(self):
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def parse_feed(self, url: str, last_guid: Optional[str] = None) -> List[Dict]:
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                return []

            new_entries = []
            for entry in feed.entries[:10]:
                entry_id = entry.get('id', entry.get('link', ''))

                if last_guid and entry_id == last_guid:
                    break

                parsed_entry = self.parse_entry(entry)
                if parsed_entry:
                    new_entries.append(parsed_entry)

            return new_entries
        except Exception:
            return []

    def parse_entry(self, entry) -> Optional[Dict]:
        try:
            content = self.extract_content(entry)
            media = self.extract_media(entry)

            return {
                'guid': entry.get('id', entry.get('link', '')),
                'title': entry.get('title', 'No title'),
                'link': entry.get('link', ''),
                'content': content,
                'media': media,
                'published': entry.get('published_parsed', None),
                'author': entry.get('author', ''),
                'tags': [tag.term for tag in entry.get('tags', [])][:5]
            }
        except:
            return None

    def extract_content(self, entry) -> str:
        content = ''

        if 'content' in entry:
            content = entry.content[0].value
        elif 'summary' in entry:
            content = entry.summary
        elif 'description' in entry:
            content = entry.description

        soup = BeautifulSoup(content, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        text = ' '.join(text.split())
        return text[:2000]

    def extract_media(self, entry) -> List[str]:
        media_urls = []

        if 'enclosures' in entry:
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('image'):
                    media_urls.append(enclosure.href)

        if 'media_content' in entry:
            for media in entry.media_content:
                if media.get('type', '').startswith('image'):
                    media_urls.append(media['url'])

        if 'media_thumbnail' in entry:
            for thumb in entry.media_thumbnail:
                if thumb.get('url'):
                    media_urls.append(thumb['url'])

        if 'content' in entry and not media_urls:
            soup = BeautifulSoup(entry.content[0].value, 'html.parser')
            for img in soup.find_all('img')[:3]:
                src = img.get('src')
                if src and src.startswith('http'):
                    media_urls.append(src)

        # 👇 ФИКС: чиним URL превью от Reddit и Twitter
        fixed_urls = [self._fix_media_url(url) for url in media_urls]

        return list(dict.fromkeys(fixed_urls))[:1]

    @staticmethod
    def _fix_media_url(url: str) -> str:
        """
        preview.redd.it → i.redd.it (оригинал вместо превью).
        Убираем query-параметры сжатия.
        """
        # Reddit: preview.redd.it → i.redd.it
        if "preview.redd.it" in url:
            url = url.replace("preview.redd.it", "i.redd.it")
            if "?" in url:
                url = url.split("?")[0]

        # Twitter/X: pbs.twimg.com → оригинал
        if "pbs.twimg.com" in url:
            if "&name=" in url:
                url = url.split("&name=")[0] + "&name=orig"
            elif "?" in url:
                url = url + "&name=orig"

        # Убираем мелкие размеры
        for param in ["?w=150", "?w=300", "&w=150", "&w=300"]:
            if param in url:
                url = url.replace(param, "")

        return url

    async def download_image(self, url: str) -> Optional[bytes]:
        if not self.session:
            self.session = aiohttp.ClientSession()

        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    content = await response.read()
                    if len(content) < 5000000:
                        return content
        except:
            pass
        return None

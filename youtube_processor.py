import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)


def extract_video_id(url_or_id: str) -> str | None:
    """Извлечь ID видео из полной или короткой ссылки YouTube."""
    if len(url_or_id) == 11 and re.match(r"^[\w-]{11}$", url_or_id):
        return url_or_id

    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"(?:youtu\.be\/)([0-9A-Za-z_-]{11})",
        r"(?:embed\/)([0-9A-Za-z_-]{11})",
        r"(?:shorts\/)([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return None


def get_video_transcript(video_id: str, languages: list[str] = None) -> tuple[str, list[dict]] | None:
    """
    Получить текст субтитров видео.
    Возвращает кортеж: (полный_текст_с_таймкодами, список_сегментов)
    """
    if languages is None:
        languages = ["uk", "ru", "en"]

    try:
        transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        formatted_lines = []
        for segment in transcript_data:
            start_sec = int(segment.get("start", 0))
            minutes = start_sec // 60
            seconds = start_sec % 60
            timestamp = f"[{minutes:02d}:{seconds:02d}]"
            text = segment.get("text", "").strip()
            if text:
                formatted_lines.append(f"{timestamp} {text}")

        full_text = "\n".join(formatted_lines)
        return full_text, transcript_data
    except Exception as e:
        logger.warning(f"Не вдалося отримати субтитри для відео {video_id}: {e}")
        return None


def fetch_latest_channel_videos(channel_id: str, max_results: int = 5) -> list[dict]:
    """
    Получить список последних видео с канала через бесплатный RSS-фид (0 квот API).
    """
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()

        root = ET.fromstring(xml_data)
        namespace = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

        videos = []
        entries = root.findall("atom:entry", namespace)
        for entry in entries[:max_results]:
            video_id_elem = entry.find("yt:videoId", namespace)
            title_elem = entry.find("atom:title", namespace)
            published_elem = entry.find("atom:published", namespace)

            if video_id_elem is not None and title_elem is not None:
                videos.append({
                    "video_id": video_id_elem.text,
                    "title": title_elem.text,
                    "published_at": published_elem.text if published_elem is not None else None,
                    "url": f"https://www.youtube.com/watch?v={video_id_elem.text}"
                })

        return videos
    except Exception as e:
        logger.error(f"Помилка при читанні RSS каналу {channel_id}: {e}")
        return []

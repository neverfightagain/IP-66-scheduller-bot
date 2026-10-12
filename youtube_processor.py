import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from youtube_transcript_api import YouTubeTranscriptApi
try:
    from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
except ImportError:
    GenericProxyConfig = None
    WebshareProxyConfig = None

logger = logging.getLogger(__name__)


def get_proxy_config():
    """
    Отримати конфігурацію проксі для YouTubeTranscriptApi.
    Підтримує:
    1. Webshare (WEBSHARE_USERNAME, WEBSHARE_PASSWORD)
    2. Будь-який проксі через YOUTUBE_PROXY, HTTPS_PROXY, HTTP_PROXY
    """
    webshare_user = os.getenv("WEBSHARE_USERNAME", "").strip()
    webshare_pass = os.getenv("WEBSHARE_PASSWORD", "").strip()
    if webshare_user and webshare_pass and WebshareProxyConfig:
        return WebshareProxyConfig(proxy_username=webshare_user, proxy_password=webshare_pass)

    proxy_url = os.getenv("YOUTUBE_PROXY", "").strip() or os.getenv("HTTPS_PROXY", "").strip() or os.getenv("HTTP_PROXY", "").strip()
    if proxy_url and GenericProxyConfig:
        return GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)

    return None


def get_proxies_dict() -> dict | None:
    """Для сумісності зі старими версіями YouTubeTranscriptApi."""
    webshare_user = os.getenv("WEBSHARE_USERNAME", "").strip()
    webshare_pass = os.getenv("WEBSHARE_PASSWORD", "").strip()
    if webshare_user and webshare_pass:
        url = f"http://{webshare_user}-rotate:{webshare_pass}@p.webshare.io:80/"
        return {"http": url, "https": url}

    proxy_url = os.getenv("YOUTUBE_PROXY", "").strip() or os.getenv("HTTPS_PROXY", "").strip() or os.getenv("HTTP_PROXY", "").strip()
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None


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

    proxy_cfg = get_proxy_config()
    if proxy_cfg:
        logger.info(f"Завантаження субтитрів для {video_id} з використанням проксі ({type(proxy_cfg).__name__})...")

    try:
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            proxies_dict = get_proxies_dict()
            kwargs = {"languages": languages}
            if proxies_dict:
                kwargs["proxies"] = proxies_dict
            transcript_data = YouTubeTranscriptApi.get_transcript(video_id, **kwargs)
        else:
            api = YouTubeTranscriptApi(proxy_config=proxy_cfg) if proxy_cfg else YouTubeTranscriptApi()
            transcript_data = api.fetch(video_id, languages=languages)

        formatted_lines = []
        raw_segments = []
        for segment in transcript_data:
            start_sec = int(segment.start if hasattr(segment, "start") else segment.get("start", 0))
            text = (segment.text if hasattr(segment, "text") else segment.get("text", "")).strip()
            duration = segment.duration if hasattr(segment, "duration") else segment.get("duration", 0)

            minutes = start_sec // 60
            seconds = start_sec % 60
            timestamp = f"[{minutes:02d}:{seconds:02d}]"
            if text:
                formatted_lines.append(f"{timestamp} {text}")
                raw_segments.append({"start": start_sec, "duration": duration, "text": text})

        full_text = "\n".join(formatted_lines)
        return full_text, raw_segments
    except Exception as e:
        err_msg = str(e)
        if "blocking requests from your IP" in err_msg and not proxy_cfg:
            logger.warning(
                f"YouTube блокує запити субтитрів з IP цього сервера для відео {video_id}. "
                "Щоб обійти блокування, додайте YOUTUBE_PROXY або WEBSHARE_USERNAME/WEBSHARE_PASSWORD у змінні середовища."
            )
        else:
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


def resolve_channel_id(url_or_handle: str) -> str | None:
    """Определить UC-идентификатор канала по ссылке, @handle или прямому ID."""
    clean = url_or_handle.strip()
    if clean.startswith("UC") and len(clean) == 24:
        return clean

    if not clean.startswith("http"):
        if clean.startswith("@"):
            clean = f"https://www.youtube.com/{clean}"
        else:
            clean = f"https://www.youtube.com/@{clean}"

    try:
        req = urllib.request.Request(clean, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        match = re.search(r'"channelId":"(UC[\w-]{22})"', html)
        if match:
            return match.group(1)
        match_meta = re.search(r'<meta itemprop="identifier" content="(UC[\w-]{22})"', html)
        if match_meta:
            return match_meta.group(1)
    except Exception as e:
        logger.warning(f"Не вдалося визначити channel_id для {url_or_handle}: {e}")
    return None


async def process_video_and_notify(bot, video: dict) -> bool:
    """
    Обробити нове відео з YouTube та розіслати конспект.
    Стратегія 3-рівнева:
    1. Прямий мультимодальний аналіз Gemini через YouTube URL (без блокування IP і без потреби в проксі)
    2. Якщо прямий аналіз недоступний, пробуємо отримати субтитри через youtube-transcript-api (з підтримкою проксі)
    3. Якщо AI-аналіз не вдався, все одно надсилаємо студентам сповіщення з посиланням на нову пару!
    """
    from database import is_video_processed, save_video_summary, add_announcement_db, get_subscribed_chats_db
    from llm_agent import analyze_lecture_video, analyze_lecture_transcript
    from formatters import format_lecture_summary, clean_markdown

    video_id = video["video_id"]
    video_url = video.get("url", f"https://www.youtube.com/watch?v={video_id}")
    video_title = video.get("title", "Лекція")

    if await is_video_processed(video_id):
        return False

    summary = None

    # Рівень 1: Прямий мультимодальний аналіз Gemini через YouTube URL
    try:
        summary = await analyze_lecture_video(video_url, video_title=video_title)
        if summary:
            logger.info(f"Отримано прямий мультимодальний аналіз Gemini для {video_id}")
    except Exception as e_direct:
        logger.warning(f"Прямий аналіз Gemini не вдався для {video_id}: {e_direct}")

    # Рівень 2: Резервний аналіз через субтитри (якщо є проксі або YouTube не заблокував IP)
    if not summary:
        transcript_info = get_video_transcript(video_id)
        if transcript_info:
            transcript_text, _ = transcript_info
            summary = await analyze_lecture_transcript(transcript_text, video_title=video_title)

    # Рівень 3: Якщо AI-аналіз не вдався, все одно сповіщаємо студентів про нову лекцію
    if not summary:
        logger.warning(f"AI-конспект недоступний для {video_id}. Відправляємо базове сповіщення про запис пари.")
        topic = video_title
        course_name = "Запис пари"
        await save_video_summary(
            video_id=video_id,
            title=topic,
            course_id=course_name,
            published_at=video.get("published_at"),
            summary={"topic": topic, "summary_points": ["Відео опубліковано на каналі групи."]}
        )
        chats = await get_subscribed_chats_db()
        if chats:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Дивитися на YouTube", url=video_url)]])
            full_msg = f"🎬 **Новий запис пари на YouTube!**\n\n📌 **{clean_markdown(topic)}**\n\n🔗 [Переглянути відео]({video_url})"
            for target in chats:
                cid = target["chat_id"]
                tid = target.get("thread_id")
                try:
                    await bot.send_message(cid, full_msg, parse_mode="Markdown", reply_markup=kb, message_thread_id=tid)
                except Exception:
                    try:
                        plain_msg = f"🎬 Новий запис пари на YouTube!\n\n📌 {topic}\n\n🔗 {video_url}"
                        await bot.send_message(cid, plain_msg, reply_markup=kb, message_thread_id=tid)
                    except Exception as e_send:
                        logger.error(f"Не вдалося надіслати базове сповіщення в чат {cid}: {e_send}")
        return True

    # Якщо конспект успішно створено:
    course_name = summary.get("subject_detected")
    topic = summary.get("topic", video_title)
    await save_video_summary(
        video_id=video_id,
        title=topic,
        course_id=course_name,
        published_at=video.get("published_at"),
        summary=summary
    )

    for ann in summary.get("teacher_announcements", []):
        if ann.strip():
            await add_announcement_db(course_id=course_name, source="youtube", text=ann.strip())

    for dl in summary.get("deadlines_mentioned", []):
        task_title = dl.get("task_title", "Завдання")
        d_date = dl.get("date", "")
        quote = dl.get("exact_quote", "")
        text = f"{task_title}: {d_date} ({quote})" if quote else f"{task_title}: {d_date}"
        await add_announcement_db(course_id=course_name, source="youtube", text=text, detected_date=d_date)

    chats = await get_subscribed_chats_db()
    if chats:
        text, kb = format_lecture_summary(
            summary=summary,
            video_title=topic,
            video_url=video_url
        )
        for target in chats:
            cid = target["chat_id"]
            tid = target.get("thread_id")
            full_msg = f"🎬 **Новий запис пари на YouTube!**\n\n{text}"
            try:
                await bot.send_message(cid, full_msg, parse_mode="Markdown", reply_markup=kb, message_thread_id=tid)
            except Exception as e:
                logger.warning(f"Markdown send failed for YouTube video in chat {cid} (thread {tid}): {e}. Retrying plain text.")
                try:
                    plain_msg = full_msg.replace("**", "").replace("*", "").replace("`", "").replace("_", "")
                    await bot.send_message(cid, plain_msg, reply_markup=kb, message_thread_id=tid)
                except Exception as e2:
                    logger.error(f"Не вдалося надіслати конспект у чат {cid}: {e2}")

    logger.info(f"Успішно оброблено нове відео {video_id}: {topic}")
    return True

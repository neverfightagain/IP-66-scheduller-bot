import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse
from config import LINKS_FILE

logger = logging.getLogger(__name__)

ALLOWED_LINK_DOMAINS = {
    "zoom.us",
    "meet.google.com",
    "teams.microsoft.com",
}


def is_valid_pair_link(url: str) -> bool:
    """Перевіряє, що посилання має протокол HTTPS та належить до списку дозволених доменів (Zoom, Google Meet, MS Teams)."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() != "https":
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if host in ALLOWED_LINK_DOMAINS:
            return True
        if host.endswith(".zoom.us") or host.endswith(".teams.microsoft.com"):
            return True
        return False
    except Exception:
        return False


def load_links() -> dict:
    """
    Завантажити словник посилань на дистанційні заняття:
    1. Читає з захищеної змінної оточення LINKS_JSON (на Render).
    2. Доповнює/перекриває локальним файлом links.json (якщо створено на диску).
    """
    data = {}

    # 1. Секретна змінна з оточення Render
    env_json = os.getenv("LINKS_JSON", "").strip()
    if env_json:
        try:
            parsed = json.loads(env_json)
            if isinstance(parsed, dict):
                data.update(parsed)
        except Exception as e:
            logger.error(f"Помилка парсингу LINKS_JSON з оточення: {e}")

    # 2. Локальний файл links.json (в .gitignore)
    if LINKS_FILE.exists():
        try:
            with open(LINKS_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)
                if isinstance(local_data, dict):
                    data.update(local_data)
        except Exception as e:
            logger.warning(f"Помилка при читанні links.json: {e}")

    return data


def save_links(links_data: dict) -> bool:
    """Зберегти словник посилань у локальний links.json."""
    try:
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(links_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Помилка при записі links.json: {e}")
        return False


def set_course_link(key: str, url: str, comment: str = "", lecturer: str = "") -> bool:
    """Додати або оновити посилання для предмету."""
    if not is_valid_pair_link(url):
        logger.warning(f"Відхилено збереження посилання на заборонений/не-whitelist домен: {url}")
        return False

    links = load_links()

    subject = key.split("(")[0].strip()
    l_type = ""
    if "(" in key and ")" in key:
        l_type = key.split("(")[1].split(")")[0].strip()

    prev = links.get(key, {})
    links[key] = {
        "subject": subject,
        "type": l_type or prev.get("type", ""),
        "lecturer": lecturer or prev.get("lecturer", ""),
        "url": url.strip(),
        "comment": comment.strip() or prev.get("comment", "")
    }
    return save_links(links)


def delete_course_link(key: str) -> bool:
    """Видалити посилання за назвою предмета."""
    links = load_links()
    norm_key = key.strip().lower()
    found_key = None
    for k in links:
        if k.strip().lower() == norm_key or norm_key in k.strip().lower():
            found_key = k
            break
    if found_key:
        del links[found_key]
        return save_links(links)
    return False


def get_lesson_link_info(name: str, lesson_type: str) -> dict:
    """
    Знайти посилання та примітку для пари.
    Пріоритет:
    1. Точний збіг 'Предмет (Тип)'
    2. Прямий збіг назви та типу заняття
    3. Нестрогий пошук за входженням назви з тим же типом
    4. Fallback: збіг лише за назвою
    """
    if not name or not str(name).strip():
        return {"url": "", "comment": ""}

    links = load_links()
    lesson_type = lesson_type or ""

    # 1. Точний збіг ключа: "Назва (Тип)"
    key_with_type = f"{name} ({lesson_type})"
    if key_with_type in links:
        item = links[key_with_type]
        if item.get("url") or item.get("comment"):
            return item

    # 2. Пошук за прямим збігом назви та типу
    norm_name = name.strip().lower()
    norm_type = lesson_type.strip().lower()

    for key, item in links.items():
        item_sub = item.get("subject", "").strip().lower()
        item_type = item.get("type", "").strip().lower()
        if item_sub == norm_name and item_type == norm_type:
            if item.get("url") or item.get("comment"):
                return item

    # 3. Нестрогий пошук за входженням назви З ТИМ ЖЕ ТИПОМ
    for key, item in links.items():
        item_sub = item.get("subject", "").strip().lower()
        item_type = item.get("type", "").strip().lower()
        if item_type == norm_type and (item_sub in norm_name or norm_name in item_sub):
            if item.get("url") or item.get("comment"):
                return item

    # 4. Fallback: збіг за назвою незалежно від типу
    for key, item in links.items():
        item_sub = item.get("subject", "").strip().lower()
        if item_sub and (item_sub in norm_name or norm_name in item_sub):
            if item.get("url"):
                return item

    return {"url": "", "comment": ""}

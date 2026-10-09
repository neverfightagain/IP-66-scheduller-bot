import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
KPI_GROUP_ID = int(os.getenv("KPI_GROUP_ID", "6084"))
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Kyiv")
KYIV_TZ = ZoneInfo(TIMEZONE_NAME)

MORNING_DIGEST_TIME = os.getenv("MORNING_DIGEST_TIME", "08:00")
NOTIFY_MINUTES_BEFORE = int(os.getenv("NOTIFY_MINUTES_BEFORE", "5"))

# Файлы данных
CHATS_FILE = BASE_DIR / "chats.json"
LINKS_FILE = BASE_DIR / "links.json"


def get_subscribed_chats() -> list[int]:
    """Получить список chat_id, подписанных на уведомления."""
    if not CHATS_FILE.exists():
        return []
    try:
        with open(CHATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("chats", [])
    except Exception:
        return []


def add_subscribed_chat(chat_id: int) -> bool:
    """Добавить чат в список рассылки."""
    chats = set(get_subscribed_chats())
    if chat_id not in chats:
        chats.add(chat_id)
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump({"chats": list(chats)}, f, indent=2)
        return True
    return False


def remove_subscribed_chat(chat_id: int) -> bool:
    """Удалить чат из списка рассылки."""
    chats = set(get_subscribed_chats())
    if chat_id in chats:
        chats.remove(chat_id)
        with open(CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump({"chats": list(chats)}, f, indent=2)
        return True
    return False

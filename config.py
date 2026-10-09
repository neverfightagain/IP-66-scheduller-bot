import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Загружаем переменные из .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

raw_token = os.getenv("BOT_TOKEN", "").strip()

# Санитизация токена (на случай если скопировали с кавычками или "BOT_TOKEN=")
if (raw_token.startswith('"') and raw_token.endswith('"')) or (raw_token.startswith("'") and raw_token.endswith("'")):
    raw_token = raw_token[1:-1].strip()
if "BOT_TOKEN=" in raw_token:
    raw_token = raw_token.split("BOT_TOKEN=", 1)[1].strip()

# Извлекаем сам токен регуляркой: число:35_символов
match = re.search(r"\d+:[\w-]{35}", raw_token)
if match:
    BOT_TOKEN = match.group(0)
else:
    BOT_TOKEN = raw_token

KPI_GROUP_ID = int(os.getenv("KPI_GROUP_ID", "6084"))
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Kyiv")
KYIV_TZ = ZoneInfo(TIMEZONE_NAME)

MORNING_DIGEST_TIME = os.getenv("MORNING_DIGEST_TIME", "08:00")
NOTIFY_MINUTES_BEFORE = int(os.getenv("NOTIFY_MINUTES_BEFORE", "5"))

# Файлы данных
CHATS_FILE = BASE_DIR / "chats.json"
LINKS_FILE = BASE_DIR / "links.json"


ENV_CHAT_ID = os.getenv("CHAT_ID", "").strip()


def get_subscribed_chats() -> list[int]:
    """Получить список chat_id, подписанных на уведомления."""
    chats = set()
    if ENV_CHAT_ID:
        try:
            chats.add(int(ENV_CHAT_ID))
        except ValueError:
            pass

    if CHATS_FILE.exists():
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for cid in data.get("chats", []):
                    chats.add(int(cid))
        except Exception:
            pass

    return list(chats)


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

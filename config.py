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

OWNER_ID = int(os.getenv("OWNER_ID", "8735281894"))
OWNER_USERNAMES = {"neverfightaga1n", "sinch"}

MORNING_DIGEST_TIME = os.getenv("MORNING_DIGEST_TIME", "08:00")
NOTIFY_MINUTES_BEFORE = int(os.getenv("NOTIFY_MINUTES_BEFORE", "5"))

# YouTube & AI Config
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "UC8pccc2zKBP6vrOlA1hWFBw").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_API_KEYS = os.getenv("GEMINI_API_KEYS", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
YOUTUBE_PROXY = os.getenv("YOUTUBE_PROXY", "").strip()
WEBSHARE_USERNAME = os.getenv("WEBSHARE_USERNAME", "").strip()
WEBSHARE_PASSWORD = os.getenv("WEBSHARE_PASSWORD", "").strip()

# Cloud SQLite Config (Turso or SQLite Cloud)
def _sanitize_env(val: str, key_prefix: str = "") -> str:
    val = (val or "").strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1].strip()
    if key_prefix and f"{key_prefix}=" in val:
        val = val.split(f"{key_prefix}=", 1)[1].strip().strip('"').strip("'")
    return val

raw_roster = os.getenv("STUDENTS_ROSTER_JSON", "").strip()
STUDENTS_ROSTER_JSON = _sanitize_env(raw_roster, "STUDENTS_ROSTER_JSON")

raw_turso_url = os.getenv("TURSO_DATABASE_URL") or os.getenv("TURSO_URL") or ""
TURSO_DATABASE_URL = _sanitize_env(raw_turso_url, "TURSO_DATABASE_URL")

raw_turso_token = (
    os.getenv("TURSO_AUTH_TOKEN")
    or os.getenv("TURSO_TOKEN")
    or os.getenv("TURSO_DATABASE_TOKEN")
    or os.getenv("TURSO_KEY")
    or ""
)
TURSO_AUTH_TOKEN = _sanitize_env(raw_turso_token, "TURSO_AUTH_TOKEN")

SQLITE_CLOUD_URL = _sanitize_env(os.getenv("SQLITE_CLOUD_URL") or os.getenv("SQLITECLOUD_URL") or "", "SQLITE_CLOUD_URL")

# Файлы данных
CHATS_FILE = BASE_DIR / "chats.json"
LINKS_FILE = BASE_DIR / "links.json"


ENV_CHAT_ID = os.getenv("CHAT_ID", "").strip()
ENV_THREAD_ID = os.getenv("THREAD_ID", "").strip()


def get_subscribed_chats() -> list[dict]:
    """
    Отримати список цільових чатів та топіків:
    [{'chat_id': int, 'thread_id': int | None}]
    """
    targets = []
    seen = set()

    if ENV_CHAT_ID:
        try:
            cid = int(ENV_CHAT_ID)
            tid = int(ENV_THREAD_ID) if ENV_THREAD_ID else None
            key = (cid, tid)
            if key not in seen:
                seen.add(key)
                targets.append({"chat_id": cid, "thread_id": tid})
        except ValueError:
            pass

    if CHATS_FILE.exists():
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("chats", []):
                    if isinstance(item, int):
                        cid, tid = item, None
                    elif isinstance(item, dict):
                        cid = int(item["chat_id"])
                        tid = int(item["thread_id"]) if item.get("thread_id") is not None else None
                    else:
                        continue
                    key = (cid, tid)
                    if key not in seen:
                        seen.add(key)
                        targets.append({"chat_id": cid, "thread_id": tid})
        except Exception:
            pass

    return targets


def add_subscribed_chat(chat_id: int, thread_id: int | None = None) -> bool:
    """Додати або перемкнути чат/топік у списку розсилки chats.json."""
    targets = get_subscribed_chats()

    # Якщо це група, вимикаємо старі топіки цієї групи, щоб не спамити в різні гілки
    if chat_id < 0:
        targets = [t for t in targets if t["chat_id"] != chat_id]

    key = (chat_id, thread_id)
    seen = {(t["chat_id"], t.get("thread_id")) for t in targets}
    if key not in seen:
        targets.append({"chat_id": chat_id, "thread_id": thread_id})
        try:
            with open(CHATS_FILE, "w", encoding="utf-8") as f:
                json.dump({"chats": targets}, f, indent=2)
            return True
        except Exception:
            pass
    return False


def remove_subscribed_chat(chat_id: int, thread_id: int | None = None) -> bool:
    """Видалити чат або конкретний топік зі списку розсилки chats.json."""
    targets = get_subscribed_chats()
    if thread_id is not None:
        new_targets = [t for t in targets if not (t["chat_id"] == chat_id and t.get("thread_id") == thread_id)]
    else:
        new_targets = [t for t in targets if t["chat_id"] != chat_id]

    if len(new_targets) != len(targets):
        try:
            with open(CHATS_FILE, "w", encoding="utf-8") as f:
                json.dump({"chats": new_targets}, f, indent=2)
            return True
        except Exception:
            pass
    return False


# Telegram Bot Username & Mini App (TMA) URL
BOT_USERNAME = os.getenv("BOT_USERNAME", "kpi_shedule_ip_66_bot").strip().lstrip("@")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ip-66-scheduller-bot.onrender.com").strip().rstrip("/")


import datetime
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import BASE_DIR, KYIV_TZ
from database import add_assignment_db, get_active_assignments_db, get_subscribed_chats_db, add_announcement_db

logger = logging.getLogger(__name__)

# Области доступа для Google Classroom (чтение курсов, заданий и объявлений)
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
]

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"


def get_classroom_credentials() -> Credentials | None:
    """Получить или обновить валидные учетные данные OAuth 2.0."""
    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            logger.warning(f"Не вдалося завантажити token.json: {e}")

    # Если токен просрочен, но есть refresh_token — обновляем в фоне
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            logger.info("Успішно оновлено токен Google Classroom.")
        except Exception as e:
            logger.error(f"Помилка оновлення токена Google Classroom: {e}")
            creds = None

    return creds


def run_auth_flow() -> bool:
    """Запустить браузерную авторизацию один раз для создания token.json."""
    if not CREDENTIALS_FILE.exists():
        print(f"❌ Файл {CREDENTIALS_FILE} не знайдено! Будь ласка, завантажте credentials.json з Google Cloud Console.")
        return False

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"✅ Успішно авторизовано! Файл {TOKEN_FILE} створено.")
        return True
    except Exception as e:
        print(f"❌ Помилка під час авторизації: {e}")
        return False


async def sync_classroom_tasks(bot = None) -> list[dict]:
    """Синхронизировать активные задания из всех курсов Classroom в SQLite."""
    creds = get_classroom_credentials()
    if not creds or not creds.valid:
        logger.debug("Google Classroom не підключено або token.json недійсний.")
        return []

    new_items = []
    try:
        service = build("classroom", "v1", credentials=creds, cache_discovery=False)
        courses_resp = service.courses().list(courseStates=["ACTIVE"]).execute()
        courses = courses_resp.get("courses", [])

        # Получаем уже сохраненные ID заданий из БД
        existing_assignments = await get_active_assignments_db()
        existing_ids = {a["id"] for a in existing_assignments}

        for course in courses:
            cid = course["id"]
            cname = course.get("name", "Невідомий курс")

            # 1. Загружаем задания (courseWork)
            cw_resp = service.courses().courseWork().list(courseId=cid).execute()
            course_works = cw_resp.get("courseWork", [])

            for cw in course_works:
                cw_id = f"gc_{cw['id']}"
                title = cw.get("title", "Без назви")
                desc = cw.get("description", "").strip()
                alt_link = cw.get("alternateLink", "")

                due_date_str = ""
                due_date_obj = cw.get("dueDate")
                due_time_obj = cw.get("dueTime")

                if due_date_obj:
                    year = due_date_obj.get("year")
                    month = due_date_obj.get("month")
                    day = due_date_obj.get("day")
                    hour = due_time_obj.get("hours", 23) if due_time_obj else 23
                    minute = due_time_obj.get("minutes", 59) if due_time_obj else 59

                    # Переводим UTC дедлайн в киевское время
                    due_dt_utc = datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone.utc)
                    due_dt_kyiv = due_dt_utc.astimezone(KYIV_TZ)
                    due_date_str = due_dt_kyiv.strftime("%Y-%m-%d %H:%M")
                else:
                    due_date_str = "Без дедлайну"

                # Если задания еще нет в базе — добавляем и пушим уведомление!
                if cw_id not in existing_ids:
                    await add_assignment_db(
                        assignment_id=cw_id,
                        course_name=cname,
                        title=title,
                        due_date=due_date_str,
                        description=desc[:150]
                    )
                    new_items.append({
                        "course": cname,
                        "title": title,
                        "due": due_date_str,
                        "link": alt_link,
                        "desc": desc
                    })
                    logger.info(f"Знайдено нове завдання в Classroom: {cname} — {title} (до {due_date_str})")

                    # Миттєвий пуш у чати
                    if bot:
                        chats = await get_subscribed_chats_db()
                        text = (
                            f"📌 **Нове завдання в Google Classroom!**\n\n"
                            f"📚 **Дисципліна:** {cname}\n"
                            f"📝 **Завдання:** {title}\n"
                            f"⏳ **Дедлайн:** `{due_date_str}`\n"
                        )
                        if desc:
                            text += f"\n📖 _{desc[:200]}_\n"
                        if alt_link:
                            text += f"\n🔗 [Відкрити в Google Classroom]({alt_link})"

                        for chat_id in chats:
                            try:
                                await bot.send_message(chat_id, text, parse_mode="Markdown")
                            except Exception as e:
                                logger.error(f"Не вдалося надіслати сповіщення Classroom у чат {chat_id}: {e}")

        return new_items
    except Exception as e:
        logger.error(f"Помилка синхронізації Google Classroom: {e}")
        return []

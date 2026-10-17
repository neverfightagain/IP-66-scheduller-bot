import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import BASE_DIR, KYIV_TZ
from database import (
    add_assignment_db,
    get_active_assignments_db,
    get_subscribed_chats_db,
    add_announcement_db,
    update_assignment_ai_summary_db,
)
import html
import re
from formatters import clean_markdown, format_latex_to_unicode, clean_course_name
from llm_agent import summarize_assignment_requirements

logger = logging.getLogger(__name__)

# Блокування для запобігання паралельним синхронізаціям
_sync_lock = asyncio.Lock()

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
    raw_env = os.getenv("GOOGLE_TOKEN_JSON", "").strip()

    # 1. Если передана переменная GOOGLE_TOKEN_JSON (на Render / облаке)
    if raw_env:
        # Убираем внешние кавычки, если пользователь случайно вставил '{"token":...}'
        if (raw_env.startswith("'") and raw_env.endswith("'")) or (raw_env.startswith('"') and raw_env.endswith('"')):
            raw_env = raw_env[1:-1].strip()
        try:
            token_data = json.loads(raw_env)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            logger.info("Успішно завантажено Google Credentials напряму з GOOGLE_TOKEN_JSON.")
        except Exception as e:
            logger.error(f"Помилка парсингу GOOGLE_TOKEN_JSON з env: {e}")

    # 2. Если из env не получилось, пробуем локальный файл token.json
    if not creds and TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
            logger.info("Успішно завантажено Google Credentials з файлу token.json.")
        except Exception as e:
            logger.error(f"Не вдалося завантажити token.json: {e}")

    # 3. Обновляем токен, если он просрочен или еще не валидирован
    if creds and (not creds.valid or creds.expired) and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Успішно оновлено токен Google Classroom через refresh_token.")
            try:
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Помилка оновлення токена Google Classroom: {e}")
            creds = None

    if not creds:
        logger.warning("Google Classroom Credentials не знайдено (ні в GOOGLE_TOKEN_JSON, ні в token.json).")

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


async def sync_classroom_tasks(bot=None, delete_demo_on_success: bool = True) -> dict:
    """
    Синхронизировать активные задания из всех курсов Classroom в SQLite.
    Возвращает статус выполнения и диагностику.
    """
    if _sync_lock.locked():
        logger.info("Синхронізація Classroom вже виконується, пропускаємо паралельний запит.")
        return {"success": True, "courses_count": 0, "new_items": [], "error": None, "already_running": True}

    async with _sync_lock:
        creds = get_classroom_credentials()
        if not creds or not creds.valid:
            err_msg = "Google Classroom не підключено або токен недійсний (перевірте GOOGLE_TOKEN_JSON на Render)."
            logger.warning(err_msg)
            return {"success": False, "courses_count": 0, "new_items": [], "error": err_msg}

    new_items = []
    try:
        service = build("classroom", "v1", credentials=creds, cache_discovery=False)
        courses_resp = service.courses().list(courseStates=["ACTIVE"]).execute()
        courses = courses_resp.get("courses", [])

        now = datetime.datetime.now(KYIV_TZ)
        start_of_current_week = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        # Отримуємо вже збережені завдання
        existing_assignments = await get_active_assignments_db()
        existing_ids = {a["id"] for a in existing_assignments}

        # Якщо в базі ще не було завдань Classroom — це первинне завантаження, спамити в чат суворо заборонено!
        is_initial_import = not any(a["id"].startswith("gc_") for a in existing_assignments)

        for course in courses:
            cid = course["id"]
            cname = course.get("name", "Невідомий курс")

            # 1. Загружаем задания (courseWork) с защитой от сбоя отдельного курса
            try:
                cw_resp = service.courses().courseWork().list(courseId=cid).execute()
                course_works = cw_resp.get("courseWork", [])
            except Exception as e:
                logger.warning(f"Не вдалося завантажити завдання для курсу {cname}: {e}")
                course_works = []

            for cw in course_works:
                cw_id = f"gc_{cw['id']}"
                title = cw.get("title", "Без назви")
                desc = cw.get("description", "").strip()
                alt_link = cw.get("alternateLink", "")

                # Дата створення завдання в Classroom
                creation_time_str = cw.get("creationTime")
                creation_dt = None
                if creation_time_str:
                    try:
                        creation_dt = datetime.datetime.fromisoformat(creation_time_str.replace("Z", "+00:00")).astimezone(KYIV_TZ)
                    except Exception:
                        pass

                due_date_str = ""
                due_date_obj = cw.get("dueDate")
                due_time_obj = cw.get("dueTime")
                due_dt_kyiv = None

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

                # Завдання, дедлайн яких минув до поточного тижня, архівуємо одразу
                status = "active"
                if due_dt_kyiv and due_dt_kyiv < start_of_current_week:
                    status = "archived"

                # Якщо завдання ще немає в базі — додаємо
                if cw_id not in existing_ids:
                    ai_sum = ""
                    if desc and desc.strip():
                        try:
                            ai_sum = await summarize_assignment_requirements(
                                title=title,
                                description=desc,
                                course_name=clean_course_name(cname)
                            )
                        except Exception as e_sum:
                            logger.warning(f"Не вдалося згенерувати AI-вижимку для '{title}': {e_sum}")

                    await add_assignment_db(
                        assignment_id=cw_id,
                        course_name=cname,
                        title=title,
                        due_date=due_date_str,
                        description=desc,
                        ai_summary=ai_sum,
                        status=status
                    )

                    # УМОВИ ДЛЯ СПОВІЩЕННЯ У ЧАТ:
                    # 1. Ніколи не спамити під час первинного імпорту бази!
                    # 2. Не надсилати старі завдання (створені ДО поточного тижня).
                    # 3. Не надсилати завдання з минулими дедлайнами (до поточного тижня).
                    should_push = False
                    if not is_initial_import:
                        is_created_this_week = creation_dt and (creation_dt >= start_of_current_week)
                        deadline_valid = (due_dt_kyiv is None) or (due_dt_kyiv >= start_of_current_week)
                        if is_created_this_week and deadline_valid:
                            should_push = True

                    if should_push:
                        new_items.append({
                            "course": cname,
                            "title": title,
                            "due": due_date_str,
                            "link": alt_link,
                            "desc": desc,
                            "ai_summary": ai_sum
                        })
                        logger.info(f"Знайдено нове актуальне завдання Classroom: {cname} — {title} (до {due_date_str})")

                        # Миттєвий пуш у чати
                        if bot:
                            chats = await get_subscribed_chats_db()
                            clean_c = html.escape(clean_course_name(cname))
                            clean_t = html.escape(title)
                            due_esc = html.escape(due_date_str)
                            text = (
                                f"📌 <b>Нове завдання в Google Classroom!</b>\n\n"
                                f"📚 <b>Дисципліна:</b> <b>{clean_c}</b>\n"
                                f"📝 <b>Завдання:</b> {clean_t}\n"
                                f"⏳ <b>Дедлайн:</b> <code>{due_esc}</code>"
                            )
                            summary_to_show = ai_sum if (ai_sum and ai_sum.strip()) else desc.strip()
                            if summary_to_show:
                                clean_desc = format_latex_to_unicode(summary_to_show)
                                if len(clean_desc) > 350:
                                    clean_desc = clean_desc[:340].rstrip() + "..."
                                text += f"<blockquote expandable>📝 <b>Суть:</b> {clean_desc}</blockquote>\n"
                            if alt_link:
                                text += f'\n🔗 <a href="{html.escape(alt_link)}">Відкрити в Google Classroom</a>'

                            for target in chats:
                                cid = target["chat_id"]
                                tid = target.get("thread_id")
                                try:
                                    await bot.send_message(cid, text, parse_mode="HTML", message_thread_id=tid)
                                except Exception as e:
                                    logger.warning(f"HTML send failed to {cid} (thread {tid}): {e}. Retrying plain text.")
                                    try:
                                        plain_text = re.sub(r'<[^>]+>', '', text)
                                        await bot.send_message(cid, plain_text, message_thread_id=tid)
                                    except Exception as e2:
                                        logger.error(f"Не вдалося надіслати сповіщення Classroom у чат {cid}: {e2}")

        # Якщо успішно завантажили курси та реальні завдання — очищаємо демо-заглушки та архівуємо старі
        if delete_demo_on_success and len(courses) > 0:
            from database import delete_assignment_db, cleanup_past_assignments_db
            await delete_assignment_db("op_lab1")
            await delete_assignment_db("asd_lab1")
            await delete_assignment_db("kdm_calc1")
            await cleanup_past_assignments_db()

        # Фоновий backfill для завдань, у яких ще немає ai_summary
        await backfill_assignment_summaries()

        return {"success": True, "courses_count": len(courses), "new_items": new_items, "error": None}
    except Exception as e:
        logger.error(f"Помилка синхронізації Google Classroom: {e}")
        return {"success": False, "courses_count": 0, "new_items": [], "error": str(e)}


async def backfill_assignment_summaries() -> int:
    """
    Фонова генерація AI-вижимок для існуючих завдань у базі, якщо вони ще не мають ai_summary.
    Дозволяє миттєво оновити старі записи без блокування інтерфейсу.
    """
    updated_count = 0
    try:
        assignments = await get_active_assignments_db()
        for a in assignments:
            aid = a["id"]
            curr_sum = a.get("ai_summary")
            raw_desc = a.get("description", "")
            if (not curr_sum or not str(curr_sum).strip()) and raw_desc and len(raw_desc.strip()) > 20:
                cname = clean_course_name(a.get("course_id", ""))
                title = a.get("title", "")
                try:
                    summary = await summarize_assignment_requirements(
                        title=title,
                        description=raw_desc,
                        course_name=cname
                    )
                    if summary and summary.strip():
                        await update_assignment_ai_summary_db(aid, summary.strip())
                        updated_count += 1
                        logger.info(f"Створено AI-вижимку для '{title}' ({aid}): {summary[:60]}...")
                except Exception as e:
                    logger.warning(f"Не вдалося оновити AI-вижимку для {aid}: {e}")
    except Exception as e:
        logger.error(f"Помилка під час backfill_assignment_summaries: {e}")
    return updated_count

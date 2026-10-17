import asyncio
from datetime import datetime, time, date, timedelta
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot

from config import (
    KYIV_TZ,
    KPI_GROUP_ID,
    MORNING_DIGEST_TIME,
    NOTIFY_MINUTES_BEFORE,
    get_subscribed_chats,
)
from kpi_api import get_lessons_for_date
from formatters import format_morning_digest, format_lesson_alert

import html
import re

logger = logging.getLogger(__name__)


def strip_html_tags(text: str) -> str:
    """Видаляє HTML теги для безпечної відправки повідомлення звичайним текстом."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    return html.unescape(clean)


def strip_markdown(text: str) -> str:
    """Зворотна сумісність: очищення спецсимволів."""
    return strip_html_tags(text).replace("**", "").replace("*", "").replace("`", "").replace("_", "")


async def safe_send_message(bot: Bot, chat_id: int, text: str, reply_markup=None, message_thread_id: int | None = None):
    """Безпечна відправка повідомлення з підтримкою топіків та відкатом на звичайний текст при помилці HTML."""
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
        )
    except Exception as e:
        logger.warning(f"Помилка відправки HTML у {chat_id} (топік {message_thread_id}): {e}. Відправляю простим текстом.")
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=strip_html_tags(text),
                parse_mode=None,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id,
            )
        except Exception as e2:
            logger.error(f"Не вдалося надіслати повідомлення у чат {chat_id} (топік {message_thread_id}): {e2}")
            return None


async def delete_message_after_delay(bot: Bot, chat_id: int, message_id: int, delay_seconds: int = 1200):
    """Автоматично видаляє старе повідомлення через delay_seconds (за замовчуванням 20 хвилин)."""
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        logger.info(f"Автоматично очищено сповіщення {message_id} у чаті {chat_id}")
    except Exception as e:
        logger.debug(f"Не вдалося видалити повідомлення {message_id}: {e}")


# Множество отправленных уведомлений, чтобы не отправлять дважды
# Формат ключа: "YYYY-MM-DD_HH:MM_SubjectName"
sent_alerts: set[str] = set()

# Кэш пар на сегодня
_today_cache_date: date | None = None
_today_cached_lessons: list[dict] = []
_today_cached_week: int = 1
_today_cached_day_name: str = ""


async def refresh_today_cache():
    """Обновить кэш расписания на сегодня."""
    global _today_cache_date, _today_cached_lessons, _today_cached_week, _today_cached_day_name
    now_date = datetime.now(KYIV_TZ).date()
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, now_date)
        _today_cache_date = now_date
        _today_cached_week = week
        _today_cached_day_name = day_name
        _today_cached_lessons = lessons
        logger.info(f"Оновлено розклад на {now_date}: {len(lessons)} пар")
    except Exception as e:
        logger.error(f"Помилка при оновленні розкладу: {e}")


def calculate_lessons_end_datetime(lessons: list[dict], target_date: date) -> datetime:
    """
    Розрахувати час закінчення останньої пари на день.
    Пара в КПІ триває 1 год 35 хв (95 хв).
    Додаємо 5 хв запасу (разом 100 хв від початку останньої пари).
    Якщо пар немає — видаляти о 16:00.
    """
    valid = [l for l in (lessons or []) if isinstance(l, dict) and l.get("time")]
    if not valid:
        return datetime.combine(target_date, time(16, 0), tzinfo=KYIV_TZ)

    last_lesson = max(valid, key=lambda l: l["time"])
    try:
        parts = [int(p) for p in last_lesson["time"][:5].split(":")]
        start_dt = datetime.combine(target_date, time(parts[0], parts[1]), tzinfo=KYIV_TZ)
        return start_dt + timedelta(minutes=100)
    except Exception:
        return datetime.combine(target_date, time(16, 0), tzinfo=KYIV_TZ)


async def process_scheduled_deletions(bot: Bot):
    """
    Перевірити базу та видалити повідомлення, час збереження яких вичерпано
    (зокрема ранковий розклад після того, як закінчилися пари).
    """
    from database import get_due_scheduled_deletions_db, remove_scheduled_deletion_db
    now_str = datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S")
    due_items = await get_due_scheduled_deletions_db(now_str)
    for item in due_items:
        cid = item["chat_id"]
        mid = item["message_id"]
        tag = item.get("tag", "digest")
        try:
            await bot.delete_message(chat_id=cid, message_id=mid)
            logger.info(f"Успішно видалено {tag} (id {mid}) у чаті {cid} після закінчення пар.")
        except Exception as e:
            logger.debug(f"Не вдалося видалити повідомлення {mid} у чаті {cid}: {e}")
        finally:
            await remove_scheduled_deletion_db(item["id"])


async def send_morning_digest(bot: Bot):
    """Отправить утренний дайджест во все подписанные чаты и топики и запланировать его автоудаление после окончания пар."""
    from database import get_subscribed_chats_db, add_scheduled_deletion_db
    targets = await get_subscribed_chats_db()
    if not targets:
        logger.info("Немає підписаних чатів для ранкового дайджесту.")
        return

    await refresh_today_cache()
    now_dt = datetime.now(KYIV_TZ)
    end_dt = calculate_lessons_end_datetime(_today_cached_lessons, now_dt.date())
    delete_time_str = end_dt.strftime("%H:%M")

    text, kb = format_morning_digest(
        _today_cached_week,
        _today_cached_day_name,
        _today_cached_lessons,
        auto_delete_time=delete_time_str if _today_cached_lessons else None
    )

    for target in targets:
        cid = target["chat_id"]
        tid = target.get("thread_id")
        sent_msg = await safe_send_message(bot, cid, text, reply_markup=kb, message_thread_id=tid)
        if sent_msg:
            await add_scheduled_deletion_db(
                chat_id=cid,
                message_id=sent_msg.message_id,
                delete_at=end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                tag="morning_digest"
            )
            logger.info(f"Заплановано авто-видалення ранкового дайджесту {sent_msg.message_id} у чаті {cid} о {delete_time_str}")


async def check_upcoming_lessons(bot: Bot):
    """
    Каждую минуту проверяем приближение пар, а также очищаем устаревший розклад после окончания пар.
    """
    global sent_alerts, _today_cache_date

    # 1. Автоматичне очищення повідомлень розкладу після завершення пар
    try:
        await process_scheduled_deletions(bot)
    except Exception as e_del:
        logger.error(f"Помилка при обробці запланованих видалень: {e_del}")

    now = datetime.now(KYIV_TZ)
    today = now.date()

    # Если сменился день — чистим старые ключи отправки
    if _today_cache_date != today:
        sent_alerts.clear()
        await refresh_today_cache()

    from database import get_subscribed_chats_db
    targets = await get_subscribed_chats_db()
    if not targets or not _today_cached_lessons:
        return

    # Интервалы уведомлений в минутах (за 20 минут и за 5 минут)
    ALERT_INTERVALS = [20, 5]

    for lesson in _today_cached_lessons:
        try:
            lesson_time_parts = [int(p) for p in lesson["time"].split(":")]
            lesson_dt = datetime.combine(
                today,
                time(lesson_time_parts[0], lesson_time_parts[1]),
                tzinfo=KYIV_TZ
            )
        except Exception:
            continue

        diff_seconds = (lesson_dt - now).total_seconds()
        diff_minutes = diff_seconds / 60.0

        for target_minutes in ALERT_INTERVALS:
            # Окно срабатывания: от (target - 1.0) до (target + 0.5) минут
            if (target_minutes - 1.0) <= diff_minutes <= (target_minutes + 0.5):
                alert_key = f"{today.isoformat()}_{lesson['time']}_{lesson['name']}_{target_minutes}"
                if alert_key in sent_alerts:
                    continue

                text, kb = format_lesson_alert(lesson, minutes_left=target_minutes)
                for target in targets:
                    cid = target["chat_id"]
                    tid = target.get("thread_id")
                    sent_msg = await safe_send_message(bot, cid, text, reply_markup=kb, message_thread_id=tid)
                    if sent_msg:
                        # Автоматически удаляем сообщение через 20 минут, чтобы не засорять чат
                        asyncio.create_task(delete_message_after_delay(bot, cid, sent_msg.message_id, delay_seconds=20 * 60))

                sent_alerts.add(alert_key)
                logger.info(f"Надіслано сповіщення за {target_minutes} хв: {lesson['name']} ({lesson['time']})")


async def send_evening_digest(bot: Bot):
    """Отправить вечернюю сводку статуса дедлайнов и пар в 21:00."""
    from database import get_active_assignments_db, get_subscribed_chats_db, get_today_announcements_db
    from formatters import format_daily_summary
    from kpi_api import get_schedule_for_date

    targets = await get_subscribed_chats_db()
    if not targets:
        return

    today_date = datetime.now(KYIV_TZ).strftime("%Y-%m-%d")
    lessons = await get_schedule_for_date(today_date)
    assignments = await get_active_assignments_db()
    announcements = await get_today_announcements_db()
    text = format_daily_summary(lessons, assignments, announcements)

    for target in targets:
        cid = target["chat_id"]
        tid = target.get("thread_id")
        await safe_send_message(bot, cid, text, message_thread_id=tid)


_youtube_check_lock = asyncio.Lock()


async def check_new_youtube_videos(bot: Bot, fallback_chat_id: int | None = None, fallback_thread_id: int | None = None) -> int:
    """Фонова перевірка нових відео на YouTube-каналі групи (кожні 10 хв) з захистом від паралельних черг."""
    from config import YOUTUBE_CHANNEL_ID
    if not YOUTUBE_CHANNEL_ID:
        return 0
    channel_id = YOUTUBE_CHANNEL_ID

    if _youtube_check_lock.locked():
        logger.info("Попередній процес обробки YouTube-відео ще триває. Пропускаємо виклик, щоб не створювати конкурентних запитів.")
        return 0

    async with _youtube_check_lock:
        from youtube_processor import fetch_latest_channel_videos, process_video_and_notify
        new_count = 0
        try:
            videos = await fetch_latest_channel_videos(channel_id, max_results=5)
            # Обробляємо нові пари строго послідовно (FIFO Queue)
            for vid in reversed(videos):  # від старіших до новіших
                processed = await process_video_and_notify(
                    bot,
                    vid,
                    fallback_chat_id=fallback_chat_id,
                    fallback_thread_id=fallback_thread_id
                )
                if processed:
                    new_count += 1
                    # Пауза між обробкою кількох пар, щоб охололи ліміти Google TPM
                    await asyncio.sleep(6)
        except Exception as e:
            logger.error(f"Помилка при перевірці YouTube-відео: {e}")
        return new_count


async def check_new_classroom_tasks(bot: Bot):
    """Фонова перевірка нових завдань у Google Classroom (кожні 15 хв)."""
    try:
        from classroom_sync import sync_classroom_tasks
        await sync_classroom_tasks(bot)
    except Exception as e:
        logger.error(f"Помилка при фоновій перевірці Classroom: {e}")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Настроить и запустить планировщик задач."""
    scheduler = AsyncIOScheduler(timezone=KYIV_TZ)

    # 1. Час ранкового дайджесту для навчальних будніх днів (08:00)
    # Навчальні дні групи ІП-66: понеділок, вівторок, четвер, п'ятниця, субота
    raw_time = (MORNING_DIGEST_TIME or "08:00").strip()
    digest_hour, digest_minute = [int(x) for x in raw_time.split(":")]

    # Ранковий дайджест пар у будні навчальні дні (пн, вт, чт, пт, сб) о 08:00
    scheduler.add_job(
        send_morning_digest,
        trigger=CronTrigger(day_of_week="mon,tue,thu,fri,sat", hour=digest_hour, minute=digest_minute, timezone=KYIV_TZ),
        args=[bot],
        name="morning_digest",
    )

    # 2. Проверка приближения пары каждую минуту
    scheduler.add_job(
        check_upcoming_lessons,
        trigger=IntervalTrigger(minutes=1, timezone=KYIV_TZ),
        args=[bot],
        name="check_upcoming_lessons",
    )

    # 3. Обновление кэша в 06:00 каждое утро
    scheduler.add_job(
        refresh_today_cache,
        trigger=CronTrigger(hour=6, minute=0, timezone=KYIV_TZ),
        name="daily_cache_refresh",
    )

    # 4. Вечерний дайджест дедлайнов в 21:00 каждый день (включая выходные)
    scheduler.add_job(
        send_evening_digest,
        trigger=CronTrigger(day_of_week="mon-sun", hour=21, minute=0, timezone=KYIV_TZ),
        args=[bot],
        name="evening_digest",
    )

    # 5. Утренний дайджест дедлайнов выходного дня в 10:00 (среда и воскресенье — дни без пар)
    scheduler.add_job(
        send_evening_digest,
        trigger=CronTrigger(day_of_week="wed,sun", hour=10, minute=0, timezone=KYIV_TZ),
        args=[bot],
        name="weekend_morning_digest",
    )

    # 6. Автоматична перевірка нових лекцій на YouTube кожні 10 хвилин
    scheduler.add_job(
        check_new_youtube_videos,
        trigger=IntervalTrigger(minutes=10, timezone=KYIV_TZ),
        args=[bot],
        name="check_new_youtube_videos",
    )

    # 7. Автоматическая проверка новых заданий в Google Classroom каждые 15 минут
    scheduler.add_job(
        check_new_classroom_tasks,
        trigger=IntervalTrigger(minutes=15, timezone=KYIV_TZ),
        args=[bot],
        name="check_new_classroom_tasks",
    )

    return scheduler

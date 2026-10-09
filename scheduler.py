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

logger = logging.getLogger(__name__)

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


async def send_morning_digest(bot: Bot):
    """Отправить утренний дайджест во все подписанные чаты."""
    chats = get_subscribed_chats()
    if not chats:
        logger.info("Немає підписаних чатів для ранкового дайджесту.")
        return

    await refresh_today_cache()
    text, kb = format_morning_digest(_today_cached_week, _today_cached_day_name, _today_cached_lessons)

    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.error(f"Не вдалося надіслати дайджест у чат {chat_id}: {e}")


async def check_upcoming_lessons(bot: Bot):
    """
    Каждую минуту проверяем, не начинается ли пара через NOTIFY_MINUTES_BEFORE (5) минут.
    """
    global sent_alerts, _today_cache_date

    now = datetime.now(KYIV_TZ)
    today = now.date()

    # Если сменился день — чистим старые ключи отправки
    if _today_cache_date != today:
        sent_alerts.clear()
        await refresh_today_cache()

    chats = get_subscribed_chats()
    if not chats or not _today_cached_lessons:
        return

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

        # Уведомляем за ~5 минут (от 4.0 до 5.5 минут до звонка)
        target_diff = float(NOTIFY_MINUTES_BEFORE)
        if (target_diff - 1.0) <= diff_minutes <= (target_diff + 0.5):
            alert_key = f"{today.isoformat()}_{lesson['time']}_{lesson['name']}"
            if alert_key in sent_alerts:
                continue

            text, kb = format_lesson_alert(lesson, minutes_left=NOTIFY_MINUTES_BEFORE)
            for chat_id in chats:
                try:
                    await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)
                except Exception as e:
                    logger.error(f"Не вдалося надіслати сповіщення у чат {chat_id}: {e}")

            sent_alerts.add(alert_key)
            logger.info(f"Надіслано сповіщення про пару: {lesson['name']} ({lesson['time']})")


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Настроить и запустить планировщик задач."""
    scheduler = AsyncIOScheduler(timezone=KYIV_TZ)

    # 1. Парсим время утреннего дайджеста из конфига (HH:MM)
    digest_hour, digest_minute = [int(x) for x in MORNING_DIGEST_TIME.split(":")]

    # Утренний дайджест с понедельника по субботу
    scheduler.add_job(
        send_morning_digest,
        trigger=CronTrigger(day_of_week="mon-sat", hour=digest_hour, minute=digest_minute, timezone=KYIV_TZ),
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

    return scheduler

import asyncio
import logging
import os
import sys
from pathlib import Path

# Принудительно включаем UTF-8 для консоли Windows
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8")

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, BASE_DIR
from handlers import router
from scheduler import setup_scheduler, refresh_today_cache

log_file = BASE_DIR / "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger("KPIScheduleBot")
# Приглушуємо шум від aiogram.event, щоб не засмічувати логи звичайними повідомленнями з чатів
logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def start_health_check_server():
    """
    Легковесный HTTP health-check сервер для облачных хостингов (Render, Koyeb, Railway).
    """
    port_str = os.getenv("PORT")
    if not port_str:
        return None

    try:
        port = int(port_str)
        app = web.Application()

        async def handle_ping(request):
            return web.Response(text="KPI Schedule Bot is OK")

        async def handle_status(request):
            from datetime import datetime
            from config import KYIV_TZ, TURSO_DATABASE_URL, SQLITE_CLOUD_URL
            from database import get_subscribed_chats_db
            from scheduler import _today_cached_lessons, _today_cached_week, _today_cached_day_name
            try:
                targets = await get_subscribed_chats_db()
                return web.json_response({
                    "status": "online",
                    "time_kyiv": datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    "database_target": "turso" if TURSO_DATABASE_URL else ("sqlitecloud" if SQLITE_CLOUD_URL else "local_sqlite"),
                    "subscribed_chats": targets,
                    "subscribed_count": len(targets),
                    "cached_lessons_count": len(_today_cached_lessons),
                    "week": _today_cached_week,
                    "day": _today_cached_day_name,
                })
            except Exception as e:
                return web.json_response({"status": "error", "error": str(e)}, status=500)

        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)
        app.router.add_get("/status", handle_status)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Health-check HTTP сервер запущено на порті {port}")
        return runner
    except Exception as e:
        logger.warning(f"Не вдалося запустити health-check сервер: {e}")
        return None


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "ПОМИЛКА: Не вказано BOT_TOKEN у файлі .env!\n"
            "Будь ласка, отримайте токен у @BotFather та впишіть його в .env файл."
        )
        return

    # Запуск опционального health-check сервера (для облака)
    http_runner = await start_health_check_server()

    masked = f"{BOT_TOKEN[:6]}...{BOT_TOKEN[-4:]}" if len(BOT_TOKEN) > 10 else "EMPTY/TOO_SHORT"
    logger.info(f"Завантажено BOT_TOKEN: {masked} (довжина: {len(BOT_TOKEN)})")

    # Инициализация бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Проверяем соединение с Telegram
    me = await bot.get_me()
    logger.info(f"Успішна авторизація: бот @{me.username} ({me.first_name})")

    # Встановлення списку команд у меню Telegram
    from aiogram.types import BotCommand
    try:
        await bot.set_my_commands([
            BotCommand(command="today", description="Розклад пар на сьогодні"),
            BotCommand(command="tomorrow", description="Розклад пар на завтра"),
            BotCommand(command="week", description="Поточний навчальний тиждень"),
            BotCommand(command="deadlines", description="Радар дедлайнів (Classroom)"),
            BotCommand(command="summary", description="Підсумок дня та дедлайни"),
            BotCommand(command="sync", description="Синхронізація з Classroom та YouTube"),
            BotCommand(command="youtube", description="Перевірити нові лекції на YouTube"),
            BotCommand(command="links", description="Посилання на Zoom/Meet"),
            BotCommand(command="setlink", description="Додати або оновити лінк"),
            BotCommand(command="dellink", description="Видалити лінк на предмет"),
            BotCommand(command="subscribe", description="Увімкнути сповіщення"),
            BotCommand(command="unsubscribe", description="Вимкнути сповіщення"),
            BotCommand(command="help", description="Повна довідка по боту"),
        ])
    except Exception as e:
        logger.warning(f"Не вдалося оновити меню команд: {e}")

    # Ініціалізація бази даних SQLite (v2.0)
    from database import init_db
    await init_db()

    # Первичная загрузка расписания на сегодня
    await refresh_today_cache()

    # Запуск планировщика задач (дайджест + пуши за 5 минут)
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планувальник завдань успішно запущено!")

    # Фонова первинна синхронізація (НЕ блокує старт прийому команд!)
    async def run_startup_syncs():
        await asyncio.sleep(2)  # Даємо боту запустити polling
        try:
            from classroom_sync import sync_classroom_tasks, backfill_assignment_summaries
            await sync_classroom_tasks(bot)
            await backfill_assignment_summaries()
        except Exception as e_cr:
            logger.warning(f"Classroom sync on startup: {e_cr}")

        try:
            from scheduler import check_new_youtube_videos
            await check_new_youtube_videos(bot)
        except Exception as e_yt:
            logger.warning(f"YouTube check on startup: {e_yt}")

    asyncio.create_task(run_startup_syncs())

    # Удаляем вебхуки и запускаем поллинг МИТТЄВО
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info(f"Бот @{me.username} запущений і очікує повідомлень...")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        if http_runner:
            await http_runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинений.")

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
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from config import BOT_TOKEN, BASE_DIR, WEBAPP_URL
from handlers import router
from scheduler import setup_scheduler, refresh_today_cache
from webapp_server import start_webapp_server

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


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "ПОМИЛКА: Не вказано BOT_TOKEN у файлі .env!\n"
            "Будь ласка, отримайте токен у @BotFather та впишіть його в .env файл."
        )
        return

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

    # Запуск сервера Telegram Mini App & REST API & Health-check
    http_runner = await start_webapp_server(bot)

    # Встановлення кнопки меню Mini App (Швидкий доступ до веб-порталу)
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📱 IP-66 Hub",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/app")
            )
        )
        logger.info(f"Встановлено MenuButtonWebApp: {WEBAPP_URL}/app")
    except Exception as e:
        logger.warning(f"Не вдалося встановити MenuButtonWebApp: {e}")

    # Встановлення списку команд у меню Telegram
    try:
        await bot.set_my_commands([
            BotCommand(command="today", description="Розклад пар на сьогодні"),
            BotCommand(command="tomorrow", description="Розклад пар на завтра"),
            BotCommand(command="week", description="Поточний навчальний тиждень"),
            BotCommand(command="queue", description="Жива черга на захист (ОП / АСД)"),
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

    # Одноразова автоматична міграція черги з Google Таблиці
    try:
        from sync_queue_sheet import auto_sync_on_startup
        # await auto_sync_on_startup(bot=bot)
    except Exception as e_q:
        logger.warning(f"Помилка при auto_sync_on_startup: {e_q}")

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

    # Фоновий самопінг для захисту від засинання Render Free Tier
    async def run_keep_alive():
        await asyncio.sleep(60)  # Чекаємо запуску веб-сервера
        ping_url = f"{WEBAPP_URL}/health" if WEBAPP_URL else None
        if not ping_url or "localhost" in ping_url or "127.0.0.1" in ping_url:
            return
        logger.info(f"Активуємо Keep-Alive пінгер для Render: {ping_url}")
        import aiohttp
        while True:
            try:
                await asyncio.sleep(600)  # кожні 10 хвилин (таймаут сну Render - 15 хв)
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    async with session.get(ping_url) as resp:
                        logger.debug(f"Keep-Alive ping status: {resp.status}")
            except asyncio.CancelledError:
                break
            except Exception as e_ping:
                logger.debug(f"Keep-Alive ping note: {e_ping}")

    asyncio.create_task(run_keep_alive())

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

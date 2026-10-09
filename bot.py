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

        app.router.add_get("/", handle_ping)
        app.router.add_get("/health", handle_ping)

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

    # Инициализация бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()
    dp.include_router(router)

    # Проверяем соединение с Telegram
    me = await bot.get_me()
    logger.info(f"Успішна авторизація: бот @{me.username} ({me.first_name})")

    # Первичная загрузка расписания на сегодня
    await refresh_today_cache()

    # Запуск планировщика задач (дайджест + пуши за 5 минут)
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планувальник завдань успішно запущено!")

    # Удаляем вебхуки и запускаем поллинг
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

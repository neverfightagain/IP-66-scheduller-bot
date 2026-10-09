import asyncio
import logging
import sys
from pathlib import Path

if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr:
    sys.stderr.reconfigure(encoding="utf-8")

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


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error(
            "ПОМИЛКА: Не вказано BOT_TOKEN у файлі .env!\n"
            "Будь ласка, отримайте токен у @BotFather та впишіть його в .env файл."
        )
        return

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    dp = Dispatcher()
    dp.include_router(router)

    me = await bot.get_me()
    logger.info(f"Успішна авторизація: бот @{me.username} ({me.first_name})")

    # Первичная загрузка расписания на сегодня
    await refresh_today_cache()

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Планувальник завдань успішно запущено!")

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info(f"Бот @{me.username} запущений і очікує повідомлень...")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинений.")

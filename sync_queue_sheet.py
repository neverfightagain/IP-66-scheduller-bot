import asyncio
import logging
import re
import sqlite3
import sys

if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

logger = logging.getLogger("SyncQueueSheet")

from database import (
    init_db,
    get_db,
    format_queue_name,
    parse_lab_info,
    normalize_queue_subject,
)

# 17 студентів з офіційної Google Таблиці
SHEET_QUEUE_DATA = [
    ("Гуринець", "2 + 3"),
    ("Сіроштан", "3 + 4"),
    ("Пришляк", "3"),
    ("Пугач", "3"),
    ("Малишенко", "3"),
    ("Петруня", "3"),
    ("Гузюк", "4"),
    ("Трощинський", "4"),
    ("Мошківський", "4"),
    ("Ігнатьєв", "4"),
    ("Коваленко", "4"),
    ("Глушич", "4"),
    ("Сахнюк", "4"),
    ("Лозовський", "4"),
    ("Новак", "4 + 5"),
    ("Архипович", "4"),
    ("Сінчіневіч", "5")
]

SUBJECT = "ОП"


async def get_all_target_chats(db) -> list[int]:
    """Визначення всіх чатів, де потрібна черга (0 для Mini App, підписані чати, існуючі черги)."""
    chats = {0, 8735281894, 777111}
    try:
        async with db.execute("SELECT DISTINCT chat_id FROM chat_subscriptions") as cur:
            rows = await cur.fetchall()
            for r in rows:
                if r[0] is not None:
                    chats.add(r[0])
    except Exception:
        pass
    try:
        async with db.execute("SELECT DISTINCT chat_id FROM lab_queues") as cur:
            rows = await cur.fetchall()
            for r in rows:
                if r[0] is not None:
                    chats.add(r[0])
    except Exception:
        pass
    try:
        from config import get_subscribed_chats
        for c in get_subscribed_chats():
            if c.get("chat_id"):
                chats.add(c["chat_id"])
    except Exception:
        pass
    return list(chats)


async def sync_queue(bot=None) -> int:
    """Синхронізувати чергу ОП з 17 студентами для всіх чатів."""
    await init_db()
    logger.info("🔄 Підключення до бази даних та очищення старої черги ОП...")

    async with get_db() as db:
        # 1. Знаходимо всі цільові чати
        target_chats = await get_all_target_chats(db)

        # 2. Очищення старої черги ОП
        await db.execute("DELETE FROM lab_queues WHERE subject = ?", (SUBJECT,))
        await db.commit()
        logger.info(f"✅ Стару чергу {SUBJECT} повністю очищено для чатів: {target_chats}.")

        # 3. Отримання всіх зареєстрованих студентів
        async with db.execute("SELECT id, real_name, telegram_username, telegram_id FROM students") as cur:
            all_students = [dict(r) for r in await cur.fetchall()]

        inserted_count = 0
        for rank, (surname, kp_raw) in enumerate(SHEET_QUEUE_DATA, 1):
            match = None
            clean_sur = surname.strip().lower()
            for s in all_students:
                rname = (s.get("real_name") or "").strip().lower()
                if rname.startswith(clean_sur):
                    match = s
                    break

            if not match:
                real_name = surname
                username = None
                user_id = 900000 + rank
            else:
                real_name = match["real_name"]
                username = match.get("telegram_username")
                user_id = match.get("telegram_id") or (100000 + match["id"])

            clean_name = format_queue_name(real_name)
            prio, lab_label = parse_lab_info(kp_raw)

            # Додаємо запис для кожного цільового chat_id
            for cid in target_chats:
                await db.execute("""
                    INSERT INTO lab_queues (
                        chat_id, subject, user_id, user_name, username, lab_number, lab_priority, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting')
                """, (cid, SUBJECT, user_id, clean_name, username, lab_label, prio))

            inserted_count += 1

        await db.commit()
        logger.info(f"🎉 Успішно занесено {inserted_count} студентів у чергу {SUBJECT}!")

        # 4. Якщо передано бота, оновлюємо закріплені повідомлення черги в чатах
        if bot:
            try:
                from webapp_server import sync_queue_message_in_chat
                for cid in target_chats:
                    if cid != 0:
                        try:
                            await sync_queue_message_in_chat(bot, cid, SUBJECT)
                        except Exception:
                            pass
            except Exception as e_sync:
                logger.debug(f"Sync queue chat messages warning: {e_sync}")

        return inserted_count


async def auto_sync_on_startup(bot=None) -> bool:
    """Виконати одноразову автоматичну міграцію черги при старті сервера."""
    from database import get_db
    try:
        async with get_db() as db:
            try:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS chat_settings (
                        chat_id INTEGER NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT,
                        PRIMARY KEY (chat_id, key)
                    );
                """)
                await db.commit()
            except Exception:
                pass

            async with db.execute("SELECT value FROM chat_settings WHERE chat_id = 0 AND key = 'sheet_queue_synced_v1'") as cur:
                row = await cur.fetchone()
                if row and row[0] == "1":
                    return False
    except Exception as e:
        logger.warning(f"auto_sync_on_startup check error: {e}")

    logger.info("⚡ Виявлено запуск нової версії — виконуємо первинну синхронізацію черги з Google Таблиці...")
    await sync_queue(bot=bot)
    try:
        async with get_db() as db:
            await db.execute("""
                INSERT OR REPLACE INTO chat_settings (chat_id, key, value)
                VALUES (0, 'sheet_queue_synced_v1', '1')
            """)
            await db.commit()
    except Exception as e_save:
        logger.warning(f"auto_sync_on_startup mark error: {e_save}")

    logger.info("✅ Первинну синхронізацію черги з Google Таблиці успішно завершено!")
    return True


if __name__ == "__main__":
    asyncio.run(sync_queue())

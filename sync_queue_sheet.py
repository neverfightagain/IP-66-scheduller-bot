import asyncio
import re
import sqlite3
import sys

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

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

TARGET_CHATS = [0, 8735281894, 777111]
SUBJECT = "ОП"

async def sync_queue():
    await init_db()
    print("🔄 Підключення до бази даних та очищення старої черги...")

    async with get_db() as db:
        # 1. Очищення старої черги
        await db.execute("DELETE FROM lab_queues")
        await db.commit()
        print("✅ Стару чергу повністю очищено з lab_queues.")

        # 2. Отримання всіх студентів
        async with db.execute("SELECT id, real_name, telegram_username, telegram_id FROM students") as cur:
            all_students = [dict(r) for r in await cur.fetchall()]

        print(f"📋 Знайдено {len(all_students)} зареєстрованих студентів у базі.")

        inserted_count = 0
        for rank, (surname, kp_raw) in enumerate(SHEET_QUEUE_DATA, 1):
            # Пошук студента за прізвищем
            match = None
            clean_sur = surname.strip().lower()
            for s in all_students:
                rname = (s.get("real_name") or "").strip().lower()
                if rname.startswith(clean_sur):
                    match = s
                    break

            if not match:
                print(f"⚠️ Увага: Студента {surname} не знайдено в базі!")
                real_name = surname
                username = None
                user_id = 900000 + rank
            else:
                real_name = match["real_name"]
                username = match.get("telegram_username")
                user_id = match.get("telegram_id") or (100000 + match["id"])

            clean_name = format_queue_name(real_name)
            prio, lab_label = parse_lab_info(kp_raw)

            # Додаємо запис для кожного цільового chat_id (0 для WebApp, і для активних груп)
            for cid in TARGET_CHATS:
                await db.execute("""
                    INSERT INTO lab_queues (
                        chat_id, subject, user_id, user_name, username, lab_number, lab_priority, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting')
                """, (cid, SUBJECT, user_id, clean_name, username, lab_label, prio))

            inserted_count += 1
            print(f"  #{rank:2d} [Пріоритет {prio}] {clean_name} (@{username or '-'}) -> {lab_label}")

        await db.commit()
        print(f"\n🎉 Успішно занесено {inserted_count} студентів у чергу {SUBJECT} для всіх чатів!")

if __name__ == "__main__":
    asyncio.run(sync_queue())

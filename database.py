import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import aiosqlite
from config import BASE_DIR, CHATS_FILE, LINKS_FILE, ENV_CHAT_ID, ENV_THREAD_ID

logger = logging.getLogger(__name__)

DB_PATH = BASE_DIR / "kpi_bot.db"


@asynccontextmanager
async def get_db():
    """Контекстный менеджер подключения к SQLite базе данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA foreign_keys = ON;")
        db.row_factory = aiosqlite.Row
        yield db


async def init_db():
    """Создание таблиц базы данных и миграция из старых JSON-файлов."""
    async with get_db() as db:
        # 1. Таблица курсов/предметов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kpi_code TEXT,
                lecturer TEXT,
                zoom_url TEXT,
                comment TEXT
            );
        """)

        # 2. Таблица настроек чатов и топиков (Telegram Forum Topics)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                thread_id INTEGER DEFAULT NULL,
                notifications_enabled INTEGER DEFAULT 1,
                summaries_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_thread
            ON chat_subscriptions (chat_id, IFNULL(thread_id, 0));
        """)

        # 3. Таблица заданий и лабораторных (Google Classroom)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                course_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                ai_summary TEXT,
                due_date TIMESTAMP,
                status TEXT DEFAULT 'active',
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        try:
            await db.execute("ALTER TABLE assignments ADD COLUMN ai_summary TEXT;")
        except Exception:
            pass

        # 4. Таблица обработанных видео с лекциями (YouTube)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                course_id TEXT,
                title TEXT NOT NULL,
                published_at TIMESTAMP,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                summary_json TEXT
            );
        """)

        # 5. Таблица объявлений преподавателей и алертов кросс-валидации
        await db.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                detected_date TIMESTAMP,
                conflict_flag INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 6. Таблиця запланованого видалення повідомлень (видалення ранкового розкладу після закінчення пар)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_deletions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                delete_at TIMESTAMP NOT NULL,
                tag TEXT DEFAULT 'digest',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 7. Таблиця розподілу варіантів та тем робіт
        await db.execute("""
            CREATE TABLE IF NOT EXISTS topic_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                variant_or_topic TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                username TEXT,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (chat_id, subject, variant_or_topic)
            );
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_topic_claims_chat_subj
            ON topic_claims (chat_id, subject);
        """)

        await db.commit()
        logger.info("База даних SQLite (kpi_bot.db) успішно ініціалізована.")

        # Автоматическая миграция из старых JSON-файлов
        await _migrate_legacy_data(db)
        await db.execute("DELETE FROM assignments WHERE id IN ('op_lab1', 'asd_lab1', 'kdm_calc1')")
        await db.commit()
        await cleanup_past_assignments_db()


async def _migrate_legacy_data(db: aiosqlite.Connection):
    """Миграция данных из старых таблиц, chats.json и links.json в SQLite."""
    # 1. Миграция из старой таблицы chat_settings, если она существовала
    try:
        async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chat_settings'") as cursor:
            if await cursor.fetchone():
                await db.execute("""
                    INSERT OR IGNORE INTO chat_subscriptions (chat_id, thread_id, notifications_enabled, summaries_enabled)
                    SELECT chat_id, NULL, notifications_enabled, summaries_enabled
                    FROM chat_settings
                """)
                await db.commit()
    except Exception as e:
        logger.warning(f"Помилка міграції chat_settings: {e}")

    # 2. Миграция chats.json
    if CHATS_FILE.exists():
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                chats = data.get("chats", [])
                for item in chats:
                    if isinstance(item, int):
                        cid, tid = item, None
                    elif isinstance(item, dict):
                        cid = int(item["chat_id"])
                        tid = int(item["thread_id"]) if item.get("thread_id") is not None else None
                    else:
                        continue
                    await db.execute("""
                        INSERT INTO chat_subscriptions (chat_id, thread_id, notifications_enabled)
                        VALUES (?, ?, 1)
                        ON CONFLICT(chat_id, IFNULL(thread_id, 0)) DO UPDATE SET notifications_enabled = 1
                    """, (cid, tid))
                await db.commit()
        except Exception as e:
            logger.warning(f"Помилка міграції chats.json: {e}")

    # 3. Добавляем чат из переменной окружения CHAT_ID / THREAD_ID, если задан
    if ENV_CHAT_ID:
        try:
            cid = int(ENV_CHAT_ID)
            tid = int(ENV_THREAD_ID) if ENV_THREAD_ID else None
            await db.execute("""
                INSERT INTO chat_subscriptions (chat_id, thread_id, notifications_enabled)
                VALUES (?, ?, 1)
                ON CONFLICT(chat_id, IFNULL(thread_id, 0)) DO UPDATE SET notifications_enabled = 1
            """, (cid, tid))
            await db.commit()
        except Exception as e:
            logger.warning(f"Помилка додавання ENV_CHAT_ID: {e}")

    # 4. Миграция links.json
    if LINKS_FILE.exists():
        try:
            with open(LINKS_FILE, "r", encoding="utf-8") as f:
                links_data = json.load(f)
                for key, item in links_data.items():
                    subj = item.get("subject", key)
                    p_type = item.get("type", "")
                    course_id = f"{subj} ({p_type})" if p_type else subj
                    lecturer = item.get("lecturer", "")
                    url = item.get("url", "")
                    comment = item.get("comment", "")
                    await db.execute("""
                        INSERT OR REPLACE INTO courses (id, name, lecturer, zoom_url, comment)
                        VALUES (?, ?, ?, ?, ?)
                    """, (course_id, subj, lecturer, url, comment))
                await db.commit()
        except Exception as e:
            logger.warning(f"Помилка міграції links.json: {e}")


# --- API для работы с чатами и топиками ---

async def get_subscribed_chats_db() -> list[dict]:
    """Получить список всех активных чатов и топиков: [{'chat_id': int, 'thread_id': int | None}]."""
    async with get_db() as db:
        async with db.execute("""
            SELECT chat_id, thread_id
            FROM chat_subscriptions
            WHERE notifications_enabled = 1
        """) as cursor:
            rows = await cursor.fetchall()
            return [{"chat_id": row["chat_id"], "thread_id": row["thread_id"]} for row in rows]


async def add_subscription_db(chat_id: int, thread_id: int | None = None) -> bool:
    """
    Добавить или активировать подписку для чата/топика.
    Для групп (chat_id < 0) переключает активный топик на новый, отключая старые.
    """
    async with get_db() as db:
        if chat_id < 0:
            await db.execute("""
                UPDATE chat_subscriptions
                SET notifications_enabled = 0
                WHERE chat_id = ? AND IFNULL(thread_id, 0) != IFNULL(?, 0)
            """, (chat_id, thread_id))

        await db.execute("""
            INSERT INTO chat_subscriptions (chat_id, thread_id, notifications_enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id, IFNULL(thread_id, 0)) DO UPDATE SET notifications_enabled = 1
        """, (chat_id, thread_id))
        await db.commit()
        return True


async def remove_subscription_db(chat_id: int, thread_id: int | None = None) -> bool:
    """Отключить уведомления для чата или конкретного топика."""
    async with get_db() as db:
        if thread_id is not None:
            await db.execute("""
                UPDATE chat_subscriptions
                SET notifications_enabled = 0
                WHERE chat_id = ? AND IFNULL(thread_id, 0) = ?
            """, (chat_id, thread_id))
        else:
            await db.execute("""
                UPDATE chat_subscriptions
                SET notifications_enabled = 0
                WHERE chat_id = ?
            """, (chat_id,))
        await db.commit()
        return True


# Алиасы для обратной совместимости
add_subscribed_chat_db = add_subscription_db
remove_subscribed_chat_db = remove_subscription_db


# --- API для работы с видео и конспектами ---

async def is_video_processed(video_id: str) -> bool:
    """Проверить, было ли видео уже сохранено в базе или сейчас обрабатывается."""
    async with get_db() as db:
        async with db.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def mark_video_processing(video_id: str, title: str, published_at: str | None = None):
    """Позначити відео як таке, що знаходиться в обробці (запобігає паралельним спробам)."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR IGNORE INTO videos (video_id, course_id, title, published_at, summary_json)
            VALUES (?, ?, ?, ?, ?)
        """, (video_id, "В обробці", title, published_at, json.dumps({"status": "processing"})))
        await db.commit()


async def save_video_summary(video_id: str, title: str, course_id: str | None, published_at: str | None, summary: dict):
    """Сохранить выжимку видео в базу данных."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO videos (video_id, course_id, title, published_at, summary_json)
            VALUES (?, ?, ?, ?, ?)
        """, (video_id, course_id, title, published_at, json.dumps(summary, ensure_ascii=False)))
        await db.commit()


async def add_announcement_db(course_id: str | None, source: str, text: str, detected_date: str | None = None, conflict_flag: int = 0) -> int:
    """Сохранить обнаруженное объявление или анонс в базу данных."""
    async with get_db() as db:
        cursor = await db.execute("""
            INSERT INTO announcements (course_id, source, text, detected_date, conflict_flag)
            VALUES (?, ?, ?, ?, ?)
        """, (course_id, source, text, detected_date, conflict_flag))
        await db.commit()
        return cursor.lastrowid


async def get_today_announcements_db(today_date: str | None = None) -> list[dict]:
    """Получить объявления и анонсы за сегодня (с коррекцией часового пояса Киева UTC+3)."""
    from datetime import datetime
    from config import KYIV_TZ
    if not today_date:
        today_date = datetime.now(KYIV_TZ).strftime("%Y-%m-%d")

    async with get_db() as db:
        async with db.execute("""
            SELECT course_id, text, detected_date, source
            FROM announcements
            WHERE date(created_at, '+3 hours') = ? OR date(created_at) = ?
            ORDER BY id ASC
        """, (today_date, today_date)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def add_assignment_db(
    assignment_id: str,
    course_name: str,
    title: str,
    due_date: str,
    description: str = "",
    ai_summary: str = "",
    status: str = "active"
) -> bool:
    """Додати або оновити дедлайн завдання (з підтримкою AI-вижимки)."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO assignments (id, course_id, title, due_date, description, ai_summary, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (assignment_id, course_name, title, due_date, description, ai_summary, status))
        await db.commit()
        return True


async def update_assignment_ai_summary_db(assignment_id: str, ai_summary: str) -> bool:
    """Оновити AI-вижимку для існуючого завдання."""
    async with get_db() as db:
        await db.execute("UPDATE assignments SET ai_summary = ? WHERE id = ?", (ai_summary, assignment_id))
        await db.commit()
        return True


async def cleanup_past_assignments_db():
    """Перевести старі завдання, дедлайн яких минув до поточного тижня, у статус 'archived'."""
    from datetime import datetime, timedelta
    from config import KYIV_TZ
    now = datetime.now(KYIV_TZ)
    monday_str = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d 00:00")

    async with get_db() as db:
        await db.execute("""
            UPDATE assignments
            SET status = 'archived'
            WHERE due_date != 'Без дедлайну' AND due_date < ?
        """, (monday_str,))
        await db.commit()


async def get_active_assignments_db() -> list[dict]:
    """Получить все активные задания, отсортированные по дедлайну."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, course_id, title, description, ai_summary, due_date, status
            FROM assignments
            WHERE status = 'active'
            ORDER BY due_date ASC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def delete_assignment_db(assignment_id: str) -> bool:
    """Удалить задание по id."""
    async with get_db() as db:
        await db.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
        await db.commit()
        return True


async def seed_demo_assignments_if_empty():
    """Заглушка: генерацію демо-дедлайнів вимкнено для реального використання."""
    pass


async def add_scheduled_deletion_db(chat_id: int, message_id: int, delete_at: str, tag: str = "digest"):
    """Зберегти повідомлення для автоматичного видалення після закінчення пар."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO scheduled_deletions (chat_id, message_id, delete_at, tag)
            VALUES (?, ?, ?, ?)
        """, (chat_id, message_id, delete_at, tag))
        await db.commit()


async def get_due_scheduled_deletions_db(current_time_str: str) -> list[dict]:
    """Отримати повідомлення, термін збереження яких закінчився."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, chat_id, message_id, delete_at, tag
            FROM scheduled_deletions
            WHERE delete_at <= ?
        """, (current_time_str,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def remove_scheduled_deletion_db(deletion_id: int):
    """Видалити повідомлення зі списку запланованого видалення."""
    async with get_db() as db:
        await db.execute("DELETE FROM scheduled_deletions WHERE id = ?", (deletion_id,))
        await db.commit()


# ==========================================
# РОЗПОДІЛ ВАРІАНТІВ ТА ТЕМ (/claim)
# ==========================================

async def claim_topic_db(
    chat_id: int,
    subject: str,
    variant_or_topic: str,
    user_id: int,
    user_name: str,
    username: str = None
) -> tuple[bool, str, dict | None]:
    """
    Зайняти варіант або тему.
    Запобігає колізіям (коли двоє хочуть один варіант).
    Якщо студент вже мав інший варіант у цьому предметі — змінює на новий.
    Повертає: (успіх: bool, повідомлення: str, попередній_власник: dict|None).
    """
    clean_subj = subject.strip()
    clean_var = variant_or_topic.strip()

    async with get_db() as db:
        # 1. Перевірка: чи не зайнятий цей варіант іншим користувачем
        async with db.execute("""
            SELECT id, user_id, user_name, username, claimed_at
            FROM topic_claims
            WHERE chat_id = ? AND subject = ? AND variant_or_topic = ?
        """, (chat_id, clean_subj, clean_var)) as cursor:
            existing = await cursor.fetchone()
            if existing:
                row = dict(existing)
                if row["user_id"] == user_id:
                    return True, f"Ви вже закріпили за собою варіант/тему «{clean_var}».", row
                holder = row["user_name"]
                if row.get("username"):
                    holder += f" (@{row['username']})"
                return False, f"Варіант/тема «{clean_var}» вже зайнятий(а) студентом {holder}!", row

        # 2. Якщо користувач вже займав інший варіант у цьому предметі, звільняємо старий
        await db.execute("""
            DELETE FROM topic_claims
            WHERE chat_id = ? AND subject = ? AND user_id = ?
        """, (chat_id, clean_subj, user_id))

        # 3. Закріплюємо новий варіант
        await db.execute("""
            INSERT INTO topic_claims (chat_id, subject, variant_or_topic, user_id, user_name, username)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, clean_subj, clean_var, user_id, user_name, username))
        await db.commit()

        return True, f"Успішно закріплено варіант/тему «{clean_var}» з предмету «{clean_subj}»!", None


async def unclaim_topic_db(chat_id: int, subject: str, user_id: int) -> bool:
    """Звільнити закріплений варіант/тему користувача."""
    clean_subj = subject.strip()
    async with get_db() as db:
        cursor = await db.execute("""
            DELETE FROM topic_claims
            WHERE chat_id = ? AND subject = ? AND user_id = ?
        """, (chat_id, clean_subj, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_claims_by_subject_db(chat_id: int, subject: str) -> list[dict]:
    """Отримати всі зайняті варіанти/теми з даного предмету."""
    clean_subj = subject.strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, subject, variant_or_topic, user_id, user_name, username, claimed_at
            FROM topic_claims
            WHERE chat_id = ? AND subject = ?
            ORDER BY variant_or_topic ASC
        """, (chat_id, clean_subj)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_free_variants_db(chat_id: int, subject: str, max_variants: int = 30) -> list[int]:
    """Знайти вільні числові варіанти (наприклад від 1 до 30) з предмету."""
    claims = await get_claims_by_subject_db(chat_id, subject)
    taken_numbers = set()
    for c in claims:
        var_str = c["variant_or_topic"].strip()
        if var_str.isdigit():
            taken_numbers.add(int(var_str))
        else:
            # Спроба витягти число з рядків типу "Варіант 5" чи "№5"
            import re
            m = re.search(r'\b\d+\b', var_str)
            if m:
                taken_numbers.add(int(m.group(0)))

    free_list = [i for i in range(1, max_variants + 1) if i not in taken_numbers]
    return free_list



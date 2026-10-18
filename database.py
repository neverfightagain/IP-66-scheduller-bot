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

        # 7. Таблиця пропозицій зміни розкладу з лекцій YouTube (AI-синхронізація)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedule_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_video_id TEXT,
                course_name TEXT,
                raw_announcement TEXT NOT NULL,
                change_type TEXT NOT NULL,
                target_date TEXT,
                pair_number INTEGER,
                details TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_schedule_proposals_status
            ON schedule_proposals (status);
        """)

        # 8. Таблиця скасованих пар
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cancelled_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                pair_number INTEGER NOT NULL,
                subject TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                cancelled_by TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (date, pair_number)
            );
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
# АВТОМАТИЧНА AI-СИНХРОНІЗАЦІЯ ОГОЛОШЕНЬ
# ==========================================

async def add_schedule_proposal_db(
    source_video_id: str | None,
    course_name: str,
    raw_announcement: str,
    change_type: str,
    target_date: str | None = None,
    pair_number: int | None = None,
    details: str = ""
) -> int:
    """Зберегти нову виявлену AI-пропозицію зміни розкладу."""
    async with get_db() as db:
        cursor = await db.execute("""
            INSERT INTO schedule_proposals (
                source_video_id, course_name, raw_announcement, change_type,
                target_date, pair_number, details, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (source_video_id, course_name.strip(), raw_announcement.strip(), change_type, target_date, pair_number, details.strip()))
        await db.commit()
        return cursor.lastrowid


async def get_pending_proposals_db() -> list[dict]:
    """Отримати список нерозглянутих AI-пропозицій зміни розкладу."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, source_video_id, course_name, raw_announcement, change_type,
                   target_date, pair_number, details, status, created_at
            FROM schedule_proposals
            WHERE status = 'pending'
            ORDER BY id ASC
        """) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def update_proposal_status_db(proposal_id: int, status: str) -> bool:
    """Оновити статус пропозиції ('approved' або 'rejected')."""
    async with get_db() as db:
        cursor = await db.execute("""
            UPDATE schedule_proposals
            SET status = ?
            WHERE id = ?
        """, (status, proposal_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_proposal_by_id_db(proposal_id: int) -> dict | None:
    """Отримати дані конкретної пропозиції."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, source_video_id, course_name, raw_announcement, change_type,
                   target_date, pair_number, details, status, created_at
            FROM schedule_proposals
            WHERE id = ?
        """, (proposal_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def cancel_pair_db(
    date_str: str,
    pair_number: int,
    subject: str = "",
    reason: str = "",
    cancelled_by: str = "Староста"
) -> bool:
    """Зафіксувати скасування пари на вказану дату."""
    clean_date = date_str.strip()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO cancelled_pairs (date, pair_number, subject, reason, cancelled_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(date, pair_number) DO UPDATE SET
                subject = excluded.subject,
                reason = excluded.reason,
                cancelled_by = excluded.cancelled_by,
                created_at = CURRENT_TIMESTAMP
        """, (clean_date, pair_number, subject.strip(), reason.strip(), cancelled_by.strip()))
        await db.commit()
        return True


async def get_cancelled_pairs_for_date_db(date_str: str) -> dict[int, dict]:
    """Отримати словник усіх скасованих пар на дату."""
    clean_date = date_str.strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, date, pair_number, subject, reason, cancelled_by, created_at
            FROM cancelled_pairs
            WHERE date = ?
        """, (clean_date,)) as cursor:
            rows = await cursor.fetchall()
            return {row["pair_number"]: dict(row) for row in rows}




from typing import Any, Optional
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
import aiosqlite
from config import (
    BASE_DIR,
    CHATS_FILE,
    LINKS_FILE,
    ENV_CHAT_ID,
    ENV_THREAD_ID,
    TURSO_DATABASE_URL,
    TURSO_AUTH_TOKEN,
    SQLITE_CLOUD_URL,
)

logger = logging.getLogger(__name__)

DB_PATH = BASE_DIR / "kpi_bot.db"


class TursoRow:
    """Обгортка над libsql_client.Row для повної сумісності з aiosqlite.Row."""
    def __init__(self, row):
        self._row = row
        self._dict = row.asdict()

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._dict[key]
        return self._row[key]

    def __iter__(self):
        return iter(self._dict.items())

    def __contains__(self, key):
        return key in self._dict

    def __repr__(self):
        return f"<TursoRow {self._dict}>"

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()


class TursoCursor:
    """Емулятор aiosqlite.Cursor для результатів Turso libSQL."""
    def __init__(self, result_set):
        self._result = result_set
        self.rows = [TursoRow(r) for r in result_set.rows]
        self.lastrowid = result_set.last_insert_rowid
        self.rowcount = result_set.rows_affected

    async def fetchall(self):
        return self.rows

    async def fetchone(self):
        return self.rows[0] if self.rows else None


class TursoCursorContext:
    """Дозволяє використовувати як `await db.execute(...)`, так і `async with db.execute(...) as cur:`."""
    def __init__(self, coro):
        self._coro = coro
        self._cursor = None

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        self._cursor = await self._coro
        return self._cursor

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class TursoConnectionWrapper:
    """Обгортка над клієнтом libsql_client.Client з API, ідентичним aiosqlite."""
    def __init__(self, client):
        self._client = client

    def execute(self, sql: str, params=None):
        async def _run():
            if params is None:
                res = await self._client.execute(sql)
            else:
                p = list(params) if isinstance(params, tuple) else params
                res = await self._client.execute(sql, p)
            return TursoCursor(res)
        return TursoCursorContext(_run())

    async def commit(self):
        # У libSQL (Turso) запити атомарно фіксуються сервером
        pass

    async def close(self):
        await self._client.close()


class SQLiteCloudRow:
    """Обгортка над sqlitecloud.Row для повної сумісності з aiosqlite.Row."""
    def __init__(self, row):
        self._row = row
        if hasattr(row, "keys"):
            self._dict = {k: row[k] for k in row.keys()}
        elif isinstance(row, dict):
            self._dict = row
        else:
            self._dict = {}

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._dict[key]
        return self._row[key]

    def __iter__(self):
        return iter(self._dict.items())

    def __contains__(self, key):
        return key in self._dict

    def __repr__(self):
        return f"<SQLiteCloudRow {self._dict}>"

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()


class SQLiteCloudCursor:
    """Емулятор aiosqlite.Cursor для sqlitecloud."""
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = getattr(cursor, "lastrowid", None)
        self.rowcount = getattr(cursor, "rowcount", 0)

    async def fetchall(self):
        rows = await asyncio.to_thread(self._cursor.fetchall)
        return [SQLiteCloudRow(r) for r in rows]

    async def fetchone(self):
        row = await asyncio.to_thread(self._cursor.fetchone)
        return SQLiteCloudRow(row) if row is not None else None


class SQLiteCloudConnectionWrapper:
    """Обгортка над sqlitecloud.Connection з API, ідентичним aiosqlite."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None):
        async def _run():
            cursor = self._conn.cursor()
            if params is None:
                await asyncio.to_thread(cursor.execute, sql)
            else:
                p = tuple(params) if isinstance(params, list) else params
                await asyncio.to_thread(cursor.execute, sql, p)
            return SQLiteCloudCursor(cursor)
        return TursoCursorContext(_run())

    async def commit(self):
        await asyncio.to_thread(self._conn.commit)

    async def close(self):
        await asyncio.to_thread(self._conn.close)


_turso_client: Optional[Any] = None
_sqlitecloud_conn: Optional[Any] = None


async def _get_turso_client():
    global _turso_client
    import libsql_client
    if _turso_client is None or getattr(_turso_client, "closed", False):
        url = TURSO_DATABASE_URL
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]

        token = TURSO_AUTH_TOKEN or None
        if not token:
            logger.error("❌ УВАГА: Задано TURSO_DATABASE_URL, але відсутній TURSO_AUTH_TOKEN в Environment Variables!")

        _turso_client = libsql_client.create_client(
            url=url,
            auth_token=token
        )
    return _turso_client


async def _get_sqlitecloud_conn():
    global _sqlitecloud_conn
    import sqlitecloud
    if _sqlitecloud_conn is None or not getattr(_sqlitecloud_conn, "is_connected", lambda: True)():
        _sqlitecloud_conn = await asyncio.to_thread(sqlitecloud.connect, SQLITE_CLOUD_URL)
    return _sqlitecloud_conn


@asynccontextmanager
async def get_db():
    """
    Контекстний менеджер підключення до бази даних.
    Підтримує:
    1. SQLite Cloud (якщо задано SQLITE_CLOUD_URL)
    2. Turso Cloud libSQL (якщо задано TURSO_DATABASE_URL)
    3. Локальну SQLite через aiosqlite (за замовчуванням)
    """
    if SQLITE_CLOUD_URL:
        conn = await _get_sqlitecloud_conn()
        yield SQLiteCloudConnectionWrapper(conn)
    elif TURSO_DATABASE_URL:
        client = await _get_turso_client()
        yield TursoConnectionWrapper(client)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA journal_mode = WAL;")
            await db.execute("PRAGMA foreign_keys = ON;")
            db.row_factory = aiosqlite.Row
            yield db


async def close_db():
    """Закрити активні з'єднання з базою даних."""
    global _turso_client, _sqlitecloud_conn
    if _turso_client is not None and not getattr(_turso_client, "closed", False):
        await _turso_client.close()
        _turso_client = None
    if _sqlitecloud_conn is not None:
        try:
            await asyncio.to_thread(_sqlitecloud_conn.close)
        except Exception:
            pass
        _sqlitecloud_conn = None


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

        # 7. Таблиця живої черги на захист лабораторних
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lab_queues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                user_name TEXT NOT NULL,
                username TEXT,
                lab_number TEXT DEFAULT '',
                lab_priority INTEGER DEFAULT 999,
                status TEXT DEFAULT 'waiting',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_lab_queues_active
            ON lab_queues (chat_id, subject);
        """)
        # Повне видалення будь-яких неактивних або застарілих записів
        await db.execute("DELETE FROM lab_queues WHERE status != 'waiting';")

        try:
            await db.execute("ALTER TABLE lab_queues ADD COLUMN lab_priority INTEGER DEFAULT 999;")
        except Exception:
            pass

        try:
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_lab_queues_priority
                ON lab_queues (chat_id, subject, lab_priority, id);
            """)
        except Exception:
            pass

        # 8. Таблиця скасованих пар старостою
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
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_cancelled_pairs_date
            ON cancelled_pairs (date);
        """)

        # 9. Таблиця автономного офлайн-кешу Campus API (Resilience Cache)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS campus_schedule_cache (
                group_id TEXT PRIMARY KEY,
                schedule_json TEXT NOT NULL,
                cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 10. Таблиця розподілу варіантів та тем робіт
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
        if SQLITE_CLOUD_URL:
            host = SQLITE_CLOUD_URL.split("@")[-1].split("?")[0]
            logger.info(f"База даних SQLite Cloud ({host}) успішно ініціалізована.")
        elif TURSO_DATABASE_URL:
            db_target = TURSO_DATABASE_URL.split("@")[-1]
            logger.info(f"База даних Turso Cloud libSQL ({db_target}) успішно ініціалізована.")
        else:
            logger.info("База даних SQLite (kpi_bot.db) успішно ініціалізована.")

        # Автоматическая миграция из старых JSON-файлов
        await _migrate_legacy_data(db)
        await db.execute("DELETE FROM assignments WHERE id IN ('op_lab1', 'asd_lab1', 'kdm_calc1')")
        await db.commit()
        await cleanup_past_assignments_db()


async def _migrate_legacy_data(db):
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
            targets = [{"chat_id": row["chat_id"], "thread_id": row["thread_id"]} for row in rows]
            if not targets and ENV_CHAT_ID:
                try:
                    cid = int(ENV_CHAT_ID)
                    tid = int(ENV_THREAD_ID) if ENV_THREAD_ID else None
                    targets = [{"chat_id": cid, "thread_id": tid}]
                except ValueError:
                    pass
            return targets


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


async def get_all_assignments_map_db() -> dict[str, dict]:
    """Отримати мапу ВСІХ завдань (активних і архівованих) для запобігання повторних викликів AI."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, course_id, title, description, ai_summary, due_date, status
            FROM assignments
        """) as cursor:
            rows = await cursor.fetchall()
            return {row["id"]: dict(row) for row in rows}


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
# ЖИВА ЧЕРГА НА ЗАХИСТ ЛАБОРАТОРНИХ
# ==========================================

def parse_lab_info(lab_raw: str | None) -> tuple[int, str]:
    """
    Визначає пріоритет роботи (найменший номер серед усіх обраних) та нормалізовану назву.
    Підтримує вибір кількох робіт (наприклад: '1, 4' -> пріоритет 1, назва 'Лаби 1, 4').
    Чим менший номер роботи (старіша практична робота), тим вищий пріоритет (менше число).
    Повертає (priority, normalized_name).
    """
    if not lab_raw:
        return 999, ""
    raw = str(lab_raw).strip()
    if not raw:
        return 999, ""
    matches = re.findall(r'\d+', raw)
    if matches:
        nums = sorted(list(set(int(m) for m in matches)))
        min_num = nums[0]
        if len(nums) == 1:
            if raw == str(min_num):
                name = f"Лаба {min_num}"
            else:
                name = raw
        else:
            name = f"Лаби {', '.join(str(n) for n in nums)}"
        return min_num, name
    return 999, raw


async def join_queue_db(
    chat_id: int,
    subject: str,
    user_id: int,
    user_name: str,
    username: str = None,
    lab_number: str = ""
) -> tuple[bool, str, int]:
    """
    Додати студента до живої черги.
    Гарантує відсутність спаму (один студент займає лише 1 місце в черзі з предмету).
    Пріоритет черги: старіші практичні роботи (менший номер) піднімаються нагору!
    При однаковому номері діє FIFO (хто раніше зайняв).
    Якщо студент уже в черзі, оновлює номер лаби та перераховує його позицію за пріоритетом.
    Повертає (успіх, повідомлення, позиція_в_черзі).
    """
    subject_clean = (subject or "ОП").strip()[:50]
    clean_name = (user_name or "Студент").strip()[:100]
    priority, clean_lab = parse_lab_info(lab_number)

    async with get_db() as db:
        # Перевірка чи вже є у черзі
        async with db.execute("""
            SELECT id, lab_number, lab_priority FROM lab_queues
            WHERE chat_id = ? AND subject = ? AND user_id = ?
        """, (chat_id, subject_clean, user_id)) as cursor:
            existing = await cursor.fetchone()
            if existing:
                existing_dict = dict(existing)
                existing_id = existing_dict["id"]
                current_p = existing_dict.get("lab_priority") or 999
                current_lab = existing_dict.get("lab_number") or ""

                # Якщо передано новий номер лаби і він відрізняється — оновлюємо
                if clean_lab and (clean_lab != current_lab or priority != current_p):
                    await db.execute("""
                        UPDATE lab_queues
                        SET lab_number = ?, lab_priority = ?, user_name = ?, username = ?
                        WHERE id = ?
                    """, (clean_lab, priority, clean_name, username, existing_id))
                    await db.commit()
                    target_priority = priority
                else:
                    target_priority = current_p

                # Визначаємо поточну позицію з урахуванням пріоритету (lab_priority ASC, id ASC)
                async with db.execute("""
                    SELECT COUNT(*) as pos FROM lab_queues
                    WHERE chat_id = ? AND subject = ? 
                      AND (lab_priority < ? OR (lab_priority = ? AND id <= ?))
                """, (chat_id, subject_clean, target_priority, target_priority, existing_id)) as pos_cursor:
                    row = await pos_cursor.fetchone()
                    pos = row["pos"] if row else 1

                if clean_lab and (clean_lab != current_lab or priority != current_p):
                    return True, f"Ви вже у черзі. Роботу оновлено: {clean_lab}. Ваша нова позиція: #{pos}", pos

                return False, f"Ви вже знаходитесь у черзі на позиції #{pos}.", pos

        # Додаємо нового учасника (гарантовано 1 актуальний запис)
        cursor = await db.execute("""
            INSERT INTO lab_queues (chat_id, subject, user_id, user_name, username, lab_number, lab_priority, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting')
        """, (chat_id, subject_clean, user_id, clean_name, username, clean_lab, priority))
        await db.commit()
        new_id = cursor.lastrowid

        # Рахуємо позицію (lab_priority ASC, id ASC)
        async with db.execute("""
            SELECT COUNT(*) as pos FROM lab_queues
            WHERE chat_id = ? AND subject = ? 
              AND (lab_priority < ? OR (lab_priority = ? AND id <= ?))
        """, (chat_id, subject_clean, priority, priority, new_id)) as pos_cursor:
            row = await pos_cursor.fetchone()
            pos = row["pos"] if row else 1

        return True, "Успішно додано до черги!", pos


async def leave_queue_db(chat_id: int, subject: str, user_id: int) -> bool:
    """Видалити студента з черги (фізичне повне видалення з бази даних)."""
    subject_clean = (subject or "ОП").strip()
    async with get_db() as db:
        cursor = await db.execute("""
            DELETE FROM lab_queues
            WHERE chat_id = ? AND subject = ? AND user_id = ?
        """, (chat_id, subject_clean, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_active_queue_db(chat_id: int, subject: str = None) -> list[dict]:
    """Отримати поточний список студентів у черзі (старіші роботи першими)."""
    subject_clean = (subject or "ОП").strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, chat_id, subject, user_id, user_name, username, lab_number, lab_priority, status, joined_at
            FROM lab_queues
            WHERE chat_id = ? AND subject = ?
            ORDER BY lab_priority ASC, id ASC
        """, (chat_id, subject_clean)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def next_in_queue_db(chat_id: int, subject: str = None) -> dict | None:
    """Перевести наступного студента на захист і видалити його запис з черги."""
    subject_clean = (subject or "ОП").strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, chat_id, subject, user_id, user_name, username, lab_number, lab_priority, joined_at
            FROM lab_queues
            WHERE chat_id = ? AND subject = ?
            ORDER BY lab_priority ASC, id ASC
            LIMIT 1
        """, (chat_id, subject_clean)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            student = dict(row)

        await db.execute("""
            DELETE FROM lab_queues
            WHERE id = ?
        """, (student["id"],))
        await db.commit()
        return student


async def clear_queue_db(chat_id: int, subject: str = None) -> int:
    """Повністю очистити активну чергу (фізичне видалення всіх записів предмету)."""
    subject_clean = (subject or "ОП").strip()
    async with get_db() as db:
        cursor = await db.execute("""
            DELETE FROM lab_queues
            WHERE chat_id = ? AND subject = ?
        """, (chat_id, subject_clean))
        await db.commit()
        return cursor.rowcount


# ==========================================
# СКАСУВАННЯ ПАР СТАРОСТОЮ (/cancel_pair)
# ==========================================

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


async def uncancel_pair_db(date_str: str, pair_number: int) -> bool:
    """Відновити скасовану пару (зняти скасування)."""
    clean_date = date_str.strip()
    async with get_db() as db:
        cursor = await db.execute("""
            DELETE FROM cancelled_pairs
            WHERE date = ? AND pair_number = ?
        """, (clean_date, pair_number))
        await db.commit()
        return cursor.rowcount > 0


async def get_cancelled_pairs_for_date_db(date_str: str) -> dict[int, dict]:
    """Отримати словник усіх скасованих пар на дату {номер_пари: {інформація}}."""
    clean_date = date_str.strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, date, pair_number, subject, reason, cancelled_by, created_at
            FROM cancelled_pairs
            WHERE date = ?
        """, (clean_date,)) as cursor:
            rows = await cursor.fetchall()
            return {row["pair_number"]: dict(row) for row in rows}


async def is_pair_cancelled_db(date_str: str, pair_number: int) -> tuple[bool, str]:
    """Перевірити, чи скасована пара. Повертає (скасовано: bool, причина: str)."""
    clean_date = date_str.strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT reason FROM cancelled_pairs
            WHERE date = ? AND pair_number = ?
        """, (clean_date, pair_number)) as cursor:
            row = await cursor.fetchone()
            if row:
                return True, row["reason"] or "Причину не вказано"
            return False, ""


# ==========================================
# АВТОНОМНИЙ ОФЛАЙН-КЕШ CAMPUS API
# ==========================================

async def save_campus_schedule_cache_db(group_id: str | int, schedule_data: dict):
    """Зберегти знімок розкладу в офлайн-кеш SQLite."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO campus_schedule_cache (group_id, schedule_json, cached_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id) DO UPDATE SET
                schedule_json = excluded.schedule_json,
                cached_at = CURRENT_TIMESTAMP
        """, (str(group_id), json.dumps(schedule_data, ensure_ascii=False)))
        await db.commit()


async def get_campus_schedule_cache_db(group_id: str | int) -> tuple[dict | None, str | None]:
    """
    Отримати останній збережений кеш розкладу для групи.
    Повертає: (дані_розкладу: dict | None, дата_кешування: str | None).
    """
    async with get_db() as db:
        async with db.execute("""
            SELECT schedule_json, cached_at
            FROM campus_schedule_cache
            WHERE group_id = ?
        """, (str(group_id),)) as cursor:
            row = await cursor.fetchone()
            if row:
                try:
                    data = json.loads(row["schedule_json"])
                    return data, str(row["cached_at"])
                except Exception:
                    return None, None
            return None, None


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



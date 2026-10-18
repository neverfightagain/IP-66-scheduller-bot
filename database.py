from typing import Any, Optional
import asyncio
import json
import logging
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
        _turso_client = libsql_client.create_client(
            url=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN or None
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


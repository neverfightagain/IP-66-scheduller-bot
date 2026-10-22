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
    OWNER_ID,
    OWNER_USERNAMES,
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
        try:
            await db.execute("ALTER TABLE assignments ADD COLUMN alternate_link TEXT;")
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

        # 7.1. Таблиця зв'язку чату та ID останнього повідомлення черги (для live-sync з Mini App)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS queue_chat_messages (
                chat_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                subject TEXT DEFAULT 'ОП',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

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
        # 11. Таблиця списку студентів групи (справжні імена та прив'язка до Telegram)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                real_name TEXT NOT NULL,
                telegram_username TEXT,
                telegram_id INTEGER,
                subgroup INTEGER DEFAULT 1,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_students_username
            ON students (telegram_username);
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_students_tg_id
            ON students (telegram_id);
        """)

        # 12. Таблиця історії захищених лабораторних робіт (AI-детекція та автовилучення з черги)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lab_defenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                real_name TEXT NOT NULL,
                telegram_id INTEGER,
                subject TEXT NOT NULL,
                lab_number TEXT NOT NULL,
                video_id TEXT,
                timestamp_sec INTEGER DEFAULT 0,
                exact_quote TEXT,
                status TEXT DEFAULT 'passed',
                confirmed INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_lab_defenses_student
            ON lab_defenses (telegram_id, subject);
        """)

        # 13. Таблиця ролей адміністраторів (Староста, Замстарости)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                real_name TEXT DEFAULT '',
                role TEXT NOT NULL DEFAULT 'deputy',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 14. Таблиця налаштувань додатку (app_settings)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        # 15. Таблиця додаткових або перенесених пар (custom_lessons)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                pair_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'Практика',
                lecturer TEXT DEFAULT '',
                time TEXT NOT NULL,
                location TEXT DEFAULT 'Онлайн',
                link_url TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_custom_lessons_date
            ON custom_lessons (date);
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

        # Автоматичне вилучення кураторів із реєстру студентів (вони не навчаються в групі)
        await db.execute("DELETE FROM students WHERE LOWER(real_name) LIKE '%куратор%'")
        await db.commit()

        # Автоматичний первинний імпорт списку групи з STUDENTS_ROSTER_JSON або students_roster.json
        from config import STUDENTS_ROSTER_JSON
        roster_data = None
        if STUDENTS_ROSTER_JSON:
            try:
                roster_data = json.loads(STUDENTS_ROSTER_JSON)
            except Exception as e_json:
                logger.warning(f"Не вдалося розпарсити STUDENTS_ROSTER_JSON з env: {e_json}")

        if not roster_data:
            roster_file = BASE_DIR / "students_roster.json"
            if roster_file.exists():
                try:
                    with open(roster_file, encoding="utf-8") as rf:
                        roster_data = json.load(rf)
                except Exception:
                    pass

        if roster_data:
            try:
                async with db.execute("SELECT COUNT(*) as cnt FROM students WHERE LOWER(real_name) NOT LIKE '%куратор%'") as cur:
                    row = await cur.fetchone()
                    if row and row["cnt"] == 0:
                        for item in roster_data:
                            rname = item.get("real_name", "")
                            if "куратор" in rname.lower():
                                continue
                            notes = item.get("notes", "")
                            if not notes and item.get("birthdate"):
                                notes = f"Д/Н: {item['birthdate']}"
                            await db.execute("""
                                INSERT INTO students (real_name, telegram_username, subgroup, notes)
                                VALUES (?, ?, ?, ?)
                            """, (rname, item.get("telegram_username"), item.get("subgroup", 1), notes))
                        await db.commit()
                        logger.info(f"Успішно імпортовано студентів з реєстру.")
            except Exception as e_rost:
                logger.warning(f"Не вдалося імпортувати студентів: {e_rost}")


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
    status: str = "active",
    alternate_link: str = ""
) -> bool:
    """Додати або оновити дедлайн завдання (з підтримкою AI-вижимки та посилання)."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO assignments (id, course_id, title, due_date, description, ai_summary, status, alternate_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (assignment_id, course_name, title, due_date, description, ai_summary, status, alternate_link))
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
        try:
            async with db.execute("""
                SELECT id, course_id, title, description, ai_summary, due_date, status, alternate_link
                FROM assignments
                WHERE status = 'active'
                ORDER BY due_date ASC
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
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
        try:
            async with db.execute("""
                SELECT id, course_id, title, description, ai_summary, due_date, status, alternate_link
                FROM assignments
            """) as cursor:
                rows = await cursor.fetchall()
                return {row["id"]: dict(row) for row in rows}
        except Exception:
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

async def has_alert_been_sent_db(alert_key: str) -> bool:
    """Перевіряє, чи було надіслано сповіщення з даним ключем (персистентно в БД)."""
    async with get_db() as db:
        # 1. Перевіряємо в app_settings
        async with db.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (f"sent_alert:{alert_key}",)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return True

        # 2. Додатковий захист для ранкового дайджесту через scheduled_deletions
        if alert_key.startswith("morning_digest_"):
            date_part = alert_key.replace("morning_digest_", "").strip()
            if date_part:
                async with db.execute(
                    "SELECT id FROM scheduled_deletions WHERE tag = 'morning_digest' AND delete_at LIKE ? LIMIT 1",
                    (f"{date_part}%",)
                ) as cur:
                    del_row = await cur.fetchone()
                    if del_row:
                        return True
    return False


async def mark_alert_sent_db(alert_key: str) -> None:
    """Записує ключ надісланого сповіщення в app_settings."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO app_settings (key, value)
            VALUES (?, '1')
            ON CONFLICT(key) DO UPDATE SET value = '1'
        """, (f"sent_alert:{alert_key}",))
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


PATRONYMIC_SUFFIXES = ("вич", "вна", "івич", "івна", "ович", "овна", "євич", "ївна", "євна")


def parse_person_name(full_name: str) -> tuple[str, str, str]:
    """
    Розбирає повне ім'я на (прізвище, ім'я, по_батькові).
    Підтримує:
    - 'Сінчіневіч Максим Ігорович' -> ('Сінчіневіч', 'Максим', 'Ігорович')
    - 'Сахнюк Володимирович Дмитро' -> ('Сахнюк', 'Дмитро', 'Володимирович')
    - 'Куратор Рома' -> ('Куратор', 'Рома', '')
    - 'Максим' -> ('', 'Максим', '')
    """
    if not full_name:
        return "", "", ""
    parts = full_name.strip().split()
    if not parts:
        return "", "", ""
    if parts[0].lower() == "куратор":
        return "Куратор", " ".join(parts[1:]), ""
    if len(parts) == 1:
        return "", parts[0], ""
    if len(parts) >= 3:
        if parts[1].lower().endswith(PATRONYMIC_SUFFIXES) and not parts[2].lower().endswith(PATRONYMIC_SUFFIXES):
            return parts[0], parts[2], parts[1]
        return parts[0], parts[1], parts[2]
    return parts[0], parts[1], ""


def format_queue_name(full_name: str) -> str:
    """
    Повертає 'Прізвище Ім'я' без по-батькові для відображення в черзі.
    """
    if not full_name:
        return ""
    surname, name, _ = parse_person_name(full_name)
    if surname == "Куратор":
        return f"Куратор {name}"
    if surname and name:
        return f"{surname} {name}"
    return name or surname or full_name.strip()


def extract_first_name(full_name: str) -> str:
    """
    Повертає суто ім'я для привітання на головному екрані (без прізвища та по-батькові).
    """
    if not full_name:
        return "Студент"
    surname, name, _ = parse_person_name(full_name)
    return name or surname or full_name.strip() or "Студент"


async def join_queue_db(
    chat_id: int,
    subject: str,
    user_id: int,
    user_name: str,
    username: str = None,
    lab_number: str = "",
    append: bool = False
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

    # Автоматична заміна на справжнє ім'я зі списку групи, якщо студент є в базі
    try:
        real_name_match = await find_student_real_name_db(user_id=user_id, telegram_username=username)
        if real_name_match:
            clean_name = format_queue_name(real_name_match)
        else:
            clean_name = format_queue_name(clean_name)
    except Exception:
        clean_name = format_queue_name(clean_name)

    clean_uname = username.lstrip("@").strip().lower() if username else None
    roster_id = None
    try:
        async with get_db() as db:
            if user_id:
                async with db.execute("SELECT id FROM students WHERE telegram_id = ? LIMIT 1", (user_id,)) as cur:
                    r = await cur.fetchone()
                    if r:
                        roster_id = r["id"]
            if not roster_id and clean_uname:
                async with db.execute("SELECT id FROM students WHERE LOWER(telegram_username) = ? LIMIT 1", (clean_uname,)) as cur:
                    r = await cur.fetchone()
                    if r:
                        roster_id = r["id"]
    except Exception:
        pass

    async with get_db() as db:
        # Перевірка чи вже є у черзі (за user_id, roster_id або username)
        if clean_uname and roster_id:
            async with db.execute("""
                SELECT id, user_id, lab_number, lab_priority FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (user_id = ? OR user_id = ? OR (username IS NOT NULL AND LOWER(username) = ?))
                ORDER BY id ASC LIMIT 1
            """, (chat_id, subject_clean, user_id, roster_id, clean_uname)) as cursor:
                existing = await cursor.fetchone()
        elif clean_uname:
            async with db.execute("""
                SELECT id, user_id, lab_number, lab_priority FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (user_id = ? OR (username IS NOT NULL AND LOWER(username) = ?))
                ORDER BY id ASC LIMIT 1
            """, (chat_id, subject_clean, user_id, clean_uname)) as cursor:
                existing = await cursor.fetchone()
        elif roster_id:
            async with db.execute("""
                SELECT id, user_id, lab_number, lab_priority FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (user_id = ? OR user_id = ?)
                ORDER BY id ASC LIMIT 1
            """, (chat_id, subject_clean, user_id, roster_id)) as cursor:
                existing = await cursor.fetchone()
        else:
            async with db.execute("""
                SELECT id, user_id, lab_number, lab_priority FROM lab_queues
                WHERE chat_id = ? AND subject = ? AND user_id = ?
                LIMIT 1
            """, (chat_id, subject_clean, user_id)) as cursor:
                existing = await cursor.fetchone()

        if existing:
            existing_dict = dict(existing)
            existing_id = existing_dict["id"]
            current_p = existing_dict.get("lab_priority") or 999
            current_lab = existing_dict.get("lab_number") or ""

            # Якщо увімкнено режим додавання (append), об'єднуємо поточні роботи з новими
            if append and current_lab and clean_lab:
                cur_nums = set(map(int, re.findall(r'\d+', current_lab)))
                new_nums = set(map(int, re.findall(r'\d+', clean_lab)))
                combined_nums = sorted(list(cur_nums.union(new_nums)))
                if combined_nums:
                    priority = combined_nums[0]
                    if len(combined_nums) == 1:
                        clean_lab = f"Лаба {combined_nums[0]}"
                    else:
                        clean_lab = f"Лаби {', '.join(str(n) for n in combined_nums)}"

            # Якщо передано новий номер лаби і він відрізняється — оновлюємо
            if clean_lab and (clean_lab != current_lab or priority != current_p):
                # КРИТИЧНО: Якщо пріоритет погіршився (наприклад, було {1, 5} з пріоритетом 1, а прибрали 1 і лишили 5):
                # Студент не залишається першим! Він стає в кінець черги для нового пріоритету (5)!
                if priority > current_p:
                    await db.execute("DELETE FROM lab_queues WHERE id = ?", (existing_id,))
                    cursor = await db.execute("""
                        INSERT INTO lab_queues (chat_id, subject, user_id, user_name, username, lab_number, lab_priority, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting')
                    """, (chat_id, subject_clean, user_id, clean_name, username, clean_lab, priority))
                    await db.commit()
                    target_id = cursor.lastrowid
                else:
                    # Пріоритет зберігся або покращився -> початкове місце і id зберігаються!
                    await db.execute("""
                        UPDATE lab_queues
                        SET lab_number = ?, lab_priority = ?, user_id = ?, user_name = ?, username = ?
                        WHERE id = ?
                    """, (clean_lab, priority, user_id, clean_name, username, existing_id))
                    await db.commit()
                    target_id = existing_id
                target_priority = priority
            else:
                target_id = existing_id
                target_priority = current_p

            # Визначаємо поточну позицію з урахуванням пріоритету (lab_priority ASC, id ASC)
            async with db.execute("""
                SELECT COUNT(*) as pos FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (lab_priority < ? OR (lab_priority = ? AND id <= ?))
            """, (chat_id, subject_clean, target_priority, target_priority, target_id)) as pos_cursor:
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


async def leave_queue_db(chat_id: int, subject: str, user_id: int, username: str = None) -> bool:
    """Видалити студента з черги (фізичне повне видалення з бази даних)."""
    subject_clean = (subject or "ОП").strip()
    clean_uname = username.lstrip("@").strip().lower() if username else None
    roster_id = None
    try:
        async with get_db() as db:
            if user_id:
                async with db.execute("SELECT id FROM students WHERE telegram_id = ? LIMIT 1", (user_id,)) as cur:
                    r = await cur.fetchone()
                    if r:
                        roster_id = r["id"]
            if not roster_id and clean_uname:
                async with db.execute("SELECT id FROM students WHERE LOWER(telegram_username) = ? LIMIT 1", (clean_uname,)) as cur:
                    r = await cur.fetchone()
                    if r:
                        roster_id = r["id"]
    except Exception:
        pass

    async with get_db() as db:
        if clean_uname and roster_id:
            cursor = await db.execute("""
                DELETE FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (user_id = ? OR user_id = ? OR (username IS NOT NULL AND LOWER(username) = ?))
            """, (chat_id, subject_clean, user_id, roster_id, clean_uname))
        elif clean_uname:
            cursor = await db.execute("""
                DELETE FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (user_id = ? OR (username IS NOT NULL AND LOWER(username) = ?))
            """, (chat_id, subject_clean, user_id, clean_uname))
        elif roster_id:
            cursor = await db.execute("""
                DELETE FROM lab_queues
                WHERE chat_id = ? AND subject = ? 
                  AND (user_id = ? OR user_id = ?)
            """, (chat_id, subject_clean, user_id, roster_id))
        else:
            cursor = await db.execute("""
                DELETE FROM lab_queues
                WHERE chat_id = ? AND subject = ? AND user_id = ?
            """, (chat_id, subject_clean, user_id))
        await db.commit()
        return cursor.rowcount > 0


async def get_active_queue_db(chat_id: int, subject: str = None) -> list[dict]:
    """Отримати поточний список студентів у черзі (старіші роботи першими, без по-батькові)."""
    subject_clean = (subject or "ОП").strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, chat_id, subject, user_id, user_name, username, lab_number, lab_priority, status, joined_at
            FROM lab_queues
            WHERE chat_id = ? AND subject = ?
            ORDER BY lab_priority ASC, id ASC
        """, (chat_id, subject_clean)) as cursor:
            rows = await cursor.fetchall()
            items = []
            for r in rows:
                item = dict(r)
                if item.get("user_name"):
                    item["user_name"] = format_queue_name(item["user_name"])
                items.append(item)
            return items


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
            if student.get("user_name"):
                student["user_name"] = format_queue_name(student["user_name"])

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


async def set_queue_message_id_db(chat_id: int, message_id: int, subject: str = "ОП") -> None:
    """Зберегти або оновити ID останнього активного повідомлення черги в чаті."""
    clean_subj = (subject or "ОП").strip()
    async with get_db() as db:
        await db.execute("""
            INSERT INTO queue_chat_messages (chat_id, message_id, subject, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                message_id = excluded.message_id,
                subject = excluded.subject,
                updated_at = CURRENT_TIMESTAMP;
        """, (chat_id, message_id, clean_subj))
        await db.commit()


async def get_queue_message_id_db(chat_id: int) -> dict | None:
    """Отримати ID останнього повідомлення черги для чату."""
    async with get_db() as db:
        async with db.execute("""
            SELECT chat_id, message_id, subject, updated_at
            FROM queue_chat_messages
            WHERE chat_id = ?
        """, (chat_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


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


# ==============================================================================
# 11. Студентський список групи (Roster: реальні імена та прив'язка до Telegram)
# ==============================================================================

async def add_or_update_student_db(
    real_name: str,
    telegram_username: str = None,
    telegram_id: int = None,
    subgroup: int = 1,
    notes: str = ""
) -> bool:
    """Додати або оновити студента в списку групи."""
    clean_real_name = (real_name or "").strip()
    if not clean_real_name:
        return False
    clean_username = telegram_username.lstrip("@").strip().lower() if telegram_username else None

    async with get_db() as db:
        existing_id = None
        if telegram_id:
            async with db.execute("SELECT id FROM students WHERE telegram_id = ?", (telegram_id,)) as cur:
                row = await cur.fetchone()
                if row:
                    existing_id = row["id"]

        if not existing_id and clean_username:
            async with db.execute("SELECT id FROM students WHERE LOWER(telegram_username) = ?", (clean_username,)) as cur:
                row = await cur.fetchone()
                if row:
                    existing_id = row["id"]

        if not existing_id:
            async with db.execute("SELECT id FROM students WHERE LOWER(real_name) = ?", (clean_real_name.lower(),)) as cur:
                row = await cur.fetchone()
                if row:
                    existing_id = row["id"]

        if existing_id:
            await db.execute("""
                UPDATE students
                SET real_name = ?,
                    telegram_username = COALESCE(?, telegram_username),
                    telegram_id = COALESCE(?, telegram_id),
                    subgroup = ?,
                    notes = ?
                WHERE id = ?
            """, (clean_real_name, clean_username, telegram_id, subgroup, notes, existing_id))
        else:
            await db.execute("""
                INSERT INTO students (real_name, telegram_username, telegram_id, subgroup, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (clean_real_name, clean_username, telegram_id, subgroup, notes))

        await db.commit()
        return True


async def get_all_students_db() -> list[dict]:
    """Отримати повний список студентів групи (без кураторів), відсортований за підгрупою та іменем."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, real_name, telegram_username, telegram_id, subgroup, notes, created_at
            FROM students
            WHERE LOWER(real_name) NOT LIKE '%куратор%'
            ORDER BY subgroup ASC, real_name ASC
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def find_student_real_name_db(user_id: int = None, telegram_username: str = None) -> str | None:
    """Знайти справжнє ім'я студента за telegram_id або username."""
    clean_uname = telegram_username.lstrip("@").strip().lower() if telegram_username else None
    async with get_db() as db:
        if user_id:
            async with db.execute("SELECT real_name FROM students WHERE telegram_id = ? LIMIT 1", (user_id,)) as cur:
                row = await cur.fetchone()
                if row and row["real_name"]:
                    return row["real_name"]

        if clean_uname:
            async with db.execute("SELECT id, real_name, telegram_id FROM students WHERE LOWER(telegram_username) = ? LIMIT 1", (clean_uname,)) as cur:
                row = await cur.fetchone()
                if row and row["real_name"]:
                    # Автоматично запам'ятовуємо telegram_id для подальших входів
                    if user_id and not row.get("telegram_id"):
                        try:
                            await db.execute("UPDATE students SET telegram_id = ? WHERE id = ?", (user_id, row["id"]))
                            await db.commit()
                        except Exception:
                            pass
                    return row["real_name"]

    return None


async def bulk_import_students_db(students_list: list[dict]) -> int:
    """Масовий імпорт списку студентів з таблиці/словника (пропускаючи кураторів)."""
    count = 0
    for s in students_list:
        rname = s.get("real_name") or s.get("name") or ""
        if "куратор" in rname.lower():
            continue
        uname = s.get("telegram_username") or s.get("username")
        tg_id = s.get("telegram_id") or s.get("user_id")
        try:
            subg = int(s.get("subgroup") or 1)
        except Exception:
            subg = 1
        notes = s.get("notes") or ""
        if rname:
            ok = await add_or_update_student_db(rname, uname, tg_id, subg, notes)
            if ok:
                count += 1
    return count


def normalize_queue_subject(subject_raw: str | None) -> str:
    """Нормалізація назви предмету для черги (підтримує аліаси для ОП та АСД)."""
    if not subject_raw:
        return ""
    clean = subject_raw.strip()
    lower = clean.lower()
    if lower in ("op", "оп", "основи програмування", "програмування", "queue_op", "join_op", "op_queue") or "основ" in lower:
        return "ОП"
    if lower in ("asd", "асд", "аісд", "алгоритми", "алгоритми та структури даних", "алгоритми і структури даних", "queue_asd", "join_asd", "asd_queue") or "алгоритм" in lower:
        return "АСД"
    return clean


async def record_lab_defense_db(
    real_name: str,
    subject: str,
    lab_number: str,
    student_id: int | None = None,
    telegram_id: int | None = None,
    video_id: str = "",
    timestamp_sec: int = 0,
    exact_quote: str = "",
    status: str = "passed",
    confirmed: int = 1
) -> int:
    """Записати факт здачі/захисту лабораторної роботи."""
    clean_subj = normalize_queue_subject(subject)
    clean_lab = lab_number.strip()
    clean_name = real_name.strip()

    async with get_db() as db:
        # Перевіряємо чи вже не було зафіксовано цей самий захист
        async with db.execute("""
            SELECT id FROM lab_defenses 
            WHERE real_name = ? AND subject = ? AND lab_number = ? AND status = 'passed'
            LIMIT 1
        """, (clean_name, clean_subj, clean_lab)) as cur:
            existing = await cur.fetchone()
            if existing:
                return existing["id"]

        cursor = await db.execute("""
            INSERT INTO lab_defenses (
                student_id, real_name, telegram_id, subject, lab_number,
                video_id, timestamp_sec, exact_quote, status, confirmed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_id, clean_name, telegram_id, clean_subj, clean_lab,
            video_id, timestamp_sec, exact_quote, status, confirmed
        ))
        await db.commit()
        return cursor.lastrowid if hasattr(cursor, "lastrowid") else 1


async def get_lab_defense_by_id_db(defense_id: int) -> dict | None:
    """Отримати запис про захист роботи за його ID."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, student_id, real_name, telegram_id, subject, lab_number,
                   video_id, timestamp_sec, exact_quote, status, confirmed, created_at
            FROM lab_defenses
            WHERE id = ?
        """, (defense_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def confirm_lab_defense_db(defense_id: int) -> dict | None:
    """Підтвердити захист роботи (перевести confirmed = 1)."""
    async with get_db() as db:
        await db.execute("""
            UPDATE lab_defenses
            SET confirmed = 1, status = 'passed'
            WHERE id = ?
        """, (defense_id,))
        await db.commit()
    return await get_lab_defense_by_id_db(defense_id)


async def reject_lab_defense_db(defense_id: int) -> bool:
    """Відхилити/скасувати зафіксований захист роботи."""
    async with get_db() as db:
        cur = await db.execute("""
            UPDATE lab_defenses
            SET status = 'rejected', confirmed = 0
            WHERE id = ?
        """, (defense_id,))
        await db.commit()
        return cur.rowcount > 0


async def get_student_queue_positions_db(user_id: int, subject: str) -> list[dict]:
    """
    Повертає список позицій студента у чергах по всіх чатах:
    [{'chat_id': int, 'position': int, 'lab_number': str}]
    """
    clean_subj = normalize_queue_subject(subject)
    positions = []
    async with get_db() as db:
        async with db.execute("""
            SELECT DISTINCT chat_id FROM lab_queues WHERE subject = ? AND user_id = ?
        """, (clean_subj, user_id)) as cur:
            chat_rows = await cur.fetchall()
            chat_ids = [r["chat_id"] for r in chat_rows]

    for cid in chat_ids:
        q_items = await get_active_queue_db(cid, clean_subj)
        for idx, item in enumerate(q_items, start=1):
            if item["user_id"] == user_id:
                positions.append({
                    "chat_id": cid,
                    "position": idx,
                    "lab_number": item.get("lab_number") or ""
                })
                break
    return positions


async def get_all_defenses_summary_db(subject: str | None = None) -> list[dict]:
    """Отримати всі підтверджені здачі робіт для всіх студентів (для зведеного табло в Mini App)."""
    async with get_db() as db:
        query = """
            SELECT id, student_id, real_name, telegram_id, subject, lab_number,
                   video_id, timestamp_sec, exact_quote, status, confirmed, created_at
            FROM lab_defenses
            WHERE status = 'passed' AND confirmed = 1
        """
        params = []
        if subject:
            clean_subj = normalize_queue_subject(subject)
            query += " AND subject = ?"
            params.append(clean_subj)

        query += " ORDER BY id ASC"
        async with db.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def toggle_student_lab_defense_db(real_name: str, subject: str, lab_number: str, telegram_id: int | None = None) -> dict:
    """Перемкнути статус зарахування роботи студента (ручна відмітка в Mini App)."""
    clean_subj = normalize_queue_subject(subject)
    clean_lab = lab_number.strip()
    clean_name = real_name.strip()
    num_match = re.search(r'\d+', clean_lab)
    digit_str = num_match.group(0) if num_match else clean_lab

    async with get_db() as db:
        async with db.execute("""
            SELECT id, status, confirmed FROM lab_defenses
            WHERE (real_name = ? OR (telegram_id IS NOT NULL AND telegram_id != 0 AND telegram_id = ?))
              AND subject = ?
              AND (lab_number = ? OR lab_number LIKE '%' || ? || '%')
            LIMIT 1
        """, (clean_name, telegram_id or 0, clean_subj, clean_lab, digit_str)) as cur:
            existing = await cur.fetchone()
            if existing:
                await db.execute("DELETE FROM lab_defenses WHERE id = ?", (existing["id"],))
                await db.commit()
                return {"passed": False, "action": "removed"}

        cursor = await db.execute("""
            INSERT INTO lab_defenses (real_name, subject, lab_number, telegram_id, video_id, exact_quote, status, confirmed)
            VALUES (?, ?, ?, ?, 'manual', '', 'passed', 1)
        """, (clean_name, clean_subj, clean_lab, telegram_id))
        await db.commit()
        return {"passed": True, "action": "added", "id": cursor.lastrowid if hasattr(cursor, "lastrowid") else 1}


async def get_student_defended_labs_db(user_id: int | None = None, real_name: str | None = None, subject: str | None = None, confirmed_only: bool = True) -> list[dict]:
    """Отримати список захищених робіт студента."""
    async with get_db() as db:
        query = "SELECT id, student_id, real_name, telegram_id, subject, lab_number, video_id, timestamp_sec, exact_quote, status, confirmed, created_at FROM lab_defenses WHERE status = 'passed'"
        params = []
        if confirmed_only:
            query += " AND confirmed = 1"
        if user_id:
            query += " AND telegram_id = ?"
            params.append(user_id)
        elif real_name:
            query += " AND real_name = ?"
            params.append(real_name)

        if subject:
            clean_subj = normalize_queue_subject(subject)
            query += " AND subject = ?"
            params.append(clean_subj)

        query += " ORDER BY id ASC"
        async with db.execute(query, tuple(params)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def remove_student_from_subject_queues_db(user_id: int, subject: str) -> list[int]:
    """
    Видалити студента з усіх активних черг з даної дисципліни.
    Повертає список chat_id, де студент був у черзі, для подальшого live-sync.
    """
    clean_subj = normalize_queue_subject(subject)
    affected_chats = []
    async with get_db() as db:
        async with db.execute("""
            SELECT DISTINCT chat_id FROM lab_queues 
            WHERE user_id = ? AND subject = ?
        """, (user_id, clean_subj)) as cur:
            rows = await cur.fetchall()
            affected_chats = [r["chat_id"] for r in rows]

        if affected_chats:
            await db.execute("""
                DELETE FROM lab_queues 
                WHERE user_id = ? AND subject = ?
            """, (user_id, clean_subj))
            await db.commit()

    return affected_chats


async def resolve_student_by_voice_mention(spoken_name: str, subject: str = None) -> dict | None:
    """
    Інтелектуальне зіставлення виголошеного викладачем імені з реєстром студентів ІП-66.
    Підтримує:
    1. Прізвище (наприклад, 'Сінчіневіч', 'Архипович')
    2. Прізвище + ім'я ('Максим Сінчіневіч', 'Сахнюк Дмитро')
    3. Лише ім'я ('Максим') — за наявності контексту черги обирає студента, який зараз стоїть у черзі!
    """
    if not spoken_name:
        return None

    clean_spoken = spoken_name.strip().lower()
    spoken_tokens = [t for t in re.split(r"[\s,._-]+", clean_spoken) if len(t) > 2]
    if not spoken_tokens:
        return None

    students = await get_all_students_db()
    if not students:
        return None

    # Отримуємо ID тих, хто зараз реально стоїть у черзі на цей предмет
    queue_user_ids = set()
    if subject:
        clean_subj = normalize_queue_subject(subject)
        async with get_db() as db:
            async with db.execute("SELECT DISTINCT user_id FROM lab_queues WHERE subject = ?", (clean_subj,)) as cur:
                rows = await cur.fetchall()
                queue_user_ids = {r["user_id"] for r in rows if r["user_id"]}

    candidates = []
    for s in students:
        rname = s["real_name"].lower()
        sur_raw, first_raw, _ = parse_person_name(s["real_name"])
        surname = sur_raw.lower()
        first_name = first_raw.lower()

        # Пріоритет 1: прямий збіг прізвища (найнадійніший критерій в академічній групі)
        if surname and any(token == surname or (len(token) >= 5 and token[:5] in surname) for token in spoken_tokens):
            score = 100
            if s.get("telegram_id") in queue_user_ids:
                score += 30
            elif s.get("telegram_id"):
                score += 15
            candidates.append((s, score))
            continue

        # Перевірка повного входження будь-якої комбінації
        if all(token in rname for token in spoken_tokens):
            candidates.append((s, 90))
            continue

        # Пріоритет 2: збіг за іменем
        if first_name and any(token == first_name for token in spoken_tokens):
            # Якщо цей студент зараз стоїть у черзі, це колосальний пріоритет!
            if s.get("telegram_id") in queue_user_ids:
                candidates.append((s, 95))
            else:
                candidates.append((s, 50))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_candidate, best_score = candidates[0]
    res = dict(best_candidate)
    res["match_score"] = best_score
    res["confidence"] = round(min(1.0, best_score / 100.0), 2)
    return res


# ==========================================
# АДМІН-ПАНЕЛЬ (ВЛАСНИК, СТАРОСТА, ЗАМСТАРОСТИ)
# ==========================================

PAIR_TIMES = {
    1: "08:30",
    2: "10:25",
    3: "12:20",
    4: "14:15",
    5: "16:10",
    6: "18:05",
}

TIME_TO_PAIR_NUMBER = {
    "08:30": 1,
    "10:25": 2,
    "12:20": 3,
    "14:15": 4,
    "16:10": 5,
    "18:05": 6,
}


async def get_admin_test_mode_db() -> bool:
    """Отримати статус режиму особистого тесту власника (за замовчуванням True)."""
    async with get_db() as db:
        async with db.execute("SELECT value FROM app_settings WHERE key = 'admin_test_mode'") as cur:
            row = await cur.fetchone()
            if row:
                val = str(row["value"]).strip().lower()
                return val in ("true", "1", "yes")
            return True


async def set_admin_test_mode_db(enabled: bool) -> bool:
    """Встановити статус режиму особистого тесту власника."""
    val = "true" if enabled else "false"
    async with get_db() as db:
        await db.execute("""
            INSERT INTO app_settings (key, value)
            VALUES ('admin_test_mode', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (val,))
        await db.commit()
        return True


async def check_admin_access_db(user_id: int | str = None, username: str = None) -> dict:
    """
    Перевірка прав доступу до адмін-панелі:
    - Власник (user_id == OWNER_ID або username в OWNER_USERNAMES) завжди має повний доступ (role: 'owner').
    - Якщо увімкнено test_mode (за замовчуванням True) — доступ дозволено виключно Власнику.
    - Якщо test_mode вимкнено — доступ надається також Старості та Замстарости з таблиці admin_roles.
    """
    clean_uid = None
    if user_id is not None:
        try:
            clean_uid = int(str(user_id).strip())
        except (ValueError, TypeError):
            clean_uid = None

    clean_uname = str(username or "").strip().lstrip("@").lower()
    clean_owner_unames = {str(u).strip().lstrip("@").lower() for u in (OWNER_USERNAMES or set())}

    is_owner = False
    if clean_uid is not None and clean_uid == OWNER_ID:
        is_owner = True
    elif clean_uname and clean_uname in clean_owner_unames:
        is_owner = True

    test_mode = await get_admin_test_mode_db()

    if is_owner:
        return {
            "is_admin": True,
            "is_owner": True,
            "role": "owner",
            "test_mode": test_mode
        }

    # Під час особистого тесту ніхто, крім власника, не має доступу
    if test_mode:
        return {
            "is_admin": False,
            "is_owner": False,
            "role": None,
            "test_mode": True
        }

    # Якщо тест-режим вимкнено, шукаємо в базі admin_roles
    async with get_db() as db:
        row = None
        if clean_uid is not None and clean_uname:
            async with db.execute("""
                SELECT id, user_id, username, real_name, role
                FROM admin_roles
                WHERE user_id = ? OR LOWER(username) = ?
                LIMIT 1
            """, (clean_uid, clean_uname)) as cur:
                row = await cur.fetchone()
        elif clean_uid is not None:
            async with db.execute("""
                SELECT id, user_id, username, real_name, role
                FROM admin_roles
                WHERE user_id = ?
                LIMIT 1
            """, (clean_uid,)) as cur:
                row = await cur.fetchone()
        elif clean_uname:
            async with db.execute("""
                SELECT id, user_id, username, real_name, role
                FROM admin_roles
                WHERE LOWER(username) = ?
                LIMIT 1
            """, (clean_uname,)) as cur:
                row = await cur.fetchone()

        if row:
            return {
                "is_admin": True,
                "is_owner": False,
                "role": row["role"],
                "test_mode": False
            }

    return {
        "is_admin": False,
        "is_owner": False,
        "role": None,
        "test_mode": False
    }


async def get_admin_roles_db() -> list[dict]:
    """Отримати список призначених адміністраторів (староста, замстарости)."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, user_id, username, real_name, role, created_at
            FROM admin_roles
            ORDER BY id ASC
        """) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def grant_admin_role_db(
    user_id: int | str = None,
    username: str = None,
    real_name: str = "",
    role: str = "deputy"
) -> bool:
    """Додати або оновити роль адміністратора ('headman' або 'deputy')."""
    clean_uid = None
    if user_id is not None:
        try:
            clean_uid = int(str(user_id).strip())
        except (ValueError, TypeError):
            clean_uid = None

    clean_uname = str(username or "").strip().lstrip("@")
    clean_rname = str(real_name or "").strip()
    target_role = "headman" if str(role).strip().lower() in ("headman", "староста") else "deputy"

    async with get_db() as db:
        # Шукаємо існуючий запис
        existing = None
        if clean_uid is not None and clean_uname:
            async with db.execute("""
                SELECT id FROM admin_roles
                WHERE user_id = ? OR LOWER(username) = LOWER(?)
                LIMIT 1
            """, (clean_uid, clean_uname)) as cur:
                existing = await cur.fetchone()
        elif clean_uid is not None:
            async with db.execute("SELECT id FROM admin_roles WHERE user_id = ? LIMIT 1", (clean_uid,)) as cur:
                existing = await cur.fetchone()
        elif clean_uname:
            async with db.execute("SELECT id FROM admin_roles WHERE LOWER(username) = LOWER(?) LIMIT 1", (clean_uname,)) as cur:
                existing = await cur.fetchone()

        if existing:
            await db.execute("""
                UPDATE admin_roles
                SET role = ?,
                    real_name = CASE WHEN ? != '' THEN ? ELSE real_name END,
                    user_id = COALESCE(?, user_id),
                    username = CASE WHEN ? != '' THEN ? ELSE username END
                WHERE id = ?
            """, (target_role, clean_rname, clean_rname, clean_uid, clean_uname, clean_uname, existing["id"]))
        else:
            await db.execute("""
                INSERT INTO admin_roles (user_id, username, real_name, role)
                VALUES (?, ?, ?, ?)
            """, (clean_uid, clean_uname or None, clean_rname, target_role))

        await db.commit()
        return True


async def revoke_admin_role_db(
    role_id: int | str = None,
    user_id: int | str = None,
    username: str = None
) -> bool:
    """Видалити права адміністратора з admin_roles."""
    async with get_db() as db:
        cur = None
        if role_id is not None:
            try:
                rid = int(str(role_id).strip())
                cur = await db.execute("DELETE FROM admin_roles WHERE id = ?", (rid,))
            except (ValueError, TypeError):
                pass
        elif user_id is not None:
            try:
                uid = int(str(user_id).strip())
                cur = await db.execute("DELETE FROM admin_roles WHERE user_id = ?", (uid,))
            except (ValueError, TypeError):
                pass
        elif username:
            uname = str(username).strip().lstrip("@")
            cur = await db.execute("DELETE FROM admin_roles WHERE LOWER(username) = LOWER(?)", (uname,))

        if cur:
            await db.commit()
            return cur.rowcount > 0
        return False


async def add_custom_lesson_db(
    date_str: str,
    pair_number: int,
    name: str,
    lesson_type: str = "Практика",
    lecturer: str = "",
    link_url: str = "",
    comment: str = "",
    created_by: str = ""
) -> int:
    """Додати додаткову або перенесену пару в розклад на вказану дату."""
    clean_date = date_str.strip()
    p_num = int(pair_number)
    time_str = PAIR_TIMES.get(p_num, "08:30")

    async with get_db() as db:
        cur = await db.execute("""
            INSERT INTO custom_lessons (
                date, pair_number, name, type, lecturer, time, location, link_url, comment, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Онлайн', ?, ?, ?)
        """, (
            clean_date,
            p_num,
            name.strip(),
            (lesson_type or "Практика").strip(),
            (lecturer or "").strip(),
            time_str,
            (link_url or "").strip(),
            (comment or "").strip(),
            (created_by or "").strip()
        ))
        await db.commit()

        new_id = getattr(cur, "lastrowid", None)
        if not new_id:
            async with db.execute("SELECT MAX(id) as last_id FROM custom_lessons WHERE date = ?", (clean_date,)) as c2:
                row = await c2.fetchone()
                new_id = row["last_id"] if row else 0
        return int(new_id or 0)


async def get_custom_lessons_for_date_db(date_str: str) -> list[dict]:
    """Отримати список усіх додаткових або перенесених пар на вказану дату."""
    clean_date = date_str.strip()
    async with get_db() as db:
        async with db.execute("""
            SELECT id, date, pair_number, name, type, lecturer, time, location, link_url, comment, created_by, created_at
            FROM custom_lessons
            WHERE date = ?
            ORDER BY pair_number ASC, id ASC
        """, (clean_date,)) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def delete_custom_lesson_db(lesson_id: int | str) -> bool:
    """Видалити додаткову або перенесену пару за її ID."""
    try:
        lid = int(str(lesson_id).strip())
    except (ValueError, TypeError):
        return False

    async with get_db() as db:
        cur = await db.execute("DELETE FROM custom_lessons WHERE id = ?", (lid,))
        await db.commit()
        return cur.rowcount > 0





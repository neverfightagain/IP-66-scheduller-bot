import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
import aiosqlite
from config import BASE_DIR, CHATS_FILE, LINKS_FILE

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

        # 2. Таблица настроек чатов (рассылки)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                notifications_enabled INTEGER DEFAULT 1,
                summaries_enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 3. Таблица заданий и лабораторных (Google Classroom)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                course_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                due_date TIMESTAMP,
                status TEXT DEFAULT 'active',
                raw_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );
        """)

        # 4. Таблица обработанных видео с лекциями (YouTube)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                course_id TEXT,
                title TEXT NOT NULL,
                published_at TIMESTAMP,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                summary_json TEXT,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );
        """)

        # 5. Таблица объявлений преподавателей и алертов кросс-валидации
        await db.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                course_id TEXT,
                source TEXT NOT NULL, -- 'youtube' или 'classroom'
                text TEXT NOT NULL,
                detected_date TIMESTAMP,
                conflict_flag INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (course_id) REFERENCES courses(id)
            );
        """)

        await db.commit()
        logger.info("База даних SQLite (kpi_bot.db) успішно ініціалізована.")

        # Автоматическая миграция из старых JSON-файлов
        await _migrate_legacy_data(db)


async def _migrate_legacy_data(db: aiosqlite.Connection):
    """Миграция данных из chats.json и links.json в SQLite."""
    # Миграция chats.json
    if CHATS_FILE.exists():
        try:
            with open(CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                chats = data.get("chats", [])
                for cid in chats:
                    await db.execute(
                        "INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)",
                        (int(cid),)
                    )
                await db.commit()
        except Exception as e:
            logger.warning(f"Помилка міграції chats.json: {e}")

    # Миграция links.json
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


# --- API для работы с чатами ---

async def get_subscribed_chats_db() -> list[int]:
    """Получить список всех chat_id с включенными уведомлениями."""
    async with get_db() as db:
        async with db.execute("SELECT chat_id FROM chat_settings WHERE notifications_enabled = 1") as cursor:
            rows = await cursor.fetchall()
            return [row["chat_id"] for row in rows]


async def add_subscribed_chat_db(chat_id: int) -> bool:
    """Добавить или активировать чат в базе данных."""
    async with get_db() as db:
        await db.execute("""
            INSERT INTO chat_settings (chat_id, notifications_enabled)
            VALUES (?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET notifications_enabled = 1
        """, (chat_id,))
        await db.commit()
        return True


async def remove_subscribed_chat_db(chat_id: int) -> bool:
    """Отключить уведомления для чата."""
    async with get_db() as db:
        await db.execute("""
            UPDATE chat_settings SET notifications_enabled = 0 WHERE chat_id = ?
        """, (chat_id,))
        await db.commit()
        return True


# --- API для работы с видео и конспектами ---

async def is_video_processed(video_id: str) -> bool:
    """Проверить, было ли видео уже обработано нейросетью."""
    async with get_db() as db:
        async with db.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def save_video_summary(video_id: str, title: str, course_id: str | None, published_at: str | None, summary: dict):
    """Сохранить выжимку видео в базу данных."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO videos (video_id, course_id, title, published_at, summary_json)
            VALUES (?, ?, ?, ?, ?)
        """, (video_id, course_id, title, published_at, json.dumps(summary, ensure_ascii=False)))
        await db.commit()

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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

        await db.commit()
        logger.info("База даних SQLite (kpi_bot.db) успішно ініціалізована.")

        # Автоматическая миграция из старых JSON-файлов
        await _migrate_legacy_data(db)
        await seed_demo_assignments_if_empty()


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


# --- API для работы с заданиями (Дедлайнами) ---

async def add_assignment_db(assignment_id: str, course_name: str, title: str, due_date: str, description: str = "") -> bool:
    """Добавить или обновить дедлайн задания."""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO assignments (id, course_id, title, due_date, description, status)
            VALUES (?, ?, ?, ?, ?, 'active')
        """, (assignment_id, course_name, title, due_date, description))
        await db.commit()
        return True


async def get_active_assignments_db() -> list[dict]:
    """Получить все активные задания, отсортированные по дедлайну."""
    async with get_db() as db:
        async with db.execute("""
            SELECT id, course_id, title, description, due_date, status
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
    """Добавить демонстрационные дедлайны для проверки, если база пустая."""
    from datetime import datetime, timedelta
    from config import KYIV_TZ
    now = datetime.now(KYIV_TZ)

    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as cnt FROM assignments") as cursor:
            row = await cursor.fetchone()
            if row and row["cnt"] > 0:
                return

        # Добавляем 3 тестовых дедлайна
        d1 = (now + timedelta(days=2)).strftime("%Y-%m-%d 23:59")
        d2 = (now + timedelta(days=4)).strftime("%Y-%m-%d 23:59")
        d3 = (now + timedelta(days=9)).strftime("%Y-%m-%d 23:59")

        demo_data = [
            ("op_lab1", "Основи програмування", "Лабораторна робота №1 (Базові конструкції)", d1, "Здавати через репозиторій GitHub"),
            ("asd_lab1", "Алгоритми та структури даних", "Лабораторна робота №1 (Основи алгоритмізації)", d2, "Звіт у форматі PDF + код"),
            ("kdm_calc1", "Комп'ютерна дискретна математика", "Розрахункова робота №1 (Множини та відношення)", d3, "Варіанти згідно зі списком у журналі")
        ]

        for aid, cname, title, due, desc in demo_data:
            await db.execute("""
                INSERT OR IGNORE INTO assignments (id, course_id, title, due_date, description, status)
                VALUES (?, ?, ?, ?, ?, 'active')
            """, (aid, cname, title, due, desc))

        await db.commit()
        logger.info("Додано тестові дедлайни для перевірки команди /deadlines.")

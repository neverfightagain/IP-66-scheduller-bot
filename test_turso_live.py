import asyncio
import os
import sys
from dotenv import load_dotenv

# Load .env
load_dotenv()

async def test_live_connection():
    url = os.getenv("TURSO_DATABASE_URL", "").strip()
    token = os.getenv("TURSO_AUTH_TOKEN", "").strip()

    if not url:
        print("[!] TURSO_DATABASE_URL не знайдено в .env!")
        print("Вкажіть її у файлі .env або запустіть скрипт, передавши змінні оточення.")
        sys.exit(1)

    print(f"[*] Підключення до Turso Cloud: {url.split('@')[-1]}")
    import database
    database.TURSO_DATABASE_URL = url
    database.TURSO_AUTH_TOKEN = token

    try:
        # 1. Ініціалізація структури таблиць у хмарі Turso
        print("[*] Ініціалізація таблиць (init_db)...")
        await database.init_db()
        print("[+] Таблиці успішно створені в Turso Cloud!")

        # 2. Тестовий запис завдання
        test_id = "test_live_check_1"
        print("[*] Запис тестового дедлайну...")
        await database.add_assignment_db(
            assignment_id=test_id,
            course_name="Хмарний тест Turso",
            title="Перевірка зв'язку",
            due_date="2026-12-31 23:59",
            description="Перевірка збереження даних у хмарі Turso",
            ai_summary="Тест пройшов успішно"
        )
        print("[+] Завдання записано!")

        # 3. Читання з хмари
        print("[*] Зчитування дедлайнів з Turso...")
        assignments = await database.get_active_assignments_db()
        found = next((a for a in assignments if a["id"] == test_id), None)
        assert found is not None, "Тестовий запис не знайдено в базі!"
        print(f"[+] Прочитано успішно: '{found['title']}' ({found['ai_summary']})")

        # 4. Видалення тестового запису
        print("[*] Очищення тестового запису...")
        await database.delete_assignment_db(test_id)
        print("[+] Тестовий запис видалено!")

        # 5. Закриття підключення
        await database.close_db()
        print("\n==========================================")
        print(" [SUCCESS] Turso Cloud працює на 100%!")
        print(" База збереже всі дані при будь-яких редеплоях.")
        print("==========================================")
    except Exception as e:
        print(f"\n[ERROR] Помилка підключення до Turso: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_live_connection())

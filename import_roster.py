import asyncio
import json
import logging
import os
import sys
from database import init_db, add_or_update_student_db, get_all_students_db
from config import STUDENTS_ROSTER_JSON

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(level=logging.INFO)

async def main():
    await init_db()

    roster_data = None
    if STUDENTS_ROSTER_JSON:
        try:
            roster_data = json.loads(STUDENTS_ROSTER_JSON)
            print(f"Завантажено {len(roster_data)} записів зі змінної середовища STUDENTS_ROSTER_JSON.")
        except Exception as e:
            print(f"Помилка парсингу STUDENTS_ROSTER_JSON: {e}")

    if not roster_data and os.path.exists("parsed_students.json"):
        with open("parsed_students.json", encoding="utf-8") as f:
            data = json.load(f)
            roster_data = data.get("students", [])

    if not roster_data:
        print("❌ Не знайдено даних студентів ні в STUDENTS_ROSTER_JSON, ні у файлі.")
        return

    count = 0
    for i, s in enumerate(roster_data, 1):
        rname = s.get("real_name", "").strip()
        uname = s.get("telegram_username")
        subgroup = s.get("subgroup", 1 if i <= 17 else 2)
        notes = s.get("notes", "")

        ok = await add_or_update_student_db(
            real_name=rname,
            telegram_username=uname,
            subgroup=subgroup,
            notes=notes
        )
        if ok:
            count += 1
            print(f"  [+] {i:2d}. {rname} (@{uname}) -> Підгрупа {subgroup}")

    print(f"\n✅ Успішно оновлено {count} студентів у базі даних!")
    all_in_db = await get_all_students_db()
    print(f"У базі даних наразі всього {len(all_in_db)} записів.")

if __name__ == "__main__":
    asyncio.run(main())

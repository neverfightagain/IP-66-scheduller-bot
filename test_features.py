import unittest
import asyncio
from formatters import clean_course_name, format_deadlines_radar, format_daily_summary, format_latex_to_unicode
from database import init_db, add_assignment_db, get_active_assignments_db, update_assignment_ai_summary_db, delete_assignment_db
from llm_agent import summarize_assignment_requirements


class TestCourseNameCleaning(unittest.TestCase):
    def test_clean_course_names(self):
        cases = {
            "English IP-65, 66": "English",
            "ЛАтаАНГ (ІП-66)": "ЛАтаАНГ",
            "ОП_26_27_ІПІ": "ОП",
            "2026/27 КДМ ІП-6Х": "КДМ",
            "АСД ІП-66": "АСД",
            "Філософія": "Філософія",
            "Теорія ймовірностей [ІП-65]": "Теорія ймовірностей",
            "Бази даних {IP-66}": "Бази даних",
            None: "Предмет",
            "": "Предмет",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_course_name(raw), expected)


class TestFormattingAndRadar(unittest.TestCase):
    def test_deadlines_radar_spacing_and_summary(self):
        # Обидва завдання на один тиждень (поточний), щоб перевірити відступи між ними
        from datetime import datetime, timedelta
        from config import KYIV_TZ
        now = datetime.now(KYIV_TZ)
        due_1 = (now + timedelta(days=1)).strftime("%Y-%m-%d 20:00")
        due_2 = (now + timedelta(days=2)).strftime("%Y-%m-%d 23:59")

        assignments = [
            {
                "id": "test_1",
                "course_id": "English IP-65, 66",
                "title": "Topic 1",
                "due_date": due_1,
                "description": "Very long raw teacher description with links https://example.com/quiz",
                "ai_summary": "Опрацювати матеріал та пройти тест.",
                "status": "active"
            },
            {
                "id": "test_2",
                "course_id": "2026/27 КДМ ІП-6Х",
                "title": "Lab 1",
                "due_date": due_2,
                "description": "Short desc",
                "ai_summary": "Виконати завдання 1-5.",
                "status": "active"
            }
        ]

        radar = format_deadlines_radar(assignments)

        # 1. Disciplines should be cleaned
        self.assertIn("<b>English</b>", radar)
        self.assertNotIn("IP-65, 66", radar)
        self.assertIn("<b>КДМ</b>", radar)
        self.assertNotIn("2026/27", radar)

        # 2. AI summaries should be used inside expandable blockquotes
        self.assertIn("<blockquote expandable>📝 <b>Суть:</b> Опрацювати матеріал та пройти тест.</blockquote>", radar)
        self.assertIn("<blockquote expandable>📝 <b>Суть:</b> Виконати завдання 1-5.</blockquote>", radar)

        # 3. Blockquote should immediately follow the deadline line without a leading newline gap
        self.assertIn("</i><blockquote expandable>", radar)
        self.assertNotIn("</i>\n   <blockquote expandable>", radar)

        # 4. Spacing between distinct assignments within the same section should be separated by double newlines (\n\n)
        self.assertIn("</blockquote>\n\n", radar)

    def test_deadlines_radar_fallback_without_ai_summary(self):
        from datetime import datetime, timedelta
        from config import KYIV_TZ
        now = datetime.now(KYIV_TZ)
        due = (now + timedelta(days=1)).strftime("%Y-%m-%d 23:59")

        assignments = [
            {
                "id": "test_fallback",
                "course_id": "АСД ІП-66",
                "title": "Lab 2",
                "due_date": due,
                "description": "Тільки сирий опис",
                "ai_summary": None,
                "status": "active"
            }
        ]
        radar = format_deadlines_radar(assignments)
        self.assertIn("<blockquote expandable>📝 <b>Суть:</b> Тільки сирий опис</blockquote>", radar)


class TestDatabaseAISummary(unittest.IsolatedAsyncioTestCase):
    async def test_assignment_ai_summary_persistence(self):
        await init_db()
        test_id = "test_unit_assignment_999"

        # Add assignment with ai_summary
        await add_assignment_db(
            assignment_id=test_id,
            course_name="Тест Курс (ІП-66)",
            title="Тестове Завдання",
            due_date="2026-10-30 23:59",
            description="Повний опис завдання",
            ai_summary="Коротка вижимка від AI"
        )

        all_assignments = await get_active_assignments_db()
        found = [a for a in all_assignments if a["id"] == test_id]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ai_summary"], "Коротка вижимка від AI")

        # Update ai_summary
        await update_assignment_ai_summary_db(test_id, "Оновлена AI-вижимка")
        all_assignments = await get_active_assignments_db()
        found = [a for a in all_assignments if a["id"] == test_id]
        self.assertEqual(found[0]["ai_summary"], "Оновлена AI-вижимка")

        # Clean up
        await delete_assignment_db(test_id)


class TestTursoDualEngine(unittest.IsolatedAsyncioTestCase):
    async def test_turso_client_compatibility(self):
        import database
        import os

        test_db_file = "test_turso_unit.db"
        orig_url = database.TURSO_DATABASE_URL
        database.TURSO_DATABASE_URL = f"file:{test_db_file}"
        try:
            await database.init_db()
            test_id = "turso_unit_1"
            await database.add_assignment_db(
                assignment_id=test_id,
                course_name="Turso Test Course",
                title="Lab Turso",
                due_date="2026-11-01 12:00",
                description="Testing Turso adapter",
                ai_summary="Turso works!"
            )
            assignments = await database.get_active_assignments_db()
            item = next((a for a in assignments if a["id"] == test_id), None)
            self.assertIsNotNone(item)
            self.assertEqual(item["ai_summary"], "Turso works!")
            self.assertEqual(item["course_id"], "Turso Test Course")

            await database.delete_assignment_db(test_id)
            assignments_after = await database.get_active_assignments_db()
            self.assertIsNone(next((a for a in assignments_after if a["id"] == test_id), None))
        finally:
            await database.close_db()
            database.TURSO_DATABASE_URL = orig_url
            if os.path.exists(test_db_file):
                os.remove(test_db_file)


class TestLLMAgentSummarizer(unittest.IsolatedAsyncioTestCase):
    async def test_short_description_fast_return(self):
        short_desc = "Здати лабораторну 1."
        result = await summarize_assignment_requirements("Лаб 1", short_desc, "АСД")
        self.assertEqual(result, short_desc)


class TestKeyRotationAndFallback(unittest.TestCase):
    def test_key_parsing_and_cooldown_recovery(self):
        import os
        import time
        from llm_agent import (
            get_gemini_keys,
            get_ordered_gemini_keys,
            mark_key_exhausted,
            mark_key_success,
            parse_retry_delay,
            _key_cooldowns
        )

        orig = os.environ.get("GEMINI_API_KEYS")
        try:
            os.environ["GEMINI_API_KEYS"] = "key1, key2, key3"
            keys = get_gemini_keys()
            self.assertEqual(keys, ["key1", "key2", "key3"])

            # 1. Спочатку всі ключі здорові -> порядок [key1, key2, key3]
            self.assertEqual(get_ordered_gemini_keys(), ["key1", "key2", "key3"])

            # 2. key1 вичерпано з кулдауном 1.0с -> черга перемикається на [key2, key3, key1]
            mark_key_exhausted("key1", cooldown_seconds=1.0)
            self.assertEqual(get_ordered_gemini_keys(), ["key2", "key3", "key1"])

            # 3. key2 теж вичерпано з кулдауном 2.0с -> черга [key3, key1, key2]
            mark_key_exhausted("key2", cooldown_seconds=2.0)
            self.assertEqual(get_ordered_gemini_keys(), ["key3", "key1", "key2"])

            # 4. Чекаємо 1.1с: кулдаун key1 минув -> key1 автоматично відновлюється на перше місце!
            time.sleep(1.1)
            self.assertEqual(get_ordered_gemini_keys(), ["key1", "key3", "key2"])

            # 5. Успішний запит скидає будь-який кулдаун
            mark_key_success("key2")
            self.assertEqual(get_ordered_gemini_keys(), ["key1", "key2", "key3"])

            # 6. Тест парсингу retry delay з 429 помилки Google
            err = "Quota exceeded... Please retry in 42.5s."
            self.assertAlmostEqual(parse_retry_delay(err), 47.5, delta=1.0)
        finally:
            _key_cooldowns.clear()
            if orig is not None:
                os.environ["GEMINI_API_KEYS"] = orig
            else:
                os.environ.pop("GEMINI_API_KEYS", None)


if __name__ == "__main__":
    unittest.main()

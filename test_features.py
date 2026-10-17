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
        assignments = [
            {
                "id": "test_1",
                "course_id": "English IP-65, 66",
                "title": "Topic 1",
                "due_date": "2026-10-18 20:00",
                "description": "Very long raw teacher description with links https://example.com/quiz",
                "ai_summary": "Опрацювати матеріал та пройти тест.",
                "status": "active"
            },
            {
                "id": "test_2",
                "course_id": "2026/27 КДМ ІП-6Х",
                "title": "Lab 1",
                "due_date": "2026-10-18 23:59",
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
        assignments = [
            {
                "id": "test_fallback",
                "course_id": "АСД ІП-66",
                "title": "Lab 2",
                "due_date": "2026-10-18 23:59",
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


class TestLLMAgentSummarizer(unittest.IsolatedAsyncioTestCase):
    async def test_short_description_fast_return(self):
        short_desc = "Здати лабораторну 1."
        result = await summarize_assignment_requirements("Лаб 1", short_desc, "АСД")
        self.assertEqual(result, short_desc)


class TestKeyRotationAndFallback(unittest.TestCase):
    def test_key_parsing_and_rotation(self):
        import os
        from llm_agent import get_gemini_keys, get_ordered_gemini_keys, advance_to_next_key, mark_key_success

        orig = os.environ.get("GEMINI_API_KEYS")
        try:
            os.environ["GEMINI_API_KEYS"] = "key_alpha, key_beta; key_gamma\nkey_delta"
            keys = get_gemini_keys()
            self.assertEqual(keys, ["key_alpha", "key_beta", "key_gamma", "key_delta"])

            # Test ordered keys
            mark_key_success("key_alpha")
            self.assertEqual(get_ordered_gemini_keys()[0], "key_alpha")

            # Advance
            advance_to_next_key()
            self.assertEqual(get_ordered_gemini_keys()[0], "key_beta")

            advance_to_next_key()
            self.assertEqual(get_ordered_gemini_keys()[0], "key_gamma")
        finally:
            if orig is not None:
                os.environ["GEMINI_API_KEYS"] = orig
            else:
                os.environ.pop("GEMINI_API_KEYS", None)


if __name__ == "__main__":
    unittest.main()

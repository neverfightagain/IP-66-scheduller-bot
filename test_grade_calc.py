import unittest
from grade_calculator import get_ects_grade, calculate_grade_projection, format_grade_report, format_ects_scale_text
from database import (
    init_db,
    set_rso_config_db,
    get_rso_config_db,
    get_db
)

class TestGradeCalculator(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.subject = "Тест-ОП"
        async with get_db() as db:
            await db.execute("DELETE FROM rso_grading WHERE subject = ?", (self.subject,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM rso_grading WHERE subject = ?", (self.subject,))
            await db.commit()

    def test_ects_grade_scale(self):
        self.assertEqual(get_ects_grade(96)[0], "A")
        self.assertEqual(get_ects_grade(88)[0], "B")
        self.assertEqual(get_ects_grade(76)[0], "C")
        self.assertEqual(get_ects_grade(68)[0], "D")
        self.assertEqual(get_ects_grade(61)[0], "E")
        self.assertEqual(get_ects_grade(45)[0], "F")

    def test_grade_projection_calculation(self):
        rso = {
            "total_labs": 4,
            "points_per_lab": 15.0,
            "mkr_points": 20.0,
            "auto_pass_threshold": 60.0
        }

        # 1. Студент має 48 балів -> до 60 бракує 12 балів (достатньо 1 лаби по 15 б.)
        proj = calculate_grade_projection(48.0, rso)
        self.assertFalse(proj["has_auto_pass"])
        self.assertEqual(proj["needed_for_pass"], 12.0)
        self.assertEqual(proj["labs_for_pass"], 1)

        # 2. Студент має 65 балів -> є автомат, бракує 10 до C (75)
        proj2 = calculate_grade_projection(65.0, rso)
        self.assertTrue(proj2["has_auto_pass"])
        self.assertEqual(proj2["needed_for_pass"], 0.0)
        self.assertEqual(proj2["needed_for_c"], 10.0)

    async def test_rso_db_persistence(self):
        ok = await set_rso_config_db(
            subject=self.subject,
            total_labs=5,
            points_per_lab=12.0,
            mkr_points=20.0,
            exam_points=20.0,
            auto_pass_threshold=60.0
        )
        self.assertTrue(ok)

        cfg = await get_rso_config_db(self.subject)
        self.assertEqual(cfg["total_labs"], 5)
        self.assertEqual(cfg["points_per_lab"], 12.0)

    def test_report_formatting(self):
        proj = calculate_grade_projection(52.0)
        text, kb = format_grade_report("АСД", 52.0, proj)
        self.assertIn("Калькулятор автомату та балів: АСД", text)
        self.assertIn("<b>Поточний бал:</b> <code>52.0 / 100</code>", text)
        self.assertIn("До автомату (60 б.):", text)
        self.assertIsNotNone(kb)

        scale = format_ects_scale_text()
        self.assertIn("Шкала оцінювання КПІ", scale)


if __name__ == "__main__":
    unittest.main()

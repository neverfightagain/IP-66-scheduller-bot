import unittest
from datetime import datetime
from config import KYIV_TZ
from debts_tracker import calculate_group_debts, format_group_debts_report, format_student_debts_report
from database import (
    init_db,
    record_student_submission_db,
    get_assignment_submissions_db,
    get_student_debts_db,
    add_assignment_db,
    delete_assignment_db,
    get_db
)

class TestGroupDebtsTracker(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.aid1 = "test_debt_lab1"
        self.aid2 = "test_debt_lab2"
        # Додаємо тестові дедлайни (один прострочений, один майбутній)
        await add_assignment_db(self.aid1, "АСД (ІП-66)", "Лабораторна 1", "2026-10-01 23:59", "Опис 1")
        await add_assignment_db(self.aid2, "КДМ (ІП-66)", "Лабораторна 2", "2026-11-01 23:59", "Опис 2")

    async def asyncTearDown(self):
        await delete_assignment_db(self.aid1)
        await delete_assignment_db(self.aid2)
        async with get_db() as db:
            await db.execute("DELETE FROM student_submissions WHERE assignment_id IN (?, ?)", (self.aid1, self.aid2))
            await db.commit()

    def test_calculate_group_debts(self):
        now_dt = datetime(2026, 10, 18, 12, 0, tzinfo=KYIV_TZ)
        assignments = [
            {"id": self.aid1, "course_id": "АСД (ІП-66)", "title": "Лабораторна 1", "due_date": "2026-10-01 23:59"},
            {"id": self.aid2, "course_id": "КДМ (ІП-66)", "title": "Лабораторна 2", "due_date": "2026-11-01 23:59"}
        ]
        summary = calculate_group_debts(assignments, now_dt=now_dt)

        self.assertEqual(summary["total_active"], 2)
        self.assertEqual(summary["total_overdue"], 1)
        self.assertEqual(summary["total_upcoming"], 1)
        self.assertIn("АСД", summary["subject_breakdown"])
        self.assertEqual(summary["subject_breakdown"]["АСД"], 1)

    async def test_record_and_get_student_submissions(self):
        # Фіксуємо здачу студентом
        ok = await record_student_submission_db(self.aid1, "Іван Іванов", status="submitted", grade=95.0)
        self.assertTrue(ok)

        subs = await get_assignment_submissions_db(self.aid1)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["student_name"], "Іван Іванов")
        self.assertEqual(subs[0]["status"], "submitted")

    async def test_student_debts_listing(self):
        # Іван здав aid1
        await record_student_submission_db(self.aid1, "Іван Іванов", status="submitted")

        # Перевіряємо борги Івана: aid1 не повинно бути серед боргів, але aid2 є
        debts = await get_student_debts_db("Іван Іванов")
        debt_ids = [d["id"] for d in debts]
        self.assertNotIn(self.aid1, debt_ids)
        self.assertIn(self.aid2, debt_ids)

    def test_format_reports(self):
        summary = {
            "total_active": 3,
            "total_overdue": 1,
            "total_upcoming": 2,
            "overdue_assignments": [
                {"id": "test_1", "course_id": "АСД", "title": "Лаба 1", "due_date": "2026-10-10"}
            ],
            "subject_breakdown": {"АСД": 1}
        }
        text, kb = format_group_debts_report(summary)
        self.assertIn("ЗВЕДЕННЯ ЗАБОРГОВАНОСТЕЙ ГРУПИ", text)
        self.assertIn("АСД", text)
        self.assertIsNotNone(kb)

        st_report = format_student_debts_report("Шевченко Тарас", summary["overdue_assignments"])
        self.assertIn("Заборгованості студента Шевченко Тарас", st_report)


if __name__ == "__main__":
    unittest.main()

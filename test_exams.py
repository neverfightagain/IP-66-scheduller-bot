import unittest
from datetime import datetime
from config import KYIV_TZ
from exams_tracker import calculate_countdown, check_exam_admission, format_exams_dashboard
from database import (
    init_db,
    add_exam_db,
    get_upcoming_exams_db,
    delete_exam_db,
    get_db
)

class TestExamsSchedule(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        async with get_db() as db:
            await db.execute("DELETE FROM exams WHERE subject = 'Тест-АСД'")
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM exams WHERE subject = 'Тест-АСД'")
            await db.commit()

    def test_countdown_calculation(self):
        now_dt = datetime(2026, 10, 20, 10, 0, tzinfo=KYIV_TZ)

        # 1. Сьогодні через 4 години
        cd_today = calculate_countdown("2026-10-20 14:00", now_dt)
        self.assertFalse(cd_today["is_past"])
        self.assertEqual(cd_today["days"], 0)
        self.assertIn("Сьогодні", cd_today["text"])

        # 2. Через 5 днів
        cd_future = calculate_countdown("2026-10-25 10:00", now_dt)
        self.assertEqual(cd_future["days"], 5)
        self.assertIn("5 днів", cd_future["text"])

        # 3. Минула подія
        cd_past = calculate_countdown("2026-10-19 10:00", now_dt)
        self.assertTrue(cd_past["is_past"])

    def test_admission_logic(self):
        # Вимога: лаби 1, 2, 3
        req = "Лаби 1, 2, 3"

        # Студент здав лаби 1 і 2 -> Не допущено
        ok1, msg1 = check_exam_admission(req, ["Лаба 1", "Лаба 2"])
        self.assertFalse(ok1)
        self.assertIn("№3", msg1)

        # Студент здав лаби 1, 2, 3 -> Допущено
        ok2, msg2 = check_exam_admission(req, ["Лаба 1", "Лаба 2", "Лаба 3"])
        self.assertTrue(ok2)
        self.assertIn("Допущено", msg2)

    async def test_exams_crud(self):
        eid = await add_exam_db(
            subject="Тест-АСД",
            event_type="МКР",
            event_date="2026-10-30 14:15",
            location="ауд. 315",
            required_labs="Лаби 1-2",
            notes="Калькулятори дозволено"
        )
        self.assertIsInstance(eid, int)

        exams = await get_upcoming_exams_db()
        found = [e for e in exams if e["id"] == eid]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["subject"], "Тест-АСД")

        # Перевірка видалення
        deleted = await delete_exam_db(eid)
        self.assertTrue(deleted)

    def test_dashboard_formatting(self):
        exams = [
            {
                "id": 1,
                "subject": "Тест-АСД",
                "event_type": "МКР",
                "event_date": "2026-10-30 14:15",
                "location": "ауд. 315",
                "required_labs": "Лаби 1-2",
                "notes": "Важлива контрольна"
            }
        ]
        text, kb = format_exams_dashboard(exams, now_dt=datetime(2026, 10, 20, tzinfo=KYIV_TZ))
        self.assertIn("Графік МКР, колоквіумів та іспитів", text)
        self.assertIn("Тест-АСД", text)
        self.assertIn("ауд. 315", text)
        self.assertIsNotNone(kb)


if __name__ == "__main__":
    unittest.main()

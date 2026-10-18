import unittest
from datetime import datetime, timedelta
from config import KYIV_TZ
from debtor_pinger import get_urgent_assignments_for_ping, format_urgent_ping_message
from database import (
    init_db,
    is_deadline_pinged_db,
    mark_deadline_pinged_db,
    get_db
)

class TestDebtorPinger(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.aid = "test_ping_assignment_99"
        async with get_db() as db:
            await db.execute("DELETE FROM urgent_deadline_pings WHERE assignment_id = ?", (self.aid,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM urgent_deadline_pings WHERE assignment_id = ?", (self.aid,))
            await db.commit()

    def test_detect_urgent_deadlines(self):
        now_dt = datetime(2026, 10, 20, 10, 0, tzinfo=KYIV_TZ)
        assignments = [
            # 1. Дедлайн через 5 годин (о 15:00 сьогодні) -> Терміново!
            {"id": "urgent_1", "course_id": "АСД", "title": "Лаба 1", "due_date": "2026-10-20 15:00"},
            # 2. Дедлайн через 5 днів -> Не терміново
            {"id": "far_2", "course_id": "КДМ", "title": "Лаба 2", "due_date": "2026-10-25 23:59"},
            # 3. Дедлайн у минулому -> Не потрапляє в майбутній пінг
            {"id": "past_3", "course_id": "Мережі", "title": "Лаба 3", "due_date": "2026-10-19 10:00"}
        ]

        urgent = get_urgent_assignments_for_ping(assignments, now_dt=now_dt)
        self.assertEqual(len(urgent), 1)
        self.assertEqual(urgent[0]["id"], "urgent_1")
        self.assertEqual(urgent[0]["hours_left"], 5)

    def test_format_urgent_ping_message(self):
        assignment = {
            "id": "urgent_test",
            "course_id": "Основи програмування (ІП-66)",
            "title": "Лабораторна 3",
            "due_date": "2026-10-20 23:59"
        }
        text, kb = format_urgent_ping_message(assignment, hours_left=4)

        self.assertIn("УВАГА, БОРЖНИКИ!", text)
        self.assertIn("Основи програмування", text)
        self.assertIn("МЕНШЕ 6 ГОДИН!", text)
        self.assertIsNotNone(kb)

    async def test_db_ping_deduplication(self):
        # Спочатку не пінговано
        pinged_before = await is_deadline_pinged_db(self.aid, "24h")
        self.assertFalse(pinged_before)

        # Фіксуємо пінг
        await mark_deadline_pinged_db(self.aid, "24h")

        # Тепер пінговано
        pinged_after = await is_deadline_pinged_db(self.aid, "24h")
        self.assertTrue(pinged_after)


if __name__ == "__main__":
    unittest.main()

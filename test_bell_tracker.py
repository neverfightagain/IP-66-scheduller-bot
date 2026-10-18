import unittest
from datetime import datetime, date, time
from config import KYIV_TZ
from bell_tracker import get_current_bell_status, format_bell_status_card, format_bell_table_text

class TestBellCountdownTracker(unittest.TestCase):
    def test_in_lesson_status(self):
        # 10:45 -> 2-га пара (10:25 - 12:00)
        dt = datetime(2026, 10, 20, 10, 45, tzinfo=KYIV_TZ)
        status = get_current_bell_status(dt)

        self.assertEqual(status["state"], "IN_LESSON")
        self.assertEqual(status["pair_num"], 2)
        # До кінця пари о 12:00 залишається 75 хв
        self.assertEqual(status["minutes_left"], 75)
        self.assertEqual(status["end_str"], "12:00")

    def test_in_break_status(self):
        # 12:10 -> Перерва між 2-ю та 3-ю парою (12:00 - 12:20)
        dt = datetime(2026, 10, 20, 12, 10, tzinfo=KYIV_TZ)
        status = get_current_bell_status(dt)

        self.assertEqual(status["state"], "IN_BREAK")
        self.assertEqual(status["from_pair_num"], 2)
        self.assertEqual(status["next_pair_num"], 3)
        self.assertEqual(status["minutes_left"], 10)
        self.assertEqual(status["next_pair_start"], "12:20")

    def test_before_lessons_status(self):
        # 07:45 -> До початку 1-ї пари (08:30)
        dt = datetime(2026, 10, 20, 7, 45, tzinfo=KYIV_TZ)
        status = get_current_bell_status(dt)

        self.assertEqual(status["state"], "BEFORE_LESSONS")
        self.assertEqual(status["minutes_left"], 45)
        self.assertEqual(status["next_pair_start"], "08:30")

    def test_after_lessons_status(self):
        # 21:30 -> Пари завершено
        dt = datetime(2026, 10, 20, 21, 30, tzinfo=KYIV_TZ)
        status = get_current_bell_status(dt)

        self.assertEqual(status["state"], "AFTER_LESSONS")

    def test_format_card(self):
        dt = datetime(2026, 10, 20, 10, 45, tzinfo=KYIV_TZ)
        status = get_current_bell_status(dt)
        text, kb = format_bell_status_card(status, active_lesson={"name": "Лінійна алгебра"})

        self.assertIn("Зараз триває 2-га пара", text)
        self.assertIn("Лінійна алгебра", text)
        self.assertIn("75 хв", text)
        self.assertIsNotNone(kb)

    def test_table_text(self):
        table = format_bell_table_text()
        self.assertIn("08:30 — 10:05", table)
        self.assertIn("10:25 — 12:00", table)


if __name__ == "__main__":
    unittest.main()

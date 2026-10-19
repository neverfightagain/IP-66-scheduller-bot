import unittest
from datetime import datetime
from database import (
    init_db,
    cancel_pair_db,
    uncancel_pair_db,
    get_cancelled_pairs_for_date_db,
    is_pair_cancelled_db,
    get_db
)
from formatters import format_morning_digest

class TestCancelPairSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.test_date = "2026-10-25"
        async with get_db() as db:
            await db.execute("DELETE FROM cancelled_pairs WHERE date = ?", (self.test_date,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM cancelled_pairs WHERE date = ?", (self.test_date,))
            await db.commit()

    async def test_cancel_and_check(self):
        # 1. Скасовуємо 2-гу пару через хворобу викладача
        ok = await cancel_pair_db(
            date_str=self.test_date,
            pair_number=2,
            subject="Теорія ймовірностей",
            reason="Хворіє викладач",
            cancelled_by="Староста (Олександр)"
        )
        self.assertTrue(ok)

        # 2. Перевіряємо статус скасування
        is_canc, reason = await is_pair_cancelled_db(self.test_date, 2)
        self.assertTrue(is_canc)
        self.assertEqual(reason, "Хворіє викладач")

        # 3. Перевіряємо пару, яка НЕ була скасована
        is_canc1, _ = await is_pair_cancelled_db(self.test_date, 1)
        self.assertFalse(is_canc1)

        # 4. Отримуємо словник усіх скасованих пар на день
        canc_map = await get_cancelled_pairs_for_date_db(self.test_date)
        self.assertIn(2, canc_map)
        self.assertEqual(canc_map[2]["reason"], "Хворіє викладач")

    async def test_uncancel_pair(self):
        await cancel_pair_db(self.test_date, 3, "АСД", "Перенесення")
        is_canc, _ = await is_pair_cancelled_db(self.test_date, 3)
        self.assertTrue(is_canc)

        # Знімаємо скасування
        uncanc = await uncancel_pair_db(self.test_date, 3)
        self.assertTrue(uncanc)

        is_canc_after, _ = await is_pair_cancelled_db(self.test_date, 3)
        self.assertFalse(is_canc_after)

    def test_format_morning_digest_with_cancelled_pair(self):
        lessons = [
            {"name": "Основи програмування", "type": "Лекція", "lecturer": "Іванов", "time": "08:30"},
            {"name": "Теорія ймовірностей", "type": "Практика", "lecturer": "Петров", "time": "10:25"},
        ]
        cancelled_map = {
            2: {"reason": "Хворіє викладач"}
        }

        text, _ = format_morning_digest(
            week=1,
            day_name="Понеділок",
            lessons=lessons,
            cancelled_pairs=cancelled_map
        )

        # Перша пара активна
        self.assertIn("<b>1.</b> <code>08:30</code> — <b>Основи програмування</b>", text)
        self.assertNotIn("<s><b>1.</b>", text)

        # Друга пара перекреслена і позначена як СКАСОВАНО
        self.assertIn("<s><b>2.</b> <code>10:25</code> — <b>Теорія ймовірностей</b> (Практика)</s> 🚫 <b>СКАСОВАНО!</b>", text)
        self.assertIn("Причина: Хворіє викладач", text)


if __name__ == "__main__":
    unittest.main()

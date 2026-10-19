import unittest
from datetime import date
from unittest.mock import patch, AsyncMock
import httpx

from database import (
    init_db,
    save_campus_schedule_cache_db,
    get_campus_schedule_cache_db,
    get_db
)
from kpi_api import get_raw_schedule, get_lessons_for_date
from formatters import format_morning_digest

DUMMY_CAMPUS_SCHEDULE = {
    "scheduleFirstWeek": [
        {
            "day": "Пн",
            "pairs": [
                {
                    "name": "Основи програмування (Кеш)",
                    "type": "Лекція",
                    "time": "08:30:00",
                    "lecturer": {"name": "Проф. Тестовий"},
                    "location": "315"
                }
            ]
        }
    ],
    "scheduleSecondWeek": []
}


class TestCampusResilienceCache(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.test_group_id = 99999
        async with get_db() as db:
            await db.execute("DELETE FROM campus_schedule_cache WHERE group_id = ?", (str(self.test_group_id),))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM campus_schedule_cache WHERE group_id = ?", (str(self.test_group_id),))
            await db.commit()

    async def test_cache_save_and_retrieve(self):
        await save_campus_schedule_cache_db(self.test_group_id, DUMMY_CAMPUS_SCHEDULE)
        cached_data, cached_at = await get_campus_schedule_cache_db(self.test_group_id)

        self.assertIsNotNone(cached_data)
        self.assertIsNotNone(cached_at)
        self.assertEqual(len(cached_data["scheduleFirstWeek"]), 1)
        self.assertEqual(cached_data["scheduleFirstWeek"][0]["day"], "Пн")

    async def test_fallback_to_cache_when_campus_fails(self):
        # 1. Заздалегідь наповнюємо кеш
        await save_campus_schedule_cache_db(self.test_group_id, DUMMY_CAMPUS_SCHEDULE)

        # 2. Мокаємо httpx.AsyncClient так, ніби Campus API повертає 502 Bad Gateway
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectTimeout("Campus API down")):
            data, is_cached, cached_at = await get_raw_schedule(self.test_group_id, use_cache_on_fail=True)

            self.assertTrue(is_cached)
            self.assertIsNotNone(cached_at)
            self.assertEqual(data["scheduleFirstWeek"][0]["pairs"][0]["name"], "Основи програмування (Кеш)")

    def test_formatter_includes_offline_badge(self):
        cached_lessons = [
            {
                "name": "Основи програмування",
                "type": "Лекція",
                "time": "08:30",
                "lecturer": "Професор",
                "is_offline_cache": True
            }
        ]

        text, _ = format_morning_digest(1, "Понеділок", cached_lessons)
        self.assertIn("автономного офлайн-кешу", text)


if __name__ == "__main__":
    unittest.main()

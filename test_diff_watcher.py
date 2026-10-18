import unittest
from diff_watcher import calculate_schedule_diff, format_schedule_diff_alert
from database import (
    init_db,
    save_schedule_snapshot_db,
    get_latest_schedule_snapshot_db,
    get_db
)

OLD_SCHEDULE = {
    "scheduleFirstWeek": [
        {
            "day": "Пн",
            "pairs": [
                {
                    "name": "Основи програмування",
                    "type": "Лекція",
                    "time": "08:30:00",
                    "location": "ауд. 315, корпус 18",
                    "lecturer": {"name": "Іванов І.І."}
                },
                {
                    "name": "АСД",
                    "type": "Лабораторна",
                    "time": "10:25:00",
                    "location": "ауд. 402",
                    "lecturer": {"name": "Петров П.П."}
                }
            ]
        }
    ],
    "scheduleSecondWeek": []
}

NEW_SCHEDULE = {
    "scheduleFirstWeek": [
        {
            "day": "Пн",
            "pairs": [
                {
                    "name": "Основи програмування",
                    "type": "Лекція",
                    "time": "08:30:00",
                    "location": "Дистанційно (Zoom)",  # Зміна локації!
                    "lecturer": {"name": "Сидоренко С.С."}  # Зміна викладача!
                },
                # АСД видалено!
                {
                    "name": "Комп'ютерні мережі",  # Нова пара!
                    "type": "Практика",
                    "time": "12:20:00",
                    "location": "ауд. 101",
                    "lecturer": {"name": "Коваленко К.К."}
                }
            ]
        }
    ],
    "scheduleSecondWeek": []
}


class TestScheduleDiffWatcher(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.group_id = 12345
        async with get_db() as db:
            await db.execute("DELETE FROM schedule_snapshots WHERE group_id = ?", (str(self.group_id),))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM schedule_snapshots WHERE group_id = ?", (str(self.group_id),))
            await db.commit()

    def test_diff_detection(self):
        diffs = calculate_schedule_diff(OLD_SCHEDULE, NEW_SCHEDULE)
        diff_types = [d["type"] for d in diffs]

        # 1. Локація змінилась (315 -> Zoom)
        self.assertIn("LOCATION_CHANGED", diff_types)

        # 2. Викладач змінився (Іванов -> Сидоренко)
        self.assertIn("LECTURER_CHANGED", diff_types)

        # 3. Видалена пара АСД
        self.assertIn("REMOVED", diff_types)

        # 4. Додана пара Мережі
        self.assertIn("ADDED", diff_types)

    def test_alert_formatting(self):
        import html
        diffs = calculate_schedule_diff(OLD_SCHEDULE, NEW_SCHEDULE)
        alert = format_schedule_diff_alert(diffs)

        self.assertIn("УВАГА! Деканат змінив розклад пар", alert)
        self.assertIn("Дистанційно (Zoom)", alert)
        self.assertIn("Сидоренко С.С.", alert)
        self.assertIn("Комп'ютерні мережі", html.unescape(alert))

    async def test_snapshot_db_persistence(self):
        await save_schedule_snapshot_db(self.group_id, OLD_SCHEDULE)
        loaded = await get_latest_schedule_snapshot_db(self.group_id)

        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded["scheduleFirstWeek"]), 1)
        self.assertEqual(loaded["scheduleFirstWeek"][0]["pairs"][0]["name"], "Основи програмування")


if __name__ == "__main__":
    unittest.main()

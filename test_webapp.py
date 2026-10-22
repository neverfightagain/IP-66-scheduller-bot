import unittest
import asyncio
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web
from unittest.mock import AsyncMock, MagicMock

from database import init_db, get_db, join_queue_db, set_queue_message_id_db
from webapp_server import create_webapp_app, sync_queue_message_in_chat

class TestWebAppServer(AioHTTPTestCase):
    async def get_application(self):
        self.mock_bot = MagicMock()
        self.mock_bot.edit_message_text = AsyncMock()
        return create_webapp_app(self.mock_bot)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await init_db()
        self.chat_id = 999888
        self.subject = "ОП"
        async with get_db() as db:
            await db.execute("DELETE FROM lab_queues WHERE chat_id = ?", (self.chat_id,))
            await db.execute("DELETE FROM queue_chat_messages WHERE chat_id = ?", (self.chat_id,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM lab_queues WHERE chat_id = ?", (self.chat_id,))
            await db.execute("DELETE FROM queue_chat_messages WHERE chat_id = ?", (self.chat_id,))
            await db.commit()
        await super().asyncTearDown()

    async def test_health_and_status_endpoints(self):
        # GET /
        resp_root = await self.client.request("GET", "/")
        self.assertEqual(resp_root.status, 200)
        text_root = await resp_root.text()
        self.assertIn("KPI Schedule Bot is OK", text_root)

        # GET /health
        resp_health = await self.client.request("GET", "/health")
        self.assertEqual(resp_health.status, 200)

        # GET /status
        resp_status = await self.client.request("GET", "/status")
        self.assertEqual(resp_status.status, 200)
        data_status = await resp_status.json()
        self.assertEqual(data_status["status"], "online")
        self.assertIn("webapp_url", data_status)

    async def test_app_index_serving(self):
        resp = await self.client.request("GET", "/app")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("IP-66 Hub", text)
        self.assertIn("telegram-web-app.js", text)

    async def test_api_queue_flow(self):
        # 1. Порожня черга
        resp = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["items"]), 0)

        # 2. Join черги через API
        join_payload = {
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 777,
            "user_name": "Тестовий Студент",
            "username": "test_user",
            "lab_number": "Лаби 1, 4"
        }
        resp_join = await self.client.request("POST", "/api/queue/join", json=join_payload)
        self.assertEqual(resp_join.status, 200)
        data_join = await resp_join.json()
        self.assertTrue(data_join["success"])
        self.assertEqual(data_join["position"], 1)

        # 3. Перевірка списку черги
        resp_q = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        data_q = await resp_q.json()
        self.assertEqual(len(data_q["items"]), 1)
        self.assertEqual(data_q["items"][0]["user_name"], "Тестовий Студент")
        self.assertEqual(data_q["items"][0]["lab_priority"], 1)

        # 4. Next student
        resp_next = await self.client.request("POST", "/api/queue/next", json={"chat_id": self.chat_id, "subject": self.subject})
        self.assertEqual(resp_next.status, 200)
        data_next = await resp_next.json()
        self.assertTrue(data_next["success"])
        self.assertEqual(data_next["student"]["user_name"], "Тестовий Студент")

        # Черга знову порожня
        resp_empty = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        data_empty = await resp_empty.json()
        self.assertEqual(len(data_empty["items"]), 0)

    async def test_api_queue_leave(self):
        # Додаємо студента
        await join_queue_db(self.chat_id, self.subject, 888, "Студент Вихід", lab_number="Лаба 2")

        # Вихід через API
        resp_leave = await self.client.request("POST", "/api/queue/leave", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 888
        })
        self.assertEqual(resp_leave.status, 200)
        data_leave = await resp_leave.json()
        self.assertTrue(data_leave["success"])

        # Перевірка що вихід відбувся
        resp_check = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        data_check = await resp_check.json()
        self.assertEqual(len(data_check["items"]), 0)

    async def test_chat_message_sync(self):
        # Записуємо message_id в базу
        await set_queue_message_id_db(self.chat_id, 12345, self.subject)

        # Викликаємо sync_queue_message_in_chat
        synced = await sync_queue_message_in_chat(self.mock_bot, self.chat_id, self.subject)
        self.assertTrue(synced)
        self.mock_bot.edit_message_text.assert_called_once()
        args, kwargs = self.mock_bot.edit_message_text.call_args
        self.assertEqual(kwargs["chat_id"], self.chat_id)
        self.assertEqual(kwargs["message_id"], 12345)
        self.assertIn("Жива черга на захист: ОП", args[0])

    async def test_api_schedule_and_deadlines(self):
        # GET /api/schedule?day=today
        resp_sched = await self.client.request("GET", "/api/schedule?day=today")
        self.assertEqual(resp_sched.status, 200)
        data_sched = await resp_sched.json()
        self.assertTrue(data_sched["success"])
        self.assertIn("lessons", data_sched)
        self.assertEqual(data_sched["mode"], "day")

        # GET /api/schedule?day=week
        resp_week = await self.client.request("GET", "/api/schedule?day=week")
        self.assertEqual(resp_week.status, 200)
        data_week = await resp_week.json()
        self.assertTrue(data_week["success"])
        self.assertEqual(data_week["mode"], "week")
        self.assertIn("days", data_week)
        self.assertEqual(len(data_week["days"]), 6)  # Пн..Сб

        # GET /api/deadlines
        resp_dead = await self.client.request("GET", "/api/deadlines")
        self.assertEqual(resp_dead.status, 200)
        data_dead = await resp_dead.json()
        self.assertTrue(data_dead["success"])
        self.assertIn("deadlines", data_dead)
        for dl in data_dead["deadlines"]:
            self.assertIn("alternate_link", dl)

    async def test_students_roster_and_name_resolution(self):
        from database import add_or_update_student_db, get_all_students_db, find_student_real_name_db
        # 1. Додавання студента
        ok = await add_or_update_student_db("Шевченко Тарас", "taras_tg", 555444, subgroup=1)
        self.assertTrue(ok)

        # 2. Пошук реального імені
        real_by_id = await find_student_real_name_db(user_id=555444)
        self.assertEqual(real_by_id, "Шевченко Тарас")

        real_by_uname = await find_student_real_name_db(telegram_username="taras_tg")
        self.assertEqual(real_by_uname, "Шевченко Тарас")

        # 3. GET /api/students
        resp = await self.client.request("GET", "/api/students")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(any(s["real_name"] == "Шевченко Тарас" for s in data["students"]))

        # 4. GET /api/student/resolve
        resp_resolve = await self.client.request("GET", "/api/student/resolve?user_id=555444")
        self.assertEqual(resp_resolve.status, 200)
        data_resolve = await resp_resolve.json()
        self.assertTrue(data_resolve["success"])
        self.assertEqual(data_resolve["real_name"], "Шевченко Тарас")
        self.assertEqual(data_resolve["first_name"], "Тарас")
        self.assertEqual(data_resolve["short_name"], "Шевченко Тарас")

        # 5. Join черги із заміною імені
        join_payload = {
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 555444,
            "user_name": "NicknameNotInRealLife",
            "username": "taras_tg",
            "lab_number": "Лаба 1"
        }
        resp_join = await self.client.request("POST", "/api/queue/join", json=join_payload)
        self.assertEqual(resp_join.status, 200)

        # Перевіряємо що в черзі збережено реальне ім'я
        resp_q = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        data_q = await resp_q.json()
        self.assertEqual(data_q["items"][0]["user_name"], "Шевченко Тарас")

    async def test_dynamic_queue_priority_and_multi_lab_updates(self):
        # 1. Студент 1 (Максим, id=101) записується на Лабу 5
        resp1 = await self.client.request("POST", "/api/queue/join", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 101,
            "user_name": "Максим Сінчіневіч",
            "username": "sinch",
            "lab_number": "Лаба 5"
        })
        self.assertEqual(resp1.status, 200)
        data1 = await resp1.json()
        self.assertTrue(data1["success"])
        self.assertEqual(data1["position"], 1)

        # 2. Студент 2 (Дмитро, id=102) також записується на Лабу 5 (пріоритет 5, після Максима)
        resp2 = await self.client.request("POST", "/api/queue/join", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 102,
            "user_name": "Дмитро Сахнюк",
            "username": "sahnyuk",
            "lab_number": "Лаба 5"
        })
        data2 = await resp2.json()
        self.assertTrue(data2["success"])
        self.assertEqual(data2["position"], 2)

        # 3. Студент 1 додає ще роботу: тепер здає "Лаби 5, 6"
        # Пріоритет залишається 5 -> початкове місце #1 повинно ЗБЕРЕГТИСЯ!
        resp1_up = await self.client.request("POST", "/api/queue/join", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 101,
            "user_name": "Максим Сінчіневіч",
            "username": "sinch",
            "lab_number": "Лаби 5, 6"
        })
        data1_up = await resp1_up.json()
        self.assertTrue(data1_up["success"])
        self.assertEqual(data1_up["position"], 1)

        # Перевірка через GET /api/queue
        q_resp = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        q_data = await q_resp.json()
        self.assertEqual(len(q_data["items"]), 2)
        self.assertEqual(q_data["items"][0]["user_id"], 101)
        self.assertEqual(q_data["items"][0]["lab_number"], "Лаби 5, 6")
        self.assertEqual(q_data["items"][1]["user_id"], 102)

        # 4. Студент 3 (Назар, id=103) записується на Лабу 4 (пріоритет 4)
        # Оскільки пріоритет 4 кращий за 5, Назар стає першим (#1), Максим стає #2, Дмитро #3
        resp3 = await self.client.request("POST", "/api/queue/join", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 103,
            "user_name": "Назар Архипович",
            "username": "arhyp",
            "lab_number": "Лаба 4"
        })
        data3 = await resp3.json()
        self.assertEqual(data3["position"], 1)

        # 5. КРАЙНІЙ ВИПАДОК: Студент 1 (Максим) прибирає Лабу 5 і залишає лише "Лаба 6"!
        # Його пріоритет погіршується з 5 до 6!
        # Він НЕ повинен залишатися попереду Дмитра (у якого пріоритет 5)!
        # Максим повинен стати позаду Дмитра (#3)!
        resp1_drop = await self.client.request("POST", "/api/queue/join", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 101,
            "user_name": "Максим Сінчіневіч",
            "username": "sinch",
            "lab_number": "Лаба 6"
        })
        data1_drop = await resp1_drop.json()
        self.assertTrue(data1_drop["success"])
        self.assertEqual(data1_drop["position"], 3)

        q_after_drop = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        items_drop = (await q_after_drop.json())["items"]
        self.assertEqual(items_drop[0]["user_id"], 103)  # Назар (Лаба 4, пріоритет 4) - #1
        self.assertEqual(items_drop[1]["user_id"], 102)  # Дмитро (Лаба 5, пріоритет 5) - #2
        self.assertEqual(items_drop[2]["user_id"], 101)  # Максим (Лаба 6, пріоритет 6) - #3

        # 6. Студент 1 додає Лабу 2: тепер "Лаби 2, 6"
        # Пріоритет стає 2 (кращий за 4, 5, 6)!
        # Максим повинен стрибнути на позицію #1!
        resp1_boost = await self.client.request("POST", "/api/queue/join", json={
            "chat_id": self.chat_id,
            "subject": self.subject,
            "user_id": 101,
            "user_name": "Максим Сінчіневіч",
            "username": "sinch",
            "lab_number": "Лаби 2, 6"
        })
        data1_boost = await resp1_boost.json()
        self.assertTrue(data1_boost["success"])
        self.assertEqual(data1_boost["position"], 1)

        q_after_boost = await self.client.request("GET", f"/api/queue?subject={self.subject}&chat_id={self.chat_id}")
        items_boost = (await q_after_boost.json())["items"]
        self.assertEqual(items_boost[0]["user_id"], 101)  # Максим (Лаби 2, 6) - #1
        self.assertEqual(items_boost[1]["user_id"], 103)  # Назар (Лаба 4) - #2
        self.assertEqual(items_boost[2]["user_id"], 102)  # Дмитро (Лаба 5) - #3

    async def test_ui_frontend_simulation(self):
        import subprocess
        # Запуск повного тесту UI контролера через Node.js
        result = subprocess.run(
            ["node", "test_frontend_ui.js"],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0, f"Frontend UI test failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        self.assertIn("ALL UI TESTS PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()

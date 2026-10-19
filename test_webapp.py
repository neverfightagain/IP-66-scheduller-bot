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
        self.assertIn("ІП-66 Студентський Портал", text)
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
        # GET /api/schedule
        resp_sched = await self.client.request("GET", "/api/schedule?day=today")
        self.assertEqual(resp_sched.status, 200)
        data_sched = await resp_sched.json()
        self.assertTrue(data_sched["success"])
        self.assertIn("lessons", data_sched)

        # GET /api/deadlines
        resp_dead = await self.client.request("GET", "/api/deadlines")
        self.assertEqual(resp_dead.status, 200)
        data_dead = await resp_dead.json()
        self.assertTrue(data_dead["success"])
        self.assertIn("deadlines", data_dead)


if __name__ == "__main__":
    unittest.main()

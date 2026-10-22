import asyncio
import unittest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from config import OWNER_ID
import database
from webapp_server import create_webapp_app


class AdminPanelTestCase(AioHTTPTestCase):
    async def get_application(self):
        await database.init_db()
        return create_webapp_app(bot=None)

    @unittest_run_loop
    async def test_admin_me_and_test_mode(self):
        # 1. Test mode default is True
        await database.set_admin_test_mode_db(True)

        # 2. Owner access
        resp = await self.client.get(f"/api/admin/me?user_id={OWNER_ID}&username=neverfightaga1n")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("is_admin"))
        self.assertTrue(data.get("is_owner"))
        self.assertEqual(data.get("role"), "owner")
        self.assertTrue(data.get("test_mode"))

        # 3. Non-owner during test_mode -> not admin
        resp = await self.client.get("/api/admin/me?user_id=11111&username=other_user")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertFalse(data.get("is_admin"))
        self.assertFalse(data.get("is_owner"))

        # 4. Turn off test_mode via owner
        resp = await self.client.post("/api/admin/test_mode", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "test_mode": False
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))
        self.assertFalse(data.get("test_mode"))

        # Non-owner trying to toggle test_mode -> 403
        resp = await self.client.post("/api/admin/test_mode", json={
            "user_id": 11111,
            "username": "other_user",
            "test_mode": True
        })
        self.assertEqual(resp.status, 403)

        # 5. Grant role to deputy
        resp = await self.client.post("/api/admin/roles/grant", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "target_user_id": 22222,
            "target_username": "deputy_user",
            "target_real_name": "Іван Тестовий",
            "role": "deputy"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))
        roles = data.get("roles", [])
        self.assertTrue(any(r["username"] == "deputy_user" for r in roles))

        # Check deputy access now that test_mode is False
        resp = await self.client.get("/api/admin/me?user_id=22222&username=deputy_user")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("is_admin"))
        self.assertFalse(data.get("is_owner"))
        self.assertEqual(data.get("role"), "deputy")

        # Clean up role
        resp = await self.client.post("/api/admin/roles/revoke", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "target_user_id": 22222,
            "target_username": "deputy_user"
        })
        self.assertEqual(resp.status, 200)

        # Re-enable test mode
        await database.set_admin_test_mode_db(True)

    @unittest_run_loop
    async def test_custom_lessons_and_schedule(self):
        target_date = "2026-10-23"

        # 1. Add custom pair
        resp = await self.client.post("/api/admin/schedule/add_pair", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "date": target_date,
            "pair_number": 3,
            "name": "Комп'ютерна графіка",
            "type": "Лабораторна",
            "lecturer": "Доцент Тестовий",
            "link_url": "https://meet.google.com/test-abc",
            "comment": "Пароль: 123",
            "admin_name": "Власник"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))
        new_id = data.get("id")
        self.assertGreater(new_id, 0)

        # 2. Check /api/schedule with date=target_date
        resp = await self.client.get(f"/api/schedule?date={target_date}")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("mode"), "day")
        self.assertEqual(data.get("date_iso"), target_date)
        lessons = data.get("lessons", [])
        custom = next((l for l in lessons if l.get("custom_id") == new_id), None)
        self.assertIsNotNone(custom)
        self.assertTrue(custom.get("is_custom"))
        self.assertEqual(custom.get("name"), "Комп'ютерна графіка")
        self.assertEqual(custom.get("time"), "12:20")
        self.assertEqual(custom.get("link_url"), "https://meet.google.com/test-abc")
        self.assertFalse(custom.get("is_cancelled"))

        # 3. Cancel this pair
        resp = await self.client.post("/api/admin/schedule/cancel", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "date": target_date,
            "pair_number": 3,
            "subject": "Комп'ютерна графіка",
            "reason": "Хворіє викладач",
            "admin_name": "Власник"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))

        # Verify it reflects as cancelled in /api/schedule
        resp = await self.client.get(f"/api/schedule?date={target_date}")
        data = await resp.json()
        lessons = data.get("lessons", [])
        custom = next((l for l in lessons if l.get("custom_id") == new_id), None)
        self.assertIsNotNone(custom)
        self.assertTrue(custom.get("is_cancelled"))
        self.assertEqual(custom.get("cancel_reason"), "Хворіє викладач")

        # 4. Uncancel this pair
        resp = await self.client.post("/api/admin/schedule/uncancel", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "date": target_date,
            "pair_number": 3
        })
        self.assertEqual(resp.status, 200)

        resp = await self.client.get(f"/api/schedule?date={target_date}")
        data = await resp.json()
        lessons = data.get("lessons", [])
        custom = next((l for l in lessons if l.get("custom_id") == new_id), None)
        self.assertFalse(custom.get("is_cancelled"))

        # 5. Delete custom pair
        resp = await self.client.post("/api/admin/schedule/delete_pair", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "id": new_id
        })
        self.assertEqual(resp.status, 200)

        resp = await self.client.get(f"/api/schedule?date={target_date}")
        data = await resp.json()
        lessons = data.get("lessons", [])
        custom = next((l for l in lessons if l.get("custom_id") == new_id), None)
        self.assertIsNone(custom)

    @unittest_run_loop
    async def test_admin_clear_queue(self):
        # 1. Join queue
        resp = await self.client.post("/api/queue/join", json={
            "chat_id": 99999,
            "subject": "ОП",
            "user_id": 77777,
            "user_name": "Тест Студент",
            "lab_number": "Лаба 1"
        })
        self.assertEqual(resp.status, 200)

        # 2. Clear queue via admin
        resp = await self.client.post("/api/admin/queue/clear", json={
            "user_id": OWNER_ID,
            "username": "neverfightaga1n",
            "chat_id": 99999,
            "subject": "ОП"
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data.get("success"))

        # 3. Verify queue is now empty
        resp = await self.client.get("/api/queue?chat_id=99999&subject=ОП")
        data = await resp.json()
        self.assertEqual(len(data.get("items", [])), 0)


if __name__ == "__main__":
    unittest.main()

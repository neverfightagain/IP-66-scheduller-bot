import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock
from aiohttp.test_utils import AioHTTPTestCase

import database
from database import (
    init_db,
    toggle_student_lab_defense_db,
    get_student_defended_labs_db,
)
from formatters import format_lecture_summary
from webapp_server import create_webapp_app


class TestLabDefensesManualSystem(AioHTTPTestCase):
    async def get_application(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._orig_db_path = database.DB_PATH
        database.DB_PATH = os.path.join(self._tmp_dir.name, "test_defenses_manual.db")
        await init_db()

        self.mock_bot = MagicMock()
        self.mock_bot.edit_message_text = AsyncMock()
        self.mock_bot.send_message = AsyncMock()
        return create_webapp_app(self.mock_bot)

    async def asyncTearDown(self):
        await super().asyncTearDown()
        database.DB_PATH = self._orig_db_path
        self._tmp_dir.cleanup()

    async def test_format_lecture_summary_no_auto_defenses(self):
        summary = {
            "subject_detected": "Основи програмування",
            "topic": "Двозв'язні списки та захист лабораторних",
            "summary_points": ["Розбір структури вузла списку"],
            "teacher_announcements": ["Наступного тижня колоквіум"],
        }
        text, kb = format_lecture_summary(summary, video_title="Практика 3", video_url="https://youtu.be/test1234567")
        self.assertIn("Основи програмування", text)
        self.assertNotIn("Зафіксовані захисти лабораторних", text)

    async def test_toggle_student_lab_defense(self):
        # 1. Ручне відмічання (додавання)
        res_add = await toggle_student_lab_defense_db("Тест Студент Тогл", "ОП", "Практикум 2", telegram_id=333444)
        self.assertTrue(res_add["passed"])

        defended = await get_student_defended_labs_db(real_name="Тест Студент Тогл", subject="ОП")
        self.assertEqual(len(defended), 1)
        self.assertEqual(defended[0]["lab_number"], "Практикум 2")

        # 2. Повторне натискання (зняття відмітки)
        res_del = await toggle_student_lab_defense_db("Тест Студент Тогл", "ОП", "Практикум 2", telegram_id=333444)
        self.assertFalse(res_del["passed"])
        self.assertEqual(res_del["action"], "removed")

    async def test_api_subjects_overview(self):
        resp = await self.client.request("GET", "/api/subjects/overview")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertIn("ОП", data["subjects"])
        self.assertIn("АСД", data["subjects"])
        self.assertEqual(data["subjects"]["ОП"]["term_plural"], "Практикуми")
        self.assertEqual(data["subjects"]["ОП"]["term_singular"], "Практикум")
        self.assertEqual(data["subjects"]["АСД"]["term_plural"], "Практичні роботи")
        self.assertEqual(data["subjects"]["АСД"]["term_singular"], "Практична робота")

    async def test_api_defenses_toggle_endpoint(self):
        payload = {
            "real_name": "Тест Сінчіневіч API",
            "subject": "ОП",
            "lab_number": "Практикум 3",
            "user_id": 999333
        }
        resp = await self.client.request("POST", "/api/defenses/toggle", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["passed"])

        # Перевірка отримання через GET /api/defenses
        resp_get = await self.client.request("GET", "/api/defenses?user_id=999333&subject=ОП")
        self.assertEqual(resp_get.status, 200)
        data_get = await resp_get.json()
        self.assertTrue(data_get["success"])
        self.assertEqual(data_get["total"], 1)

        # Перевірка зняття відмітки тим же ендпоінтом
        resp_toggle_off = await self.client.request("POST", "/api/defenses/toggle", json=payload)
        self.assertEqual(resp_toggle_off.status, 200)
        data_off = await resp_toggle_off.json()
        self.assertTrue(data_off["success"])
        self.assertFalse(data_off["passed"])


if __name__ == "__main__":
    unittest.main()

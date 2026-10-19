import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from aiohttp.test_utils import AioHTTPTestCase

from database import (
    init_db,
    get_db,
    add_or_update_student_db,
    join_queue_db,
    get_active_queue_db,
    record_lab_defense_db,
    get_student_defended_labs_db,
    remove_student_from_subject_queues_db,
    resolve_student_by_voice_mention,
    normalize_queue_subject,
)
from formatters import format_lecture_summary
from webapp_server import create_webapp_app


class TestLabDefensesSystem(AioHTTPTestCase):
    async def get_application(self):
        self.mock_bot = MagicMock()
        self.mock_bot.edit_message_text = AsyncMock()
        self.mock_bot.send_message = AsyncMock()
        return create_webapp_app(self.mock_bot)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await init_db()
        self.chat_id = -1004483900746
        self.subject = "ОП"

        # Очищення тестових таблиць
        async with get_db() as db:
            await db.execute("DELETE FROM lab_defenses WHERE subject IN ('ОП', 'АСД')")
            await db.execute("DELETE FROM lab_queues WHERE chat_id = ?", (self.chat_id,))
            await db.execute("DELETE FROM students WHERE real_name LIKE 'Тест%' OR telegram_username = 'test_max'")
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM lab_defenses WHERE subject IN ('ОП', 'АСД')")
            await db.execute("DELETE FROM lab_queues WHERE chat_id = ?", (self.chat_id,))
            await db.execute("DELETE FROM students WHERE real_name LIKE 'Тест%' OR telegram_username = 'test_max'")
            await db.commit()
        await super().asyncTearDown()

    async def test_record_and_get_defenses(self):
        # 1. Запис першого захисту
        def_id_1 = await record_lab_defense_db(
            real_name="Тест Сінчіневіч Максим",
            subject="ОП",
            lab_number="Лаба 1",
            telegram_id=111222,
            video_id="vid_test_1",
            timestamp_sec=2535,
            exact_quote="Сінчіневіч, першу лабу прийняв",
            status="passed"
        )
        self.assertGreater(def_id_1, 0)

        # 2. Повторний запис того ж самого захисту (ідемпотентність)
        def_id_dup = await record_lab_defense_db(
            real_name="Тест Сінчіневіч Максим",
            subject="ОП",
            lab_number="Лаба 1",
            telegram_id=111222,
            video_id="vid_test_1"
        )
        self.assertEqual(def_id_1, def_id_dup)

        # 3. Запис другої лаби
        def_id_2 = await record_lab_defense_db(
            real_name="Тест Сінчіневіч Максим",
            subject="ОП",
            lab_number="Лаба 2",
            telegram_id=111222,
            video_id="vid_test_2"
        )
        self.assertNotEqual(def_id_1, def_id_2)

        # 4. Отримання списку захищених робіт
        items = await get_student_defended_labs_db(user_id=111222, subject="ОП")
        self.assertEqual(len(items), 2)
        labs = [it["lab_number"] for it in items]
        self.assertIn("Лаба 1", labs)
        self.assertIn("Лаба 2", labs)

    async def test_resolve_student_by_voice_mention(self):
        # Додаємо тестових студентів у базу з унікальними прізвищами
        await add_or_update_student_db("Кібернетенко Максим Ігорович", "test_kiber", 1001, subgroup=1)
        await add_or_update_student_db("Роботенко Назар Миколайович", "test_robot", 1002, subgroup=2)
        await add_or_update_student_db("Алгоритменко Максим Олегович", "test_algo", 1003, subgroup=2)

        # 1. Пошук за прізвищем
        match_surname = await resolve_student_by_voice_mention("Кібернетенко")
        self.assertIsNotNone(match_surname)
        self.assertEqual(match_surname["telegram_id"], 1001)

        match_nazar = await resolve_student_by_voice_mention("Назар Роботенко")
        self.assertIsNotNone(match_nazar)
        self.assertEqual(match_nazar["telegram_id"], 1002)

        # 2. Неоднозначне ім'я ("Максим") без черги
        match_any = await resolve_student_by_voice_mention("Максим")
        self.assertIsNotNone(match_any)

        # 3. Контекст черги: Кібернетенко стоїть у черзі на ОП!
        await join_queue_db(self.chat_id, "ОП", 1001, "Кібернетенко Максим", "test_kiber", "Лаба 1")

        # Тепер коли викладач каже просто "Максим", контекст черги віддає перевагу Кібернетенку!
        match_prio = await resolve_student_by_voice_mention("Максим", subject="ОП")
        self.assertIsNotNone(match_prio)
        self.assertEqual(match_prio["telegram_id"], 1001)

    async def test_remove_student_from_subject_queues(self):
        # Ставимо студента в чергу
        await join_queue_db(self.chat_id, "ОП", 777333, "Тест Студент", "test_st", "Лаба 3")
        q_before = await get_active_queue_db(self.chat_id, "ОП")
        self.assertEqual(len(q_before), 1)

        # Автоматичне вилучення з черги дисципліни
        affected_chats = await remove_student_from_subject_queues_db(777333, "ОП")
        self.assertIn(self.chat_id, affected_chats)

        q_after = await get_active_queue_db(self.chat_id, "ОП")
        self.assertEqual(len(q_after), 0)

    async def test_format_lecture_summary_with_defenses(self):
        summary = {
            "subject_detected": "Основи програмування",
            "topic": "Двозв'язні списки та захист лабораторних",
            "summary_points": ["Розбір структури вузла списку"],
            "teacher_announcements": ["Наступного тижня колоквіум"],
            "defenses_detected": [
                {
                    "student_raw_name": "Сінчіневіч Максим",
                    "lab_number": "Лаба 2",
                    "status": "passed",
                    "timestamp": "42:15"
                }
            ]
        }
        text, kb = format_lecture_summary(summary, video_title="Практика 3", video_url="https://youtu.be/test1234567")
        self.assertIn("Зафіксовані захисти лабораторних", text)
        self.assertIn("Сінчіневіч Максим", text)
        self.assertIn("Лаба 2", text)
        self.assertIn("42:15", text)

    async def test_api_defenses_endpoint(self):
        # Створюємо захист
        await record_lab_defense_db(
            real_name="Тест Студент API",
            subject="ОП",
            lab_number="Лаба 4",
            telegram_id=999111,
            video_id="vid_api_1",
            status="passed"
        )

        resp = await self.client.request("GET", "/api/defenses?user_id=999111&subject=ОП")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["defenses"][0]["lab_number"], "Лаба 4")
        self.assertEqual(data["defenses"][0]["real_name"], "Тест Студент API")


if __name__ == "__main__":
    unittest.main()

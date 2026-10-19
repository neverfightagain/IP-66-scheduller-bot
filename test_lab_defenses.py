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

    async def test_confirm_and_reject_lab_defense_db(self):
        from database import confirm_lab_defense_db, reject_lab_defense_db, get_lab_defense_by_id_db

        # 1. Захист очікує підтвердження (confirmed=0)
        def_id_1 = await record_lab_defense_db(
            real_name="Тест Студент Підтвердження",
            subject="ОП",
            lab_number="Практикум 1",
            telegram_id=555111,
            video_id="vid_conf_1",
            confirmed=0
        )
        rec_before = await get_lab_defense_by_id_db(def_id_1)
        self.assertEqual(rec_before["confirmed"], 0)

        # 2. Підтвердження
        rec_after = await confirm_lab_defense_db(def_id_1)
        self.assertIsNotNone(rec_after)
        self.assertEqual(rec_after["confirmed"], 1)
        self.assertEqual(rec_after["status"], "passed")

        # 3. Відхилення другого захисту
        def_id_2 = await record_lab_defense_db(
            real_name="Тест Студент Відхилення",
            subject="АСД",
            lab_number="Практична 1",
            telegram_id=555222,
            video_id="vid_conf_2",
            confirmed=0
        )
        rej_ok = await reject_lab_defense_db(def_id_2)
        self.assertTrue(rej_ok)
        rec_rej = await get_lab_defense_by_id_db(def_id_2)
        self.assertEqual(rec_rej["status"], "rejected")

    async def test_get_student_queue_positions(self):
        from database import get_student_queue_positions_db

        # Ставимо студента в чергу
        await join_queue_db(self.chat_id, "ОП", 888111, "Тест Позиція", "pos_user", "Лаба 1")
        positions = await get_student_queue_positions_db(888111, "ОП")
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["position"], 1)
        self.assertEqual(positions[0]["chat_id"], self.chat_id)

    async def test_toggle_student_lab_defense(self):
        from database import toggle_student_lab_defense_db, get_student_defended_labs_db

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
        # Перевірка строгої термінології: Практикуми для ОП, Практичні роботи для АСД
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

        # Перевірка зняття відмітки тим же ендпоінтом
        resp_toggle_off = await self.client.request("POST", "/api/defenses/toggle", json=payload)
        self.assertEqual(resp_toggle_off.status, 200)
        data_off = await resp_toggle_off.json()
        self.assertTrue(data_off["success"])
        self.assertFalse(data_off["passed"])

    async def test_cb_queue_def_confirm_and_reject(self):
        from handlers import cb_queue_actions
        from database import record_lab_defense_db, get_active_queue_db, get_lab_defense_by_id_db

        # Студент стає в чергу
        await join_queue_db(self.chat_id, "ОП", 654321, "Тест Підтверджуваний", "test_conf", "Лаба 1")
        q_init = await get_active_queue_db(self.chat_id, "ОП")
        self.assertEqual(len(q_init), 1)

        # Створюємо захист, що очікує підтвердження
        def_id = await record_lab_defense_db(
            real_name="Тест Підтверджуваний",
            subject="ОП",
            lab_number="Практикум 1",
            telegram_id=654321,
            video_id="vid_test_cb",
            confirmed=0
        )

        # Mock CallbackQuery для confirm
        mock_cb = MagicMock()
        mock_cb.data = f"q:def_confirm:{def_id}:654321:ОП"
        mock_cb.message.chat.id = self.chat_id
        mock_cb.from_user.full_name = "Староста Тест"
        mock_cb.answer = AsyncMock()
        mock_cb.message.edit_text = AsyncMock()
        mock_cb.bot = self.mock_bot

        await cb_queue_actions(mock_cb)

        # Перевіряємо: захист підтверджено в базі
        def_rec = await get_lab_defense_by_id_db(def_id)
        self.assertEqual(def_rec["confirmed"], 1)

        # Студента автоматично виписано з черги
        q_after = await get_active_queue_db(self.chat_id, "ОП")
        self.assertEqual(len(q_after), 0)
        mock_cb.message.edit_text.assert_called_once()
        self.assertIn("Захист підтверджено", mock_cb.message.edit_text.call_args[0][0])


if __name__ == "__main__":
    unittest.main()


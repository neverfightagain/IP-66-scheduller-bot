import unittest
import asyncio
from database import (
    init_db,
    join_queue_db,
    leave_queue_db,
    get_active_queue_db,
    next_in_queue_db,
    clear_queue_db,
    get_db
)

class TestLabQueueSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.chat_id = 999001
        self.subject = "Тест-АСД"
        async with get_db() as db:
            await db.execute("DELETE FROM lab_queues WHERE chat_id = ?", (self.chat_id,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM lab_queues WHERE chat_id = ?", (self.chat_id,))
            await db.commit()

    async def test_join_and_fifo_order(self):
        # 1. Студент 1 стає в чергу
        ok, msg, pos = await join_queue_db(
            chat_id=self.chat_id,
            subject=self.subject,
            user_id=101,
            user_name="Іван Іванов",
            username="ivanov",
            lab_number="Лаба 1"
        )
        self.assertTrue(ok)
        self.assertEqual(pos, 1)

        # 2. Студент 2 стає в чергу
        ok2, msg2, pos2 = await join_queue_db(
            chat_id=self.chat_id,
            subject=self.subject,
            user_id=102,
            user_name="Петро Петренко",
            username="petrenko",
            lab_number="Лаба 2"
        )
        self.assertTrue(ok2)
        self.assertEqual(pos2, 2)

        # 3. Перевірка списку черги (FIFO)
        q = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(len(q), 2)
        self.assertEqual(q[0]["user_name"], "Іван Іванов")
        self.assertEqual(q[1]["user_name"], "Петро Петренко")

    async def test_duplicate_prevention(self):
        # Додаємо перший раз
        ok, msg, pos = await join_queue_db(
            chat_id=self.chat_id,
            subject=self.subject,
            user_id=101,
            user_name="Іван Іванов"
        )
        self.assertTrue(ok)
        self.assertEqual(pos, 1)

        # Спроба додати вдруге того самого
        ok_dup, msg_dup, pos_dup = await join_queue_db(
            chat_id=self.chat_id,
            subject=self.subject,
            user_id=101,
            user_name="Іван Іванов"
        )
        self.assertFalse(ok_dup)
        self.assertIn("вже знаходитесь", msg_dup)
        self.assertEqual(pos_dup, 1)

    async def test_leave_queue(self):
        await join_queue_db(self.chat_id, self.subject, 101, "Іван Іванов")
        await join_queue_db(self.chat_id, self.subject, 102, "Петро Петренко")

        # Студент 1 виходить з черги
        left = await leave_queue_db(self.chat_id, self.subject, 101)
        self.assertTrue(left)

        q = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["user_name"], "Петро Петренко")

    async def test_next_in_queue(self):
        await join_queue_db(self.chat_id, self.subject, 101, "Іван Іванов")
        await join_queue_db(self.chat_id, self.subject, 102, "Петро Петренко")

        # Переводимо першого студента
        next_student = await next_in_queue_db(self.chat_id, self.subject)
        self.assertIsNotNone(next_student)
        self.assertEqual(next_student["user_name"], "Іван Іванов")

        # Залишився один
        q = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["user_name"], "Петро Петренко")

        # Наступний
        next_student_2 = await next_in_queue_db(self.chat_id, self.subject)
        self.assertEqual(next_student_2["user_name"], "Петро Петренко")

        # Черга порожня
        next_empty = await next_in_queue_db(self.chat_id, self.subject)
        self.assertIsNone(next_empty)

    async def test_multi_subject_isolation(self):
        # Дві різні черги в одному чаті
        await join_queue_db(self.chat_id, "АСД", 101, "Іван Іванов")
        await join_queue_db(self.chat_id, "Мережі", 102, "Петро Петренко")

        q_asd = await get_active_queue_db(self.chat_id, "АСД")
        q_net = await get_active_queue_db(self.chat_id, "Мережі")

        self.assertEqual(len(q_asd), 1)
        self.assertEqual(len(q_net), 1)
        self.assertEqual(q_asd[0]["user_name"], "Іван Іванов")
        self.assertEqual(q_net[0]["user_name"], "Петро Петренко")

        await clear_queue_db(self.chat_id, "АСД")
        await clear_queue_db(self.chat_id, "Мережі")

    async def test_op_and_asd_dual_queues_and_hub(self):
        from handlers import format_queues_hub_view, normalize_queue_subject, format_queue_view

        # Тест нормалізації аліасів
        self.assertEqual(normalize_queue_subject("op"), "ОП")
        self.assertEqual(normalize_queue_subject("оп"), "ОП")
        self.assertEqual(normalize_queue_subject("asd"), "АСД")
        self.assertEqual(normalize_queue_subject("асд"), "АСД")
        self.assertEqual(normalize_queue_subject("Основи програмування"), "ОП")
        self.assertEqual(normalize_queue_subject("Алгоритми та структури даних"), "АСД")

        # Додаємо студентів у чергу ОП
        await join_queue_db(self.chat_id, "ОП", 201, "Олексій Олексієнко", "oleksiy", "Лаба 1")
        # Додаємо студентів у чергу АСД
        await join_queue_db(self.chat_id, "АСД", 202, "Марія Марієнко", "maria", "Лаба 3")

        op_items = await get_active_queue_db(self.chat_id, "ОП")
        asd_items = await get_active_queue_db(self.chat_id, "АСД")

        self.assertEqual(len(op_items), 1)
        self.assertEqual(len(asd_items), 1)
        self.assertEqual(op_items[0]["user_name"], "Олексій Олексієнко")
        self.assertEqual(asd_items[0]["user_name"], "Марія Марієнко")

        # Перевірка форматування Hub (обидві черги в одному повідомленні)
        hub_text, hub_kb = format_queues_hub_view(op_items, asd_items)
        self.assertIn("Основи програмування (ОП)", hub_text)
        self.assertIn("Олексій Олексієнко", hub_text)
        self.assertIn("Алгоритми та структури даних (АСД)", hub_text)
        self.assertIn("Марія Марієнко", hub_text)

        # Перевірка наявності кнопок навігації в Hub
        button_callbacks = [b.callback_data for row in hub_kb.inline_keyboard for b in row]
        self.assertIn("q:view:ОП", button_callbacks)
        self.assertIn("q:view:АСД", button_callbacks)
        self.assertIn("q:pick:ОП:hub", button_callbacks)
        self.assertIn("q:pick:АСД:hub", button_callbacks)

        # Перевірка наявності швидкого перемикання між ОП та АСД в окремих чергах
        op_text, op_kb = format_queue_view("ОП", op_items)
        op_buttons = [b.callback_data for row in op_kb.inline_keyboard for b in row]
        self.assertIn("q:view:АСД", op_buttons)
        self.assertIn("q:pick:ОП", op_buttons)
        self.assertIn("q:hub", op_buttons)

        asd_text, asd_kb = format_queue_view("АСД", asd_items)
        asd_buttons = [b.callback_data for row in asd_kb.inline_keyboard for b in row]
        self.assertIn("q:view:ОП", asd_buttons)
        self.assertIn("q:pick:АСД", asd_buttons)
        self.assertIn("q:hub", asd_buttons)

        # Очищення
        await clear_queue_db(self.chat_id, "ОП")
        await clear_queue_db(self.chat_id, "АСД")

    async def test_physical_deletion_no_dead_rows(self):
        # Перевірка: при leave, next та clear записи дійсно видаляються, а не засмічують базу статусами left/done/cleared
        await join_queue_db(self.chat_id, "ОП", 301, "Тест 1", "test1", "Лаба 1")
        await join_queue_db(self.chat_id, "ОП", 302, "Тест 2", "test2", "Лаба 2")

        # Перевіряємо прямим SQL-запитом кількість рядків у таблиці
        async with get_db() as db:
            async with db.execute("SELECT COUNT(*) as cnt FROM lab_queues WHERE chat_id = ? AND subject = 'ОП'", (self.chat_id,)) as c:
                row = await c.fetchone()
                self.assertEqual(row["cnt"], 2)

        # Студент 301 виходить з черги -> рядок фізично видаляється
        await leave_queue_db(self.chat_id, "ОП", 301)
        async with get_db() as db:
            async with db.execute("SELECT COUNT(*) as cnt FROM lab_queues WHERE chat_id = ? AND subject = 'ОП'", (self.chat_id,)) as c:
                row = await c.fetchone()
                self.assertEqual(row["cnt"], 1)

        # Викликаємо студента 302 на захист (next_in_queue) -> рядок видаляється
        st = await next_in_queue_db(self.chat_id, "ОП")
        self.assertIsNotNone(st)
        self.assertEqual(st["user_id"], 302)
        async with get_db() as db:
            async with db.execute("SELECT COUNT(*) as cnt FROM lab_queues WHERE chat_id = ? AND subject = 'ОП'", (self.chat_id,)) as c:
                row = await c.fetchone()
                self.assertEqual(row["cnt"], 0)

        # Тест оновлення номеру лаби без дублювання записів
        await join_queue_db(self.chat_id, "ОП", 303, "Тест 3", "test3", "Лаба 1")
        ok_upd, msg_upd, _ = await join_queue_db(self.chat_id, "ОП", 303, "Тест 3", "test3", "Лаба 2")
        self.assertTrue(ok_upd)
        self.assertIn("оновлено", msg_upd)

        # Рядок усе ще 1, але лаба тепер "Лаба 2"
        q = await get_active_queue_db(self.chat_id, "ОП")
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["lab_number"], "Лаба 2")

        await clear_queue_db(self.chat_id, "ОП")

    async def test_add_additional_labs_without_losing_queue_position(self):
        # 1. Студент 1 стає в чергу з Лабою 2 (позиція #1)
        ok1, _, pos1 = await join_queue_db(self.chat_id, self.subject, 701, "Олександр", lab_number="Лаба 2")
        self.assertTrue(ok1)
        self.assertEqual(pos1, 1)

        # 2. Студент 2 стає в чергу з Лабою 3 (позиція #2)
        ok2, _, pos2 = await join_queue_db(self.chat_id, self.subject, 702, "Дмитро", lab_number="Лаба 3")
        self.assertTrue(ok2)
        self.assertEqual(pos2, 2)

        # 3. Студент 1 додає ще й Лабу 3 (append=True): тепер здає "Лаби 2, 3"
        ok_add, msg_add, pos_add = await join_queue_db(
            self.chat_id, self.subject, 701, "Олександр", lab_number="Лаба 3", append=True
        )
        self.assertTrue(ok_add)
        self.assertEqual(pos_add, 1)  # Залишається на #1, не летить вниз!

        q = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(len(q), 2)
        self.assertEqual(q[0]["user_name"], "Олександр")
        self.assertEqual(q[0]["lab_number"], "Лаби 2, 3")
        self.assertEqual(q[0]["lab_priority"], 2)

        # 4. Студент 1 оновлює з WebApp (надсилає повний набір "Лаби 2, 4")
        ok_web, _, pos_web = await join_queue_db(
            self.chat_id, self.subject, 701, "Олександр", lab_number="Лаби 2, 4", append=False
        )
        self.assertTrue(ok_web)
        self.assertEqual(pos_web, 1)

        q2 = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(q2[0]["lab_number"], "Лаби 2, 4")
        self.assertEqual(q2[0]["user_name"], "Олександр")

        await clear_queue_db(self.chat_id, self.subject)

    async def test_oldest_labs_surface_to_top(self):
        # 1. Студент з Лабою 4 стає в чергу
        ok1, _, pos1 = await join_queue_db(self.chat_id, self.subject, 401, "Андрій", lab_number="Лаба 4")
        self.assertTrue(ok1)
        self.assertEqual(pos1, 1)

        # 2. Студент з Лабою 2 стає в чергу -> спливає на #1!
        ok2, _, pos2 = await join_queue_db(self.chat_id, self.subject, 402, "Богдан", lab_number="Лаба 2")
        self.assertTrue(ok2)
        self.assertEqual(pos2, 1)

        # 3. Студент з Лабою 1 (найстаріша) -> спливає на #1!
        ok3, _, pos3 = await join_queue_db(self.chat_id, self.subject, 403, "Василь", lab_number="Лаба 1")
        self.assertTrue(ok3)
        self.assertEqual(pos3, 1)

        # 4. Студент з Лабою 2 (однакова з Богданом -> FIFO)
        ok4, _, pos4 = await join_queue_db(self.chat_id, self.subject, 404, "Григорій", lab_number="Лаба 2")
        self.assertTrue(ok4)
        self.assertEqual(pos4, 3)

        # Перевірка черги за порядком
        q = await get_active_queue_db(self.chat_id, self.subject)
        names = [item["user_name"] for item in q]
        self.assertEqual(names, ["Василь", "Богдан", "Григорій", "Андрій"])
        labs = [item["lab_number"] for item in q]
        self.assertEqual(labs, ["Лаба 1", "Лаба 2", "Лаба 2", "Лаба 4"])

        # Наступний у черзі має бути Василь (Лаба 1)
        called = await next_in_queue_db(self.chat_id, self.subject)
        self.assertEqual(called["user_name"], "Василь")
        self.assertEqual(called["lab_number"], "Лаба 1")

        await clear_queue_db(self.chat_id, self.subject)

    async def test_lab_picker_view_and_normalization(self):
        from handlers import format_lab_picker_view
        from database import parse_lab_info

        # Тест розбору номерів однієї та кількох лаб
        self.assertEqual(parse_lab_info("1"), (1, "Лаба 1"))
        self.assertEqual(parse_lab_info("Лаба 2"), (2, "Лаба 2"))
        self.assertEqual(parse_lab_info("Лр 3 захист"), (3, "Лр 3 захист"))
        self.assertEqual(parse_lab_info("1, 4"), (1, "Лаби 1, 4"))
        self.assertEqual(parse_lab_info("4, 1"), (1, "Лаби 1, 4"))
        self.assertEqual(parse_lab_info("Лаби 2, 5"), (2, "Лаби 2, 5"))
        self.assertEqual(parse_lab_info("Лаба 3 і Лаба 6"), (3, "Лаби 3, 6"))
        self.assertEqual(parse_lab_info(""), (999, ""))
        self.assertEqual(parse_lab_info(None), (999, ""))

        # Перевірка клавіатури вибору лаб без обраних
        text, kb = format_lab_picker_view("ОП", selected_labs=[])
        self.assertIn("Вибір практичних/лабораторних робіт (ОП)", text)
        self.assertIn("Пріоритет автоматично розраховується", text)
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("q:t:ОП::1:0", callbacks)
        self.assertIn("q:t:ОП::4:0", callbacks)
        self.assertIn("q:view:ОП", callbacks)
        self.assertIn("q:hub", callbacks)

        # Перевірка клавіатури з кількома обраними лабами (1 та 4)
        text_sel, kb_sel = format_lab_picker_view("ОП", selected_labs=[1, 4])
        self.assertIn("Лаби 1, 4", text_sel)
        self.assertIn("Ваш пріоритет у черзі:</b> Лаба 1", text_sel)
        callbacks_sel = [b.callback_data for row in kb_sel.inline_keyboard for b in row]
        self.assertIn("q:sub:ОП:1,4", callbacks_sel)
        self.assertIn("q:t:ОП::clear:0", callbacks_sel)

        await clear_queue_db(self.chat_id, "ОП")

    async def test_multi_lab_defense_priority(self):
        # Перевірка: коли студент здає кілька лаб (наприклад, 1 і 4),
        # його пріоритет визначається за найменшою/найстарішою лабою (Лаба 1).

        # 1. Студент А здає Лабу 4
        await join_queue_db(self.chat_id, self.subject, 501, "Андрій", lab_number="Лаба 4")

        # 2. Студент Б здає Лаби 1 та 4 (пріоритет 1!) -> має спливти на позицію #1
        ok_b, _, pos_b = await join_queue_db(self.chat_id, self.subject, 502, "Богдан", lab_number="1, 4")
        self.assertTrue(ok_b)
        self.assertEqual(pos_b, 1)

        # 3. Студент В здає Лаби 2 та 3 (пріоритет 2) -> позиція #2 (між Богданом #1 і Андрієм #3)
        ok_v, _, pos_v = await join_queue_db(self.chat_id, self.subject, 503, "Василь", lab_number="2, 3")
        self.assertTrue(ok_v)
        self.assertEqual(pos_v, 2)

        # 4. Студент Г здає тільки Лабу 1 (пріоритет 1, як і у Богдана, але Богдан був раніше -> FIFO)
        ok_g, _, pos_g = await join_queue_db(self.chat_id, self.subject, 504, "Григорій", lab_number="1")
        self.assertTrue(ok_g)
        self.assertEqual(pos_g, 2) # Богдан (1), Григорій (1), Василь (2), Андрій (4)

        # Перевірка списку черги
        q = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(len(q), 4)
        self.assertEqual(q[0]["user_name"], "Богдан")
        self.assertEqual(q[0]["lab_number"], "Лаби 1, 4")

        self.assertEqual(q[1]["user_name"], "Григорій")
        self.assertEqual(q[1]["lab_number"], "Лаба 1")

        self.assertEqual(q[2]["user_name"], "Василь")
        self.assertEqual(q[2]["lab_number"], "Лаби 2, 3")

        self.assertEqual(q[3]["user_name"], "Андрій")
        self.assertEqual(q[3]["lab_number"], "Лаба 4")

        # Наступний на черзі має бути Богдан
        first = await next_in_queue_db(self.chat_id, self.subject)
        self.assertEqual(first["user_name"], "Богдан")
        self.assertEqual(first["lab_number"], "Лаби 1, 4")

        await clear_queue_db(self.chat_id, self.subject)

    async def test_patronymic_removal_and_first_name_extraction(self):
        from database import format_queue_name, extract_first_name

        # Перевірка видалення по-батькові в черзі: "Прізвище Ім'я"
        self.assertEqual(format_queue_name("Архипович Назар Миколайович"), "Архипович Назар")
        self.assertEqual(format_queue_name("Сінчіневіч Максим Ігорович"), "Сінчіневіч Максим")
        self.assertEqual(format_queue_name("Сахнюк Володимирович Дмитро"), "Сахнюк Дмитро")
        self.assertEqual(format_queue_name("Шевченко Тарас"), "Шевченко Тарас")
        self.assertEqual(format_queue_name("Куратор Рома"), "Куратор Рома")
        self.assertEqual(format_queue_name("Максим"), "Максим")
        self.assertEqual(format_queue_name(""), "")

        # Перевірка отримання суто імені для привітання: "Ім'я"
        self.assertEqual(extract_first_name("Архипович Назар Миколайович"), "Назар")
        self.assertEqual(extract_first_name("Сінчіневіч Максим Ігорович"), "Максим")
        self.assertEqual(extract_first_name("Сахнюк Володимирович Дмитро"), "Дмитро")
        self.assertEqual(extract_first_name("Шевченко Тарас"), "Тарас")
        self.assertEqual(extract_first_name("Куратор Рома"), "Рома")
        self.assertEqual(extract_first_name("Максим"), "Максим")
        self.assertEqual(extract_first_name(""), "Студент")

        # Перевірка збереження та відображення в черзі без по-батькові
        await join_queue_db(self.chat_id, self.subject, 601, "Іванов Іван Іванович", lab_number="Лаба 1")
        items = await get_active_queue_db(self.chat_id, self.subject)
        self.assertEqual(items[0]["user_name"], "Іванов Іван")

        called = await next_in_queue_db(self.chat_id, self.subject)
        self.assertEqual(called["user_name"], "Іванов Іван")

        await clear_queue_db(self.chat_id, self.subject)

    async def test_webapp_button_and_deep_link_redirect(self):
        from handlers import make_webapp_button, extract_command_args, cmd_start
        from config import BOT_USERNAME, WEBAPP_URL
        from aiogram.types import Message, Chat, User
        from unittest.mock import AsyncMock

        # 1. Приватний чат (chat_id > 0) -> нативна web_app кнопка
        btn_private = make_webapp_button("Відкрити", f"{WEBAPP_URL}/app?chat_id=123", chat_id=123)
        self.assertIsNotNone(btn_private.web_app)
        self.assertEqual(btn_private.web_app.url, f"{WEBAPP_URL}/app?chat_id=123")
        self.assertIsNone(btn_private.url)

        # 2. Груповий чат (chat_id < 0) -> перенаправлення через deep link у приватні повідомлення бота
        btn_group = make_webapp_button("Відкрити", f"{WEBAPP_URL}/app?chat_id=-1004483900746", chat_id=-1004483900746, subject="ОП")
        self.assertIsNone(btn_group.web_app)
        self.assertIsNotNone(btn_group.url)
        self.assertIn(f"t.me/{BOT_USERNAME}?start=app_m1004483900746_op", btn_group.url)

        # 3. Перевірка для АСД
        btn_asd = make_webapp_button("Відкрити", f"{WEBAPP_URL}/app?chat_id=-1004483900746", chat_id=-1004483900746, subject="АСД")
        self.assertIn("start=app_m1004483900746_asd", btn_asd.url)

        # 4. Перевірка extract_command_args
        self.assertEqual(extract_command_args("/start app_m1004483900746_op"), "app_m1004483900746_op")
        self.assertEqual(extract_command_args("/start"), "")

        # 5. Тест cmd_start з параметром запуску TMA
        mock_msg = AsyncMock(spec=Message)
        mock_msg.chat = Chat(id=777111, type="private")
        mock_msg.from_user = User(id=777111, is_bot=False, first_name="Максим", username="sinch")
        mock_msg.text = "/start app_m1004483900746_op"
        mock_msg.answer = AsyncMock()

        await cmd_start(mock_msg)
        mock_msg.answer.assert_called_once()
        sent_text, kwargs = mock_msg.answer.call_args[0][0], mock_msg.answer.call_args[1]
        self.assertIn("Привіт", sent_text)
        self.assertIn("ІП-66 Портал", sent_text)
        reply_markup = kwargs.get("reply_markup")
        self.assertIsNotNone(reply_markup)
        tma_btn = reply_markup.inline_keyboard[0][0]
        self.assertIsNotNone(tma_btn.web_app)
        self.assertIn("chat_id=-1004483900746", tma_btn.web_app.url)
        self.assertIn("subject=ОП", tma_btn.web_app.url)


if __name__ == "__main__":
    unittest.main()



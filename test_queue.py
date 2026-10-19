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
        self.assertIn("q:join:ОП", button_callbacks)
        self.assertIn("q:join:АСД", button_callbacks)

        # Перевірка наявності швидкого перемикання між ОП та АСД в окремих чергах
        op_text, op_kb = format_queue_view("ОП", op_items)
        op_buttons = [b.callback_data for row in op_kb.inline_keyboard for b in row]
        self.assertIn("q:view:АСД", op_buttons)
        self.assertIn("q:hub", op_buttons)

        asd_text, asd_kb = format_queue_view("АСД", asd_items)
        asd_buttons = [b.callback_data for row in asd_kb.inline_keyboard for b in row]
        self.assertIn("q:view:ОП", asd_buttons)
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


if __name__ == "__main__":
    unittest.main()



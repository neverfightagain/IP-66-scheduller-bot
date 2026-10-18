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
        # Очистити перед тестом
        await clear_queue_db(self.chat_id, self.subject)

    async def asyncTearDown(self):
        await clear_queue_db(self.chat_id, self.subject)

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


if __name__ == "__main__":
    unittest.main()

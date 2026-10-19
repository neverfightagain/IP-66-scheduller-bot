import unittest
from database import (
    init_db,
    claim_topic_db,
    unclaim_topic_db,
    get_claims_by_subject_db,
    get_free_variants_db,
    get_db
)

class TestTopicClaimSystem(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.chat_id = 888100
        self.subject = "Тест-КДМ"
        async with get_db() as db:
            await db.execute("DELETE FROM topic_claims WHERE chat_id = ?", (self.chat_id,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM topic_claims WHERE chat_id = ?", (self.chat_id,))
            await db.commit()

    async def test_claim_and_collision_prevention(self):
        # 1. Студент 1 займає варіант 5
        ok, msg, holder = await claim_topic_db(
            chat_id=self.chat_id,
            subject=self.subject,
            variant_or_topic="5",
            user_id=201,
            user_name="Олексій",
            username="alex"
        )
        self.assertTrue(ok)
        self.assertIn("Успішно", msg)
        self.assertIsNone(holder)

        # 2. Студент 2 намагається зайняти той самий варіант 5
        ok2, msg2, holder2 = await claim_topic_db(
            chat_id=self.chat_id,
            subject=self.subject,
            variant_or_topic="5",
            user_id=202,
            user_name="Богдан",
            username="bogdan"
        )
        self.assertFalse(ok2)
        self.assertIn("вже зайнятий", msg2)
        self.assertEqual(holder2["user_name"], "Олексій")

    async def test_user_replaces_own_variant(self):
        # Студент 1 бере варіант 3
        await claim_topic_db(self.chat_id, self.subject, "3", 201, "Олексій")
        # Потім передумує і бере варіант 7
        ok, msg, _ = await claim_topic_db(self.chat_id, self.subject, "7", 201, "Олексій")
        self.assertTrue(ok)

        # Перевірка: варіант 3 тепер вільний, а 7 зайнятий
        claims = await get_claims_by_subject_db(self.chat_id, self.subject)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["variant_or_topic"], "7")

    async def test_unclaim(self):
        await claim_topic_db(self.chat_id, self.subject, "12", 201, "Олексій")
        unclaimed = await unclaim_topic_db(self.chat_id, self.subject, 201)
        self.assertTrue(unclaimed)

        claims = await get_claims_by_subject_db(self.chat_id, self.subject)
        self.assertEqual(len(claims), 0)

    async def test_free_variants_calculation(self):
        # Займаємо варіанти 1, 2, 4
        await claim_topic_db(self.chat_id, self.subject, "1", 201, "Студент 1")
        await claim_topic_db(self.chat_id, self.subject, "2", 202, "Студент 2")
        await claim_topic_db(self.chat_id, self.subject, "4", 203, "Студент 3")

        # Перевіряємо вільні серед перших 5
        free_vars = await get_free_variants_db(self.chat_id, self.subject, max_variants=5)
        self.assertEqual(free_vars, [3, 5])


if __name__ == "__main__":
    unittest.main()

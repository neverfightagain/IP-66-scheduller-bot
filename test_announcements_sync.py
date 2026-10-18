import unittest
from announcements_sync import detect_schedule_proposal, format_proposal_card, apply_proposal
from database import (
    init_db,
    add_schedule_proposal_db,
    get_pending_proposals_db,
    update_proposal_status_db,
    get_proposal_by_id_db,
    get_cancelled_pairs_for_date_db,
    get_db
)

class TestAnnouncementsSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        async with get_db() as db:
            await db.execute("DELETE FROM schedule_proposals")
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM schedule_proposals")
            await db.commit()

    def test_detect_cancellation_announcement(self):
        ann = "Шановні студенти, другої пари у п'ятницю не буде, викладач на конференції."
        prop = detect_schedule_proposal(ann, course_name="АСД", video_id="vid_123")
        self.assertIsNotNone(prop)
        self.assertEqual(prop["change_type"], "cancellation")
        self.assertEqual(prop["pair_number"], 2)
        self.assertIsNotNone(prop["target_date"])

    def test_detect_reschedule_announcement(self):
        ann = "Лекція переноситься на вівторок третю пару."
        prop = detect_schedule_proposal(ann, course_name="КДМ")
        self.assertIsNotNone(prop)
        self.assertEqual(prop["change_type"], "reschedule")
        self.assertEqual(prop["pair_number"], 3)

    def test_detect_online_switch_announcement(self):
        ann = "Наступне практичне заняття проведемо в Zoom дистанційно."
        prop = detect_schedule_proposal(ann, course_name="Мережі")
        self.assertIsNotNone(prop)
        self.assertEqual(prop["change_type"], "online_switch")

    async def test_proposal_lifecycle_and_approval(self):
        # 1. Створюємо пропозицію
        pid = await add_schedule_proposal_db(
            source_video_id="vid_test",
            course_name="Основи програмування",
            raw_announcement="У п'ятницю пари не буде",
            change_type="cancellation",
            target_date="2026-10-30",
            pair_number=1,
            details="Виявлено Gemini"
        )
        self.assertIsInstance(pid, int)

        # 2. Перевіряємо в списку pending
        pending = await get_pending_proposals_db()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], pid)

        # 3. Перевіряємо форматування картки
        text, kb = format_proposal_card(pending[0])
        self.assertIn("Основи програмування", text)
        self.assertIn("2026-10-30", text)
        self.assertIn(f"prop:approve:{pid}", kb.inline_keyboard[0][0].callback_data)

        # 4. Схвалюємо пропозицію через apply_proposal
        ok, msg = await apply_proposal(pid)
        self.assertTrue(ok)
        self.assertIn("схвалено", msg)

        # 5. Перевіряємо, що вона більше не в pending
        pending_after = await get_pending_proposals_db()
        self.assertEqual(len(pending_after), 0)

        # 6. Перевіряємо, що в cancelled_pairs з'явився запис про скасування пари
        canc = await get_cancelled_pairs_for_date_db("2026-10-30")
        self.assertIn(1, canc)


if __name__ == "__main__":
    unittest.main()

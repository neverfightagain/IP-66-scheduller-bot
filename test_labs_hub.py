import unittest
from labs_hub import format_labs_hub_message, get_material_icon
from database import (
    init_db,
    add_lab_material_db,
    get_lab_materials_by_subject_db,
    delete_lab_material_db,
    get_db
)

class TestLabsHub(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.test_subject = "Тест-Мережі"
        async with get_db() as db:
            await db.execute("DELETE FROM lab_materials WHERE subject = ?", (self.test_subject,))
            await db.commit()

    async def asyncTearDown(self):
        async with get_db() as db:
            await db.execute("DELETE FROM lab_materials WHERE subject = ?", (self.test_subject,))
            await db.commit()

    def test_icon_detection(self):
        self.assertEqual(get_material_icon("https://github.com/org/repo"), "🐙")
        self.assertEqual(get_material_icon("https://drive.google.com/file/d/123"), "📁")
        self.assertEqual(get_material_icon("https://example.com/guide.pdf"), "📄")
        self.assertEqual(get_material_icon("https://example.com/archive.zip"), "📦")
        self.assertEqual(get_material_icon("https://youtube.com/watch?v=123"), "🎬")

    async def test_materials_crud(self):
        mid = await add_lab_material_db(
            subject=self.test_subject,
            lab_title="Методичка до Лаби 1",
            url="https://drive.google.com/test",
            description="Офіційний посібник кафедри"
        )
        self.assertIsInstance(mid, int)

        mats = await get_lab_materials_by_subject_db(self.test_subject)
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0]["lab_title"], "Методичка до Лаби 1")

        # Видалення
        deleted = await delete_lab_material_db(mid)
        self.assertTrue(deleted)

    def test_format_hub_message(self):
        materials = [
            {
                "id": 1,
                "lab_title": "Методичні вказівки до лаби 1",
                "url": "https://example.com/lab1.pdf",
                "material_type": "pdf",
                "description": "Формат звіту"
            }
        ]
        text, kb = format_labs_hub_message("АСД", materials)
        self.assertIn("Хаб методичок та умов: АСД", text)
        self.assertIn("Методичні вказівки до лаби 1", text)
        self.assertEqual(len(kb.inline_keyboard), 1)
        self.assertEqual(kb.inline_keyboard[0][0].url, "https://example.com/lab1.pdf")


if __name__ == "__main__":
    unittest.main()

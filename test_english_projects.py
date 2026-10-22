import unittest
import asyncio
import io
import zipfile
import json
import base64
from pathlib import Path
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

from database import (
    get_db,
    init_db,
    create_project_board_db,
    delete_project_board_db,
    get_project_boards_db,
    create_or_join_project_group_db,
    leave_project_group_db,
    save_project_group_material_db,
    save_project_group_ai_qa_db,
    set_admin_test_mode_db,
    grant_admin_role_db
)
from webapp_server import create_webapp_app, extract_text_from_uploaded_file
from llm_agent import generate_english_presentation_qa


class TestEnglishProjects(AioHTTPTestCase):
    async def get_application(self):
        return create_webapp_app(bot=None)

    async def setUpAsync(self):
        await super().setUpAsync()
        await init_db()
        await set_admin_test_mode_db(True)

    @unittest_run_loop
    async def test_database_board_and_groups_crud(self):
        # 1. Create board with initial topics
        topics = ["Cloud Native Microservices", "AI in Healthcare", "Cybersecurity in IoT"]
        board_id = await create_project_board_db(
            title="English Speaking Project 2026",
            subject="Англійська",
            description="Presentation defense for Module 1",
            max_members=3,
            initial_topics=topics,
            created_by="Admin"
        )
        self.assertGreater(board_id, 0)

        # 2. Verify get_project_boards_db
        boards = await get_project_boards_db("Англійська")
        self.assertTrue(any(b["id"] == board_id for b in boards))
        board = next(b for b in boards if b["id"] == board_id)
        self.assertEqual(board["title"], "English Speaking Project 2026")
        self.assertEqual(board["max_members"], 3)
        self.assertEqual(len(board["groups"]), 3)
        self.assertEqual(board["groups"][0]["topic_title"], "Cloud Native Microservices")

        # 3. User joins existing group #1
        g1_id = board["groups"][0]["id"]
        ok, msg, gid = await create_or_join_project_group_db(
            board_id=board_id,
            user_id=111,
            user_name="Сінчіневіч Максим",
            username="sinch",
            group_id=g1_id
        )
        self.assertTrue(ok)
        self.assertEqual(gid, g1_id)

        # Add teammate #2 to group #1
        ok2, msg2, gid2 = await create_or_join_project_group_db(
            board_id=board_id,
            user_id=222,
            user_name="Петренко Петро",
            username="petro",
            group_id=g1_id
        )
        self.assertTrue(ok2)

        # Add teammate #3 to group #1 (reaches max_members=3)
        ok3, msg3, gid3 = await create_or_join_project_group_db(
            board_id=board_id,
            user_id=333,
            user_name="Іванов Іван",
            username="ivan",
            group_id=g1_id
        )
        self.assertTrue(ok3)

        # Teammate #4 tries to join group #1 -> Rejected!
        ok4, msg4, gid4 = await create_or_join_project_group_db(
            board_id=board_id,
            user_id=444,
            user_name="Сидоренко Василь",
            username="vasyl",
            group_id=g1_id
        )
        self.assertFalse(ok4)
        self.assertIn("заповнена", msg4.lower())

        # 4. User 111 creates a NEW group with topic and teammate
        ok_new, msg_new, new_gid = await create_or_join_project_group_db(
            board_id=board_id,
            user_id=111,
            user_name="Сінчіневіч Максим",
            username="sinch",
            topic_title="Quantum Computing Algorithms",
            teammates=[{"user_id": 555, "user_name": "Коваленко Денис", "username": "denys"}]
        )
        self.assertTrue(ok_new)
        self.assertNotEqual(new_gid, g1_id)

        # Verify User 111 was removed from old group #1 and now in new group
        boards_after = await get_project_boards_db("Англійська")
        b_after = next(b for b in boards_after if b["id"] == board_id)
        g1_after = next(g for g in b_after["groups"] if g["id"] == g1_id)
        self.assertFalse(any(m["user_id"] == 111 for m in g1_after["members"]))
        self.assertEqual(len(g1_after["members"]), 2)  # 222 and 333 remain

        new_g = next(g for g in b_after["groups"] if g["id"] == new_gid)
        self.assertEqual(len(new_g["members"]), 2)  # 111 (leader) and 555 (member)
        self.assertTrue(any(m["role"] == "leader" and m["user_id"] == 111 for m in new_g["members"]))

        # 5. Save presentation material and AI Q&A
        qa_data = [
            {"question": "What is superposition?", "answer": "Superposition is...", "tip": "Mention slide 3."}
        ]
        ok_mat = await save_project_group_material_db(new_gid, "Slide text on Quantum gates", "quantum.pptx")
        self.assertTrue(ok_mat)
        ok_qa = await save_project_group_ai_qa_db(new_gid, qa_data)
        self.assertTrue(ok_qa)

        # Verify Q&A saved and parsed
        b_final = next(b for b in await get_project_boards_db("Англійська") if b["id"] == board_id)
        g_final = next(g for g in b_final["groups"] if g["id"] == new_gid)
        self.assertEqual(g_final["file_name"], "quantum.pptx")
        self.assertEqual(len(g_final["ai_qa"]), 1)
        self.assertEqual(g_final["ai_qa"][0]["question"], "What is superposition?")

        # 6. Leave group
        ok_leave = await leave_project_group_db(new_gid, user_id=111)
        self.assertTrue(ok_leave)

        # 7. Delete board
        ok_del = await delete_project_board_db(board_id)
        self.assertTrue(ok_del)
        boards_empty = await get_project_boards_db("Англійська")
        self.assertFalse(any(b["id"] == board_id for b in boards_empty))

    @unittest_run_loop
    async def test_file_extractor(self):
        # Plain text
        txt = extract_text_from_uploaded_file("notes.txt", b"My speech text")
        self.assertEqual(txt, "My speech text")

        # Docx
        buf_docx = io.BytesIO()
        with zipfile.ZipFile(buf_docx, "w") as z:
            z.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>Extracted Docx Text</w:t></w:r></w:p></w:body></w:document>")
        self.assertEqual(extract_text_from_uploaded_file("doc.docx", buf_docx.getvalue()), "Extracted Docx Text")

        # PPTX
        buf_pptx = io.BytesIO()
        with zipfile.ZipFile(buf_pptx, "w") as z:
            z.writestr("ppt/slides/slide1.xml", "<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Introduction to Cloud</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
        pptx_res = extract_text_from_uploaded_file("presentation.pptx", buf_pptx.getvalue())
        self.assertIn("Slide 1: Introduction to Cloud", pptx_res)

    @unittest_run_loop
    async def test_llm_qa_generator(self):
        qa_pairs = await generate_english_presentation_qa("Cybersecurity in Fintech", "We analyze cryptographic hashing algorithms.")
        self.assertIsInstance(qa_pairs, list)
        self.assertGreaterEqual(len(qa_pairs), 5)
        for pair in qa_pairs:
            self.assertIn("question", pair)
            self.assertIn("answer", pair)
            self.assertIn("tip", pair)

    @unittest_run_loop
    async def test_api_test_mode_isolation(self):
        await set_admin_test_mode_db(True)
        # Create a test board
        bid = await create_project_board_db("Board 1", "Англійська")

        # 1. Non-admin student requests boards -> restricted_by_test_mode == True, boards == []
        resp_student = await self.client.get("/api/projects/boards?subject=Англійська&user_id=777000&username=random_student")
        self.assertEqual(resp_student.status, 200)
        data_st = await resp_student.json()
        self.assertTrue(data_st["success"])
        self.assertTrue(data_st["restricted_by_test_mode"])
        self.assertEqual(len(data_st["boards"]), 0)

        # 2. Owner (8735281894 / sinch) requests boards -> restricted_by_test_mode == False, sees boards!
        resp_owner = await self.client.get("/api/projects/boards?subject=Англійська&user_id=8735281894&username=sinch")
        self.assertEqual(resp_owner.status, 200)
        data_ow = await resp_owner.json()
        self.assertTrue(data_ow["success"])
        self.assertFalse(data_ow["restricted_by_test_mode"])
        self.assertTrue(any(b["id"] == bid for b in data_ow["boards"]))

        # Cleanup
        await delete_project_board_db(bid)

    @unittest_run_loop
    async def test_api_upload_and_generate(self):
        bid = await create_project_board_db("AI Presentations", "Англійська")
        ok, msg, gid = await create_or_join_project_group_db(bid, 8735281894, "Максим", "sinch", "Deep Learning")

        sample_txt = "Deep Learning architectures use convolutional layers."
        b64_file = base64.b64encode(sample_txt.encode("utf-8")).decode("utf-8")

        resp = await self.client.post("/api/projects/groups/upload_and_generate", json={
            "group_id": gid,
            "topic_title": "Deep Learning",
            "content_text": "Overview of neural networks",
            "file_name": "ai.txt",
            "file_base64": b64_file
        })
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["qa_list"]), 5)
        self.assertIn("Deep Learning architectures", data["content_text"])

        # Cleanup
        await delete_project_board_db(bid)


if __name__ == "__main__":
    unittest.main()

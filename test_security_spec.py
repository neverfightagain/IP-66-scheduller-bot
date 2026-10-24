"""
test_security_spec.py — Повний набір тестів специфікації безпеки (Пункти A та B).
Перевіряє відповідність проекту вимогам безпеки:
- Блок A: Авторизація Telegram-команд та валідація whitelist-доменів лінків.
- Блок B: Автентифікація X-Telegram-Init-Data, перевірка HMAC-SHA256, auth_date, захист від IDOR та контроль ролей у REST API.
"""

import hashlib
import hmac
import json
import time
import urllib.parse
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp.test_utils import TestClient, TestServer
from aiogram.types import Chat, Message, User

import config
import database
import webapp_server
from webapp_server import create_webapp_app


# =====================================================================
# ДОПОМІЖНІ УТИЛІТИ: Генерація X-Telegram-Init-Data за стандартом Telegram
# =====================================================================

def make_telegram_init_data(
    user_id: int,
    username: str = "testuser",
    first_name: str = "Test",
    bot_token: str = "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ123456789",
    auth_date: int = None,
    tamper_hash: bool = False,
    extra_fields: dict = None
) -> str:
    """Генерація валідного або тестового рядка X-Telegram-Init-Data."""
    if auth_date is None:
        auth_date = int(time.time())

    user_dict = {
        "id": user_id,
        "first_name": first_name,
        "last_name": "User",
        "username": username,
        "language_code": "uk"
    }

    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF60gAAAAAN0XrSD12345",
        "user": json.dumps(user_dict, separators=(",", ":"))
    }
    if extra_fields:
        params.update({k: str(v) for k, v in extra_fields.items()})

    # Створення data_check_string за правилами Telegram (сортування ключів)
    check_items = [f"{k}={v}" for k, v in sorted(params.items())]
    data_check_string = "\n".join(check_items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    correct_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    final_hash = "0000000000000000000000000000000000000000000000000000000000000000" if tamper_hash else correct_hash
    params["hash"] = final_hash

    return urllib.parse.urlencode(params)


def create_mock_message(text: str, user_id: int, username: str = "student", chat_id: int = -100123456789) -> Message:
    """Створення mock-повідомлення aiogram для виклику хендлерів."""
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.message_id = 999
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = chat_id
    msg.chat.type = "supergroup"
    msg.from_user = MagicMock(spec=User)
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.from_user.first_name = "Студент"
    msg.answer = AsyncMock()
    return msg


async def invoke_handler(handler, msg):
    """Безпечний виклик хендлера команди як з аргументом bot, так і без нього."""
    try:
        return await handler(msg, MagicMock())
    except TypeError:
        return await handler(msg)


# =====================================================================
# БЛОК A: Тести специфікації для команд Telegram-бота
# =====================================================================

class TestTelegramBotCommandsSecuritySpec(unittest.IsolatedAsyncioTestCase):
    """
    Вимоги специфікації A:
    1. Не-адмін отримує відмову на виклик адмін-команд (/setlink, /dellink, /adddeadline, /deldeadline,
       /sync, /youtube, /subscribe, /unsubscribe, /test_alert, /status), дані не змінюються.
    2. /setlink дозволяє виключно https:// та whitelist-домени (zoom.us, meet.google.com, teams.microsoft.com).
    3. Не-адмін не може видалити завдання Classroom (/deldeadline gc_...).
    """

    OWNER_UID = config.OWNER_ID
    STUDENT_UID = 111222333  # Звичайний студент, не адмін

    def setUp(self):
        # Ізоляція перевірки адмін-прав у пам'яті: тільки OWNER_UID вважається адміном
        async def mock_check_admin(user_id=None, username=None):
            is_adm = (user_id == self.OWNER_UID)
            return {
                "is_admin": is_adm,
                "is_owner": is_adm,
                "role": "owner" if is_adm else None,
                "test_mode": False
            }
        self.patcher_admin = patch("database.check_admin_access_db", side_effect=mock_check_admin)
        self.patcher_admin.start()

    def tearDown(self):
        self.patcher_admin.stop()

    async def test_non_admin_commands_rejected(self):
        """Не-адмін викликає адмін-команди -> повинен отримати відмову з поясненням про відсутність прав."""
        from handlers import (
            cmd_set_link, cmd_del_link, cmd_add_deadline, cmd_del_deadline,
            cmd_sync, cmd_youtube, cmd_subscribe, cmd_unsubscribe, cmd_test_alert, cmd_status
        )

        test_commands = [
            ("/setlink Математика | https://zoom.us/j/123", cmd_set_link),
            ("/dellink Математика", cmd_del_link),
            ("/adddeadline ОП | Лаба 1 | 2026-12-31 23:59 | Опис", cmd_add_deadline),
            ("/deldeadline manual_12345", cmd_del_deadline),
            ("/sync", cmd_sync),
            ("/youtube", cmd_youtube),
            ("/subscribe", cmd_subscribe),
            ("/unsubscribe", cmd_unsubscribe),
            ("/test_alert", cmd_test_alert),
            ("/status", cmd_status),
        ]

        for cmd_text, handler in test_commands:
            base_cmd = cmd_text.split()[0]
            msg = create_mock_message(cmd_text, user_id=self.STUDENT_UID, username="regular_student")

            with patch("handlers.safe_answer", new_callable=AsyncMock) as mock_answer:
                await invoke_handler(handler, msg)
                mock_answer.assert_called_once()
                response_text = str(mock_answer.call_args).lower()
                has_access_denied = any(w in response_text for w in [
                    "немає прав", "доступ заборонено", "тільки для старости", "недостатньо прав", "відмовлено"
                ])
                self.assertTrue(
                    has_access_denied,
                    f"СПЕЦИФІКАЦІЯ ПОРУШЕНА: Команда {base_cmd} виконалася без перевірки прав для не-адміна!"
                )

    async def test_setlink_domain_whitelist_rejects_insecure_or_phishing_urls(self):
        """Адмін викликає /setlink з http:// або лівим доменом -> отримує відмову (дозволені тільки zoom/meet/teams)."""
        from handlers import cmd_set_link

        invalid_urls = [
            "http://zoom.us/j/123456",                   # Незахищений протокол HTTP
            "https://evil.com/phish",                    # Фішинговий домен
            "https://zoom.us.attacker.com/session",      # Спроба обходу за префіксом домену
            "https://not-whitelisted-domain.org/meeting" # Довільний сторонній домен
        ]

        for bad_url in invalid_urls:
            cmd_text = f"/setlink Філософія (Лек) | {bad_url} | Zoom"
            msg = create_mock_message(cmd_text, user_id=self.OWNER_UID, username="sinch")

            with patch("handlers.safe_answer", new_callable=AsyncMock) as mock_answer, \
                 patch("links_manager.set_course_link") as mock_set:
                await invoke_handler(cmd_set_link, msg)
                mock_set.assert_not_called()
                mock_answer.assert_called_once()
                response_text = str(mock_answer.call_args).lower()
                has_domain_warning = any(w in response_text for w in [
                    "дозволені лише", "некоректний домен", "небезпечне посилання", "whitelist", "тільки https"
                ])
                self.assertTrue(
                    has_domain_warning,
                    f"СПЕЦИФІКАЦІЯ ПОРУШЕНА: /setlink прийняв небезпечний або не-whitelist URL: {bad_url}"
                )

    async def test_setlink_whitelisted_domain_success(self):
        """Адмін викликає /setlink з валідним посиланням https://zoom.us/j/123 -> успішно зберігається."""
        from handlers import cmd_set_link

        valid_url = "https://zoom.us/j/123"
        cmd_text = f"/setlink Філософія (Лек) | {valid_url} | Zoom"
        msg = create_mock_message(cmd_text, user_id=self.OWNER_UID, username="sinch")

        with patch("handlers.safe_answer", new_callable=AsyncMock) as mock_answer, \
             patch("links_manager.set_course_link") as mock_set:
            await invoke_handler(cmd_set_link, msg)
            mock_set.assert_called_once_with("Філософія (Лек)", valid_url, "Zoom")
            mock_answer.assert_called_once()
            response_text = str(mock_answer.call_args).lower()
            self.assertTrue("успішно" in response_text)

    async def test_non_admin_cannot_delete_classroom_deadline(self):
        """Не-адмін намагається видалити дедлайн Classroom (gc_...) -> отримує відмову."""
        from handlers import cmd_del_deadline

        msg = create_mock_message("/deldeadline gc_12345", user_id=self.STUDENT_UID, username="regular_student")

        with patch("handlers.safe_answer", new_callable=AsyncMock) as mock_answer, \
             patch("database.delete_assignment_db", new_callable=AsyncMock) as mock_del:
            await invoke_handler(cmd_del_deadline, msg)
            mock_del.assert_not_called()
            mock_answer.assert_called_once()
            response_text = str(mock_answer.call_args).lower()
            self.assertTrue(
                any(w in response_text for w in ["немає прав", "доступ заборонено", "тільки для старости"]),
                "СПЕЦИФІКАЦІЯ ПОРУШЕНА: Не-адмін зміг ініціювати видалення завдання Classroom!"
            )


# =====================================================================
# БЛОК B: Тести специфікації для REST API черги Telegram Mini App
# =====================================================================

class TestWebAppQueueSecuritySpec(unittest.IsolatedAsyncioTestCase):
    """
    Вимоги специфікації B:
    1. Запит без X-Telegram-Init-Data до /api/queue/join, /leave, /next -> 401 Unauthorized.
    2. Запит з підробленою підписом -> 401 Unauthorized.
    3. Запит із простроченим auth_date (> 1 год) -> 401 Unauthorized.
    4. Захист від IDOR: сервер ігнорує чужий user_id з тіла запиту і використовує user_id з initData (або повертає 403).
    5. Звичайний студент викликає /api/queue/next -> 403 Forbidden.
    """

    BOT_TOKEN = "1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ123456789"
    OWNER_ID = config.OWNER_ID
    STUDENT_ID = 555000111
    VICTIM_ID = 999888777

    async def asyncSetUp(self):
        # Патчимо BOT_TOKEN і в config, і в webapp_server (якщо він там є або з'явиться)
        self.patch_cfg = patch.object(config, "BOT_TOKEN", self.BOT_TOKEN)
        self.patch_cfg.start()
        if hasattr(webapp_server, "BOT_TOKEN"):
            self.patch_srv = patch.object(webapp_server, "BOT_TOKEN", self.BOT_TOKEN)
            self.patch_srv.start()
        else:
            self.patch_srv = None

        app = create_webapp_app(bot=None)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.patch_cfg.stop()
        if self.patch_srv:
            self.patch_srv.stop()

    async def test_queue_endpoints_require_init_data_header(self):
        """Запит без X-Telegram-Init-Data до /api/queue/join, leave, next -> 401 Unauthorized."""
        endpoints = [
            ("/api/queue/join", {"chat_id": 1, "subject": "ОП", "user_id": self.STUDENT_ID, "lab_number": "Лаба 1"}),
            ("/api/queue/leave", {"chat_id": 1, "subject": "ОП", "user_id": self.STUDENT_ID}),
            ("/api/queue/next", {"chat_id": 1, "subject": "ОП"}),
        ]
        for url, payload in endpoints:
            resp = await self.client.post(url, json=payload)
            self.assertEqual(
                resp.status, 401,
                f"СПЕЦИФІКАЦІЯ ПОРУШЕНА: {url} повернув {resp.status} замість 401 Unauthorized при відсутності X-Telegram-Init-Data!"
            )

    async def test_queue_endpoints_reject_tampered_signature(self):
        """Запит з підробленою підписом initData -> 401 Unauthorized."""
        tampered_init = make_telegram_init_data(
            user_id=self.STUDENT_ID,
            bot_token=self.BOT_TOKEN,
            tamper_hash=True
        )
        headers = {"X-Telegram-Init-Data": tampered_init}
        resp = await self.client.post("/api/queue/join", json={
            "chat_id": 1, "subject": "ОП", "user_id": self.STUDENT_ID, "lab_number": "Лаба 1"
        }, headers=headers)

        self.assertEqual(
            resp.status, 401,
            f"СПЕЦИФІКАЦІЯ ПОРУШЕНА: Сервер прийняв підроблений підпис Telegram initData (статус {resp.status})!"
        )

    async def test_queue_endpoints_reject_expired_auth_date(self):
        """Запит із простроченим auth_date (> 1 год) -> 401 Unauthorized."""
        two_hours_ago = int(time.time()) - 7200
        expired_init = make_telegram_init_data(
            user_id=self.STUDENT_ID,
            bot_token=self.BOT_TOKEN,
            auth_date=two_hours_ago
        )
        headers = {"X-Telegram-Init-Data": expired_init}
        resp = await self.client.post("/api/queue/join", json={
            "chat_id": 1, "subject": "ОП", "user_id": self.STUDENT_ID, "lab_number": "Лаба 1"
        }, headers=headers)

        self.assertEqual(
            resp.status, 401,
            f"СПЕЦИФІКАЦІЯ ПОРУШЕНА: Сервер прийняв прострочену сесію auth_date > 1h (статус {resp.status})!"
        )

    async def test_queue_idor_prevention(self):
        """
        Захист від IDOR: Користувач з валідною initData (user_id=555000111) передає чужий user_id=999888777 в тілі.
        Сервер повинен або повернути 403 Forbidden, або ігнорувати чужий ID і діяти тільки від імені 555000111.
        """
        valid_init = make_telegram_init_data(user_id=self.STUDENT_ID, bot_token=self.BOT_TOKEN)
        headers = {"X-Telegram-Init-Data": valid_init}

        with patch("webapp_server.leave_queue_db", new_callable=AsyncMock) as mock_leave:
            mock_leave.return_value = True
            resp = await self.client.post("/api/queue/leave", json={
                "chat_id": 1,
                "subject": "ОП",
                "user_id": self.VICTIM_ID  # Спроба вилучити жертву!
            }, headers=headers)

            if resp.status == 200:
                # Якщо статус 200, перевіряємо, щоб у базу передався ID з initData (555000111), а не жертви
                self.assertTrue(mock_leave.called, "leave_queue_db не було викликано")
                called_user_id = mock_leave.call_args[0][2] if len(mock_leave.call_args[0]) > 2 else mock_leave.call_args.kwargs.get("user_id")
                self.assertEqual(
                    called_user_id, self.STUDENT_ID,
                    f"СПЕЦИФІКАЦІЯ ПОРУШЕНА (IDOR!): Сервер видалив жертву {self.VICTIM_ID} замість користувача з initData {self.STUDENT_ID}!"
                )
            else:
                self.assertIn(resp.status, (400, 401, 403))

    async def test_queue_next_forbidden_for_regular_student(self):
        """Обычный студент (не админ) викликає /api/queue/next -> 403 Forbidden."""
        student_init = make_telegram_init_data(user_id=self.STUDENT_ID, bot_token=self.BOT_TOKEN)
        headers = {"X-Telegram-Init-Data": student_init}

        resp = await self.client.post("/api/queue/next", json={
            "chat_id": 1,
            "subject": "ОП"
        }, headers=headers)

        self.assertEqual(
            resp.status, 403,
            f"СПЕЦИФІКАЦІЯ ПОРУШЕНА: Звичайний студент зміг викликати /api/queue/next (статус {resp.status} замість 403 Forbidden)!"
        )


if __name__ == "__main__":
    unittest.main()

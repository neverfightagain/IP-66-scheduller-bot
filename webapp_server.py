import os
import json
import hmac
import hashlib
import time
import urllib.parse
import asyncio
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from config import (
    BASE_DIR,
    BOT_TOKEN,
    KYIV_TZ,
    KPI_GROUP_ID,
    TURSO_DATABASE_URL,
    SQLITE_CLOUD_URL,
    WEBAPP_URL,
    OWNER_ID,
)
from handlers import make_webapp_button
from scheduler import safe_send_message, refresh_today_cache
import base64
import zipfile
import io
import re
import xml.etree.ElementTree as ET

from database import (
    create_project_board_db,
    delete_project_board_db,
    get_project_boards_db,
    create_or_join_project_group_db,
    leave_project_group_db,
    save_project_group_material_db,
    save_project_group_ai_qa_db,
    get_subscribed_chats_db,
    get_active_queue_db,
    get_all_queues_cached_db,
    join_queue_db,
    leave_queue_db,
    next_in_queue_db,
    clear_queue_db,
    get_queue_message_id_db,
    get_active_assignments_db,
    get_all_students_db,
    find_student_real_name_db,
    format_queue_name,
    extract_first_name,
    get_cancelled_pairs_for_date_db,
    cancel_pair_db,
    uncancel_pair_db,
    get_custom_lessons_for_date_db,
    add_custom_lesson_db,
    delete_custom_lesson_db,
    check_admin_access_db,
    get_admin_roles_db,
    grant_admin_role_db,
    revoke_admin_role_db,
    set_admin_test_mode_db,
    get_admin_test_mode_db,
    TIME_TO_PAIR_NUMBER,
    PAIR_TIMES,
)
from kpi_api import get_lessons_for_date
from links_manager import load_links

logger = logging.getLogger("WebAppServer")

WEBAPP_DIR = BASE_DIR / "webapp"


def cors_headers() -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "X-Telegram-Init-Data, Content-Type, Authorization",
    }


def json_response_cors(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers=cors_headers())


def verify_telegram_init_data(init_data_raw: str, max_age_sec: int = 86400) -> dict | None:
    """Перевіряє криптографічний підпис Telegram WebApp initData (HMAC-SHA256)."""
    if not init_data_raw or not BOT_TOKEN:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data_raw, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        auth_date = int(parsed.get("auth_date", "0") or "0")
        if max_age_sec > 0 and abs(time.time() - auth_date) > max_age_sec:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None
        user_raw = parsed.get("user")
        return json.loads(user_raw) if user_raw else None
    except Exception:
        return None


def get_verified_webapp_user(request: web.Request, body_data: dict | None = None) -> dict | None:
    """Витягує та верифікує користувача з заголовка X-Telegram-Init-Data або поля initData."""
    raw_init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or (body_data.get("initData") if isinstance(body_data, dict) else None)
        or request.query.get("initData")
        or ""
    ).strip()
    return verify_telegram_init_data(raw_init_data)


_ws_clients: set[web.WebSocketResponse] = set()


async def broadcast_queue_ws(event_meta: dict | None = None) -> None:
    """Миттєво розіслати оновлений стан обох черг (ОП та АСД) усім підключеним WebSocket-клієнтам."""
    if not _ws_clients:
        return
    try:
        queues, version = await get_all_queues_cached_db()
        payload = {
            "type": "queue_update",
            "version": version,
            "queues": queues,
        }
        if event_meta:
            payload.update(event_meta)
        msg_str = json.dumps(payload, ensure_ascii=False)
        stale: list[web.WebSocketResponse] = []

        async def _send_one(ws: web.WebSocketResponse):
            if ws.closed:
                stale.append(ws)
                return
            try:
                await ws.send_str(msg_str)
            except Exception:
                stale.append(ws)

        await asyncio.gather(*(_send_one(ws) for ws in list(_ws_clients)), return_exceptions=True)
        for ws in stale:
            _ws_clients.discard(ws)
    except Exception as e:
        logger.debug(f"WebSocket broadcast error: {e}")


def schedule_bg_chat_sync(bot: Bot | None, chat_id: int, subject: str = None) -> None:
    """Неблокуюча фонова синхронізація повідомлення черги в чаті Telegram (0 мс очікування для клієнта)."""
    if not bot or not chat_id:
        return
    try:
        asyncio.create_task(sync_queue_message_in_chat(bot, chat_id, subject))
    except Exception:
        pass


async def sync_queue_message_in_chat(bot: Bot | None, chat_id: int, subject: str = None) -> bool:
    """Оновити повідомлення черги в груповому чаті Telegram у реальному часі."""
    if not bot or not chat_id:
        return False
    try:
        from handlers import format_queue_view
        record = await get_queue_message_id_db(chat_id)
        if not record:
            return False
        msg_id = record["message_id"]
        saved_subj = record.get("subject") or "ОП"
        target_subj = subject or saved_subj

        items = await get_active_queue_db(chat_id, target_subj)
        text, kb = format_queue_view(target_subj, items, chat_id=chat_id)
        await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, parse_mode="HTML", reply_markup=kb)
        return True
    except Exception as e:
        logger.debug(f"Не вдалося оновити повідомлення черги в чаті {chat_id}: {e}")
        return False


async def broadcast_schedule_change_notification(bot: Bot | None, text: str):
    """
    Розсилає сповіщення про зміну в розкладі з урахуванням режиму тестування (test_mode).
    - Якщо test_mode == True: надсилає тільки Власнику в ЛС (OWNER_ID) з поміткою про тест.
    - Якщо test_mode == False: розсилає у всі підписані чати/топіки.
    """
    if bot is None:
        return

    try:
        test_mode = await get_admin_test_mode_db()
        app_url = f"{WEBAPP_URL}/app"

        if test_mode:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                make_webapp_button("📱 Відкрити IP-66 Hub", app_url, chat_id=OWNER_ID)
            ]])
            test_text = f"🧪 <i>[Тест-режим: сповіщення бачите тільки ви]</i>\n\n{text}"
            await safe_send_message(bot, OWNER_ID, test_text, reply_markup=kb)
            logger.info("Надіслано сповіщення про зміну розкладу у тест-режимі (тільки власнику).")
        else:
            targets = await get_subscribed_chats_db()
            for target in targets:
                cid = target["chat_id"]
                tid = target.get("thread_id")
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    make_webapp_button("📱 Відкрити IP-66 Hub", app_url, chat_id=cid)
                ]])
                await safe_send_message(bot, cid, text, reply_markup=kb, message_thread_id=tid)
            logger.info(f"Розіслано сповіщення про зміну розкладу у {len(targets)} чатів.")
    except Exception as e:
        logger.error(f"Помилка при розсилці сповіщення про зміну розкладу: {e}")


def extract_text_from_uploaded_file(filename: str, file_bytes: bytes) -> str:
    """
    Витягує текст із завантаженого файлу (.pptx, .docx, .txt, .md, .csv)
    виключно за допомогою стандартної бібліотеки Python.
    """
    fn_lower = filename.lower()
    if fn_lower.endswith(".pptx"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                slide_files = [f for f in z.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", f)]
                def slide_num(f_name):
                    m = re.search(r"slide(\d+)\.xml", f_name)
                    return int(m.group(1)) if m else 999
                slide_files.sort(key=slide_num)

                slides_text = []
                for s_file in slide_files:
                    s_xml = z.read(s_file)
                    root = ET.fromstring(s_xml)
                    texts = []
                    for elem in root.iter():
                        if elem.tag.endswith("}t") or elem.tag == "t":
                            if elem.text:
                                texts.append(elem.text.strip())
                    s_num = slide_num(s_file)
                    slide_content = " ".join(t for t in texts if t)
                    if slide_content:
                        slides_text.append(f"Slide {s_num}: {slide_content}")

                return "\n\n".join(slides_text)
        except Exception as e:
            logger.warning(f"Помилка парсингу .pptx файлу {filename}: {e}")
            return ""

    elif fn_lower.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                doc_xml = z.read("word/document.xml")
                root = ET.fromstring(doc_xml)
                texts = []
                for elem in root.iter():
                    if elem.tag.endswith("}t") or elem.tag == "t":
                        if elem.text:
                            texts.append(elem.text)
                return " ".join(texts).strip()
        except Exception as e:
            logger.warning(f"Помилка парсингу .docx файлу {filename}: {e}")
            return ""

    else:
        for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
            try:
                return file_bytes.decode(enc).strip()
            except UnicodeDecodeError:
                continue
        return file_bytes.decode("utf-8", errors="ignore").strip()


def is_security_lockdown() -> bool:
    return os.getenv("SECURITY_LOCKDOWN", "1").strip().lower() not in ("0", "false", "no")


@web.middleware
async def security_lockdown_middleware(request: web.Request, handler):
    if request.method != "OPTIONS" and is_security_lockdown():
        p = request.path
        if (
            p == "/status"
            or p == "/api/students"
            or p.startswith("/api/students/")
            or p.startswith("/api/admin/")
            or p.startswith("/api/projects/")
        ):
            return json_response_cors(
                {"success": False, "error": "Ендпоінт тимчасово заблоковано на період безпекового аудиту"},
                status=503,
            )
    return await handler(request)


def create_webapp_app(bot: Bot | None = None) -> web.Application:
    """Створює веб-додаток aiohttp для Telegram Mini App, REST API та health-check."""
    app = web.Application(middlewares=[security_lockdown_middleware])

    # OPTIONS preflight handler for CORS
    async def handle_options(request):
        return web.Response(status=200, headers=cors_headers())

    # --- Health & Status ---
    async def handle_ping(request):
        return web.Response(text="KPI Schedule Bot is OK")

    async def handle_status(request):
        from scheduler import _today_cached_lessons, _today_cached_week, _today_cached_day_name
        try:
            targets = await get_subscribed_chats_db()
            return json_response_cors({
                "status": "online",
                "time_kyiv": datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "database_target": "turso" if TURSO_DATABASE_URL else ("sqlitecloud" if SQLITE_CLOUD_URL else "local_sqlite"),
                "subscribed_chats": targets,
                "subscribed_count": len(targets),
                "cached_lessons_count": len(_today_cached_lessons),
                "week": _today_cached_week,
                "day": _today_cached_day_name,
                "webapp_url": WEBAPP_URL,
            })
        except Exception as e:
            return json_response_cors({"status": "error", "error": str(e)}, status=500)

    # --- WebApp HTML Index ---
    async def handle_app_index(request):
        index_file = WEBAPP_DIR / "index.html"
        if not index_file.exists():
            return web.Response(text="Telegram Mini App is compiling...", content_type="text/html")
        return web.FileResponse(index_file)

    # --- WebSocket Real-Time Queue Channel (/ws) ---
    async def handle_websocket(request):
        ws = web.WebSocketResponse(heartbeat=25.0)
        await ws.prepare(request)
        ws_user: dict | None = None

        async def _enforce_auth_timeout():
            await asyncio.sleep(5.0)
            if ws_user is None and not ws.closed:
                try:
                    await ws.send_str(json.dumps({
                        "type": "auth_error",
                        "error": "Authentication timeout (5s)"
                    }, ensure_ascii=False))
                except Exception:
                    pass
                await ws.close()

        auth_timeout_task = asyncio.create_task(_enforce_auth_timeout())
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue

                    action = data.get("action")
                    req_id = data.get("req_id")

                    if action == "ping":
                        await ws.send_str(json.dumps({"type": "pong", "req_id": req_id}))
                        continue

                    if action == "auth":
                        raw_init = str(data.get("initData", "")).strip()
                        verified = verify_telegram_init_data(raw_init)
                        if not verified or not verified.get("id"):
                            await ws.send_str(json.dumps({
                                "type": "auth_error",
                                "req_id": req_id,
                                "success": False,
                                "error": "Недійсний підпис Telegram initData"
                            }, ensure_ascii=False))
                            await ws.close()
                            break

                        ws_user = verified
                        auth_timeout_task.cancel()
                        _ws_clients.add(ws)
                        queues, version = await get_all_queues_cached_db()
                        await ws.send_str(json.dumps({
                            "type": "queue_update",
                            "req_id": req_id,
                            "authenticated": True,
                            "version": version,
                            "queues": queues,
                        }, ensure_ascii=False))
                        continue

                    # До отримання валідного фрейму auth жодні дії не виконуються
                    if ws_user is None:
                        await ws.send_str(json.dumps({
                            "type": "action_result",
                            "req_id": req_id,
                            "action": action,
                            "success": False,
                            "error": "Unauthorized: send {'action': 'auth', 'initData': '...'} first"
                        }, ensure_ascii=False))
                        continue

                    if action == "get_queues":
                        q_snap, v_snap = await get_all_queues_cached_db()
                        await ws.send_str(json.dumps({
                            "type": "action_result",
                            "req_id": req_id,
                            "action": action,
                            "success": True,
                            "version": v_snap,
                            "queues": q_snap,
                        }, ensure_ascii=False))
                        continue

                    if action == "queue_join":
                        chat_id = int(data.get("chat_id", 0) or 0)
                        subject = str(data.get("subject", "ОП")).strip()
                        user_id = int(ws_user["id"])
                        username = str(ws_user.get("username") or "").strip() or None
                        tg_full_name = " ".join(
                            p for p in (ws_user.get("first_name"), ws_user.get("last_name")) if p
                        ).strip()
                        real_name = await find_student_real_name_db(user_id=user_id, telegram_username=username)
                        user_name = real_name or tg_full_name or str(data.get("user_name", "Студент")).strip() or "Студент"
                        lab_number = str(data.get("lab_number", "")).strip()
                        append = bool(data.get("append", False))

                        ok, res_msg, pos = await join_queue_db(
                            chat_id, subject, user_id, user_name, username, lab_number, append=append
                        )
                        schedule_bg_chat_sync(bot, chat_id, subject)
                        q_snap, v_snap = await get_all_queues_cached_db()
                        await ws.send_str(json.dumps({
                            "type": "action_result",
                            "req_id": req_id,
                            "action": action,
                            "success": ok,
                            "message": res_msg,
                            "position": pos,
                            "subject": subject,
                            "lab_number": lab_number,
                            "version": v_snap,
                            "queues": q_snap,
                        }, ensure_ascii=False))
                        await broadcast_queue_ws({"trigger": "join", "subject": subject})

                    elif action == "queue_leave":
                        chat_id = int(data.get("chat_id", 0) or 0)
                        subject = str(data.get("subject", "ОП")).strip()
                        user_id = int(ws_user["id"])
                        username = str(ws_user.get("username") or "").strip() or None

                        ok = await leave_queue_db(chat_id, subject, user_id, username=username)
                        schedule_bg_chat_sync(bot, chat_id, subject)
                        q_snap, v_snap = await get_all_queues_cached_db()
                        await ws.send_str(json.dumps({
                            "type": "action_result",
                            "req_id": req_id,
                            "action": action,
                            "success": ok,
                            "message": f"Ви вийшли з черги {subject}." if ok else "Вас не було в черзі.",
                            "version": v_snap,
                            "queues": q_snap,
                        }, ensure_ascii=False))
                        await broadcast_queue_ws({"trigger": "leave", "subject": subject})

                    elif action == "queue_next":
                        user_id = int(ws_user["id"])
                        access = await check_admin_access_db(user_id=user_id)
                        if not access.get("is_admin"):
                            await ws.send_str(json.dumps({
                                "type": "action_result",
                                "req_id": req_id,
                                "action": action,
                                "success": False,
                                "error": "Тільки староста або адміністратор може викликати наступного"
                            }, ensure_ascii=False))
                            continue
                        chat_id = int(data.get("chat_id", 0) or 0)
                        subject = str(data.get("subject", "ОП")).strip()
                        student = await next_in_queue_db(chat_id, subject)
                        schedule_bg_chat_sync(bot, chat_id, subject)
                        q_snap, v_snap = await get_all_queues_cached_db()
                        await ws.send_str(json.dumps({
                            "type": "action_result",
                            "req_id": req_id,
                            "action": action,
                            "success": True,
                            "student": student,
                            "has_next": student is not None,
                            "version": v_snap,
                            "queues": q_snap,
                        }, ensure_ascii=False))
                        await broadcast_queue_ws({"trigger": "next", "subject": subject, "called_student": student})

                    elif action == "queue_clear":
                        user_id = int(ws_user["id"])
                        access = await check_admin_access_db(user_id=user_id)
                        if not access.get("is_admin"):
                            await ws.send_str(json.dumps({
                                "type": "action_result",
                                "req_id": req_id,
                                "action": action,
                                "success": False,
                                "error": "Немає прав доступу"
                            }, ensure_ascii=False))
                            continue
                        chat_id = int(data.get("chat_id", 0) or 0)
                        subject = str(data.get("subject", "ОП")).strip()
                        count = await clear_queue_db(chat_id, subject=subject)
                        schedule_bg_chat_sync(bot, chat_id, subject)
                        q_snap, v_snap = await get_all_queues_cached_db()
                        await ws.send_str(json.dumps({
                            "type": "action_result",
                            "req_id": req_id,
                            "action": action,
                            "success": True,
                            "message": f"Чергу {subject} очищено (видалено {count} студентів)",
                            "count": count,
                            "version": v_snap,
                            "queues": q_snap,
                        }, ensure_ascii=False))
                        await broadcast_queue_ws({"trigger": "clear", "subject": subject})

                elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                    break
        except Exception as e:
            logger.debug(f"WebSocket connection closed with error: {e}")
        finally:
            auth_timeout_task.cancel()
            _ws_clients.discard(ws)
        return ws

    # --- REST API: Queue ---
    async def handle_api_queue_get(request):
        try:
            subject = request.query.get("subject", "ОП").strip()
            chat_id_str = request.query.get("chat_id", "0").strip()
            chat_id = int(chat_id_str) if chat_id_str.lstrip("-").isdigit() else 0

            queues, version = await get_all_queues_cached_db()
            items = queues.get(subject)
            if items is None:
                items = await get_active_queue_db(chat_id, subject)
            return json_response_cors({
                "success": True,
                "subject": subject,
                "chat_id": chat_id,
                "items": items,
                "total": len(items),
                "queues": queues,
                "version": version,
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_join(request):
        try:
            data = await request.json()
            verified_user = get_verified_webapp_user(request, data)
            if not verified_user or not verified_user.get("id"):
                return json_response_cors({"success": False, "error": "Необхідна авторизація через Telegram Mini App"}, status=401)

            user_id = int(verified_user["id"])
            username = str(verified_user.get("username") or "").strip() or None
            tg_full_name = " ".join(
                p for p in (verified_user.get("first_name"), verified_user.get("last_name")) if p
            ).strip()
            real_name = await find_student_real_name_db(user_id=user_id, telegram_username=username)
            user_name = real_name or tg_full_name or str(data.get("user_name", "Студент")).strip() or "Студент"

            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()
            lab_number = str(data.get("lab_number", "")).strip()
            append = bool(data.get("append", False))

            ok, msg, pos = await join_queue_db(chat_id, subject, user_id, user_name, username, lab_number, append=append)
            schedule_bg_chat_sync(bot, chat_id, subject)
            queues, version = await get_all_queues_cached_db()
            await broadcast_queue_ws({"trigger": "join", "subject": subject})

            return json_response_cors({
                "success": ok,
                "message": msg,
                "position": pos,
                "subject": subject,
                "lab_number": lab_number,
                "queues": queues,
                "version": version,
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_leave(request):
        try:
            data = await request.json()
            verified_user = get_verified_webapp_user(request, data)
            if not verified_user or not verified_user.get("id"):
                return json_response_cors({"success": False, "error": "Необхідна авторизація через Telegram Mini App"}, status=401)

            user_id = int(verified_user["id"])
            username = str(verified_user.get("username") or "").strip() or None
            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()

            ok = await leave_queue_db(chat_id, subject, user_id, username=username)
            schedule_bg_chat_sync(bot, chat_id, subject)
            queues, version = await get_all_queues_cached_db()
            await broadcast_queue_ws({"trigger": "leave", "subject": subject})

            return json_response_cors({
                "success": ok,
                "message": f"Ви вийшли з черги {subject}." if ok else "Вас не було в черзі.",
                "queues": queues,
                "version": version,
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_next(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Тільки староста або адміністратор може викликати наступного"}, status=403)

            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()

            student = await next_in_queue_db(chat_id, subject)
            schedule_bg_chat_sync(bot, chat_id, subject)
            queues, version = await get_all_queues_cached_db()
            await broadcast_queue_ws({"trigger": "next", "subject": subject, "called_student": student})

            return json_response_cors({
                "success": True,
                "student": student,
                "has_next": student is not None,
                "queues": queues,
                "version": version,
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_sync_sheet(request):
        try:
            from sync_queue_sheet import sync_queue
            count = await sync_queue(bot=bot)
            return json_response_cors({
                "success": True,
                "message": f"Синхронізовано {count} студентів з Google Таблиці",
                "count": count
            })
        except Exception as e:
            logger.error(f"Error syncing queue from sheet via API: {e}")
            return json_response_cors({"success": False, "error": str(e)}, status=500)

    # --- REST API: Schedule ---
    async def handle_api_schedule(request):
        try:
            from links_manager import get_lesson_link_info
            day_param = request.query.get("day", "").strip().lower()
            date_param = request.query.get("date", "").strip()
            now_kyiv = datetime.now(KYIV_TZ)

            if day_param == "week":
                monday = now_kyiv.date() - timedelta(days=now_kyiv.weekday())
                week_days = []
                current_week_num = 1
                all_week_lessons = []
                for day_offset in range(6):  # Пн, Вв, Ср, Чт, Пт, Сб (без неділі)
                    cur_date = monday + timedelta(days=day_offset)
                    cur_iso = cur_date.strftime("%Y-%m-%d")
                    w_num, d_name, day_lessons = await get_lessons_for_date(KPI_GROUP_ID, cur_date)
                    current_week_num = w_num

                    cancelled = await get_cancelled_pairs_for_date_db(cur_iso)
                    custom_list = await get_custom_lessons_for_date_db(cur_iso)

                    enriched_day_lessons = []
                    for idx, l in enumerate(day_lessons, 1):
                        p_num = int(l.get("pair_number") or TIME_TO_PAIR_NUMBER.get((l.get("time") or "")[:5], idx))
                        is_canc = p_num in cancelled
                        canc_info = cancelled.get(p_num, {})
                        lname = l.get("name", "")
                        ltype = l.get("type", "")
                        link_info = get_lesson_link_info(lname, ltype)
                        item = {
                            **l,
                            "pair_number": p_num,
                            "day_name": d_name,
                            "date": cur_iso,
                            "link_url": link_info.get("url", "").strip(),
                            "link_comment": link_info.get("comment", "").strip(),
                            "is_cancelled": is_canc,
                            "cancel_reason": canc_info.get("reason", "") if is_canc else "",
                            "cancelled_by": canc_info.get("cancelled_by", "") if is_canc else "",
                            "is_custom": False,
                        }
                        enriched_day_lessons.append(item)

                    for c in custom_list:
                        c_pnum = int(c["pair_number"])
                        is_canc = c_pnum in cancelled
                        canc_info = cancelled.get(c_pnum, {})
                        item = {
                            "is_custom": True,
                            "custom_id": c["id"],
                            "pair_number": c_pnum,
                            "name": c["name"],
                            "type": c["type"],
                            "lecturer": c["lecturer"],
                            "time": c["time"],
                            "location": c.get("location") or "Онлайн",
                            "link_url": c.get("link_url") or "",
                            "link_comment": c.get("comment") or "",
                            "is_cancelled": is_canc,
                            "cancel_reason": canc_info.get("reason", "") if is_canc else "",
                            "cancelled_by": canc_info.get("cancelled_by", "") if is_canc else "",
                            "created_by": c.get("created_by", ""),
                            "day_name": d_name,
                            "date": cur_iso,
                        }
                        enriched_day_lessons.append(item)

                    enriched_day_lessons.sort(key=lambda x: (int(x.get("pair_number") or 99), x.get("time") or ""))

                    for item in enriched_day_lessons:
                        all_week_lessons.append(item)

                    week_days.append({
                        "date": cur_iso,
                        "date_formatted": cur_date.strftime("%d.%m"),
                        "day_name": d_name,
                        "lessons": enriched_day_lessons,
                        "is_today": cur_date == now_kyiv.date()
                    })

                return json_response_cors({
                    "success": True,
                    "mode": "week",
                    "week": current_week_num,
                    "days": week_days,
                    "lessons": all_week_lessons,
                    "total": len(all_week_lessons)
                })

            if date_param:
                try:
                    target_date = datetime.strptime(date_param[:10], "%Y-%m-%d").date()
                except Exception:
                    target_date = now_kyiv.date()
            elif day_param == "tomorrow":
                target_date = (now_kyiv + timedelta(days=1)).date()
            else:
                target_date = now_kyiv.date()

            date_iso = target_date.strftime("%Y-%m-%d")
            week_num, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, target_date)

            cancelled = await get_cancelled_pairs_for_date_db(date_iso)
            custom_list = await get_custom_lessons_for_date_db(date_iso)

            enriched_lessons = []
            for idx, l in enumerate(lessons, 1):
                p_num = int(l.get("pair_number") or TIME_TO_PAIR_NUMBER.get((l.get("time") or "")[:5], idx))
                is_canc = p_num in cancelled
                canc_info = cancelled.get(p_num, {})
                lname = l.get("name", "")
                ltype = l.get("type", "")
                link_info = get_lesson_link_info(lname, ltype)
                enriched_lessons.append({
                    **l,
                    "pair_number": p_num,
                    "link_url": link_info.get("url", "").strip(),
                    "link_comment": link_info.get("comment", "").strip(),
                    "is_cancelled": is_canc,
                    "cancel_reason": canc_info.get("reason", "") if is_canc else "",
                    "cancelled_by": canc_info.get("cancelled_by", "") if is_canc else "",
                    "is_custom": False,
                })

            for c in custom_list:
                c_pnum = int(c["pair_number"])
                is_canc = c_pnum in cancelled
                canc_info = cancelled.get(c_pnum, {})
                enriched_lessons.append({
                    "is_custom": True,
                    "custom_id": c["id"],
                    "pair_number": c_pnum,
                    "name": c["name"],
                    "type": c["type"],
                    "lecturer": c["lecturer"],
                    "time": c["time"],
                    "location": c.get("location") or "Онлайн",
                    "link_url": c.get("link_url") or "",
                    "link_comment": c.get("comment") or "",
                    "is_cancelled": is_canc,
                    "cancel_reason": canc_info.get("reason", "") if is_canc else "",
                    "cancelled_by": canc_info.get("cancelled_by", "") if is_canc else "",
                    "created_by": c.get("created_by", ""),
                })

            enriched_lessons.sort(key=lambda x: (int(x.get("pair_number") or 99), x.get("time") or ""))

            return json_response_cors({
                "success": True,
                "mode": "day",
                "date": date_iso,
                "date_iso": date_iso,
                "day_name": day_name,
                "week": week_num,
                "lessons": enriched_lessons,
                "total": len(enriched_lessons)
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # --- REST API: Deadlines ---
    async def handle_api_deadlines(request):
        try:
            assignments = await get_active_assignments_db()
            now_kyiv = datetime.now(KYIV_TZ)

            clean_deadlines = []
            for a in assignments:
                title_lower = (a.get("title") or "").lower()
                # Фільтруємо пробні або тестові завдання
                if any(bad in title_lower for bad in ["пробне", "тренувальн", "демо-завдання"]):
                    continue

                due_str = a.get("due_date", "")
                if not due_str or due_str == "Без дедлайну":
                    continue

                # Перевіряємо актуальність дати
                try:
                    if len(due_str) == 10:
                        due_dt = datetime.strptime(due_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KYIV_TZ)
                    else:
                        due_dt = datetime.strptime(due_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)

                    # Не показуємо старі минулі дедлайни (понад 2 дні тому)
                    if due_dt < now_kyiv - timedelta(days=2):
                        continue
                except Exception:
                    continue

                # Зрозуміла назва предмету
                course_raw = a.get("course_id") or ""
                course_clean = course_raw
                if "ОП" in course_raw:
                    course_clean = "Основи програмування (ОП)"
                elif "КДМ" in course_raw:
                    course_clean = "Дискретна математика (КДМ)"
                elif "АСД" in course_raw:
                    course_clean = "Алгоритми та структури даних (АСД)"
                elif any(m in course_raw for m in ["Мат", "Матем", "ЛААГ"]):
                    course_clean = "Вища математика"

                alt_link = a.get("alternate_link") or "https://classroom.google.com"

                clean_deadlines.append({
                    **a,
                    "alternate_link": alt_link,
                    "course_clean": course_clean,
                    "due_time": due_dt.strftime("%Y-%m-%d %H:%M"),
                    "due_formatted": due_dt.strftime("%d.%m о %H:%M")
                })

            clean_deadlines.sort(key=lambda x: x["due_time"])

            return json_response_cors({
                "success": True,
                "deadlines": clean_deadlines,
                "total": len(clean_deadlines)
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # --- REST API: Students Roster ---
    async def handle_api_students_get(request):
        try:
            students = await get_all_students_db()
            students = [s for s in students if "куратор" not in (s.get("real_name") or "").lower()]
            return json_response_cors({
                "success": True,
                "students": students,
                "total": len(students)
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_student_resolve(request):
        try:
            user_id_str = request.query.get("user_id", "0").strip()
            user_id = int(user_id_str) if user_id_str.lstrip("-").isdigit() and int(user_id_str) != 0 else None
            username = request.query.get("username", "").strip() or None

            real_name = await find_student_real_name_db(user_id=user_id, telegram_username=username)
            first_name = extract_first_name(real_name) if real_name else None
            short_name = format_queue_name(real_name) if real_name else None
            return json_response_cors({
                "success": True,
                "real_name": real_name,
                "first_name": first_name,
                "short_name": short_name,
                "found": real_name is not None
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # --- REST API: Defenses ---
    async def handle_api_defenses(request):
        try:
            from database import get_student_defended_labs_db, get_all_defenses_summary_db
            user_id_str = request.query.get("user_id", "0").strip()
            user_id = int(user_id_str) if user_id_str.lstrip("-").isdigit() and int(user_id_str) != 0 else None
            subject = request.query.get("subject", "").strip() or None
            real_name = request.query.get("real_name", "").strip() or None
            is_all = request.query.get("all", "0").strip() in ("1", "true")

            if is_all:
                defenses = await get_all_defenses_summary_db(subject=subject)
            else:
                defenses = await get_student_defended_labs_db(user_id=user_id, real_name=real_name, subject=subject)

            return json_response_cors({
                "success": True,
                "defenses": defenses,
                "total": len(defenses)
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_defenses_toggle(request):
        try:
            from database import toggle_student_lab_defense_db
            data = await request.json()
            real_name = str(data.get("real_name", "")).strip()
            subject = str(data.get("subject", "ОП")).strip()
            lab_number = str(data.get("lab_number", "")).strip()
            user_id_raw = data.get("user_id")
            user_id = int(user_id_raw) if user_id_raw else None

            if not real_name or not lab_number:
                return json_response_cors({"success": False, "error": "real_name and lab_number are required"}, status=400)

            res = await toggle_student_lab_defense_db(
                real_name=real_name,
                subject=subject,
                lab_number=lab_number,
                telegram_id=user_id
            )
            return json_response_cors({
                "success": True,
                "real_name": real_name,
                "subject": subject,
                "lab_number": lab_number,
                **res
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_subjects_overview(request):
        try:
            from database import get_all_students_db, get_all_defenses_summary_db
            students = await get_all_students_db()
            defenses = await get_all_defenses_summary_db()

            subjects_meta = {
                "ОП": {
                    "code": "ОП",
                    "title": "Основи програмування",
                    "term_singular": "Практикум",
                    "term_plural": "Практикуми",
                    "total_works": 8,
                    "emoji": "💻"
                },
                "АСД": {
                    "code": "АСД",
                    "title": "Алгоритми та структури даних",
                    "term_singular": "Практична робота",
                    "term_plural": "Практичні роботи",
                    "total_works": 8,
                    "emoji": "🧮"
                }
            }

            return json_response_cors({
                "success": True,
                "subjects": subjects_meta,
                "students": students,
                "defenses": defenses,
                "total_students": len(students),
                "total_defenses": len(defenses)
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # --- Helper: перевірка прав адміністратора ---
    async def require_admin_auth(request: web.Request) -> tuple[dict, dict]:
        """
        Перевіряє криптографічний підпис Telegram WebApp initData
        та права адміністратора виключно за числовим user_id.
        Повертає (access_dict, data_dict).
        """
        data = {}
        if request.method == "POST":
            try:
                data = await request.json()
            except Exception:
                data = {}
        verified_user = get_verified_webapp_user(request, data)
        if not verified_user or not verified_user.get("id"):
            return {"is_admin": False, "is_owner": False, "role": None}, data
        user_id = int(verified_user["id"])
        access = await check_admin_access_db(user_id=user_id)
        return access, data

    # --- REST API: Admin Panel ---
    async def handle_api_admin_me(request):
        try:
            access, _ = await require_admin_auth(request)
            if access.get("is_admin"):
                access["roles"] = await get_admin_roles_db()
                try:
                    from links_manager import load_links
                    access["links"] = load_links()
                except Exception:
                    access["links"] = {}
            return json_response_cors({"success": True, **access})
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_test_mode(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)
            if not access.get("is_owner"):
                return json_response_cors({"success": False, "error": "Тільки власник може змінювати тест-режим"}, status=403)

            test_mode = bool(data.get("test_mode"))
            await set_admin_test_mode_db(test_mode)
            return json_response_cors({"success": True, "test_mode": test_mode})
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_schedule_cancel(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            date_str = str(data.get("date", "")).strip()
            pair_number = int(data.get("pair_number", 1))
            subject = str(data.get("subject", "")).strip()
            reason = str(data.get("reason", "")).strip()
            admin_name = str(data.get("admin_name", "")).strip() or (
                "Власник" if access.get("is_owner") else "Староста"
            )

            if not date_str:
                return json_response_cors({"success": False, "error": "date is required"}, status=400)

            ok = await cancel_pair_db(
                date_str=date_str,
                pair_number=pair_number,
                subject=subject,
                reason=reason,
                cancelled_by=admin_name
            )
            if ok:
                try:
                    await refresh_today_cache()
                except Exception:
                    pass

                pair_time = PAIR_TIMES.get(pair_number, "")
                subject_str = subject or f"Пара №{pair_number}"
                reason_str = reason or "Причина не вказана"
                msg_text = (
                    f"🚫 <b>Пару скасовано!</b>\n\n"
                    f"📅 <b>Дата:</b> {date_str}\n"
                    f"🔢 <b>Пара:</b> №{pair_number} ({pair_time})\n"
                    f"📘 <b>Дисципліна:</b> {subject_str}\n"
                    f"💬 <b>Причина:</b> {reason_str}"
                )
                asyncio.create_task(broadcast_schedule_change_notification(bot, msg_text))

            return json_response_cors({
                "success": bool(ok),
                "message": f"Пару №{pair_number} на {date_str} скасовано",
                "date": date_str,
                "pair_number": pair_number
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_schedule_uncancel(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            date_str = str(data.get("date", "")).strip()
            pair_number = int(data.get("pair_number", 1))

            if not date_str:
                return json_response_cors({"success": False, "error": "date is required"}, status=400)

            ok = await uncancel_pair_db(date_str=date_str, pair_number=pair_number)
            if ok:
                try:
                    await refresh_today_cache()
                except Exception:
                    pass

                pair_time = PAIR_TIMES.get(pair_number, "")
                subj_str = (ok.get("subject") if isinstance(ok, dict) and ok.get("subject") else f"Пара №{pair_number}")
                msg_text = (
                    f"↩️ <b>Пару відновлено в розкладі!</b>\n\n"
                    f"📅 <b>Дата:</b> {date_str}\n"
                    f"🔢 <b>Пара:</b> №{pair_number} ({pair_time})\n"
                    f"📘 <b>Дисципліна:</b> {subj_str}"
                )
                asyncio.create_task(broadcast_schedule_change_notification(bot, msg_text))

            return json_response_cors({
                "success": bool(ok),
                "message": f"Скасування пари №{pair_number} знято" if ok else "Пара не була скасована",
                "date": date_str,
                "pair_number": pair_number
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_schedule_add_pair(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            date_str = str(data.get("date", "")).strip()
            pair_number = int(data.get("pair_number", 1))
            name = str(data.get("name", "")).strip()
            lesson_type = str(data.get("type", "Практика")).strip()
            lecturer = str(data.get("lecturer", "")).strip()
            link_url = str(data.get("link_url", "")).strip()
            comment = str(data.get("comment", "")).strip()
            admin_name = str(data.get("admin_name", "")).strip() or (
                "Власник" if access.get("is_owner") else "Староста"
            )

            if not date_str or not name:
                return json_response_cors({"success": False, "error": "date and name are required"}, status=400)

            new_id = await add_custom_lesson_db(
                date_str=date_str,
                pair_number=pair_number,
                name=name,
                lesson_type=lesson_type,
                lecturer=lecturer,
                link_url=link_url,
                comment=comment,
                created_by=admin_name
            )
            if new_id:
                try:
                    await refresh_today_cache()
                except Exception:
                    pass

                pair_time = PAIR_TIMES.get(pair_number, "")
                lecturer_str = lecturer or "Не вказаний"
                link_line = f"\n🔗 <a href='{link_url}'>Посилання на пару</a>" if link_url else ""
                comment_line = f"\n💬 <b>Коментар:</b> {comment}" if comment else ""
                msg_text = (
                    f"🟣 <b>Додано нову пару / перенесення!</b>\n\n"
                    f"📅 <b>Дата:</b> {date_str}\n"
                    f"🔢 <b>Пара:</b> №{pair_number} ({pair_time}) • {lesson_type}\n"
                    f"📘 <b>Дисципліна:</b> {name}\n"
                    f"👤 <b>Викладач:</b> {lecturer_str}"
                    f"{link_line}{comment_line}"
                )
                asyncio.create_task(broadcast_schedule_change_notification(bot, msg_text))

            return json_response_cors({
                "success": True,
                "id": new_id,
                "message": "Пару успішно додано в розклад"
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_schedule_delete_pair(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            lesson_id = int(data.get("id", 0))
            if not lesson_id:
                return json_response_cors({"success": False, "error": "id is required"}, status=400)

            ok = await delete_custom_lesson_db(lesson_id)
            if ok:
                try:
                    await refresh_today_cache()
                except Exception:
                    pass

                del_date = ok.get("date", "") if isinstance(ok, dict) else ""
                del_pair_num = ok.get("pair_number", 1) if isinstance(ok, dict) else 1
                del_time = (ok.get("time") or PAIR_TIMES.get(del_pair_num, "")) if isinstance(ok, dict) else ""
                del_name = ok.get("name", f"Пара #{lesson_id}") if isinstance(ok, dict) else f"Пара #{lesson_id}"
                msg_text = (
                    f"🗑 <b>Додаткову пару видалено з розкладу</b>\n\n"
                    f"📅 <b>Дата:</b> {del_date}\n"
                    f"🔢 <b>Пара:</b> №{del_pair_num} ({del_time})\n"
                    f"📘 <b>Дисципліна:</b> {del_name}"
                )
                asyncio.create_task(broadcast_schedule_change_notification(bot, msg_text))

            return json_response_cors({
                "success": bool(ok),
                "message": "Пару успішно видалено" if ok else "Пару не знайдено"
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_roles_grant(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            target_user_id = data.get("target_user_id")
            target_username = data.get("target_username")
            target_real_name = str(data.get("target_real_name", "")).strip()
            role = str(data.get("role", "deputy")).strip()

            if not target_user_id and not target_username:
                return json_response_cors({"success": False, "error": "target_user_id or target_username required"}, status=400)

            await grant_admin_role_db(
                user_id=target_user_id,
                username=target_username,
                real_name=target_real_name,
                role=role
            )
            roles = await get_admin_roles_db()
            return json_response_cors({"success": True, "roles": roles})
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_roles_revoke(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            role_id = data.get("role_id")
            target_user_id = data.get("target_user_id")
            target_username = data.get("target_username")

            if not role_id and not target_user_id and not target_username:
                return json_response_cors({"success": False, "error": "role_id, target_user_id or target_username required"}, status=400)

            await revoke_admin_role_db(
                role_id=role_id,
                user_id=target_user_id,
                username=target_username
            )
            roles = await get_admin_roles_db()
            return json_response_cors({"success": True, "roles": roles})
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_admin_queue_clear(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()

            count = await clear_queue_db(chat_id, subject=subject)
            schedule_bg_chat_sync(bot, chat_id, subject)
            queues, version = await get_all_queues_cached_db()
            await broadcast_queue_ws({"trigger": "clear", "subject": subject})

            return json_response_cors({
                "success": True,
                "message": f"Чергу {subject} очищено (видалено {count} студентів)",
                "count": count,
                "queues": queues,
                "version": version,
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # --- Projects & English Groups API (v3.2) ---
    async def handle_api_projects_boards(request):
        try:
            subject = str(request.query.get("subject", "Англійська")).strip()
            user_id = request.query.get("user_id")
            username = request.query.get("username")

            access = await check_admin_access_db(user_id=user_id, username=username)
            test_mode = access.get("test_mode", False)
            is_admin = access.get("is_admin", False)

            if test_mode and not is_admin:
                return json_response_cors({
                    "success": True,
                    "restricted_by_test_mode": True,
                    "test_mode": True,
                    "is_admin": False,
                    "boards": []
                })

            boards = await get_project_boards_db(subject=subject)
            return json_response_cors({
                "success": True,
                "restricted_by_test_mode": False,
                "test_mode": test_mode,
                "is_admin": is_admin,
                "boards": boards
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_projects_boards_create(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            title = str(data.get("title", "")).strip()
            if not title:
                return json_response_cors({"success": False, "error": "Вкажіть назву набору груп (title)"}, status=400)

            subject = str(data.get("subject", "Англійська")).strip()
            description = str(data.get("description", "")).strip()
            max_members = int(data.get("max_members", 3))

            initial_topics_raw = data.get("initial_topics")
            initial_topics = []
            if isinstance(initial_topics_raw, list):
                initial_topics = [str(t).strip() for t in initial_topics_raw if str(t).strip()]
            elif isinstance(initial_topics_raw, str) and initial_topics_raw.strip():
                initial_topics = [t.strip() for t in re.split(r"[\n,;]", initial_topics_raw) if t.strip()]

            admin_name = str(data.get("admin_name") or access.get("real_name") or access.get("username") or "Староста")
            board_id = await create_project_board_db(
                title=title,
                subject=subject,
                description=description,
                max_members=max_members,
                initial_topics=initial_topics,
                created_by=admin_name
            )
            return json_response_cors({
                "success": True,
                "board_id": board_id,
                "message": f"Набір груп «{title}» успішно створено"
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_projects_boards_delete(request):
        try:
            access, data = await require_admin_auth(request)
            if not access.get("is_admin"):
                return json_response_cors({"success": False, "error": "Немає прав доступу"}, status=403)

            board_id = data.get("board_id")
            if not board_id:
                return json_response_cors({"success": False, "error": "board_id required"}, status=400)

            ok = await delete_project_board_db(board_id)
            return json_response_cors({
                "success": ok,
                "message": "Набір груп видалено" if ok else "Борд не знайдено"
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_projects_groups_join(request):
        try:
            data = await request.json()
            board_id = data.get("board_id")
            if not board_id:
                return json_response_cors({"success": False, "error": "board_id is required"}, status=400)

            group_id = data.get("group_id")
            user_id = data.get("user_id")
            user_name = str(data.get("user_name", "")).strip()
            username = str(data.get("username", "")).strip()
            topic_title = str(data.get("topic_title", "")).strip()
            teammates = data.get("teammates")

            if not user_name:
                return json_response_cors({"success": False, "error": "user_name is required"}, status=400)

            ok, msg, gid = await create_or_join_project_group_db(
                board_id=board_id,
                user_id=user_id,
                user_name=user_name,
                username=username,
                topic_title=topic_title,
                group_id=group_id,
                teammates=teammates
            )
            return json_response_cors({
                "success": ok,
                "message": msg,
                "group_id": gid
            }, status=200 if ok else 400)
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_projects_groups_leave(request):
        try:
            data = await request.json()
            group_id = data.get("group_id")
            if not group_id:
                return json_response_cors({"success": False, "error": "group_id is required"}, status=400)

            user_id = data.get("user_id")
            user_name = data.get("user_name")

            ok = await leave_project_group_db(
                group_id=group_id,
                user_id=user_id,
                user_name=user_name
            )
            return json_response_cors({
                "success": ok,
                "message": "Ви вийшли з групи" if ok else "Учасника не знайдено"
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_projects_groups_upload_and_generate(request):
        try:
            data = await request.json()
            group_id = data.get("group_id")
            if not group_id:
                return json_response_cors({"success": False, "error": "group_id is required"}, status=400)

            topic_title = str(data.get("topic_title", "")).strip()
            content_text = str(data.get("content_text", "")).strip()
            file_name = str(data.get("file_name", "")).strip()
            file_b64 = str(data.get("file_base64", "")).strip()

            if file_b64:
                if "," in file_b64:
                    file_b64 = file_b64.split(",", 1)[1]
                file_bytes = base64.b64decode(file_b64)
                extracted_text = extract_text_from_uploaded_file(file_name, file_bytes)
                if extracted_text:
                    content_text = f"{content_text}\n\n[Зміст файлу {file_name}]:\n{extracted_text}".strip() if content_text else extracted_text

            await save_project_group_material_db(
                group_id=group_id,
                content_text=content_text,
                file_name=file_name,
                topic_title=topic_title if topic_title else None
            )

            from llm_agent import generate_english_presentation_qa
            qa_list = await generate_english_presentation_qa(topic_title, content_text)
            await save_project_group_ai_qa_db(group_id, qa_list)

            return json_response_cors({
                "success": True,
                "qa_list": qa_list,
                "content_text": content_text,
                "file_name": file_name,
                "message": f"Згенеровано {len(qa_list)} питань та відповідей!"
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # Реєстрація роутів
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/app", handle_app_index)
    app.router.add_get("/ws", handle_websocket)

    # API
    app.router.add_route("OPTIONS", "/api/{tail:.*}", handle_options)
    app.router.add_get("/api/queue", handle_api_queue_get)
    app.router.add_post("/api/queue/join", handle_api_queue_join)
    app.router.add_post("/api/queue/leave", handle_api_queue_leave)
    app.router.add_post("/api/queue/next", handle_api_queue_next)
    app.router.add_get("/api/queue/sync_sheet", handle_api_queue_sync_sheet)
    app.router.add_post("/api/queue/sync_sheet", handle_api_queue_sync_sheet)
    app.router.add_get("/api/schedule", handle_api_schedule)
    app.router.add_get("/api/deadlines", handle_api_deadlines)
    app.router.add_get("/api/students", handle_api_students_get)
    app.router.add_get("/api/student/resolve", handle_api_student_resolve)
    app.router.add_get("/api/defenses", handle_api_defenses)
    app.router.add_post("/api/defenses/toggle", handle_api_defenses_toggle)
    app.router.add_get("/api/subjects/overview", handle_api_subjects_overview)

    # Projects & English Groups API (v3.2)
    app.router.add_get("/api/projects/boards", handle_api_projects_boards)
    app.router.add_post("/api/projects/boards/create", handle_api_projects_boards_create)
    app.router.add_post("/api/projects/boards/delete", handle_api_projects_boards_delete)
    app.router.add_post("/api/projects/groups/join", handle_api_projects_groups_join)
    app.router.add_post("/api/projects/groups/leave", handle_api_projects_groups_leave)
    app.router.add_post("/api/projects/groups/upload_and_generate", handle_api_projects_groups_upload_and_generate)

    # Admin API
    app.router.add_get("/api/admin/me", handle_api_admin_me)
    app.router.add_post("/api/admin/test_mode", handle_api_admin_test_mode)
    app.router.add_post("/api/admin/schedule/cancel", handle_api_admin_schedule_cancel)
    app.router.add_post("/api/admin/schedule/uncancel", handle_api_admin_schedule_uncancel)
    app.router.add_post("/api/admin/schedule/add_pair", handle_api_admin_schedule_add_pair)
    app.router.add_post("/api/admin/schedule/delete_pair", handle_api_admin_schedule_delete_pair)
    app.router.add_post("/api/admin/roles/grant", handle_api_admin_roles_grant)
    app.router.add_post("/api/admin/roles/revoke", handle_api_admin_roles_revoke)
    app.router.add_post("/api/admin/queue/clear", handle_api_admin_queue_clear)

    # Static files
    if WEBAPP_DIR.exists():
        app.router.add_static("/webapp/", WEBAPP_DIR, name="webapp")

    return app


async def start_webapp_server(bot: Bot | None = None) -> web.AppRunner | None:
    """Запуск сервера aiohttp."""
    port_str = os.getenv("PORT") or "8080"
    try:
        port = int(port_str)
        app = create_webapp_app(bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"🚀 Telegram Mini App & API сервер успішно запущено на порті {port}")
        return runner
    except Exception as e:
        logger.warning(f"Не вдалося запустити WebApp сервер: {e}")
        return None

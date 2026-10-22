import os
import json
import asyncio
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from aiohttp import web
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from config import (
    BASE_DIR,
    KYIV_TZ,
    KPI_GROUP_ID,
    TURSO_DATABASE_URL,
    SQLITE_CLOUD_URL,
    WEBAPP_URL,
    OWNER_ID,
)
from handlers import make_webapp_button
from scheduler import safe_send_message, refresh_today_cache
from database import (
    get_subscribed_chats_db,
    get_active_queue_db,
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
        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Telegram-Init-Data",
    }


def json_response_cors(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers=cors_headers())


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


def create_webapp_app(bot: Bot | None = None) -> web.Application:
    """Створює веб-додаток aiohttp для Telegram Mini App, REST API та health-check."""
    app = web.Application()

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

    # --- REST API: Queue ---
    async def handle_api_queue_get(request):
        try:
            subject = request.query.get("subject", "ОП").strip()
            chat_id_str = request.query.get("chat_id", "0").strip()
            chat_id = int(chat_id_str) if chat_id_str.lstrip("-").isdigit() else 0

            items = await get_active_queue_db(chat_id, subject)
            return json_response_cors({
                "success": True,
                "subject": subject,
                "chat_id": chat_id,
                "items": items,
                "total": len(items)
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_join(request):
        try:
            data = await request.json()
            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()
            user_id = int(data.get("user_id", 0))
            user_name = str(data.get("user_name", "Студент")).strip()
            username = str(data.get("username", "")).strip() or None
            lab_number = str(data.get("lab_number", "")).strip()
            append = bool(data.get("append", False))

            if not user_id:
                return json_response_cors({"success": False, "error": "user_id is required"}, status=400)

            ok, msg, pos = await join_queue_db(chat_id, subject, user_id, user_name, username, lab_number, append=append)
            # Синхронізуємо повідомлення в групі Telegram
            if chat_id != 0 and bot:
                await sync_queue_message_in_chat(bot, chat_id, subject)

            return json_response_cors({
                "success": ok,
                "message": msg,
                "position": pos,
                "subject": subject,
                "lab_number": lab_number
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_leave(request):
        try:
            data = await request.json()
            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()
            user_id = int(data.get("user_id", 0))
            username = str(data.get("username", "")).strip() or None

            if not user_id and not username:
                return json_response_cors({"success": False, "error": "user_id or username is required"}, status=400)

            ok = await leave_queue_db(chat_id, subject, user_id, username=username)
            if chat_id != 0 and bot:
                await sync_queue_message_in_chat(bot, chat_id, subject)

            return json_response_cors({
                "success": ok,
                "message": f"Ви вийшли з черги {subject}." if ok else "Вас не було в черзі."
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    async def handle_api_queue_next(request):
        try:
            data = await request.json()
            chat_id = int(data.get("chat_id", 0))
            subject = str(data.get("subject", "ОП")).strip()

            student = await next_in_queue_db(chat_id, subject)
            if chat_id != 0 and bot:
                await sync_queue_message_in_chat(bot, chat_id, subject)

            return json_response_cors({
                "success": True,
                "student": student,
                "has_next": student is not None
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
    async def require_admin_auth(request) -> tuple[dict, dict]:
        """
        Читає user_id та username з JSON тіла або query,
        перевіряє права через check_admin_access_db.
        Повертає (access_dict, data_dict).
        """
        data = {}
        if request.method == "POST":
            try:
                data = await request.json()
            except Exception:
                data = {}
        user_id = data.get("user_id") if data.get("user_id") is not None else request.query.get("user_id")
        username = data.get("username") or request.query.get("username")
        access = await check_admin_access_db(user_id=user_id, username=username)
        return access, data

    # --- REST API: Admin Panel ---
    async def handle_api_admin_me(request):
        try:
            user_id = request.query.get("user_id")
            username = request.query.get("username")
            access = await check_admin_access_db(user_id=user_id, username=username)
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
            if chat_id != 0 and bot:
                await sync_queue_message_in_chat(bot, chat_id, subject)

            return json_response_cors({
                "success": True,
                "message": f"Чергу {subject} очищено (видалено {count} студентів)",
                "count": count
            })
        except Exception as e:
            return json_response_cors({"success": False, "error": str(e)}, status=400)

    # Реєстрація роутів
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/app", handle_app_index)

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

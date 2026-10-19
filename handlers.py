import asyncio
from datetime import datetime, timedelta
import html
import logging
import re
import uuid

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest

from config import (
    KYIV_TZ,
    KPI_GROUP_ID,
    add_subscribed_chat,
    remove_subscribed_chat,
    get_subscribed_chats,
)
from kpi_api import get_lessons_for_date, get_current_time_info
from links_manager import load_links
from formatters import format_morning_digest, clean_markdown, escape_html_text

logger = logging.getLogger(__name__)

router = Router()


def strip_html_tags(text: str) -> str:
    """Видаляє HTML теги для безпечної відправки повідомлення звичайним текстом."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    return html.unescape(clean)


def strip_markdown(text: str) -> str:
    """Зворотна сумісність: очищення спецсимволів."""
    return strip_html_tags(text).replace("**", "").replace("*", "").replace("`", "").replace("_", "").replace("~", "")


async def safe_answer(message: Message, text: str, reply_markup=None, disable_web_page_preview: bool = False):
    """Безпечна відправка повідомлення з підтримкою HTML та резервним plain-text варіантом при збоях парсера."""
    try:
        return await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        logger.warning(f"Помилка парсингу HTML: {e}. Відправляю простим текстом.")
        plain_text = strip_html_tags(text)
        return await message.answer(
            plain_text,
            parse_mode=None,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except Exception as e:
        logger.error(f"Непередбачена помилка в safe_answer: {e}")
        plain_text = strip_html_tags(text)
        return await message.answer(
            plain_text,
            parse_mode=None,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )


async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None):
    """Безпечне редагування тексту повідомлення з підтримкою HTML та резервним plain-text варіантом."""
    try:
        return await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as e:
        logger.warning(f"Помилка парсингу HTML при редагуванні: {e}. Редагую простим текстом.")
        plain_text = strip_html_tags(text)
        try:
            return await callback.message.edit_text(plain_text, parse_mode=None, reply_markup=reply_markup)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Помилка в safe_edit_text: {e}")


def normalize_due_date(due_str: str) -> str | None:
    """Валідація та нормалізація введеної користувачем дати дедлайну."""
    s = due_str.strip()
    formats = [
        ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M"),
        ("%Y-%m-%d", "%Y-%m-%d 23:59"),
        ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"),
        ("%d.%m.%Y", "%Y-%m-%d 23:59"),
    ]
    for in_fmt, out_fmt in formats:
        try:
            dt = datetime.strptime(s, in_fmt)
            return dt.strftime(out_fmt)
        except ValueError:
            continue
    return None


@router.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    chat_type = message.chat.type
    thread_id = getattr(message, "message_thread_id", None)

    from database import add_subscription_db
    is_new = await add_subscription_db(chat_id, thread_id)
    add_subscribed_chat(chat_id, thread_id)

    is_group = chat_type in (ChatType.GROUP, ChatType.SUPERGROUP)
    topic_desc = f" (топік ID: <code>{thread_id}</code>)" if thread_id else ""
    chat_desc = f"цього групового чату{topic_desc}" if is_group else "вас"
    id_info = f"\n🆔 <b>ID чату:</b> <code>{chat_id}</code>" if is_group else ""
    if thread_id:
        id_info += f"\n📌 <b>ID топіку:</b> <code>{thread_id}</code>"

    sub_status = (
        f"✅ Сповіщення активовано для {chat_desc}!{id_info}"
        if is_new
        else f"ℹ️ {chat_desc.capitalize()} вже підписано на сповіщення.{id_info}"
    )

    text = (
        "👋 <b>Привіт! Я розумний розклад-асистент ІП-66.</b>\n\n"
        "🤖 <b>Що я роблю на автоматі:</b>\n"
        "• ☀️ <b>08:00</b> — Ранковий розклад пар з посиланнями на заняття\n"
        "• 🔔 <b>За 20 та 5 хв</b> — Нагадування перед кожною парою (з автовидаленням через 20 хв)\n"
        "• 📚 <b>Google Classroom</b> — Миттєві сповіщення про нові завдання та дедлайни\n"
        "• 🎬 <b>YouTube <code>@ip-66_studio</code></b> — Автоматичний конспект лекцій через Gemini AI\n"
        "• 🌙 <b>21:00</b> (та 10:00 у вихідні) — Розумний підсумок дня /summary\n\n"
        f"{sub_status}\n\n"
        "📋 <b>Повний список команд:</b>\n\n"
        "📅 <b>Розклад пар:</b>\n"
        "/today — Розклад пар на сьогодні з лінками на Zoom/Meet\n"
        "/tomorrow — Розклад пар на завтра\n"
        "/week — Номер поточного тижня (чисельник/знаменник) та київський час\n"
        "/links — Збережені посилання на конференції та лекції\n"
        "/setlink — Додати/оновити посилання на пару (<code>/setlink Предмет | URL | Коментар</code>)\n"
        "/dellink — Видалити посилання на предмет (<code>/dellink Предмет</code>)\n\n"
        "📊 <b>Дедлайни та Classroom:</b>\n"
        "/deadlines — Радар усіх дедлайнів (палаючі, на тиждень, без дедлайну)\n"
        "/summary — Підсумок дня, що задали та палаючі дедлайни\n"
        "/sync — Миттєва ручна синхронізація з Google Classroom\n"
        "/adddeadline — Додати завдання вручну (<code>/adddeadline Предмет | Назва | Дедлайн | Опис</code>)\n"
        "/deldeadline — Видалити завдання за ID (<code>/deldeadline &lt;id&gt;</code>)\n\n"
        "⚙️ <b>Керування сповіщеннями:</b>\n"
        "/subscribe — Увімкнути сповіщення в цьому чаті / топіку\n"
        "/unsubscribe — Вимкнути сповіщення\n"
        "/help — Повна довідка з поясненням можливостей"
    )
    await safe_answer(message, text)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)

    from database import add_subscription_db
    await add_subscription_db(chat_id, thread_id)
    add_subscribed_chat(chat_id, thread_id)

    if thread_id:
        await safe_answer(
            message,
            f"✅ <b>Сповіщення успішно налаштовано для цього топіку!</b>\n\n"
            f"🆔 <b>ID чату:</b> <code>{chat_id}</code>\n"
            f"📌 <b>ID топіку:</b> <code>{thread_id}</code>\n\n"
            f"🎯 Усі ранкові розклади, нагадування перед парами, дедлайни з Classroom та конспекти лекцій "
            f"надсилатимуться <b>виключно в цю гілку</b>."
        )
    else:
        await safe_answer(
            message,
            f"✅ <b>Сповіщення успішно активовано для цього чату!</b>\n"
            f"🆔 <b>ID чату:</b> <code>{chat_id}</code>"
        )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)

    from database import remove_subscription_db
    await remove_subscription_db(chat_id, thread_id)
    remove_subscribed_chat(chat_id, thread_id)

    if thread_id:
        await safe_answer(message, f"🛑 Сповіщення для топіку <code>{thread_id}</code> вимкнено.")
    else:
        await safe_answer(message, "🛑 Сповіщення для цього чату вимкнено.")


@router.message(Command("today"))
async def cmd_today(message: Message):
    today = datetime.now(KYIV_TZ).date()
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, today)
        is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

        from scheduler import calculate_lessons_end_datetime, update_today_cache
        from database import add_scheduled_deletion_db, get_cancelled_pairs_for_date_db
        update_today_cache(week, day_name, lessons, today)

        now_dt = datetime.now(KYIV_TZ)
        end_dt = calculate_lessons_end_datetime(lessons, today)
        delete_time_str = end_dt.strftime("%H:%M")
        show_delete = is_group and lessons and end_dt > now_dt

        cancelled_map = await get_cancelled_pairs_for_date_db(today.isoformat())
        text, kb = format_morning_digest(
            week,
            day_name,
            lessons,
            auto_delete_time=delete_time_str if show_delete else None,
            cancelled_pairs=cancelled_map
        )
        sent = await safe_answer(message, text, reply_markup=kb)
        if sent and show_delete:
            await add_scheduled_deletion_db(
                chat_id=message.chat.id,
                message_id=sent.message_id,
                delete_at=end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                tag="today_command"
            )
    except Exception as e:
        await safe_answer(message, f"⚠️ Не вдалося отримати розклад: {escape_html_text(str(e))}")


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message):
    tomorrow = datetime.now(KYIV_TZ).date() + timedelta(days=1)
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, tomorrow)
        text, kb = format_morning_digest(week, day_name, lessons)
        text = text.replace("на сьогодні", "на завтра")
        await safe_answer(message, text, reply_markup=kb)
    except Exception as e:
        await safe_answer(message, f"⚠️ Не вдалося отримати розклад: {escape_html_text(str(e))}")


@router.message(Command("week"))
async def cmd_week(message: Message):
    try:
        info = await get_current_time_info()
        week = info.get("currentWeek", 1)
        now = datetime.now(KYIV_TZ)
        time_str = now.strftime("%H:%M:%S")
        await safe_answer(
            message,
            f"🕒 <b>Київський час:</b> <code>{time_str}</code>\n"
            f"📅 <b>Зараз триває:</b> <code>{week}-й тиждень</code> ({'Чисельник' if week == 1 else 'Знаменник'})",
        )
    except Exception as e:
        await safe_answer(message, f"⚠️ Не вдалося визначити тиждень: {escape_html_text(str(e))}")


@router.message(Command("links"))
async def cmd_links(message: Message):
    links = load_links()
    if not links:
        await safe_answer(message, "📂 Список посилань порожній.")
        return

    lines = ["🔗 <b>Збережені посилання на заняття:</b>\n"]
    has_any = False
    for title, data in links.items():
        url = data.get("url", "").strip()
        comment = data.get("comment", "").strip()
        if url:
            has_any = True
            c_title = escape_html_text(str(title))
            c_comment = escape_html_text(str(comment))
            comment_str = f" <i>({c_comment})</i>" if c_comment else ""
            lines.append(f'• <b>{c_title}</b>:\n  <a href="{html.escape(url)}">Приєднатися</a>{comment_str}')

    if not has_any:
        await safe_answer(message, "ℹ️ Посилання ще не додані в <code>links.json</code>.")
        return

    await safe_answer(message, "\n\n".join(lines), disable_web_page_preview=True)


@router.message(Command("setlink"))
async def cmd_set_link(message: Message):
    from links_manager import set_course_link
    raw_text = message.text.replace("/setlink", "", 1).strip()
    parts = [p.strip() for p in raw_text.split("|")]
    if len(parts) < 2:
        await safe_answer(
            message,
            "ℹ️ <b>Формат додавання/оновлення посилання на пару:</b>\n"
            "<code>/setlink Предмет (Тип) | URL | Коментар (необов'язково)</code>\n\n"
            "Приклад:\n"
            "<code>/setlink Філософія (Лек) | https://us02web.zoom.us/j/... | Zoom</code>"
        )
        return

    raw_key = parts[0][:100].strip()
    url = parts[1].strip()
    comment = parts[2][:100].strip() if len(parts) > 2 else ""

    if not (url.startswith("http://") or url.startswith("https://")):
        await safe_answer(message, "❌ Посилання має починатися з <code>https://</code> або <code>http://</code>!")
        return

    set_course_link(raw_key, url, comment)
    c_key = escape_html_text(raw_key)
    comment_str = f" <i>({escape_html_text(comment)})</i>" if comment else ""
    await safe_answer(
        message,
        f"✅ Посилання для <b>{c_key}</b> успішно збережено!\n"
        f'🔗 <a href="{html.escape(url)}">Перейти до заняття</a>{comment_str}'
    )


@router.message(Command("dellink"))
async def cmd_del_link(message: Message):
    from links_manager import delete_course_link
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_answer(message, "ℹ️ Вкажіть назву предмета для видалення:\n<code>/dellink Назва</code>")
        return

    key = parts[1].strip()
    if delete_course_link(key):
        await safe_answer(message, f"🗑 Посилання для <b>{escape_html_text(key)}</b> видалено!")
    else:
        await safe_answer(message, f"⚠️ Посилання для «{escape_html_text(key)}» не знайдено.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📖 <b>Повна довідка по боту ІП-66:</b>\n\n"
        "📅 <b>Розклад пар та посилання:</b>\n"
        "• /today — Пари на сьогодні з посиланнями на Zoom/Teams/Meet\n"
        "• /tomorrow — Пари на завтра\n"
        "• /week — Номер навчального тижня (1 чи 2) та точний київський час\n"
        "• /links — База збережених посилань на дистанційні заняття\n"
        "• /setlink — Додати або оновити посилання на пару (<code>/setlink Предмет | URL | Коментар</code>)\n"
        "• /dellink — Видалити посилання на предмет (<code>/dellink Предмет</code>)\n\n"
        "📊 <b>Завдання, Classroom та AI:</b>\n"
        "• /deadlines — Радар активних завдань з Google Classroom із розрахунком часу, що залишився\n"
        "• /summary (або /evening) — Розумний підсумок дня (пари, що задали, анонси та палаючі дедлайни)\n"
        "• /sync — Примусова синхронізація завдань із Google Classroom\n"
        "• /adddeadline — Додати власне завдання або дедлайн вручну\n"
        "  <i>Формат:</i> <code>/adddeadline Предмет | Назва | РРРР-ММ-ДД HH:MM | Опис</code>\n"
        "• /deldeadline — Видалити завдання за ID (<code>/deldeadline &lt;id&gt;</code>)\n\n"
        "🔔 <b>Автоматичні функції бота:</b>\n"
        "• ☀️ <b>08:00 (Пн-Сб)</b> — Ранковий дайджест пар на день\n"
        "• ⏰ <b>За 20 хв і 5 хв до пари</b> — Нагадування з прямим лінком (автовидалення через 20 хв)\n"
        "• 📚 <b>Кожні 15 хв</b> — Перевірка нових завдань у Google Classroom\n"
        "• 🎬 <b>Кожні 10 хв</b> — Моніторинг нових лекцій на YouTube <code>@ip-66_studio</code> та Gemini AI конспект\n"
        "• 🌙 <b>21:00</b> — Вечірній підсумок дня (о 10:00 у вихідні дні)\n\n"
        "⚙️ <b>Керування чатом:</b>\n"
        "• /subscribe — Увімкнути автоматичні сповіщення для цього чату / топіку\n"
        "• /unsubscribe — Призупинити сповіщення для цього чату / топіку"
    )
    await safe_answer(message, text)


@router.message(Command("deadlines"))
async def cmd_deadlines(message: Message):
    from database import get_active_assignments_db
    from formatters import format_deadlines_radar

    assignments = await get_active_assignments_db()
    text = format_deadlines_radar(assignments)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Оновити з Google Classroom", callback_data="refresh_deadlines")]
        ]
    )
    await safe_answer(message, text, reply_markup=kb)


@router.callback_query(F.data == "refresh_deadlines")
async def cb_refresh_deadlines(callback: CallbackQuery, bot: Bot):
    await callback.answer("⏳ Синхронізація з Classroom...")
    from classroom_sync import sync_classroom_tasks
    from database import get_active_assignments_db
    from formatters import format_deadlines_radar

    res = await sync_classroom_tasks(bot=bot)
    assignments = await get_active_assignments_db()
    text = format_deadlines_radar(assignments)

    if not res.get("success"):
        err_msg = escape_html_text(str(res.get("error", "Помилка")))
        text += f"\n\n⚠️ <i>Синхронізація не вдалася: {err_msg}</i>"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Оновити з Google Classroom", callback_data="refresh_deadlines")]
        ]
    )
    await safe_edit_text(callback, text, reply_markup=kb)


async def _run_youtube_check_bg(message: Message, bot: Bot, status_msg: Message):
    from scheduler import check_new_youtube_videos
    try:
        new_cnt = await check_new_youtube_videos(
            bot=bot,
            fallback_chat_id=message.chat.id,
            fallback_thread_id=message.message_thread_id,
        )
        if new_cnt > 0:
            res_text = f"✅ Оброблено та опубліковано нових лекцій: <b>{new_cnt}</b>! Пости надіслано в чат."
        else:
            res_text = "ℹ️ Наразі нових неопублікованих лекцій на YouTube немає (усі останні відео вже оброблено)."
        if status_msg:
            try:
                await status_msg.edit_text(res_text, parse_mode="HTML")
                return
            except Exception:
                pass
        await safe_answer(message, res_text)
    except Exception as e:
        err_text = f"❌ Помилка при перевірці YouTube: {escape_html_text(str(e))}"
        if status_msg:
            try:
                await status_msg.edit_text(err_text, parse_mode="HTML")
                return
            except Exception:
                pass
        await safe_answer(message, err_text)


@router.message(Command("youtube"))
async def cmd_youtube(message: Message, bot: Bot):
    status_msg = await safe_answer(message, "🎬 Перевіряю нові лекції на YouTube-каналі групи...")
    asyncio.create_task(_run_youtube_check_bg(message, bot, status_msg))


async def _run_sync_bg(message: Message, bot: Bot, status_msg: Message):
    from classroom_sync import sync_classroom_tasks
    from database import get_active_assignments_db
    from scheduler import check_new_youtube_videos

    # 1. Синхронізація Google Classroom
    res = await sync_classroom_tasks(bot=bot)

    # 2. Перевірка YouTube
    yt_status = ""
    try:
        yt_new = await check_new_youtube_videos(bot=bot)
        if yt_new > 0:
            yt_status = f"\n🎬 <b>YouTube:</b> знайдено та опубліковано нових лекцій: {yt_new}."
        else:
            yt_status = "\n🎬 <b>YouTube:</b> перевірено, нових лекцій немає."
    except Exception as e_yt:
        yt_status = f"\n⚠️ <b>YouTube:</b> {escape_html_text(str(e_yt))}"

    if not res.get("success"):
        err = escape_html_text(str(res.get("error", "Невідома помилка")))
        err_text = (
            f"❌ <b>Помилка синхронізації Google Classroom:</b>\n<code>{err}</code>{yt_status}\n\n"
            f"ℹ️ <b>Що перевірити:</b>\n"
            f"1. Чи додана змінна <code>GOOGLE_TOKEN_JSON</code> в налаштуваннях Render (розділ <b>Environment</b>).\n"
            f"2. Чи натиснута кнопка <b>Save Changes</b> на Render."
        )
        if status_msg:
            try:
                await status_msg.edit_text(err_text, parse_mode="HTML")
                return
            except Exception:
                pass
        await safe_answer(message, err_text)
        return

    active = await get_active_assignments_db()
    courses_cnt = res.get("courses_count", 0)
    new_cnt = len(res.get("new_items", []))
    total_cnt = len(active)

    success_text = (
        f"✅ <b>Google Classroom та YouTube успішно синхронізовано!</b>\n\n"
        f"📚 Знайдено активних курсів: <b>{courses_cnt}</b>\n"
        f"🆕 Нових завдань завантажено: <b>{new_cnt}</b>\n"
        f"📋 Всього активних завдань у базі: <b>{total_cnt}</b>{yt_status}\n\n"
        f"Введіть /deadlines, щоб переглянути оновлений радар завдань! 🎯"
    )
    if status_msg:
        try:
            await status_msg.edit_text(success_text, parse_mode="HTML")
            return
        except Exception:
            pass
    await safe_answer(message, success_text)


@router.message(Command("sync"))
async def cmd_sync(message: Message, bot: Bot):
    status_msg = await safe_answer(message, "🔄 Запускаю синхронізацію з Google Classroom та YouTube...")
    asyncio.create_task(_run_sync_bg(message, bot, status_msg))


@router.message(Command("adddeadline"))
async def cmd_add_deadline(message: Message):
    from database import add_assignment_db

    raw_text = message.text.replace("/adddeadline", "", 1).strip()
    parts = [p.strip() for p in raw_text.split("|")]
    if len(parts) < 3:
        await safe_answer(
            message,
            "ℹ️ <b>Формат додавання дедлайну:</b>\n"
            "<code>/adddeadline Предмет | Назва завдання | РРРР-ММ-ДД HH:MM | Опис (необов'язково)</code>\n\n"
            "Приклад:\n"
            "<code>/adddeadline Основи програмування | Лабораторна №1 | 2026-10-15 23:59 | Здати в репозиторій</code>",
        )
        return

    course_name = escape_html_text(parts[0][:60])
    title = escape_html_text(parts[1][:150])
    raw_date = parts[2][:30].strip()
    desc = parts[3][:300] if len(parts) > 3 else ""

    due_date = normalize_due_date(raw_date)
    if not due_date:
        await safe_answer(
            message,
            "❌ <b>Невірний формат дати!</b>\n\n"
            "Вкажіть дату в одному з форматів:\n"
            "• <code>РРРР-ММ-ДД HH:MM</code> (наприклад, <code>2026-10-25 23:59</code>)\n"
            "• <code>РРРР-ММ-ДД</code> (наприклад, <code>2026-10-25</code>)\n"
            "• <code>ДД.ММ.РРРР HH:MM</code> (наприклад, <code>25.10.2026 23:59</code>)\n"
            "• <code>ДД.ММ.РРРР</code> (наприклад, <code>25.10.2026</code>)"
        )
        return

    aid = f"manual_{uuid.uuid4().hex[:6]}"
    await add_assignment_db(aid, course_name, title, due_date, desc)
    await safe_answer(
        message,
        f"✅ Дедлайн успішно додано!\n🆔 ID: <code>{aid}</code>\n📚 <b>{course_name}</b> — {title}\n⏳ <b>Дедлайн:</b> <code>{due_date}</code>"
    )


@router.message(Command("deldeadline"))
async def cmd_del_deadline(message: Message):
    from database import delete_assignment_db

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_answer(message, "ℹ️ Вкажіть ID дедлайну для видалення:\n<code>/deldeadline &lt;id&gt;</code>")
        return

    aid = escape_html_text(parts[1].strip()[:50])
    await delete_assignment_db(aid)
    await safe_answer(message, f"🗑 Дедлайн <code>{aid}</code> видалено або позначено як виконаний!")


@router.message(Command("evening"))
async def cmd_evening(message: Message):
    await cmd_summary(message)


@router.message(Command("summary"))
async def cmd_summary(message: Message):
    from formatters import format_daily_summary
    from database import get_active_assignments_db, get_today_announcements_db
    from kpi_api import get_schedule_for_date

    try:
        today_date = datetime.now(KYIV_TZ).strftime("%Y-%m-%d")
        lessons = await get_schedule_for_date(today_date)
        assignments = await get_active_assignments_db()
        announcements = await get_today_announcements_db()

        text = format_daily_summary(lessons, assignments, announcements)
        await safe_answer(message, text)
    except Exception as e:
        logger.error(f"Помилка в cmd_summary: {e}", exc_info=True)
        await safe_answer(message, f"⚠️ Не вдалося сформувати підсумок дня: {escape_html_text(str(e))}")

@router.message(Command("status"))
async def cmd_status(message: Message):
    """Показати діагностику підписки цього чату та статус бота."""
    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)

    from database import get_subscribed_chats_db
    targets = await get_subscribed_chats_db()
    is_subscribed = any(
        t["chat_id"] == chat_id and (thread_id is None or t.get("thread_id") == thread_id)
        for t in targets
    )

    now_kyiv = datetime.now(KYIV_TZ).strftime("%Y-%m-%d %H:%M:%S")

    status_icon = "🟢 ПІДПИСАНО" if is_subscribed else "🔴 НЕ ПІДПИСАНО"
    advice = (
        "✅ <b>Цей чат отримує всі сповіщення:</b> ранковий розклад о 08:00, нагадування перед парами, дедлайни Classroom та конспекти лекцій."
        if is_subscribed
        else "⚠️ <b>УВАГА: Цей чат НЕ підписано на сповіщення!</b>\nНадішліть команду <code>/subscribe</code> або <code>/start</code> прямо в цей чат/топік, щоб увімкнути сповіщення."
    )

    text = (
        f"📊 <b>Діагностика бота:</b>\n\n"
        f"• <b>Статус цього чату:</b> {status_icon}\n"
        f"• <b>ID чату:</b> <code>{chat_id}</code>\n"
        f"• <b>ID топіку:</b> <code>{thread_id or 'Загальний'}</code>\n"
        f"• <b>Час сервера (Київ):</b> <code>{now_kyiv}</code>\n"
        f"• <b>Усього підписаних чатів у базі:</b> {len(targets)}\n\n"
        f"{advice}\n\n"
        f"💡 Щоб протестувати надсилання прямо зараз, відправте <code>/test_alert</code>"
    )
    await safe_answer(message, text)


@router.message(Command("test_alert"))
async def cmd_test_alert(message: Message):
    """Надіслати тестове нагадування в цей чат/топік прямо зараз."""
    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)

    from database import add_subscription_db
    await add_subscription_db(chat_id, thread_id)

    dummy_lesson = {
        "name": "Тестова пара (ІП-66)",
        "type": "Практика",
        "time": "12:20",
        "lecturer": "Тестовий викладач",
        "tag": "prac",
        "location": "Zoom"
    }
    from formatters import format_lesson_alert
    text, kb = format_lesson_alert(dummy_lesson, minutes_left=5)
    await safe_answer(message, f"🧪 <b>Тестове нагадування:</b>\n\n{text}", reply_markup=kb)


# ==========================================
# ЖИВА ЧЕРГА НА ЗАХИСТ ЛАБОРАТОРНИХ (/queue)
# ==========================================

def format_queue_view(subject: str, queue_items: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування тексту черги та інлайн-кнопок управління."""
    clean_subj = subject or "Загальна"
    header = f"📋 <b>Жива черга на захист: {clean_subj}</b>\n"
    if not queue_items:
        text = f"{header}\n<i>Черга наразі порожня. Будьте першим!</i>"
    else:
        text = f"{header}\n"
        for idx, item in enumerate(queue_items, start=1):
            user_display = item["user_name"]
            if item.get("username"):
                user_display += f" (@{item['username']})"
            lab_info = f" — <i>{item['lab_number']}</i>" if item.get("lab_number") else ""
            badge = "🥇 " if idx == 1 else f"{idx}. "
            text += f"{badge}<b>{user_display}</b>{lab_info}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✋ Зайняти чергу", callback_data=f"q:join:{clean_subj}"),
                InlineKeyboardButton(text="🚪 Вийти", callback_data=f"q:leave:{clean_subj}"),
            ],
            [
                InlineKeyboardButton(text="➡️ Наступний", callback_data=f"q:next:{clean_subj}"),
                InlineKeyboardButton(text="🔄 Оновити", callback_data=f"q:refresh:{clean_subj}"),
            ],
            [
                InlineKeyboardButton(text="🧹 Очистити чергу", callback_data=f"q:clear:{clean_subj}"),
            ]
        ]
    )
    return text, kb


@router.message(Command("queue"))
async def cmd_queue(message: Message):
    from database import get_active_queue_db
    parts = message.text.split(maxsplit=1)
    subject = parts[1].strip() if len(parts) > 1 else "Загальна"
    chat_id = message.chat.id
    items = await get_active_queue_db(chat_id, subject)
    text, kb = format_queue_view(subject, items)
    await safe_answer(message, text, reply_markup=kb)


@router.message(Command("join_queue"))
async def cmd_join_queue(message: Message):
    from database import join_queue_db, get_active_queue_db
    raw = message.text.replace("/join_queue", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")] if "|" in raw else raw.split(maxsplit=1)
    subject = parts[0] if len(parts) > 0 and parts[0] else "Загальна"
    lab_number = parts[1] if len(parts) > 1 else ""

    user = message.from_user
    user_id = user.id
    user_name = user.full_name
    username = user.username

    ok, msg, pos = await join_queue_db(message.chat.id, subject, user_id, user_name, username, lab_number)
    items = await get_active_queue_db(message.chat.id, subject)
    text, kb = format_queue_view(subject, items)
    await safe_answer(message, f"{'✅' if ok else 'ℹ️'} {msg}\n\n" + text, reply_markup=kb)


@router.message(Command("leave_queue"))
async def cmd_leave_queue(message: Message):
    from database import leave_queue_db, get_active_queue_db
    parts = message.text.split(maxsplit=1)
    subject = parts[1].strip() if len(parts) > 1 else "Загальна"
    ok = await leave_queue_db(message.chat.id, subject, message.from_user.id)
    msg = "✅ Ви вийшли з черги." if ok else "ℹ️ Вас не було в черзі."
    items = await get_active_queue_db(message.chat.id, subject)
    text, kb = format_queue_view(subject, items)
    await safe_answer(message, f"{msg}\n\n" + text, reply_markup=kb)


@router.message(Command("next_in_queue"))
async def cmd_next_in_queue(message: Message):
    from database import next_in_queue_db, get_active_queue_db
    parts = message.text.split(maxsplit=1)
    subject = parts[1].strip() if len(parts) > 1 else "Загальна"
    student = await next_in_queue_db(message.chat.id, subject)
    if not student:
        await safe_answer(message, f"ℹ️ Черга з предмету <b>{subject}</b> порожня!")
        return

    name = student["user_name"]
    un = f" (@{student['username']})" if student.get("username") else ""
    items = await get_active_queue_db(message.chat.id, subject)
    text, kb = format_queue_view(subject, items)
    await safe_answer(message, f"🎯 <b>Зараз захищає:</b> {name}{un}\n\n" + text, reply_markup=kb)


@router.message(Command("clear_queue"))
async def cmd_clear_queue(message: Message):
    from database import clear_queue_db
    parts = message.text.split(maxsplit=1)
    subject = parts[1].strip() if len(parts) > 1 else "Загальна"
    count = await clear_queue_db(message.chat.id, subject)
    await safe_answer(message, f"🧹 Чергу з предмету <b>{subject}</b> очищено! (Видалено записів: {count})")


@router.callback_query(F.data.startswith("q:"))
async def cb_queue_actions(callback: CallbackQuery):
    from database import join_queue_db, leave_queue_db, next_in_queue_db, clear_queue_db, get_active_queue_db
    data = callback.data.split(":")
    if len(data) < 3:
        await callback.answer()
        return

    action = data[1]
    subject = data[2]
    chat_id = callback.message.chat.id
    user = callback.from_user

    if action == "join":
        ok, msg, _ = await join_queue_db(chat_id, subject, user.id, user.full_name, user.username)
        await callback.answer(msg, show_alert=not ok)
    elif action == "leave":
        ok = await leave_queue_db(chat_id, subject, user.id)
        await callback.answer("Ви вийшли з черги" if ok else "Вас не було в черзі", show_alert=False)
    elif action == "next":
        next_st = await next_in_queue_db(chat_id, subject)
        if next_st:
            await callback.answer(f"Наступний: {next_st['user_name']}", show_alert=False)
        else:
            await callback.answer("Черга порожня!", show_alert=True)
    elif action == "clear":
        await clear_queue_db(chat_id, subject)
        await callback.answer("Чергу очищено!", show_alert=False)
    elif action == "refresh":
        await callback.answer("Чергу оновлено", show_alert=False)

    # Оновлюємо інтерфейс черги
    items = await get_active_queue_db(chat_id, subject)
    text, kb = format_queue_view(subject, items)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass


# ==========================================
# СКАСУВАННЯ ПАР СТАРОСТОЮ (/cancel_pair)
# ==========================================

@router.message(Command("cancel_pair"))
async def cmd_cancel_pair(message: Message):
    from database import cancel_pair_db, get_cancelled_pairs_for_date_db
    raw = message.text.replace("/cancel_pair", "", 1).strip()
    if not raw:
        await safe_answer(
            message,
            "ℹ️ <b>Формат скасування пари:</b>\n"
            "<code>/cancel_pair &lt;номер_пари: 1-6&gt; [причина]</code>\n"
            "<code>/cancel_pair &lt;номер_пари&gt; &lt;РРРР-ММ-ДД&gt; | [причина]</code>\n\n"
            "Приклади:\n"
            "• <code>/cancel_pair 2 Хворіє викладач</code> (скасувати 2-гу пару на сьогодні)\n"
            "• <code>/cancel_pair 1 2026-10-25 | Пари не буде</code>"
        )
        return

    tokens = raw.split(maxsplit=2)
    if not tokens[0].isdigit():
        await safe_answer(message, "❌ Першим параметром має бути номер пари (1-6)!")
        return

    pair_num = int(tokens[0])
    target_date = datetime.now(KYIV_TZ).strftime("%Y-%m-%d")
    reason = "Скасовано викладачем/старостою"

    if len(tokens) > 1:
        # Перевірка чи другий токен є датою
        from handlers import normalize_due_date
        norm_date = normalize_due_date(tokens[1])
        if norm_date:
            target_date = norm_date.split()[0]
            reason = tokens[2].strip(" |") if len(tokens) > 2 else reason
        else:
            reason = " ".join(tokens[1:]).strip(" |")

    who = message.from_user.full_name
    await cancel_pair_db(target_date, pair_num, subject="", reason=reason, cancelled_by=who)

    await safe_answer(
        message,
        f"🚫 <b>Пару №{pair_num} успішно скасовано!</b>\n"
        f"📅 <b>Дата:</b> <code>{target_date}</code>\n"
        f"📝 <b>Причина:</b> {escape_html_text(reason)}\n"
        f"👤 <b>Зафіксував:</b> {escape_html_text(who)}\n\n"
        f"<i>💡 Нагадування перед цією парою вимкнено, а в розкладі вона відображатиметься як перекреслена.</i>"
    )


@router.message(Command("uncancel_pair"))
async def cmd_uncancel_pair(message: Message):
    from database import uncancel_pair_db
    raw = message.text.replace("/uncancel_pair", "", 1).strip().split()
    if not raw or not raw[0].isdigit():
        await safe_answer(message, "ℹ️ Вкажіть номер пари для відновлення:\n<code>/uncancel_pair &lt;номер_пари&gt; [РРРР-ММ-ДД]</code>")
        return

    pair_num = int(raw[0])
    target_date = raw[1] if len(raw) > 1 else datetime.now(KYIV_TZ).strftime("%Y-%m-%d")

    ok = await uncancel_pair_db(target_date, pair_num)
    if ok:
        await safe_answer(message, f"✅ Скасування пари №{pair_num} на <code>{target_date}</code> знято! Вона знову активна в розкладі.")
    else:
        await safe_answer(message, f"ℹ️ Пара №{pair_num} на <code>{target_date}</code> не була скасована.")


@router.message(Command("cancelled_pairs"))
async def cmd_cancelled_pairs(message: Message):
    from database import get_cancelled_pairs_for_date_db
    parts = message.text.split(maxsplit=1)
    target_date = parts[1].strip() if len(parts) > 1 else datetime.now(KYIV_TZ).strftime("%Y-%m-%d")

    canc_map = await get_cancelled_pairs_for_date_db(target_date)
    if not canc_map:
        await safe_answer(message, f"🏖 На дату <code>{target_date}</code> немає скасованих пар.")
        return

    lines = [f"🚫 <b>Скасовані пари на {target_date}:</b>\n"]
    for p_num in sorted(canc_map.keys()):
        info = canc_map[p_num]
        lines.append(f"• <b>Пара №{p_num}:</b> <i>{escape_html_text(info['reason'])}</i> (від {escape_html_text(info['cancelled_by'])})")

    await safe_answer(message, "\n".join(lines))

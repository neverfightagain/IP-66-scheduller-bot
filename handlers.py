import logging
import uuid
from datetime import datetime, timedelta
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
from formatters import format_morning_digest, clean_markdown

logger = logging.getLogger(__name__)

router = Router()


def strip_markdown(text: str) -> str:
    """Видаляє символи Markdown для безпечної відправки повідомлення звичайним текстом."""
    return (
        text.replace("**", "")
        .replace("*", "")
        .replace("`", "")
        .replace("_", "")
        .replace("~", "")
    )


async def safe_answer(message: Message, text: str, reply_markup=None, disable_web_page_preview: bool = False):
    """Безпечна відправка повідомлення з резервним plain-text варіантом при збоях Markdown-парсера."""
    try:
        return await message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except TelegramBadRequest as e:
        logger.warning(f"Помилка парсингу Markdown: {e}. Відправляю простим текстом.")
        plain_text = strip_markdown(text)
        return await message.answer(
            plain_text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
    except Exception as e:
        logger.error(f"Непередбачена помилка в safe_answer: {e}")
        plain_text = strip_markdown(text)
        return await message.answer(
            plain_text,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )


async def safe_edit_text(callback: CallbackQuery, text: str, reply_markup=None):
    """Безпечне редагування тексту повідомлення з резервним plain-text варіантом."""
    try:
        return await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as e:
        logger.warning(f"Помилка парсингу Markdown при редагуванні: {e}. Редагую простим текстом.")
        plain_text = strip_markdown(text)
        try:
            return await callback.message.edit_text(plain_text, reply_markup=reply_markup)
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
    topic_desc = f" (топік ID: `{thread_id}`)" if thread_id else ""
    chat_desc = f"цього групового чату{topic_desc}" if is_group else "вас"
    id_info = f"\n🆔 **ID чату:** `{chat_id}`" if is_group else ""
    if thread_id:
        id_info += f"\n📌 **ID топіку:** `{thread_id}`"

    sub_status = (
        f"✅ Сповіщення активовано для {chat_desc}!{id_info}"
        if is_new
        else f"ℹ️ {chat_desc.capitalize()} вже підписано на сповіщення.{id_info}"
    )

    text = (
        "👋 **Привіт! Я розумний розклад-асистент ІП-66.**\n\n"
        "🤖 **Що я роблю на автоматі:**\n"
        "• ☀️ **08:00** — Ранковий розклад пар з посиланнями на заняття\n"
        "• 🔔 **За 20 та 5 хв** — Нагадування перед кожною парою (з автовидаленням через 20 хв)\n"
        "• 📚 **Google Classroom** — Миттєві сповіщення про нові завдання та дедлайни\n"
        "• 🎬 **YouTube `@ip-66_studio`** — Автоматичний конспект лекцій через Gemini AI\n"
        "• 🌙 **21:00** (та 10:00 у вихідні) — Розумний підсумок дня `/summary`\n\n"
        f"{sub_status}\n\n"
        "📋 **Повний список команд:**\n\n"
        "📅 **Розклад пар:**\n"
        "/today — Розклад пар на сьогодні з лінками на Zoom/Meet\n"
        "/tomorrow — Розклад пар на завтра\n"
        "/week — Номер поточного тижня (чисельник/знаменник) та київський час\n"
        "/links — Збережені посилання на конференції та лекції\n"
        "/setlink — Додати/оновити посилання на пару (`/setlink Предмет | URL | Коментар`)\n"
        "/dellink — Видалити посилання на предмет (`/dellink Предмет`)\n\n"
        "📊 **Дедлайни та Classroom:**\n"
        "/deadlines — Радар усіх дедлайнів (палаючі, на тиждень, без дедлайну)\n"
        "/summary — Підсумок дня, що задали та палаючі дедлайни\n"
        "/sync — Миттєва ручна синхронізація з Google Classroom\n"
        "/adddeadline — Додати завдання вручну (`/adddeadline Предмет | Назва | Дедлайн | Опис`)\n"
        "/deldeadline — Видалити завдання за ID (`/deldeadline <id>`)\n\n"
        "⚙️ **Керування сповіщеннями:**\n"
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
            f"✅ **Сповіщення успішно налаштовано для цього топіку!**\n\n"
            f"🆔 **ID чату:** `{chat_id}`\n"
            f"📌 **ID топіку:** `{thread_id}`\n\n"
            f"🎯 Усі ранкові розклади, нагадування перед парами, дедлайни з Classroom та конспекти лекцій "
            f"надсилатимуться **виключно в цю гілку**."
        )
    else:
        await safe_answer(
            message,
            f"✅ **Сповіщення успішно активовано для цього чату!**\n"
            f"🆔 **ID чату:** `{chat_id}`"
        )


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    chat_id = message.chat.id
    thread_id = getattr(message, "message_thread_id", None)

    from database import remove_subscription_db
    await remove_subscription_db(chat_id, thread_id)
    remove_subscribed_chat(chat_id, thread_id)

    if thread_id:
        await safe_answer(message, f"🛑 Сповіщення для топіку `{thread_id}` вимкнено.")
    else:
        await safe_answer(message, "🛑 Сповіщення для цього чату вимкнено.")


@router.message(Command("today"))
async def cmd_today(message: Message):
    today = datetime.now(KYIV_TZ).date()
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, today)
        is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

        from scheduler import calculate_lessons_end_datetime
        from database import add_scheduled_deletion_db

        now_dt = datetime.now(KYIV_TZ)
        end_dt = calculate_lessons_end_datetime(lessons, today)
        delete_time_str = end_dt.strftime("%H:%M")
        show_delete = is_group and lessons and end_dt > now_dt

        text, kb = format_morning_digest(
            week,
            day_name,
            lessons,
            auto_delete_time=delete_time_str if show_delete else None
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
        await safe_answer(message, f"⚠️ Не вдалося отримати розклад: {clean_markdown(str(e))}")



@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message):
    tomorrow = datetime.now(KYIV_TZ).date() + timedelta(days=1)
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, tomorrow)
        text, kb = format_morning_digest(week, day_name, lessons)
        text = text.replace("на сьогодні", "на завтра")
        await safe_answer(message, text, reply_markup=kb)
    except Exception as e:
        await safe_answer(message, f"⚠️ Не вдалося отримати розклад: {clean_markdown(str(e))}")


@router.message(Command("week"))
async def cmd_week(message: Message):
    try:
        info = await get_current_time_info()
        week = info.get("currentWeek", 1)
        now = datetime.now(KYIV_TZ)
        time_str = now.strftime("%H:%M:%S")
        await safe_answer(
            message,
            f"🕒 **Київський час:** `{time_str}`\n"
            f"📅 **Зараз триває:** `{week}-й тиждень` ({'Чисельник' if week == 1 else 'Знаменник'})",
        )
    except Exception as e:
        await safe_answer(message, f"⚠️ Не вдалося визначити тиждень: {clean_markdown(str(e))}")


@router.message(Command("links"))
async def cmd_links(message: Message):
    links = load_links()
    if not links:
        await safe_answer(message, "📂 Список посилань порожній.")
        return

    lines = ["🔗 **Збережені посилання на заняття:**\n"]
    has_any = False
    for title, data in links.items():
        url = data.get("url", "").strip()
        comment = data.get("comment", "").strip()
        if url:
            has_any = True
            c_title = clean_markdown(str(title))
            c_comment = clean_markdown(str(comment))
            comment_str = f" _({c_comment})_" if c_comment else ""
            lines.append(f"• **{c_title}**:\n  [Приєднатися]({url}){comment_str}")

    if not has_any:
        await safe_answer(message, "ℹ️ Посилання ще не додані в `links.json`.")
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
            "ℹ️ **Формат додавання/оновлення посилання на пару:**\n"
            "`/setlink Предмет (Тип) | URL | Коментар (необов'язково)`\n\n"
            "Приклад:\n"
            "`/setlink Філософія (Лек) | https://us02web.zoom.us/j/... | Zoom`"
        )
        return

    raw_key = parts[0][:100].strip()
    url = parts[1].strip()
    comment = parts[2][:100].strip() if len(parts) > 2 else ""

    if not (url.startswith("http://") or url.startswith("https://")):
        await safe_answer(message, "❌ Посилання має починатися з `https://` або `http://`!")
        return

    set_course_link(raw_key, url, comment)
    c_key = clean_markdown(raw_key)
    comment_str = f" _({clean_markdown(comment)})_" if comment else ""
    await safe_answer(
        message,
        f"✅ Посилання для **{c_key}** успішно збережено!\n"
        f"🔗 [Перейти до заняття]({url}){comment_str}"
    )


@router.message(Command("dellink"))
async def cmd_del_link(message: Message):
    from links_manager import delete_course_link
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_answer(message, "ℹ️ Вкажіть назву предмета для видалення:\n`/dellink Назва`")
        return

    key = parts[1].strip()
    if delete_course_link(key):
        await safe_answer(message, f"🗑 Посилання для **{clean_markdown(key)}** видалено!")
    else:
        await safe_answer(message, f"⚠️ Посилання для «{clean_markdown(key)}» не знайдено.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📖 **Повна довідка по боту ІП-66:**\n\n"
        "📅 **Розклад пар та посилання:**\n"
        "• /today — Пари на сьогодні з посиланнями на Zoom/Teams/Meet\n"
        "• /tomorrow — Пари на завтра\n"
        "• /week — Номер навчального тижня (1 чи 2) та точний київський час\n"
        "• /links — База збережених посилань на дистанційні заняття\n"
        "• /setlink — Додати або оновити посилання на пару (`/setlink Предмет | URL | Коментар`)\n"
        "• /dellink — Видалити посилання на предмет (`/dellink Предмет`)\n\n"
        "📊 **Завдання, Classroom та AI:**\n"
        "• /deadlines — Радар активних завдань з Google Classroom із розрахунком часу, що залишився\n"
        "• /summary (або /evening) — Розумний підсумок дня (пари, що задали, анонси та палаючі дедлайни)\n"
        "• /sync — Примусова синхронізація завдань із Google Classroom\n"
        "• /adddeadline — Додати власне завдання або дедлайн вручну\n"
        "  _Формат:_ `/adddeadline Предмет | Назва | РРРР-ММ-ДД HH:MM | Опис`\n"
        "• /deldeadline — Видалити завдання за ID (`/deldeadline <id>`)\n\n"
        "🔔 **Автоматичні функції бота:**\n"
        "• ☀️ **08:00 (Пн-Сб)** — Ранковий дайджест пар на день\n"
        "• ⏰ **За 20 хв і 5 хв до пари** — Нагадування з прямим лінком (автовидалення через 20 хв)\n"
        "• 📚 **Кожні 15 хв** — Перевірка нових завдань у Google Classroom\n"
        "• 🎬 **Кожні 30 хв** — Моніторинг нових лекцій на YouTube `@ip-66_studio` та Gemini AI конспект\n"
        "• 🌙 **21:00** — Вечірній підсумок дня (о 10:00 у вихідні дні)\n\n"
        "⚙️ **Керування чатом:**\n"
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
        err_msg = clean_markdown(str(res.get("error", "Помилка")))
        text += f"\n\n⚠️ _Синхронізація не вдалася: {err_msg}_"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Оновити з Google Classroom", callback_data="refresh_deadlines")]
        ]
    )
    await safe_edit_text(callback, text, reply_markup=kb)


@router.message(Command("sync"))
async def cmd_sync(message: Message, bot: Bot):
    status_msg = await safe_answer(message, "🔄 Запускаю синхронізацію з Google Classroom...")
    from classroom_sync import sync_classroom_tasks
    from database import get_active_assignments_db

    res = await sync_classroom_tasks(bot=bot)
    if not res.get("success"):
        err = clean_markdown(str(res.get("error", "Невідома помилка")))
        err_text = (
            f"❌ **Помилка синхронізації Google Classroom:**\n`{err}`\n\n"
            f"ℹ️ **Що перевірити:**\n"
            f"1. Чи додана змінна `GOOGLE_TOKEN_JSON` в налаштуваннях Render (розділ **Environment**).\n"
            f"2. Чи натиснута кнопка **Save Changes** на Render."
        )
        if status_msg:
            try:
                await status_msg.edit_text(err_text, parse_mode="Markdown")
            except Exception:
                await safe_answer(message, err_text)
        else:
            await safe_answer(message, err_text)
        return

    active = await get_active_assignments_db()
    courses_cnt = res.get("courses_count", 0)
    new_cnt = len(res.get("new_items", []))
    total_cnt = len(active)

    success_text = (
        f"✅ **Google Classroom успішно синхронізовано!**\n\n"
        f"📚 Знайдено активних курсів: **{courses_cnt}**\n"
        f"🆕 Нових завдань завантажено: **{new_cnt}**\n"
        f"📋 Всього активних завдань у базі: **{total_cnt}**\n\n"
        f"Введіть /deadlines, щоб переглянути оновлений радар завдань! 🎯"
    )
    if status_msg:
        try:
            await status_msg.edit_text(success_text, parse_mode="Markdown")
        except Exception:
            await safe_answer(message, success_text)
    else:
        await safe_answer(message, success_text)


@router.message(Command("adddeadline"))
async def cmd_add_deadline(message: Message):
    from database import add_assignment_db

    raw_text = message.text.replace("/adddeadline", "", 1).strip()
    parts = [p.strip() for p in raw_text.split("|")]
    if len(parts) < 3:
        await safe_answer(
            message,
            "ℹ️ **Формат додавання дедлайну:**\n"
            "`/adddeadline Предмет | Назва завдання | РРРР-ММ-ДД HH:MM | Опис (необов'язково)`\n\n"
            "Приклад:\n"
            "`/adddeadline Основи програмування | Лабораторна №1 | 2026-10-15 23:59 | Здати в репозиторій`",
        )
        return

    course_name = clean_markdown(parts[0][:60])
    title = clean_markdown(parts[1][:150])
    raw_date = parts[2][:30].strip()
    desc = clean_markdown(parts[3][:300]) if len(parts) > 3 else ""

    due_date = normalize_due_date(raw_date)
    if not due_date:
        await safe_answer(
            message,
            "❌ **Невірний формат дати!**\n\n"
            "Вкажіть дату в одному з форматів:\n"
            "• `РРРР-ММ-ДД HH:MM` (наприклад, `2026-10-25 23:59`)\n"
            "• `РРРР-ММ-ДД` (наприклад, `2026-10-25`)\n"
            "• `ДД.ММ.РРРР HH:MM` (наприклад, `25.10.2026 23:59`)\n"
            "• `ДД.ММ.РРРР` (наприклад, `25.10.2026`)"
        )
        return

    aid = f"manual_{uuid.uuid4().hex[:6]}"
    await add_assignment_db(aid, course_name, title, due_date, desc)
    await safe_answer(
        message,
        f"✅ Дедлайн успішно додано!\n🆔 ID: `{aid}`\n📚 **{course_name}** — {title}\n⏳ **Дедлайн:** `{due_date}`"
    )


@router.message(Command("deldeadline"))
async def cmd_del_deadline(message: Message):
    from database import delete_assignment_db

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await safe_answer(message, "ℹ️ Вкажіть ID дедлайну для видалення:\n`/deldeadline <id>`")
        return

    aid = clean_markdown(parts[1].strip()[:50])
    await delete_assignment_db(aid)
    await safe_answer(message, f"🗑 Дедлайн `{aid}` видалено або позначено як виконаний!")


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
        await safe_answer(message, f"⚠️ Не вдалося сформувати підсумок дня: {clean_markdown(str(e))}")

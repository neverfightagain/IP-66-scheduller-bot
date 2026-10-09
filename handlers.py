from datetime import datetime, timedelta
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatType

from config import (
    KYIV_TZ,
    KPI_GROUP_ID,
    add_subscribed_chat,
    remove_subscribed_chat,
    get_subscribed_chats,
)
from kpi_api import get_lessons_for_date, get_current_time_info
from links_manager import load_links
from formatters import format_morning_digest

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    chat_type = message.chat.type

    is_new = add_subscribed_chat(chat_id)

    chat_desc = "цього групового чату" if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP) else "вас"
    sub_status = f"✅ Сповіщення активовано для {chat_desc}!" if is_new else f"ℹ️ {chat_desc.capitalize()} вже підписано на сповіщення."

    text = (
        "👋 **Привіт! Я бот розкладу ІП-66.**\n\n"
        "Я надсилаю:\n"
        "☀️ **Розклад** пар о 08:00\n"
        "🔔 **Сповіщення за 5 хвилин** до початку кожної пари із посиланням на Zoom/Meet\n\n"
        f"{sub_status}\n\n"
        "📌 **Корисні команди:**\n"
        "/today — Розклад на сьогодні\n"
        "/tomorrow — Розклад на завтра\n"
        "/week — Який зараз тиждень (1-й чи 2-й)\n"
        "/links — Список усіх збережених посилань на Zoom/Meet\n"
        "/subscribe — Увімкнути сповіщення\n"
        "/unsubscribe — Вимкнути сповіщення\n"
        "/help — Довідка"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    chat_id = message.chat.id
    if add_subscribed_chat(chat_id):
        await message.answer("✅ Чат успішно підписано на автоматичні сповіщення!")
    else:
        await message.answer("ℹ️ Цей чат вже підписаний на сповіщення.")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    chat_id = message.chat.id
    if remove_subscribed_chat(chat_id):
        await message.answer("🛑 Сповіщення для цього чату вимкнено.")
    else:
        await message.answer("ℹ️ Цей чат не був підписаний на сповіщення.")


@router.message(Command("today"))
async def cmd_today(message: Message):
    today = datetime.now(KYIV_TZ).date()
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, today)
        text, kb = format_morning_digest(week, day_name, lessons)
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        await message.answer(f"⚠️ Не вдалося отримати розклад: {e}")


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message):
    tomorrow = datetime.now(KYIV_TZ).date() + timedelta(days=1)
    try:
        week, day_name, lessons = await get_lessons_for_date(KPI_GROUP_ID, tomorrow)
        text, kb = format_morning_digest(week, day_name, lessons)
        # Меняем заголовок на "на завтра"
        text = text.replace("на сьогодні", "на завтра")
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        await message.answer(f"⚠️ Не вдалося отримати розклад: {e}")


@router.message(Command("week"))
async def cmd_week(message: Message):
    try:
        info = await get_current_time_info()
        week = info.get("currentWeek", 1)
        now = datetime.now(KYIV_TZ)
        time_str = now.strftime("%H:%M:%S")
        await message.answer(
            f"🕒 **Київський час:** `{time_str}`\n"
            f"📅 **Зараз триває:** `{week}-й тиждень` ({'Чисельник' if week == 1 else 'Знаменник'})",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"⚠️ Не вдалося визначити тиждень: {e}")


@router.message(Command("links"))
async def cmd_links(message: Message):
    links = load_links()
    if not links:
        await message.answer("📂 Список посилань порожній.")
        return

    lines = ["🔗 **Збережені посилання на заняття:**\n"]
    has_any = False
    for title, data in links.items():
        url = data.get("url", "").strip()
        comment = data.get("comment", "").strip()
        if url:
            has_any = True
            comment_str = f" _({comment})_" if comment else ""
            lines.append(f"• **{title}**:\n  [Приєднатися]({url}){comment_str}")

    if not has_any:
        await message.answer("ℹ️ Посилання ще не додані в `links.json`.")
        return

    await message.answer("\n\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "**Команди бота:**\n\n"
        "/today — Розклад на сьогодні\n"
        "/tomorrow — Розклад на завтра\n"
        "/week — Поточний тиждень та київський час\n"
        "/links — Список посилань на Zoom/Meet\n"
        "/subscribe — Увімкнути сповіщення в цьому чаті\n"
        "/unsubscribe — Вимкнути сповіщення\n"
        "/help — Ця довідка"
    )
    await message.answer(text, parse_mode="Markdown")

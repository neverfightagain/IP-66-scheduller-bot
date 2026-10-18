from datetime import datetime
from config import KYIV_TZ
from formatters import clean_course_name, escape_html_text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_urgent_assignments_for_ping(assignments: list[dict], now_dt: datetime = None) -> list[dict]:
    """
    Знаходить завдання, дедлайн яких настане протягом наступних 24 годин.
    """
    if now_dt is None:
        now_dt = datetime.now(KYIV_TZ)

    urgent = []
    for a in assignments:
        due_str = a.get("due_date", "")
        if not due_str:
            continue
        try:
            if len(due_str) == 10:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KYIV_TZ)
            else:
                due_dt = datetime.strptime(due_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
        except Exception:
            continue

        diff_seconds = (due_dt - now_dt).total_seconds()
        diff_hours = diff_seconds / 3600.0

        # Якщо дедлайн між 0 та 24 годинами
        if 0 < diff_hours <= 24.5:
            a_copy = dict(a)
            a_copy["hours_left"] = max(1, int(diff_hours))
            a_copy["due_dt"] = due_dt
            urgent.append(a_copy)

    return urgent


def format_urgent_ping_message(assignment: dict, hours_left: int) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування публічного пінгу-нагадування про палаючий дедлайн."""
    sname = clean_course_name(assignment.get("course_id") or assignment.get("course_name") or "Предмет")
    title = escape_html_text(assignment.get("title", "Завдання"))
    due_str = assignment.get("due_date", "")
    aid = assignment.get("id", "")

    time_badge = "🔥 <b>МЕНШЕ 6 ГОДИН!</b>" if hours_left <= 6 else f"⏳ <b>ЗАЛИШИЛОСЬ {hours_left} ГОД!</b>"

    lines = [
        f"🚨 <b>УВАГА, БОРЖНИКИ! ДЕДЛАЙН НАБЛИЖАЄТЬСЯ!</b>\n",
        f"{time_badge}",
        f"📚 <b>Предмет:</b> <b>{sname}</b>",
        f"🎯 <b>Завдання:</b> {title}",
        f"⏰ <b>Дедлайн:</b> <code>{due_str}</code>\n",
        "⚠️ <i>Хто ще не здав роботу в Google Classroom — здавайте негайно, щоб уникнути штрафних балів або неатестації!</i>"
    ]

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Я вже здав!", callback_data=f"ping_done:{aid}"),
                InlineKeyboardButton(text="📋 Деталі завдання", callback_data=f"ping_info:{aid}")
            ]
        ]
    )
    return "\n".join(lines), kb

from datetime import datetime
from config import KYIV_TZ
from links_manager import get_lesson_link_info
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def format_morning_digest(week: int, day_name: str, lessons: list[dict]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not lessons:
        return f"🏖 **Розклад на сьогодні ({day_name}, {week}-й тиждень):**\n\nСьогодні пар немає!", None

    lines = [
        f"📅 **Розклад на сьогодні ({day_name}, {week}-й тиждень):**\n"
    ]

    for idx, l in enumerate(lessons, 1):
        link_info = get_lesson_link_info(l["name"], l["type"])
        url = link_info.get("url", "").strip()
        comment = link_info.get("comment", "").strip()

        link_str = ""
        if url:
            link_str = f"\n   🔗 [Zoom / Meet]({url})"
            if comment:
                link_str += f" _({comment})_"
        elif comment:
            link_str = f"\n   ℹ️ _{comment}_"

        lines.append(
            f"**{idx}.** `{l['time']}` — **{l['name']}** ({l['type']})\n"
            f"   👤 {l['lecturer']}{link_str}"
        )

    return "\n\n".join(lines), None


def format_lesson_alert(lesson: dict, minutes_left: int = 5) -> tuple[str, InlineKeyboardMarkup | None]:

    now = datetime.now(KYIV_TZ)
    current_time_str = now.strftime("%H:%M")

    link_info = get_lesson_link_info(lesson["name"], lesson["type"])
    url = link_info.get("url", "").strip()
    comment = link_info.get("comment", "").strip()

    if minutes_left >= 15:
        title = f"⏳ **Нагадування: пара через {minutes_left} хвилин!**"
    else:
        title = f"🔔 **Увага! Пара починається через {minutes_left} хвилин!**"

    text_parts = [
        f"{title}\n",
        f"⏰ **Поточний час:** `{current_time_str}`",
        f"⏳ **Початок:** `{lesson['time']}` (через {minutes_left} хв)\n",
        f"📖 **Предмет:** **{lesson['name']}**",
        f"🏷 **Тип:** {lesson['type']}",
        f"👤 **Викладач:** {lesson['lecturer']}",
    ]

    keyboard = None
    if url:
        text_parts.append(f"\n🔗 **Посилання:** [Перейти до заняття]({url})")
        if comment:
            text_parts.append(f"📝 **Примітка:** {comment}")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Приєднатися до заняття", url=url)]
            ]
        )
    elif comment:
        text_parts.append(f"\nℹ️ **Посилання:** _{comment}_")

    return "\n".join(text_parts), keyboard


def format_lecture_summary(summary: dict, video_title: str, video_url: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Форматирование карточки конспекта лекции для Telegram."""
    subject = summary.get("subject_detected") or "Пара"
    topic = summary.get("topic") or video_title

    lines = [
        "🎬 **Новий конспект лекції з YouTube!**\n",
        f"📚 **Предмет:** **{subject}**",
        f"🎯 **Тема:** {topic}\n",
    ]

    points = summary.get("summary_points", [])
    if points:
        lines.append("📌 **Головні тези з заняття:**")
        for pt in points:
            lines.append(f"• {pt}")
        lines.append("")

    announcements = summary.get("teacher_announcements", [])
    if announcements:
        lines.append("📢 **Оголошення викладача:**")
        for ann in announcements:
            lines.append(f"• {ann}")
        lines.append("")

    deadlines = summary.get("deadlines_mentioned", [])
    if deadlines:
        lines.append("⏳ **Згадані дедлайни та терміни:**")
        for dl in deadlines:
            title = dl.get("task_title", "Завдання")
            date_str = dl.get("date", "")
            quote = dl.get("exact_quote", "")
            d_line = f"• **{title}**: {date_str}" if date_str else f"• **{title}**"
            if quote:
                d_line += f" _(«{quote}»)_"
            lines.append(d_line)
        lines.append("")

    lines.append(f"🔗 [Переглянути запис на YouTube]({video_url})")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Дивитися запис на YouTube", url=video_url)]
        ]
    )

    return "\n".join(lines), keyboard

from datetime import datetime, timedelta
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


def format_deadlines_radar(assignments: list[dict]) -> str:
    """Форматирование радара дедлайнов на текущую и следующую неделю."""
    if not assignments:
        return "🎉 **На найближчий час дедлайнів немає! Все чисто, відпочивайте!**"

    now = datetime.now(KYIV_TZ)
    today = now.date()
    # Воскресенье текущей недели
    days_to_sunday = 6 - today.weekday()
    this_week_end = today + timedelta(days=days_to_sunday)
    next_week_end = this_week_end + timedelta(days=7)

    this_week = []
    next_week = []
    later = []

    for a in assignments:
        due_str = a.get("due_date", "")
        try:
            if len(due_str) == 10:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KYIV_TZ)
            else:
                due_dt = datetime.strptime(due_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
        except Exception:
            later.append((a, due_str, "📅", "🟢"))
            continue

        due_date = due_dt.date()
        diff = due_dt - now
        total_hours = int(diff.total_seconds() // 3600)
        days_left = diff.days

        if total_hours < 0:
            time_left_str = "⚠️ прострочено!"
            emoji = "🔴"
        elif total_hours < 24:
            time_left_str = f"залишилось {total_hours} год"
            emoji = "🔴"
        elif days_left < 3:
            time_left_str = f"залишилось {days_left} дн"
            emoji = "🟡"
        else:
            time_left_str = f"залишилось {days_left} дн"
            emoji = "🟢"

        item = (a, due_dt.strftime("%d.%m о %H:%M"), time_left_str, emoji)

        if due_date <= this_week_end:
            this_week.append(item)
        elif due_date <= next_week_end:
            next_week.append(item)
        else:
            later.append(item)

    lines = ["📋 **РАДАР ДЕДЛАЙНІВ (ІП-66):**\n"]

    if this_week:
        lines.append("🔥 **ГОРИТЬ НА ЦЬОМУ ТИЖНІ:**")
        for a, due_f, rem, emoji in this_week:
            desc = f"\n   📝 _{a['description']}_" if a.get("description") else ""
            lines.append(f"{emoji} **{a['course_id']}** — {a['title']}\n   ⏳ **Дедлайн:** {due_f} *({rem})*{desc}")
        lines.append("")

    if next_week:
        lines.append("🟡 **НА НАСТУПНИЙ ТИЖДЕНЬ:**")
        for a, due_f, rem, emoji in next_week:
            desc = f"\n   📝 _{a['description']}_" if a.get("description") else ""
            lines.append(f"• **{a['course_id']}** — {a['title']}\n   ⏳ До {due_f} *({rem})*{desc}")
        lines.append("")

    if later:
        lines.append("🟢 **ПІЗНІШЕ:**")
        for a, due_f, rem, emoji in later:
            lines.append(f"• **{a['course_id']}** — {a['title']} (до {due_f})")
        lines.append("")

    return "\n".join(lines).strip()


def format_evening_digest(assignments: list[dict]) -> str:
    """Форматирование вечерней сводки в 21:00."""
    now = datetime.now(KYIV_TZ)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    days_to_sunday = 6 - today.weekday()
    this_week_end = today + timedelta(days=days_to_sunday)

    tomorrow_count = 0
    this_week_count = 0

    for a in assignments:
        due_str = a.get("due_date", "")
        try:
            due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
            if due_date == tomorrow:
                tomorrow_count += 1
            if due_date <= this_week_end:
                this_week_count += 1
        except Exception:
            pass

    lines = [
        "🌙 **Вечірній статус дедлайнів (21:00):**\n",
    ]

    if tomorrow_count > 0:
        lines.append(f"🔴 **Увага! На завтра горить дедлайнів: {tomorrow_count}**")
    else:
        lines.append("✅ На завтра дедлайнів немає, можна спокійно виспатися!")

    if this_week_count > 0:
        lines.append(f"⏳ До кінця цього тижня залишилося здати робіт: **{this_week_count}**.")

    lines.append("\n👉 Повний список і таймери: команда `/deadlines`")
    return "\n".join(lines)

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
    no_deadline_count = 0

    for a in assignments:
        due_str = a.get("due_date", "")
        if not due_str or due_str == "Без дедлайну":
            no_deadline_count += 1
            continue

        try:
            if len(due_str) == 10:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KYIV_TZ)
            else:
                due_dt = datetime.strptime(due_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
        except Exception:
            no_deadline_count += 1
            continue

        due_date = due_dt.date()
        diff = due_dt - now
        total_hours = int(diff.total_seconds() // 3600)
        days_left = diff.days

        # Пропускаємо старі завдання, дедлайн яких був до поточного тижня
        monday_this_week = today - timedelta(days=today.weekday())
        if due_date < monday_this_week:
            continue

        if total_hours < 0:
            time_left_str = "⚠️ прострочено"
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

    if no_deadline_count > 0:
        lines.append(f"📌 _Завдань та практикумів без фіксованого дедлайну:_ **{no_deadline_count}**\n")

    return "\n".join(lines).strip()


def format_daily_summary(lessons: list[dict], assignments: list[dict], announcements: list[dict] = None) -> str:
    """
    Форматирование адаптивной сводки дня (в 21:00 или по команде /summary):
    - В будние дни (когда есть пары):
        1) Пары, которые были сегодня, темы / что задавали / анонсы преподавателя.
        2) Статус дедлайнов: что горит на завтра (красный) и до конца недели.
    - В выходные дни (или когда пар нет):
        1) Отдых / подготовка к новой учебной неделе.
        2) Ближайшие горящие дедлайны на следующую неделю.
    """
    now = datetime.now(KYIV_TZ)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    days_to_sunday = 6 - today.weekday()
    this_week_end = today + timedelta(days=days_to_sunday)
    next_week_end = this_week_end + timedelta(days=7)
    # Если сегодня были пары — показываем рабочий дайджест дня.
    # Если пар не было — показываем сводку выходного/свободного дня с фокусом на дедлайны.
    has_lessons = bool(lessons)
    is_weekend_day = now.weekday() in (5, 6)

    tomorrow_assignments = []
    this_week_assignments = []
    next_week_assignments = []

    for a in assignments:
        due_str = a.get("due_date", "")
        try:
            if len(due_str) == 10:
                due_dt = datetime.strptime(due_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KYIV_TZ)
            else:
                due_dt = datetime.strptime(due_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
        except Exception:
            continue

        due_date = due_dt.date()
        monday_this_week = today - timedelta(days=today.weekday())
        if due_date < monday_this_week:
            continue

        diff = due_dt - now
        total_hours = int(diff.total_seconds() // 3600)
        days_left = diff.days

        time_str = f"залишилось {days_left} дн" if days_left > 0 else (f"залишилось {total_hours} год" if total_hours > 0 else "⚠️ прострочено")
        formatted_due = due_dt.strftime("%d.%m о %H:%M")

        item = (a, formatted_due, time_str)
        if due_date == tomorrow:
            tomorrow_assignments.append(item)
        if due_date <= this_week_end:
            this_week_assignments.append(item)
        elif due_date <= next_week_end:
            next_week_assignments.append(item)

    lines = []
    if not has_lessons:
        if is_weekend_day:
            lines.append("🌴 **ПІДСУМОК ТИЖНЯ ТА ДЕДЛАЙНИ (ІП-66):**\n")
            lines.append("🏖 Сьогодні вихідний, пар не було! Час відпочити та набратися сил перед новим тижнем.\n")
        else:
            date_str = now.strftime("%d.%m.%Y")
            lines.append(f"🌙 **ПІДСУМОК ДНЯ (ІП-66) — {date_str}:**\n")
            lines.append("🏖 Сьогодні пар за розкладом не було.\n")

        upcoming = this_week_assignments if this_week_assignments else next_week_assignments
        if upcoming:
            lines.append("🔥 **Ближчі дедлайни (на наступний тиждень):**")
            for a, due_f, rem in upcoming:
                desc = f" — _{a['description']}_" if a.get("description") else ""
                lines.append(f"• 🟡 **{a['course_id']}** — {a['title']} (до {due_f}, *{rem}*){desc}")
        else:
            lines.append("✅ **Гарячих дедлайнів немає, можна спокійно відпочивати перед новим навчальним тижнем!**")
    else:
        date_str = now.strftime("%d.%m.%Y")
        lines.append(f"🌙 **ПІДСУМОК ДНЯ (ІП-66) — {date_str}:**\n")

        if lessons:
            lines.append("🎓 **Пари, що були сьогодні:**")
            for idx, l in enumerate(lessons, 1):
                lesson_line = f"**{idx}.** `{l['time']}` — **{l['name']}** ({l['type']})"
                lines.append(lesson_line)
                if announcements:
                    for ann in announcements:
                        if ann.get("course_id") and ann["course_id"].lower() in l["name"].lower():
                            lines.append(f"   📢 _{ann['text']}_")
            lines.append("")
        else:
            lines.append("🏖 Сьогодні пар за розкладом не було.\n")

        lines.append("🔥 **Статус дедлайнів:**")
        if tomorrow_assignments:
            lines.append(f"🔴 **Увага! На завтра горить ({len(tomorrow_assignments)}):**")
            for a, due_f, rem in tomorrow_assignments:
                desc = f" — _{a['description']}_" if a.get("description") else ""
                lines.append(f"• **{a['course_id']}** — {a['title']} (до {due_f}){desc}")
        else:
            lines.append("✅ На завтра дедлайнів немає, можна спокійно виспатися!")

        if this_week_assignments:
            count = len(this_week_assignments)
            lines.append(f"⏳ До кінця цього тижня залишилося здати робіт: **{count}**.")

    lines.append("\n👉 Повний список і таймери: команда `/deadlines`")
    return "\n".join(lines).strip()


def format_evening_digest(assignments: list[dict], lessons: list[dict] = None, announcements: list[dict] = None) -> str:
    """Форматирование вечерней сводки в 21:00 (совместимость)."""
    return format_daily_summary(lessons or [], assignments, announcements or [])

import html
import re
from datetime import datetime, timedelta
from config import KYIV_TZ
from links_manager import get_lesson_link_info
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Таблиця заміни базових макросів LaTeX на Unicode
LATEX_REPLACEMENTS = [
    # Greek lowercase & uppercase
    (r'\\alpha', 'α'), (r'\\beta', 'β'), (r'\\gamma', 'γ'), (r'\\delta', 'δ'),
    (r'\\epsilon', 'ε'), (r'\\lambda', 'λ'), (r'\\mu', 'μ'), (r'\\pi', 'π'),
    (r'\\sigma', 'σ'), (r'\\tau', 'τ'), (r'\\phi', 'φ'), (r'\\omega', 'ω'),
    (r'\\Delta', 'Δ'), (r'\\Sigma', 'Σ'), (r'\\Omega', 'Ω'),
    # Sets & Logic
    (r'\\forall', '∀'), (r'\\exists', '∃'), (r'\\in', '∈'), (r'\\notin', '∉'),
    (r'\\subset', '⊂'), (r'\\subseteq', '⊆'), (r'\\cup', '∪'), (r'\\cap', '∩'),
    (r'\\emptyset', '∅'), (r'\\to', '→'), (r'\\rightarrow', '→'),
    (r'\\implies', '⇒'), (r'\\iff', '⇔'), (r'\\neg', '¬'),
    (r'\\mathbb\{R\}', 'ℝ'), (r'\\mathbb\{N\}', 'ℕ'), (r'\\mathbb\{Z\}', 'ℤ'), (r'\\mathbb\{Q\}', 'ℚ'),
    # Relations & Operators
    (r'\\le(q)?\b', '≤'), (r'\\ge(q)?\b', '≥'), (r'\\ne(q)?\b', '≠'),
    (r'\\approx', '≈'), (r'\\pm', '±'), (r'\\times', '×'), (r'\\cdot', '·'),
    (r'\\sum', '∑'), (r'\\prod', '∏'), (r'\\infty', '∞'),
    # Plain text comparison shorthands
    (r'>=', '≥'), (r'<=', '≤'), (r'!=', '≠'),
]

SUPERSCRIPTS = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
    'n': 'ⁿ', 'i': 'ⁱ', 'x': 'ˣ', 'y': 'ʸ'
}

SUBSCRIPTS = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
    'i': 'ᵢ', 'j': 'ⱼ', 'k': 'ₖ', 'n': 'ₙ', 'm': 'ₘ', 'x': 'ₓ', 'y': 'ᵧ'
}


def escape_html_text(text: str | None) -> str:
    """Безпечне екранування тексту для HTML розмітки Telegram."""
    if text is None:
        return ""
    return html.escape(str(text).strip())


def clean_markdown(text: str | None) -> str:
    """Зворотна сумісність: очищення небезпечних спецсимволів."""
    if text is None:
        return ""
    text = str(text)
    return (
        text.replace("*", "")
        .replace("`", "'")
        .replace("_", " ")
        .replace("[", "(")
        .replace("]", ")")
        .strip()
    )


def clean_course_name(course_name: str | None) -> str:
    """Очистити назву дисципліни від номерів груп, років та технічного сміття (наприклад '2026/27 КДМ ІП-6Х' -> 'КДМ')."""
    if not course_name:
        return "Предмет"
    name = str(course_name).strip()
    # 1. Видаляємо академічні роки на початку або в середині (наприклад '2026/27 ', '2025/2026 ')
    name = re.sub(r'^(20\d\d/\d{2,4}\s*|20\d\d[-_]\d{2,4}\s*)', '', name)
    # 2. Видаляємо суфікси років на кшталт '_26_27_ІПІ' або '_2026_2027'
    name = re.sub(r'[_]?\d{2}[_-]\d{2}(?:_[a-zA-Zа-яА-ЯёЁіІїЇєЄ]+)?', '', name)
    # 3. Видаляємо позначення груп на кшталт '(ІП-66)', 'IP-65, 66', 'ІП-6Х', 'ІП-65'
    name = re.sub(r'[\(\[\{]?\s*(?:ІП|IP)[-_\s]?[0-9xXхХ]*(?:\s*[,/]\s*[0-9xXхХ]+)*\s*[\)\]\}]?', '', name, flags=re.IGNORECASE)
    # 4. Прибираємо зайві підкреслення, дефіси та пробіли
    name = re.sub(r'[_]+', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip(' -_,./')
    return name or str(course_name).strip()


def format_latex_to_unicode(text: str | None) -> str:
    """Конвертує базовий LaTeX, формули та математичні вирази у красивий Unicode для Telegram."""
    if not text:
        return ""
    text = str(text)

    # 1. Екрануємо базовий HTML (<, >, &), щоб уникнути конфліктів розмітки
    text = html.escape(text)

    # 2. Заміна LaTeX макросів на Unicode символи
    for pattern, sym in LATEX_REPLACEMENTS:
        text = re.sub(pattern, sym, text)

    # 3. Степені: x^2 -> x², x^{2} -> x²
    def replace_sup(m):
        val = m.group(1) or m.group(2)
        return ''.join(SUPERSCRIPTS.get(c, c) for c in val)
    text = re.sub(r'\^\{([0-9a-zA-Z+-=()]+)\}|\^([0-9a-zA-Z+-=()])', replace_sup, text)

    # 4. Індекси: x_1 -> x₁, x_{i} -> xᵢ
    def replace_sub(m):
        val = m.group(1) or m.group(2)
        return ''.join(SUBSCRIPTS.get(c, c) for c in val)
    text = re.sub(r'_\{([0-9a-zA-Z+-=()]+)\}|_([0-9a-zA-Z+-=()])', replace_sub, text)

    # 5. Дроби: \frac{a}{b} -> (a / b)
    text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', text)

    # 6. Квадратний корінь: \sqrt{x} -> √(x)
    text = re.sub(r'\\sqrt\{([^}]+)\}', r'√(\1)', text)

    # 7. Формули $...$ або $$...$$ обгортаємо в <code> для моноширинного підсвічування
    text = re.sub(r'\$\$([^$]+)\$\$', r'<code>\1</code>', text)
    text = re.sub(r'\$([^$]+)\$', r'<code>\1</code>', text)

    # 8. Жирний текст: **text** -> <b>text</b>
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

    # 9. Моноширинний код: `code` -> <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    return text.strip()


def format_morning_digest(
    week: int | str | None,
    day_name: str | None,
    lessons: list[dict] | None,
    auto_delete_time: str | None = None,
    cancelled_pairs: dict[int, dict] | None = None
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Форматування ранкового дайджесту розкладу пар (HTML)."""
    lessons = lessons or []
    w_str = escape_html_text(str(week) if week is not None else "1")
    d_str = escape_html_text(str(day_name) if day_name is not None else "")
    if not lessons:
        msg = f"🏖 <b>Розклад на сьогодні ({d_str}, {w_str}-й тиждень):</b>\n\nСьогодні пар немає!"
        if auto_delete_time:
            msg += f"\n\n🧹 <i>Повідомлення буде очищено о {escape_html_text(auto_delete_time)}</i>"
        return msg, None

    lines = [
        f"📅 <b>Розклад на сьогодні ({d_str}, {w_str}-й тиждень):</b>\n"
    ]

    for idx, l in enumerate(lessons, 1):
        if not isinstance(l, dict):
            continue
        lname = escape_html_text(l.get("name", "Пара"))
        ltype = escape_html_text(l.get("type", ""))
        llect = escape_html_text(l.get("lecturer", "Не вказано"))
        ltime = escape_html_text(l.get("time", ""))

        link_info = get_lesson_link_info(l.get("name", ""), l.get("type", ""))
        url = link_info.get("url", "").strip()
        comment = escape_html_text(link_info.get("comment", "").strip())

        type_str = f" ({ltype})" if ltype else ""

        if cancelled_pairs and idx in cancelled_pairs:
            reason = cancelled_pairs[idx].get("reason", "Причину не вказано")
            lines.append(
                f"<s><b>{idx}.</b> <code>{ltime}</code> — <b>{lname}</b>{type_str}</s> 🚫 <b>СКАСОВАНО!</b>\n"
                f"   ⚠️ <i>Причина: {escape_html_text(reason)}</i>"
            )
            continue

        link_str = ""
        if url:
            link_str = f'\n   🔗 <a href="{html.escape(url)}">Zoom / Meet</a>'
            if comment:
                link_str += f" <i>({comment})</i>"
        elif comment:
            link_str = f"\n   ℹ️ <i>{comment}</i>"

        lines.append(
            f"<b>{idx}.</b> <code>{ltime}</code> — <b>{lname}</b>{type_str}\n"
            f"   👤 {llect}{link_str}"
        )

    if any(isinstance(l, dict) and l.get("is_offline_cache") for l in lessons):
        lines.append("⚠️ <i>Сервер розкладу КПІ (Campus API) тимчасово недоступний. Дані надано з автономного офлайн-кешу бота.</i>")

    if auto_delete_time:
        lines.append(f"🧹 <i>Повідомлення буде автоматично видалено після завершення пар (о {escape_html_text(auto_delete_time)})</i>")

    return "\n\n".join(lines), None


def format_lesson_alert(lesson: dict | None, minutes_left: int = 5) -> tuple[str, InlineKeyboardMarkup | None]:
    """Форматування сповіщення перед початком пари за 20 або 5 хвилин (HTML)."""
    lesson = lesson or {}
    now = datetime.now(KYIV_TZ)
    current_time_str = now.strftime("%H:%M")

    lname = escape_html_text(lesson.get("name", "Пара"))
    ltype = escape_html_text(lesson.get("type", ""))
    llect = escape_html_text(lesson.get("lecturer", "Не вказано"))
    ltime = escape_html_text(lesson.get("time", ""))

    link_info = get_lesson_link_info(lesson.get("name", ""), lesson.get("type", ""))
    url = link_info.get("url", "").strip()
    comment = escape_html_text(link_info.get("comment", "").strip())

    if minutes_left >= 15:
        title = f"⏳ <b>Нагадування: пара через {minutes_left} хвилин!</b>"
    else:
        title = f"🔔 <b>Увага! Пара починається через {minutes_left} хвилин!</b>"

    text_parts = [
        f"{title}\n",
        f"⏰ <b>Поточний час:</b> <code>{current_time_str}</code>",
        f"⏳ <b>Початок:</b> <code>{ltime}</code> (через {minutes_left} хв)\n",
        f"📖 <b>Предмет:</b> <b>{lname}</b>",
        f"🏷 <b>Тип:</b> {ltype}",
        f"👤 <b>Викладач:</b> {llect}",
    ]

    keyboard = None
    if url:
        text_parts.append(f'\n🔗 <b>Посилання:</b> <a href="{html.escape(url)}">Перейти до заняття</a>')
        if comment:
            text_parts.append(f"📝 <b>Примітка:</b> {comment}")
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Приєднатися до заняття", url=url)]
            ]
        )
    elif comment:
        text_parts.append(f"\nℹ️ <b>Посилання:</b> <i>{comment}</i>")

    return "\n".join(text_parts), keyboard


def format_lecture_summary(summary: dict | None, video_title: str = "", video_url: str = "") -> tuple[str, InlineKeyboardMarkup | None]:
    """Форматування картки AI-конспекту лекції для Telegram (HTML)."""
    summary = summary or {}
    subject = escape_html_text(summary.get("subject_detected") or "Пара")
    raw_topic = summary.get("topic") or video_title or "Лекція"
    topic = format_latex_to_unicode(raw_topic)

    lines = [
        "🎬 <b>Новий конспект лекції з YouTube!</b>\n",
        f"📚 <b>Предмет:</b> <b>{subject}</b>",
        f"🎯 <b>Тема:</b> {topic}\n",
    ]

    points = summary.get("summary_points", [])
    if isinstance(points, list) and points:
        lines.append("📌 <b>Детальний конспект заняття:</b>")
        for pt in points:
            if pt:
                clean_pt = format_latex_to_unicode(str(pt))
                lines.append(f"• {clean_pt}")
        lines.append("")

    announcements = summary.get("teacher_announcements", [])
    if isinstance(announcements, list) and announcements:
        lines.append("📢 <b>Оголошення викладача:</b>")
        for ann in announcements:
            if ann:
                clean_ann = format_latex_to_unicode(str(ann))
                lines.append(f"• {clean_ann}")
        lines.append("")

    deadlines = summary.get("deadlines_mentioned", [])
    if isinstance(deadlines, list) and deadlines:
        lines.append("⏳ <b>Згадані дедлайни та терміни:</b>")
        for dl in deadlines:
            if isinstance(dl, dict):
                t_title = format_latex_to_unicode(dl.get("task_title") or "Завдання")
                d_date = escape_html_text(dl.get("date") or "")
                quote = format_latex_to_unicode(dl.get("exact_quote") or "")
                d_line = f"• <b>{t_title}</b>: <code>{d_date}</code>" if d_date else f"• <b>{t_title}</b>"
                if quote:
                    d_line += f" <i>(«{quote}»)</i>"
                lines.append(d_line)
        lines.append("")

    if video_url:
        lines.append(f'🔗 <a href="{html.escape(video_url)}">Переглянути запис на YouTube</a>')

    keyboard = None
    if video_url:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Дивитися запис на YouTube", url=video_url)]
            ]
        )

    res = "\n".join(lines).strip()
    if len(res) > 3900:
        res = res[:3800] + "\n\n⚠️ <i>...конспект скорочено через обмеження довжини Telegram.</i>"
    return res, keyboard


def format_deadlines_radar(assignments: list[dict] | None) -> str:
    """Форматування радара дедлайнів на поточний та наступний тиждень (HTML + expandable blockquotes)."""
    assignments = assignments or []
    if not assignments:
        return "🎉 <b>На найближчий час дедлайнів немає! Все чисто, відпочивайте!</b>"

    now = datetime.now(KYIV_TZ)
    today = now.date()
    days_to_sunday = 6 - today.weekday()
    this_week_end = today + timedelta(days=days_to_sunday)
    next_week_end = this_week_end + timedelta(days=7)

    this_week = []
    next_week = []
    later = []
    no_deadline_count = 0

    for a in assignments:
        if not isinstance(a, dict):
            continue
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

    lines = ["📋 <b>РАДАР ДЕДЛАЙНІВ (ІП-66):</b>\n"]

    def _render_item(a: dict, due_f: str, rem: str, emoji_sign: str, bullet: bool = False) -> str:
        raw_cname = a.get("course_id") or "Предмет"
        cname = escape_html_text(clean_course_name(raw_cname))
        title = escape_html_text(a.get("title") or "Завдання")
        
        # Пріоритет: спочатку стисла AI-вижимка, якщо немає - оригінальний опис
        summary = a.get("ai_summary") or a.get("description") or ""
        prefix = f"{emoji_sign} " if not bullet else "• "
        item_str = f"{prefix}<b>{cname}</b> — {title}\n   ⏳ <b>Дедлайн:</b> {due_f} <i>({rem})</i>"
        if summary and summary.strip():
            clean_desc = format_latex_to_unicode(summary.strip())
            if len(clean_desc) > 350:
                clean_desc = clean_desc[:340].rstrip() + "..."
            item_str += f"<blockquote expandable>📝 <b>Суть:</b> {clean_desc}</blockquote>"
        return item_str

    if this_week:
        lines.append("🔥 <b>ГОРИТЬ НА ЦЬОМУ ТИЖНІ:</b>")
        rendered_week = [_render_item(a, due_f, rem, emoji) for a, due_f, rem, emoji in this_week]
        lines.append("\n\n".join(rendered_week))
        lines.append("")

    if next_week:
        lines.append("🟡 <b>НА НАСТУПНИЙ ТИЖДЕНЬ:</b>")
        rendered_next = [_render_item(a, due_f, rem, emoji, bullet=True) for a, due_f, rem, emoji in next_week]
        lines.append("\n\n".join(rendered_next))
        lines.append("")

    if later:
        lines.append("🟢 <b>ПІЗНІШЕ:</b>")
        rendered_later = []
        for a, due_f, rem, emoji in later:
            raw_cname = a.get("course_id") or "Предмет"
            cname = escape_html_text(clean_course_name(raw_cname))
            title = escape_html_text(a.get("title") or "Завдання")
            rendered_later.append(f"• <b>{cname}</b> — {title} (до {due_f})")
        lines.append("\n".join(rendered_later))
        lines.append("")

    if no_deadline_count > 0:
        lines.append(f"📌 <i>Завдань та практикумів без фіксованого дедлайну:</i> <b>{no_deadline_count}</b>\n")

    res = "\n".join(lines).strip()
    if len(res) > 3900:
        res = res[:3800] + "\n\n⚠️ <i>...список скорочено через обмеження довжини Telegram.</i>"
    return res


def format_daily_summary(lessons: list[dict] | None = None, assignments: list[dict] | None = None, announcements: list[dict] | None = None) -> str:
    """
    Форматування адаптивного підсумку дня (о 21:00 або по команді /summary):
    - У навчальні дні:
        1) Пари, які були сьогодні, теми та оголошення викладачів.
        2) Статус дедлайнів на завтра та до кінця тижня.
    - У вихідні дні (середа та неділя):
        1) Відпочинок перед навчанням.
        2) Ближчі палаючі дедлайни на наступний тиждень.
    """
    lessons = lessons or []
    assignments = assignments or []
    announcements = announcements or []

    now = datetime.now(KYIV_TZ)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    days_to_sunday = 6 - today.weekday()
    this_week_end = today + timedelta(days=days_to_sunday)
    next_week_end = this_week_end + timedelta(days=7)

    has_lessons = bool(lessons)
    is_weekend_day = now.weekday() in (2, 6)

    tomorrow_assignments = []
    this_week_assignments = []
    next_week_assignments = []

    for a in assignments:
        if not isinstance(a, dict):
            continue
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
            lines.append("🌴 <b>ПІДСУМОК ТИЖНЯ ТА ДЕДЛАЙНИ (ІП-66):</b>\n")
            lines.append("🏖 Сьогодні вихідний, пар не було! Час відпочити та набратися сил перед новим тижнем.\n")
        else:
            date_str = now.strftime("%d.%m.%Y")
            lines.append(f"🌙 <b>ПІДСУМОК ДНЯ (ІП-66) — {date_str}:</b>\n")
            lines.append("🏖 Сьогодні пар за розкладом не було.\n")

        upcoming = this_week_assignments if this_week_assignments else next_week_assignments
        if upcoming:
            lines.append("🔥 <b>Ближчі дедлайни (на наступний тиждень):</b>")
            for a, due_f, rem in upcoming:
                cname = escape_html_text(a.get("course_id") or "Предмет")
                title = escape_html_text(a.get("title") or "Завдання")
                summary = a.get("ai_summary") or a.get("description") or ""
                desc_str = ""
                if summary and summary.strip():
                    clean_desc = format_latex_to_unicode(summary.strip())
                    if len(clean_desc) > 250:
                        clean_desc = clean_desc[:240].rstrip() + "..."
                    desc_str = f"<blockquote expandable>📝 <b>Суть:</b> {clean_desc}</blockquote>"
                cname = escape_html_text(clean_course_name(a.get("course_id") or "Предмет"))
                lines.append(f"• 🟡 <b>{cname}</b> — {title} (до {due_f}, <i>{rem}</i>){desc_str}")
        else:
            lines.append("✅ <b>Гарячих дедлайнів немає, можна спокійно відпочивати перед новим навчальним тижнем!</b>")
    else:
        date_str = now.strftime("%d.%m.%Y")
        lines.append(f"🌙 <b>ПІДСУМОК ДНЯ (ІП-66) — {date_str}:</b>\n")

        if lessons:
            lines.append("🎓 <b>Пари, що були сьогодні:</b>")
            for idx, l in enumerate(lessons, 1):
                if not isinstance(l, dict):
                    continue
                lname = escape_html_text(clean_course_name(l.get("name", "Пара")))
                ltype = escape_html_text(l.get("type", ""))
                ltime = escape_html_text(l.get("time", ""))
                type_str = f" ({ltype})" if ltype else ""
                lesson_line = f"<b>{idx}.</b> <code>{ltime}</code> — <b>{lname}</b>{type_str}"
                lines.append(lesson_line)
                if announcements:
                    for ann in announcements:
                        if isinstance(ann, dict) and ann.get("course_id") and ann["course_id"].lower() in str(l.get("name", "")).lower():
                            clean_ann = format_latex_to_unicode(str(ann.get("text", "")))
                            lines.append(f"   📢 <i>{clean_ann}</i>")
            lines.append("")
        else:
            lines.append("🏖 Сьогодні пар за розкладом не було.\n")

        lines.append("🔥 <b>Статус дедлайнів:</b>")
        if tomorrow_assignments:
            lines.append(f"🔴 <b>Увага! На завтра горить ({len(tomorrow_assignments)}):</b>")
            for a, due_f, rem in tomorrow_assignments:
                cname = escape_html_text(clean_course_name(a.get("course_id") or "Предмет"))
                title = escape_html_text(a.get("title") or "Завдання")
                summary = a.get("ai_summary") or a.get("description") or ""
                desc_str = ""
                if summary and summary.strip():
                    clean_desc = format_latex_to_unicode(summary.strip())
                    if len(clean_desc) > 250:
                        clean_desc = clean_desc[:240].rstrip() + "..."
                    desc_str = f"<blockquote expandable>📝 <b>Суть:</b> {clean_desc}</blockquote>"
                lines.append(f"• <b>{cname}</b> — {title} (до {due_f}){desc_str}")
        else:
            lines.append("✅ На завтра дедлайнів немає, можна спокійно виспатися!")

        if this_week_assignments:
            count = len(this_week_assignments)
            lines.append(f"⏳ До кінця цього тижня залишилося здати робіт: <b>{count}</b>.")

    lines.append("\n👉 Повний список і таймери: команда /deadlines")
    res = "\n".join(lines).strip()
    if len(res) > 3900:
        res = res[:3800] + "\n\n⚠️ <i>...зводку скорочено через ліміти Telegram.</i>"
    return res


def format_evening_digest(assignments: list[dict], lessons: list[dict] = None, announcements: list[dict] = None) -> str:
    """Форматування вечірньої зводки о 21:00 (сумісність)."""
    return format_daily_summary(lessons or [], assignments, announcements or [])

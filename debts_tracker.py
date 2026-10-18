from datetime import datetime
from config import KYIV_TZ
from formatters import clean_course_name, escape_html_text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def calculate_group_debts(assignments: list[dict], now_dt: datetime = None) -> dict:
    """
    Аналізує всі активні дедлайни та розраховує статистику заборгованостей групи.
    """
    if now_dt is None:
        now_dt = datetime.now(KYIV_TZ)

    now_str = now_dt.strftime("%Y-%m-%d %H:%M")

    overdue_list = []
    upcoming_list = []
    subject_counts = {}

    for a in assignments:
        due = a.get("due_date") or ""
        subj = clean_course_name(a.get("course_id") or a.get("course_name") or "Предмет")

        if due and due < now_str:
            overdue_list.append(a)
            subject_counts[subj] = subject_counts.get(subj, 0) + 1
        else:
            upcoming_list.append(a)

    return {
        "total_active": len(assignments),
        "total_overdue": len(overdue_list),
        "total_upcoming": len(upcoming_list),
        "overdue_assignments": overdue_list,
        "subject_breakdown": subject_counts
    }


def format_group_debts_report(summary: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування загального звіту по заборгованостях групи."""
    total_overdue = summary["total_overdue"]
    total_active = summary["total_active"]
    breakdown = summary["subject_breakdown"]
    overdue_items = summary["overdue_assignments"]

    if total_overdue == 0:
        text = (
            "🎉 <b>У групи немає жодного простроченого дедлайну!</b>\n\n"
            f"Всі активні завдання ({total_active}) знаходяться в межах встановлених термінів."
        )
    else:
        lines = [
            f"🚨 <b>ЗВЕДЕННЯ ЗАБОРГОВАНОСТЕЙ ГРУПИ ({total_overdue} боргів):</b>\n",
            "📊 <b>Хвости за предметами:</b>"
        ]
        for subj, count in sorted(breakdown.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"• <b>{subj}:</b> <code>{count}</code> прострочених робіт")

        lines.append("\n📋 <b>Список палаючих заборгованостей:</b>")
        for item in overdue_items[:8]:
            s_name = clean_course_name(item.get("course_id") or item.get("course_name"))
            t_title = escape_html_text(item.get("title", "Завдання"))
            d_date = item.get("due_date", "")
            lines.append(f"❌ <b>{s_name}</b>: {t_title}\n   ⏳ <i>Дедлайн сплив: {d_date}</i>")

        if len(overdue_items) > 8:
            lines.append(f"\n<i>...та ще {len(overdue_items) - 8} завдань.</i>")

        lines.append("\n💡 <i>Щоб переглянути свої борги:</i> <code>/mydebts [Прізвище]</code>")
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Оновити", callback_data="debts:refresh"),
                InlineKeyboardButton(text="📅 Дедлайни", callback_data="debts:deadlines")
            ]
        ]
    )
    return text, kb


def format_student_debts_report(student_name: str, debts: list[dict]) -> str:
    """Форматування персонального списку хвостів студента."""
    s_name = escape_html_text(student_name)
    if not debts:
        return f"🌟 <b>Студент {s_name} не має заборгованостей!</b> Всі роботи успішно здано."

    lines = [
        f"👤 <b>Заборгованості студента {s_name} ({len(debts)} робіт):</b>\n"
    ]
    for d in debts:
        c_name = clean_course_name(d.get("course_id") or d.get("course_name"))
        title = escape_html_text(d.get("title", "Завдання"))
        due = d.get("due_date", "Не вказано")
        lines.append(f"• <b>{c_name}</b>: {title}\n  ⏳ <i>Дедлайн: {due}</i> (ID: <code>{d.get('id')}</code>)")

    lines.append("\n💡 <i>Якщо ви вже здали роботу, староста може відмітити її через:</i>\n<code>/mark_done &lt;id&gt; | {s_name}</code>")
    return "\n".join(lines)

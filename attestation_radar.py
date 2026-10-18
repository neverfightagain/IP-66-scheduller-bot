from datetime import datetime, date, timedelta
from config import KYIV_TZ
from formatters import clean_course_name, escape_html_text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def calculate_semester_week(current_date: date = None) -> dict:
    """
    Визначає поточний навчальний тиждень семестру в КПІ
    та кількість тижнів до 1-ї (8-й тиждень) та 2-ї (14-й тиждень) атестацій.
    """
    if current_date is None:
        current_date = datetime.now(KYIV_TZ).date()

    # Осінній семестр стартує 1 вересня
    year = current_date.year if current_date.month >= 8 else current_date.year - 1
    semester_start = date(year, 9, 1)

    # Знаходимо понеділок старту
    start_monday = semester_start - timedelta(days=semester_start.weekday())
    curr_monday = current_date - timedelta(days=current_date.weekday())

    week_number = max(1, ((curr_monday - start_monday).days // 7) + 1)

    weeks_to_att1 = max(0, 8 - week_number)
    weeks_to_att2 = max(0, 14 - week_number)

    target_attestation = 1 if week_number <= 8 else 2

    return {
        "current_week": week_number,
        "weeks_to_att1": weeks_to_att1,
        "weeks_to_att2": weeks_to_att2,
        "target_attestation": target_attestation
    }


def analyze_attestation_status(assignments: list[dict], attestation_num: int = 1, current_date: date = None) -> dict:
    """
    Аналізує навантаження та дедлайни для проходження атестації.
    """
    if current_date is None:
        current_date = datetime.now(KYIV_TZ).date()

    sem_info = calculate_semester_week(current_date)
    now_str = current_date.strftime("%Y-%m-%d")

    # Групуємо завдання за предметами
    subjects = {}
    for a in assignments:
        sname = clean_course_name(a.get("course_id") or a.get("course_name") or "Предмет")
        if sname not in subjects:
            subjects[sname] = {"total": 0, "overdue": 0, "upcoming": 0}

        subjects[sname]["total"] += 1
        due = a.get("due_date", "")
        if due and due[:10] < now_str:
            subjects[sname]["overdue"] += 1
        else:
            subjects[sname]["upcoming"] += 1

    green_zone = []
    yellow_zone = []
    red_zone = []

    for sname, data in subjects.items():
        if data["overdue"] == 0:
            green_zone.append(sname)
        elif data["overdue"] == 1:
            yellow_zone.append((sname, data))
        else:
            red_zone.append((sname, data))

    return {
        "attestation_num": attestation_num,
        "semester_info": sem_info,
        "green_zone": green_zone,
        "yellow_zone": yellow_zone,
        "red_zone": red_zone,
        "total_subjects": len(subjects)
    }


def format_attestation_report(analysis: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування інтерактивного звіту атестаційного радару."""
    att_num = analysis["attestation_num"]
    sem = analysis["semester_info"]
    cur_w = sem["current_week"]
    weeks_left = sem["weeks_to_att1"] if att_num == 1 else sem["weeks_to_att2"]

    lines = [
        f"🎯 <b>АТЕСТАЦІЙНИЙ РАДАР ГРУПИ ({att_num}-ша атестація)</b>",
        f"📅 <b>Поточний навчальний тиждень:</b> {cur_w}-й",
        f"⏳ <b>До офіційної атестації:</b> {weeks_left} тижнів (атестаційний {8 if att_num == 1 else 14}-й тиждень)\n"
    ]

    red = analysis["red_zone"]
    yellow = analysis["yellow_zone"]
    green = analysis["green_zone"]

    if red:
        lines.append("🔴 <b>Критична зона ризику (неатестація близько!):</b>")
        for sname, data in red:
            lines.append(f"• <b>{sname}</b> — <code>{data['overdue']}</code> прострочених робіт!")
        lines.append("")

    if yellow:
        lines.append("🟡 <b>Зона уваги (підтягнути хвости):</b>")
        for sname, data in yellow:
            lines.append(f"• <b>{sname}</b> — 1 прострочена робота")
        lines.append("")

    if green:
        lines.append("🟢 <b>Безпечна зона (готові до атестації):</b>")
        lines.append(f"• {', '.join(green)}")
        lines.append("")

    if not red and not yellow and not green:
        lines.append("<i>Наразі немає активних завдань у системі.</i>")

    lines.append("💡 <i>Критерій КПІ: для отримання атестації необхідно мати зданими мінімум 50% запланованих робіт.</i>")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1️⃣ 1-ша атестація (8 тиж.)", callback_data="att:1"),
                InlineKeyboardButton(text="2️⃣ 2-га атестація (14 тиж.)", callback_data="att:2")
            ],
            [
                InlineKeyboardButton(text="🔄 Оновити", callback_data=f"att:refresh:{att_num}")
            ]
        ]
    )
    return "\n".join(lines), kb

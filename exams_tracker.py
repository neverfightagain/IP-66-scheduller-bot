import re
from datetime import datetime
from config import KYIV_TZ
from formatters import escape_html_text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def calculate_countdown(event_date_str: str, now_dt: datetime = None) -> dict:
    """Розраховує скільки днів та годин залишилось до контрольної/іспиту."""
    if now_dt is None:
        now_dt = datetime.now(KYIV_TZ)

    try:
        if len(event_date_str) == 10:
            target_dt = datetime.strptime(event_date_str, "%Y-%m-%d").replace(hour=23, minute=59, tzinfo=KYIV_TZ)
        else:
            target_dt = datetime.strptime(event_date_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
    except Exception:
        return {"days": 0, "hours": 0, "is_past": False, "text": "Дата уточнюється"}

    diff = target_dt - now_dt
    total_seconds = int(diff.total_seconds())

    if total_seconds < 0:
        return {"days": 0, "hours": 0, "is_past": True, "text": "Завершено"}

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600

    if days == 0:
        text = f"🔥 Сьогодні! (через {hours} год)"
    elif days == 1:
        text = f"⚠️ Завтра о {target_dt.strftime('%H:%M')}"
    elif days <= 3:
        text = f"⏳ Через {days} дні ({hours} год)"
    else:
        text = f"📅 Через {days} днів"

    return {"days": days, "hours": hours, "is_past": False, "text": text}


def check_exam_admission(required_labs: str, submitted_labs: list[str]) -> tuple[bool, str]:
    """
    Перевіряє, чи виконані умови допуску до контрольної роботи.
    Наприклад: 'Лаби 1-3' -> потрібно мати 'Лаба 1', 'Лаба 2', 'Лаба 3'.
    """
    if not required_labs or not required_labs.strip():
        return True, "Допуск вільний (без обов'язкових попередніх умов)"

    # Спроба витягти номери необхідних лаб
    nums = [int(n) for n in re.findall(r'\b\d+\b', required_labs)]
    if not nums:
        return True, f"Вимога викладача: {required_labs}"

    submitted_nums = []
    for s in submitted_labs:
        for n in re.findall(r'\b\d+\b', str(s)):
            submitted_nums.append(int(n))

    missing = [n for n in nums if n not in submitted_nums]
    if not missing:
        return True, "✅ Допущено! Усі необхідні роботи здано."

    missing_str = ", ".join(f"№{m}" for m in missing)
    return False, f"❌ Не допущено! Не здано роботи: {missing_str} (Вимога: {required_labs})"


def format_exams_dashboard(exams: list[dict], now_dt: datetime = None) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування інтерактивного календаря сесії та контрольних."""
    if now_dt is None:
        now_dt = datetime.now(KYIV_TZ)

    active_exams = []
    for e in exams:
        cd = calculate_countdown(e["event_date"], now_dt)
        if not cd["is_past"]:
            e_copy = dict(e)
            e_copy["countdown"] = cd
            active_exams.append(e_copy)

    if not active_exams:
        text = (
            "🏖 <b>Графік контрольних та іспитів:</b>\n\n"
            "Наразі немає запланованих МКР чи іспитів. Всі відпочивають!\n\n"
            "💡 <i>Додати контрольну/іспит (староста):</i>\n"
            "<code>/add_exam Предмет | Тип (МКР/Екзамен) | РРРР-ММ-ДД HH:MM | Ауд/Zoom | Вимоги допуску</code>"
        )
    else:
        lines = [
            f"📅 <b>Графік МКР, колоквіумів та іспитів ({len(active_exams)} подій):</b>\n"
        ]
        for e in active_exams:
            subj = escape_html_text(e["subject"])
            etype = escape_html_text(e["event_type"])
            edate = e["event_date"]
            loc = escape_html_text(e.get("location") or "Аудиторія уточнюється")
            cd_text = e["countdown"]["text"]
            req = escape_html_text(e.get("required_labs") or "Немає")
            notes = f"\n   📝 <i>{escape_html_text(e['notes'])}</i>" if e.get("notes") else ""

            badge = "🔴" if e["countdown"]["days"] <= 2 else ("🟡" if e["countdown"]["days"] <= 7 else "🟢")

            lines.append(
                f"{badge} <b>{etype}: {subj}</b>\n"
                f"   ⏳ <b>Термін:</b> <code>{edate}</code> ({cd_text})\n"
                f"   📍 <b>Формат / Місце:</b> {loc}\n"
                f"   🔒 <b>Умова допуску:</b> {req}{notes}\n"
                f"   🆔 <code>/del_exam {e['id']}</code>"
            )

        text = "\n\n".join(lines)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Оновити", callback_data="exam:refresh"),
                InlineKeyboardButton(text="⏳ Дедлайни", callback_data="exam:deadlines")
            ]
        ]
    )
    return text, kb

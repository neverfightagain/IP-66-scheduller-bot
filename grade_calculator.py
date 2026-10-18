import math
from formatters import escape_html_text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_ects_grade(points: float) -> tuple[str, str]:
    """Визначає оцінку за шкалою КПІ / ECTS."""
    p = round(points, 1)
    if p >= 95:
        return "A", "Відмінно"
    elif p >= 85:
        return "B", "Дуже добре"
    elif p >= 75:
        return "C", "Добре"
    elif p >= 65:
        return "D", "Задовільно"
    elif p >= 60:
        return "E", "Достатньо (Залік)"
    else:
        return "F", "Незадовільно (Не зараховано)"


def calculate_grade_projection(current_points: float, rso: dict = None) -> dict:
    """
    Розраховує прогноз балів та кількість лаб/робіт до отримання автомату.
    """
    if rso is None:
        rso = {
            "total_labs": 4,
            "points_per_lab": 15.0,
            "mkr_points": 20.0,
            "auto_pass_threshold": 60.0
        }

    points_per_lab = rso.get("points_per_lab", 15.0)
    auto_thresh = rso.get("auto_pass_threshold", 60.0)

    cur_grade, cur_desc = get_ects_grade(current_points)

    needed_for_pass = max(0.0, round(auto_thresh - current_points, 1))
    needed_for_c = max(0.0, round(75.0 - current_points, 1))
    needed_for_a = max(0.0, round(95.0 - current_points, 1))

    labs_for_pass = math.ceil(needed_for_pass / points_per_lab) if points_per_lab > 0 else 0
    labs_for_c = math.ceil(needed_for_c / points_per_lab) if points_per_lab > 0 else 0

    has_auto_pass = current_points >= auto_thresh

    return {
        "current_points": current_points,
        "current_ects": cur_grade,
        "current_desc": cur_desc,
        "has_auto_pass": has_auto_pass,
        "needed_for_pass": needed_for_pass,
        "needed_for_c": needed_for_c,
        "needed_for_a": needed_for_a,
        "labs_for_pass": labs_for_pass,
        "labs_for_c": labs_for_c,
        "points_per_lab": points_per_lab
    }


def format_grade_report(subject: str, current_points: float, proj: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування картки прогнозу балів та автомату."""
    clean_subj = escape_html_text(subject or "Дисципліна")
    ects = proj["current_ects"]
    desc = proj["current_desc"]

    badge = "🎉" if proj["has_auto_pass"] else "🎯"

    lines = [
        f"{badge} <b>Калькулятор автомату та балів: {clean_subj}</b>\n",
        f"📊 <b>Поточний бал:</b> <code>{current_points} / 100</code>",
        f"🏷 <b>Рейтинг:</b> <b>{ects} ({desc})</b>\n"
    ]

    if proj["has_auto_pass"]:
        lines.append("✅ <b>Вітаємо! У вас вже є гарантований залік/автомат!</b>")
        if proj["needed_for_c"] > 0:
            lines.append(f"• До оцінки <b>C (Добре, 75 б.)</b>: бракує <code>{proj['needed_for_c']}</code> б.")
        if proj["needed_for_a"] > 0:
            lines.append(f"• До оцінки <b>A (Відмінно, 95 б.)</b>: бракує <code>{proj['needed_for_a']}</code> б.")
    else:
        lines.append(f"⏳ <b>До автомату (60 б.):</b> бракує <code>{proj['needed_for_pass']}</code> балів.")
        if proj["labs_for_pass"] > 0:
            lines.append(f"💡 <i>Достатньо успішно захистити ще ~{proj['labs_for_pass']} лаб(и) по {proj['points_per_lab']} б. кожна.</i>")

    lines.append("\n📋 <i>Шкала КПІ: 60+ (E), 65+ (D), 75+ (C), 85+ (B), 95+ (A).</i>")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Шкала оцінювання КПІ", callback_data="grade:scale")
            ]
        ]
    )
    return "\n".join(lines), kb


def format_ects_scale_text() -> str:
    """Офіційна шкала переведення балів КПІ ім. Ігоря Сікорського."""
    return (
        "📊 <b>Шкала оцінювання КПІ (ECTS):</b>\n\n"
        "• <b>95 — 100:</b> Відмінно (A)\n"
        "• <b>85 — 94:</b> Дуже добре (B)\n"
        "• <b>75 — 84:</b> Добре (C)\n"
        "• <b>65 — 74:</b> Задовільно (D)\n"
        "• <b>60 — 64:</b> Достатньо (E) — поріг заліку/автомату\n"
        "• <b>Менше 60:</b> Незадовільно (F) — додаткова сесія\n\n"
        "💡 <i>Студенти з рейтингом 60+ балів звільняються від складання іспиту за наявності автомату.</i>"
    )

from datetime import datetime, time, timedelta
from config import KYIV_TZ
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

KPI_BELL_SCHEDULE = [
    {"num": 1, "start": time(8, 30), "end": time(10, 5), "start_str": "08:30", "end_str": "10:05"},
    {"num": 2, "start": time(10, 25), "end": time(12, 0), "start_str": "10:25", "end_str": "12:00"},
    {"num": 3, "start": time(12, 20), "end": time(13, 55), "start_str": "12:20", "end_str": "13:55"},
    {"num": 4, "start": time(14, 15), "end": time(15, 50), "start_str": "14:15", "end_str": "15:50"},
    {"num": 5, "start": time(16, 10), "end": time(17, 45), "start_str": "16:10", "end_str": "17:45"},
    {"num": 6, "start": time(18, 30), "end": time(20, 5), "start_str": "18:30", "end_str": "20:05"},
]


def get_current_bell_status(now_dt: datetime = None) -> dict:
    """
    Аналізує поточний час відносно сітки дзвінків КПІ.
    """
    if now_dt is None:
        now_dt = datetime.now(KYIV_TZ)

    cur_time = now_dt.time()
    today_date = now_dt.date()

    # 1. До початку першої пари
    first_pair = KPI_BELL_SCHEDULE[0]
    if cur_time < first_pair["start"]:
        first_dt = datetime.combine(today_date, first_pair["start"], tzinfo=KYIV_TZ)
        mins = int((first_dt - now_dt).total_seconds() // 60)
        return {
            "state": "BEFORE_LESSONS",
            "minutes_left": mins,
            "next_pair_num": 1,
            "next_pair_start": first_pair["start_str"]
        }

    # 2. Перевіряємо кожну пару та перерви
    for idx, pair in enumerate(KPI_BELL_SCHEDULE):
        # Чи зараз йде пара?
        if pair["start"] <= cur_time < pair["end"]:
            end_dt = datetime.combine(today_date, pair["end"], tzinfo=KYIV_TZ)
            mins = int((end_dt - now_dt).total_seconds() // 60)
            next_pair = KPI_BELL_SCHEDULE[idx + 1] if idx + 1 < len(KPI_BELL_SCHEDULE) else None
            return {
                "state": "IN_LESSON",
                "pair_num": pair["num"],
                "start_str": pair["start_str"],
                "end_str": pair["end_str"],
                "minutes_left": mins,
                "next_pair_start": next_pair["start_str"] if next_pair else None,
                "next_pair_num": next_pair["num"] if next_pair else None
            }

        # Чи зараз перерва після цієї пари?
        if idx + 1 < len(KPI_BELL_SCHEDULE):
            next_pair = KPI_BELL_SCHEDULE[idx + 1]
            if pair["end"] <= cur_time < next_pair["start"]:
                next_dt = datetime.combine(today_date, next_pair["start"], tzinfo=KYIV_TZ)
                mins = int((next_dt - now_dt).total_seconds() // 60)
                return {
                    "state": "IN_BREAK",
                    "from_pair_num": pair["num"],
                    "next_pair_num": next_pair["num"],
                    "next_pair_start": next_pair["start_str"],
                    "minutes_left": mins
                }

    # 3. Після закінчення останньої пари
    return {
        "state": "AFTER_LESSONS",
        "last_pair_end": KPI_BELL_SCHEDULE[-1]["end_str"]
    }


def format_bell_status_card(status: dict, active_lesson: dict = None) -> tuple[str, InlineKeyboardMarkup]:
    """
    Генерує картку зворотного відліку дзвінків.
    """
    state = status["state"]

    if state == "IN_LESSON":
        mins = status["minutes_left"]
        num = status["pair_num"]
        end_t = status["end_str"]

        lesson_name = f"📚 <b>{active_lesson['name']}</b>\n" if active_lesson else ""
        next_info = ""
        if status.get("next_pair_start"):
            next_info = f"\n🥪 <b>Перерва:</b> о {end_t} (до {status['next_pair_start']})"

        text = (
            f"🔔 <b>Зараз триває {num}-га пара!</b>\n"
            f"⏰ <b>Час:</b> <code>{status['start_str']} — {end_t}</code>\n"
            f"{lesson_name}"
            f"⏳ <b>До дзвінка з пари:</b> <b>{mins} хв</b> (дзвінок о {end_t}){next_info}"
        )

    elif state == "IN_BREAK":
        mins = status["minutes_left"]
        next_num = status["next_pair_num"]
        next_start = status["next_pair_start"]
        text = (
            f"☕ <b>Зараз перерва!</b> (після {status['from_pair_num']}-ї пари)\n\n"
            f"⏳ <b>До початку {next_num}-ї пари залишилось:</b> <b>{mins} хв</b>\n"
            f"🔔 Дзвінок на урок о <code>{next_start}</code>"
        )

    elif state == "BEFORE_LESSONS":
        mins = status["minutes_left"]
        hours = mins // 60
        rem_mins = mins % 60
        time_desc = f"{hours} год {rem_mins} хв" if hours > 0 else f"{rem_mins} хв"
        text = (
            f"🌅 <b>Пари ще не розпочалися.</b>\n\n"
            f"⏳ До дзвінка на 1-шу пару (<code>{status['next_pair_start']}</code>) залишилось: <b>{time_desc}</b>"
        )

    else:
        text = (
            "🎉 <b>Всі пари на сьогодні завершено!</b>\n\n"
            "Дзвінки закінчились о <code>20:05</code>. Відпочивайте та перевірте дедлайни через /deadlines."
        )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Розклад дзвінків КПІ", callback_data="bell:table"),
                InlineKeyboardButton(text="🔄 Оновити", callback_data="bell:refresh")
            ]
        ]
    )
    return text, kb


def format_bell_table_text() -> str:
    """Таблиця дзвінків КПІ."""
    lines = [
        "📋 <b>Офіційний розклад дзвінків КПІ:</b>\n",
        "• <b>1 пара:</b> <code>08:30 — 10:05</code> <i>(перерва 20 хв)</i>",
        "• <b>2 пара:</b> <code>10:25 — 12:00</code> <i>(велика перерва 20 хв)</i>",
        "• <b>3 пара:</b> <code>12:20 — 13:55</code> <i>(перерва 20 хв)</i>",
        "• <b>4 пара:</b> <code>14:15 — 15:50</code> <i>(перерва 20 хв)</i>",
        "• <b>5 пара:</b> <code>16:10 — 17:45</code> <i>(перерва 15 хв)</i>",
        "• <b>6 пара:</b> <code>18:30 — 20:05</code>\n",
        "⏱ <i>Тривалість пари: 1 год 35 хв (95 хв).</i>"
    ]
    return "\n".join(lines)

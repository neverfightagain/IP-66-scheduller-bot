import re
from datetime import datetime, timedelta
from config import KYIV_TZ
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

WEEKDAYS_UA = {
    "понеділок": 0, "вівторок": 1, "середу": 2, "середа": 2,
    "четвер": 3, "п'ятницю": 4, "пʼятницю": 4, "пятницю": 4, "п'ятниця": 4,
    "суботу": 5, "субота": 5, "неділю": 6, "неділя": 6
}

PAIR_NUMBERS_UA = {
    "1": 1, "першу": 1, "першої": 1, "1-шу": 1, "1шу": 1, "перша": 1,
    "2": 2, "другу": 2, "другої": 2, "2-гу": 2, "2гу": 2, "друга": 2,
    "3": 3, "третю": 3, "третьої": 3, "3-тю": 3, "3тю": 3, "третя": 3,
    "4": 4, "четверту": 4, "четвертої": 4, "4-ту": 4, "4ту": 4, "четверта": 4,
    "5": 5, "п'яту": 5, "п'ятої": 5, "5-ту": 5, "5ту": 5, "пяту": 5, "пятої": 5,
    "6": 6, "шосту": 6, "шостої": 6, "6-ту": 6, "6ту": 6
}


def detect_schedule_proposal(announcement_text: str, course_name: str = "", video_id: str = None) -> dict | None:
    """
    Аналізує текст викладача з лекції на наявність змін у розкладі:
    скасування, перенесення або перехід у Zoom.
    """
    if not announcement_text:
        return None

    text_lower = announcement_text.lower()

    # 1. Визначення типу зміни
    change_type = None
    if any(k in text_lower for k in ["не буде", "скасовано", "відмінено", "скасовується"]):
        change_type = "cancellation"
    elif any(k in text_lower for k in ["переноситься", "перенесено", "перенесемо"]):
        change_type = "reschedule"
    elif any(k in text_lower for k in ["в zoom", "онлайн", "дистанційно", "у zoom"]):
        change_type = "online_switch"

    if not change_type:
        return None

    # 2. Визначення номеру пари
    pair_number = None
    for word, num in PAIR_NUMBERS_UA.items():
        if re.search(rf"\b{word}\s+пар", text_lower) or re.search(rf"пар[а-я]*\s+(?:№\s*)?{word}\b", text_lower):
            pair_number = num
            break

    # 3. Визначення дати
    target_date = None
    today = datetime.now(KYIV_TZ).date()

    if "завтра" in text_lower:
        target_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "сьогодні" in text_lower:
        target_date = today.strftime("%Y-%m-%d")
    else:
        # Шукаємо день тижня (наприклад "у п'ятницю")
        for day_name, weekday_idx in WEEKDAYS_UA.items():
            if day_name in text_lower:
                days_ahead = (weekday_idx - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7  # наступний відповідний день
                target_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                break

    # Шукаємо явну дату (наприклад 25.10 або 2026-10-25)
    date_match = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b", text_lower)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else today.year
        try:
            target_date = datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return {
        "source_video_id": video_id,
        "course_name": course_name or "Дисципліна",
        "raw_announcement": announcement_text,
        "change_type": change_type,
        "target_date": target_date,
        "pair_number": pair_number,
        "details": f"Автоматично виявлено з оголошення викладача на лекції"
    }


def format_proposal_card(proposal: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Генерує повідомлення для старости з інлайн-кнопками підтвердження."""
    pid = proposal["id"]
    ctype = proposal["change_type"]
    cname = proposal.get("course_name", "Пара")
    tdate = proposal.get("target_date") or "Уточнити дату"
    pnum = f"Пара №{proposal['pair_number']}" if proposal.get("pair_number") else "Всі пари дня"

    type_titles = {
        "cancellation": "🚫 <b>Скасування пари</b>",
        "reschedule": "🔄 <b>Перенесення пари</b>",
        "online_switch": "💻 <b>Перехід на дистант (Zoom)</b>"
    }
    header = type_titles.get(ctype, "⚠️ <b>Зміна в розкладі</b>")

    text = (
        f"🤖 <b>AI виявив зміну розкладу у відео лекції!</b>\n\n"
        f"{header}\n"
        f"📚 <b>Предмет:</b> {cname}\n"
        f"📅 <b>Дата:</b> <code>{tdate}</code> ({pnum})\n"
        f"💬 <b>Слова викладача:</b> <i>«{proposal['raw_announcement']}»</i>\n\n"
        f"Застосувати ці зміни до графіку розкладу групи?"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Застосувати зміни", callback_data=f"prop:approve:{pid}"),
                InlineKeyboardButton(text="❌ Відхилити", callback_data=f"prop:reject:{pid}"),
            ]
        ]
    )
    return text, kb


async def apply_proposal(proposal_id: int) -> tuple[bool, str]:
    """Застосовує зміни з пропозиції до бази даних."""
    from database import get_proposal_by_id_db, update_proposal_status_db, cancel_pair_db

    prop = await get_proposal_by_id_db(proposal_id)
    if not prop:
        return False, "Пропозицію не знайдено."

    if prop["status"] != "pending":
        return False, f"Пропозицію вже було розглянуто ({prop['status']})."

    await update_proposal_status_db(proposal_id, "approved")

    # Якщо це скасування — фіксуємо в скасованих парах
    if prop["change_type"] == "cancellation" and prop.get("target_date"):
        p_num = prop.get("pair_number") or 1
        await cancel_pair_db(
            date_str=prop["target_date"],
            pair_number=p_num,
            subject=prop.get("course_name", ""),
            reason=f"Оголошено викладачем на YouTube: «{prop['raw_announcement']}»",
            cancelled_by="AI Announcement Sync"
        )
        return True, f"✅ Зміни схвалено! Пару №{p_num} на {prop['target_date']} скасовано в розкладі."

    return True, f"✅ Пропозицію #{proposal_id} успішно схвалено!"

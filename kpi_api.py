from datetime import datetime, date
import httpx
from config import KYIV_TZ

BASE_API_URL = "https://api.campus.kpi.ua"

DAY_CODE_TO_WEEKDAY = {
    "Пн": 0,
    "Вв": 1,
    "Ср": 2,
    "Чт": 3,
    "Пт": 4,
    "Сб": 5,
    "Нд": 6,
}

WEEKDAY_TO_DAY_CODE = {v: k for k, v in DAY_CODE_TO_WEEKDAY.items()}

WEEKDAY_FULL_NAMES = {
    0: "Понеділок",
    1: "Вівторок",
    2: "Середа",
    3: "Четвер",
    4: "П'ятниця",
    5: "Субота",
    6: "Неділя",
}


async def get_current_time_info() -> dict:
    url = f"{BASE_API_URL}/time/current"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_raw_schedule(group_id: int) -> dict:
    url = f"{BASE_API_URL}/schedule/lessons?groupId={group_id}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def get_lessons_for_date(group_id: int, target_date: date = None) -> tuple[int, str, list[dict]]:
    if target_date is None:
        target_date = datetime.now(KYIV_TZ).date()

    time_info = await get_current_time_info()
    current_week = time_info.get("currentWeek", 1)

    today = datetime.now(KYIV_TZ).date()
    days_diff = (target_date - today).days
    today_iso_week = today.isocalendar()[1]
    target_iso_week = target_date.isocalendar()[1]
    week_diff = target_iso_week - today_iso_week
    
    target_week = current_week
    if week_diff % 2 != 0:
        target_week = 2 if current_week == 1 else 1

    schedule_data = await get_raw_schedule(group_id)
    week_key = "scheduleFirstWeek" if target_week == 1 else "scheduleSecondWeek"
    days_list = schedule_data.get(week_key, [])

    weekday = target_date.weekday()
    target_day_code = WEEKDAY_TO_DAY_CODE.get(weekday, "")
    day_name_full = WEEKDAY_FULL_NAMES.get(weekday, "")

    today_str = target_date.strftime("%Y-%m-%d")

    matching_day = next((d for d in days_list if d.get("day") == target_day_code), None)
    if not matching_day:
        return target_week, day_name_full, []

    raw_pairs = matching_day.get("pairs", [])
    valid_lessons = []

    for p in raw_pairs:
        dates = p.get("dates")
        if dates and len(dates) > 0:
            if today_str not in dates:
                continue

        lecturer_obj = p.get("lecturer") or {}
        valid_lessons.append({
            "name": p.get("name", ""),
            "type": p.get("type", ""),
            "time": p.get("time", "")[:5],  # "HH:MM"
            "lecturer": lecturer_obj.get("name") or "Не вказано",
            "tag": p.get("tag", ""),
            "location": p.get("location") or "Онлайн",
        })

    valid_lessons.sort(key=lambda x: x["time"])
    return target_week, day_name_full, valid_lessons

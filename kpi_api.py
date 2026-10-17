from datetime import datetime, date, timedelta
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
    today_monday = today - timedelta(days=today.weekday())
    target_monday = target_date - timedelta(days=target_date.weekday())
    week_diff = (target_monday - today_monday).days // 7
    target_week = 2 if (current_week + week_diff) % 2 == 0 else 1

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
        if not isinstance(p, dict):
            continue
        dates = p.get("dates")
        if dates and len(dates) > 0:
            if today_str not in dates:
                continue

        lecturer_obj = p.get("lecturer") or {}
        valid_lessons.append({
            "name": p.get("name") or "Пара",
            "type": p.get("type") or "",
            "time": (p.get("time") or "")[:5],  # "HH:MM"
            "lecturer": lecturer_obj.get("name") or "Не вказано",
            "tag": p.get("tag") or "",
            "location": p.get("location") or "Онлайн",
        })

    valid_lessons.sort(key=lambda x: x["time"])
    return target_week, day_name_full, valid_lessons


async def get_schedule_for_date(target_date = None, group_id: int = None) -> list[dict]:
    """Отримати список розкладу пар на конкретну дату для групи (за замовчуванням ІП-66)."""
    from config import KPI_GROUP_ID
    gid = group_id if group_id is not None else KPI_GROUP_ID

    if isinstance(target_date, str):
        try:
            target_date = datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except Exception:
            target_date = datetime.now(KYIV_TZ).date()
    elif target_date is None:
        target_date = datetime.now(KYIV_TZ).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    try:
        _, _, lessons = await get_lessons_for_date(gid, target_date)
        return lessons
    except Exception:
        return []


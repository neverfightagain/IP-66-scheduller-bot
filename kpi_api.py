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
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        # Fallback розрахунок академічного тижня при падінні API
        today = datetime.now(KYIV_TZ).date()
        semester_start = date(today.year if today.month >= 8 else today.year - 1, 9, 1)
        sem_monday = semester_start - timedelta(days=semester_start.weekday())
        cur_monday = today - timedelta(days=today.weekday())
        weeks_passed = (cur_monday - sem_monday).days // 7
        calculated_week = 1 if (weeks_passed % 2 == 0) else 2
        return {"currentWeek": calculated_week, "currentDay": today.strftime("%Y-%m-%d")}


async def get_raw_schedule(group_id: int, use_cache_on_fail: bool = True) -> tuple[dict, bool, str | None]:
    """
    Отримати сирий розклад з Campus API.
    При збої або таймауті перемикається на автономний SQLite-кеш.
    Повертає: (дані: dict, з_кешу: bool, дата_кешу: str | None).
    """
    from database import save_campus_schedule_cache_db, get_campus_schedule_cache_db
    url = f"{BASE_API_URL}/schedule/lessons?groupId={group_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            # Зберігаємо свіжі дані в офлайн-кеш
            try:
                await save_campus_schedule_cache_db(group_id, data)
            except Exception:
                pass
            return data, False, None
    except Exception as e:
        if not use_cache_on_fail:
            raise e
        # Шукаємо збережений знімок в базі даних
        cached_data, cached_at = await get_campus_schedule_cache_db(group_id)
        if cached_data:
            return cached_data, True, cached_at
        raise e


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

    schedule_data, is_cached, cached_at = await get_raw_schedule(group_id)
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

        loc_raw = p.get("location")
        if isinstance(loc_raw, dict):
            loc_val = loc_raw.get("title") or loc_raw.get("name") or "Онлайн"
        elif isinstance(loc_raw, str):
            loc_val = loc_raw.strip() or "Онлайн"
        else:
            loc_val = "Онлайн"

        lecturer_obj = p.get("lecturer") or {}
        lesson_dict = {
            "name": p.get("name") or "Пара",
            "type": p.get("type") or "",
            "time": (p.get("time") or "")[:5],  # "HH:MM"
            "lecturer": lecturer_obj.get("name") or "Не вказано",
            "tag": p.get("tag") or "",
            "location": loc_val,
            "is_offline_cache": is_cached,
            "cached_at": cached_at,
        }
        valid_lessons.append(lesson_dict)

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


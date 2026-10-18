import logging
from formatters import escape_html_text

logger = logging.getLogger(__name__)

DAY_NAMES_UA = {
    "Пн": "Понеділок",
    "Вв": "Вівторок",
    "Ср": "Середа",
    "Чт": "Четвер",
    "Пт": "П'ятниця",
    "Сб": "Субота",
    "Нд": "Неділя"
}


def _normalize_pairs_map(schedule_data: dict) -> dict[tuple[int, str, str], dict]:
    """
    Індексує пари за ключем (тиждень: 1|2, код_дня: 'Пн', час: '08:30').
    """
    result = {}
    if not schedule_data:
        return result

    for week_num, key in [(1, "scheduleFirstWeek"), (2, "scheduleSecondWeek")]:
        days = schedule_data.get(key, [])
        for d in days:
            day_code = d.get("day", "")
            pairs = d.get("pairs", [])
            for p in pairs:
                time_str = (p.get("time") or "")[:5]
                lecturer_name = (p.get("lecturer") or {}).get("name") or "Не вказано"
                pair_info = {
                    "name": p.get("name") or "Пара",
                    "type": p.get("type") or "",
                    "time": time_str,
                    "location": p.get("location") or "Онлайн",
                    "lecturer": lecturer_name,
                    "week": week_num,
                    "day_code": day_code,
                    "day_name": DAY_NAMES_UA.get(day_code, day_code)
                }
                result[(week_num, day_code, time_str)] = pair_info
    return result


def calculate_schedule_diff(old_schedule: dict | None, new_schedule: dict | None) -> list[dict]:
    """
    Обчислює різницю між старим та новим розкладом.
    Виявляє зміни аудиторій, викладачів, перенесення, нові або видалені пари.
    """
    old_map = _normalize_pairs_map(old_schedule)
    new_map = _normalize_pairs_map(new_schedule)

    diffs = []

    # 1. Перевірка пар, що були змінені або видалені
    for key, old_pair in old_map.items():
        if key not in new_map:
            diffs.append({
                "type": "REMOVED",
                "week": old_pair["week"],
                "day_name": old_pair["day_name"],
                "time": old_pair["time"],
                "name": old_pair["name"],
                "old_val": f"{old_pair['name']} ({old_pair['location']})",
                "new_val": "Видалено деканатом"
            })
        else:
            new_pair = new_map[key]
            # Перевірка локації / аудиторії
            if old_pair["location"].strip().lower() != new_pair["location"].strip().lower():
                diffs.append({
                    "type": "LOCATION_CHANGED",
                    "week": old_pair["week"],
                    "day_name": old_pair["day_name"],
                    "time": old_pair["time"],
                    "name": new_pair["name"],
                    "old_val": old_pair["location"],
                    "new_val": new_pair["location"]
                })
            # Перевірка викладача
            if old_pair["lecturer"].strip().lower() != new_pair["lecturer"].strip().lower():
                diffs.append({
                    "type": "LECTURER_CHANGED",
                    "week": old_pair["week"],
                    "day_name": old_pair["day_name"],
                    "time": old_pair["time"],
                    "name": new_pair["name"],
                    "old_val": old_pair["lecturer"],
                    "new_val": new_pair["lecturer"]
                })
            # Перевірка назви предмету
            if old_pair["name"].strip().lower() != new_pair["name"].strip().lower():
                diffs.append({
                    "type": "NAME_CHANGED",
                    "week": old_pair["week"],
                    "day_name": old_pair["day_name"],
                    "time": old_pair["time"],
                    "name": new_pair["name"],
                    "old_val": old_pair["name"],
                    "new_val": new_pair["name"]
                })

    # 2. Перевірка нових доданих пар
    for key, new_pair in new_map.items():
        if key not in old_map:
            diffs.append({
                "type": "ADDED",
                "week": new_pair["week"],
                "day_name": new_pair["day_name"],
                "time": new_pair["time"],
                "name": new_pair["name"],
                "old_val": "Не було пари",
                "new_val": f"{new_pair['name']} ({new_pair['location']}, {new_pair['lecturer']})"
            })

    return diffs


def format_schedule_diff_alert(diff_items: list[dict]) -> str:
    """Форматування сповіщення про знайдені зміни в розкладі від деканату."""
    if not diff_items:
        return "✅ Змін у розкладі від деканату не виявлено."

    lines = [
        "🚨 <b>УВАГА! Деканат змінив розклад пар на Campus:</b>\n"
    ]

    for d in diff_items:
        w = f"{d['week']}-й тиждень"
        day = d['day_name']
        t = d['time']
        name = escape_html_text(d['name'])
        old_val = escape_html_text(d['old_val'])
        new_val = escape_html_text(d['new_val'])

        if d["type"] == "LOCATION_CHANGED":
            lines.append(
                f"📍 <b>{name}</b> ({w}, {day} о <code>{t}</code>)\n"
                f"   ❌ Було: <s>{old_val}</s>\n"
                f"   ✅ Стало: <b>{new_val}</b>"
            )
        elif d["type"] == "LECTURER_CHANGED":
            lines.append(
                f"👤 <b>{name}</b> ({w}, {day} о <code>{t}</code>) — зміна викладача:\n"
                f"   ❌ Було: <s>{old_val}</s>\n"
                f"   ✅ Стало: <b>{new_val}</b>"
            )
        elif d["type"] == "NAME_CHANGED":
            lines.append(
                f"🔄 <b>Заміна предмету</b> ({w}, {day} о <code>{t}</code>):\n"
                f"   ❌ Було: <s>{old_val}</s>\n"
                f"   ✅ Стало: <b>{new_val}</b>"
            )
        elif d["type"] == "ADDED":
            lines.append(
                f"➕ <b>Нова пара!</b> ({w}, {day} о <code>{t}</code>):\n"
                f"   📚 <b>{new_val}</b>"
            )
        elif d["type"] == "REMOVED":
            lines.append(
                f"🗑 <b>Пару скасовано деканатом</b> ({w}, {day} о <code>{t}</code>):\n"
                f"   <s>{old_val}</s>"
            )

    lines.append("\nℹ️ <i>Перевірте актуальні аудиторії та посилання перед початком пар!</i>")
    return "\n\n".join(lines)


async def check_and_notify_schedule_diff(bot, group_id: int) -> list[dict]:
    """
    Перевіряє різницю між поточним розкладом та попереднім збереженим знімком.
    Якщо є зміни — розсилає сповіщення у підписані чати.
    """
    from kpi_api import get_raw_schedule
    from database import get_latest_schedule_snapshot_db, save_schedule_snapshot_db, get_subscribed_chats_db
    from handlers import safe_answer

    old_snapshot = await get_latest_schedule_snapshot_db(group_id)
    try:
        current_schedule, _, _ = await get_raw_schedule(group_id)
    except Exception as e:
        logger.warning(f"Не вдалося отримати поточний розклад для перевірки змін: {e}")
        return []

    if not old_snapshot:
        # Перший запуск — зберігаємо еталонний знімок
        await save_schedule_snapshot_db(group_id, current_schedule)
        return []

    diffs = calculate_schedule_diff(old_snapshot, current_schedule)
    if diffs:
        # Оновлюємо знімок
        await save_schedule_snapshot_db(group_id, current_schedule)
        alert_text = format_schedule_diff_alert(diffs)

        # Розсилаємо
        targets = await get_subscribed_chats_db()
        for t in targets:
            cid = t["chat_id"]
            tid = t.get("thread_id")
            try:
                await bot.send_message(chat_id=cid, text=alert_text, parse_mode="HTML", message_thread_id=tid)
            except Exception as e:
                logger.error(f"Помилка відправки Diff Alert у чат {cid}: {e}")

    return diffs

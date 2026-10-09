import json
from pathlib import Path
from config import LINKS_FILE


def load_links() -> dict:
    """Загрузить словарь ссылок из links.json."""
    if not LINKS_FILE.exists():
        return {}
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Помилка при читанні links.json: {e}")
        return {}


def save_links(links_data: dict) -> bool:
    """Сохранить обновлённый словарь ссылок в links.json."""
    try:
        with open(LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(links_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Помилка при записі links.json: {e}")
        return False


def get_lesson_link_info(name: str, lesson_type: str) -> dict:
    """
    Найти ссылку и примечание для предмета.
    Приоритет: точное совпадение 'Предмет (Тип)' -> совпадение по имени и типу -> совпадение только по имени.
    """
    links = load_links()
    
    # 1. Точное совпадение ключа: "Название (Тип)"
    key_with_type = f"{name} ({lesson_type})"
    if key_with_type in links:
        item = links[key_with_type]
        if item.get("url") or item.get("comment"):
            return item

    # 2. Поиск по прямому совпадению названия предмета и типа занятия
    norm_name = name.strip().lower()
    norm_type = lesson_type.strip().lower()

    for key, item in links.items():
        item_sub = item.get("subject", "").strip().lower()
        item_type = item.get("type", "").strip().lower()
        if item_sub == norm_name and item_type == norm_type:
            if item.get("url") or item.get("comment"):
                return item

    # 3. Нестрогий поиск по вхождению названия С ТЕМ ЖЕ ТИПОМ
    for key, item in links.items():
        item_sub = item.get("subject", "").strip().lower()
        item_type = item.get("type", "").strip().lower()
        if item_type == norm_type and (item_sub in norm_name or norm_name in item_sub):
            if item.get("url") or item.get("comment"):
                return item

    # 4. Fallback: совпадение по названию независимо от типа (если ссылки для типа нет)
    for key, item in links.items():
        item_sub = item.get("subject", "").strip().lower()
        if item_sub and (item_sub in norm_name or norm_name in item_sub):
            if item.get("url"):
                return item

    return {"url": "", "comment": ""}

import html
from formatters import escape_html_text
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_material_icon(url: str, mat_type: str = "") -> str:
    """Визначає іконку типу файлу чи ресурсу."""
    url_l = (url or "").lower()
    t_l = (mat_type or "").lower()

    if "github.com" in url_l:
        return "🐙"
    elif "drive.google.com" in url_l or "docs.google.com" in url_l:
        return "📁"
    elif "youtube.com" in url_l or "youtu.be" in url_l:
        return "🎬"
    elif url_l.endswith(".pdf") or "pdf" in t_l:
        return "📄"
    elif url_l.endswith((".zip", ".rar", ".7z", ".tar.gz")):
        return "📦"
    return "🔗"


def format_labs_hub_message(subject: str, materials: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Форматування хабу матеріалів лабораторних робіт."""
    clean_subj = subject or "Всі предмети"

    if not materials:
        text = (
            f"📚 <b>Хаб методичок та умов: {escape_html_text(clean_subj)}</b>\n\n"
            "<i>Матеріалів наразі не додано.</i>\n\n"
            "💡 <b>Як додати методичку чи посилання (староста/студент):</b>\n"
            "<code>/add_lab Предмет | Назва матеріалу | Посилання | [Опис]</code>\n\n"
            "Приклад:\n"
            "<code>/add_lab АСД | Методичка до Лаби 1-3 | https://drive.google.com/... | Офіційні вимоги</code>"
        )
        return text, InlineKeyboardMarkup(inline_keyboard=[])

    lines = [
        f"📚 <b>Хаб методичок та умов: {escape_html_text(clean_subj)}</b>\n"
    ]

    kb_rows = []
    for m in materials:
        title = escape_html_text(m.get("lab_title") or "Матеріал")
        url = m.get("url", "")
        desc = f" — <i>{escape_html_text(m['description'])}</i>" if m.get("description") else ""
        icon = get_material_icon(url, m.get("material_type"))

        lines.append(f"{icon} <b>{title}</b>{desc}\n   🆔 <code>/del_lab {m['id']}</code>")

        if url.startswith(("http://", "https://")):
            btn_title = f"{icon} {m.get('lab_title', 'Відкрити')[:25]}"
            kb_rows.append([InlineKeyboardButton(text=btn_title, url=url)])

    text = "\n\n".join(lines)
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows[:8])  # максимум 8 швидких кнопок в повідомленні
    return text, kb

import asyncio
import datetime
import json
import logging
import os
import re
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
Ти — академічний аналітичний AI-асистент для студентської групи ІП-66 КПІ.
Твоє завдання — уважно проаналізувати стенограму (субтитри з таймкодами) або відеозапис університетської пари та скласти чітку структуровану вижимку для одногрупників.

Звертай особливу увагу на:
1. Тему заняття та ключові теоретичні/практичні концепції.
2. Будь-які оголошення викладача (перенесення пар, контрольні, колоквіуми, вимоги до захисту робіт).
3. Дати дедлайнів або перенесення дедлайнів лабораторних/домашніх завдань із точними цитатами викладача!

Відповідай СТРОГО валідним JSON-об'єктом за наступною схемою:
{
  "subject_detected": "Назва дисципліни (наприклад: Алгоритми та структури даних, Комп'ютерна дискретна математика, Математичний аналіз, Основи програмування тощо)",
  "topic": "Коротка та точна тема заняття",
  "summary_points": [
    "Теза 1: що розбирали",
    "Теза 2: ключовий алгоритм або формула",
    "Теза 3: практичні приклади"
  ],
  "teacher_announcements": [
    "Оголошення викладача (якщо є)"
  ],
  "deadlines_mentioned": [
    {
      "task_title": "Назва роботи/лабораторної",
      "date": "Згадана дата (якщо вказана)",
      "exact_quote": "Точна фраза викладача з таймкодом"
    }
  ]
}
"""

_active_key_idx = 0
_exhausted_keys: set[str] = set()


def get_gemini_keys() -> list[str]:
    """Отримати список доступних ключів Gemini (підтримка пулу ключів через кому або один ключ)."""
    raw = os.getenv("GEMINI_API_KEYS", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not raw:
        return []
    return [k.strip() for k in re.split(r"[,;]", raw) if k.strip()]


def get_gemini_client() -> tuple[genai.Client | None, str]:
    """Отримати клієнт Gemini для першого невичерпаного ключа з пулу."""
    global _active_key_idx, _exhausted_keys
    keys = get_gemini_keys()
    if not keys:
        return None, ""

    for _ in range(len(keys)):
        k = keys[_active_key_idx % len(keys)]
        if k not in _exhausted_keys:
            return genai.Client(api_key=k), k
        _active_key_idx = (_active_key_idx + 1) % len(keys)

    # Якщо всі вичерпані, повертаємо поточний (на випадок скидання добового ліміту Google)
    k = keys[_active_key_idx % len(keys)]
    return genai.Client(api_key=k), k


def rotate_key(exhausted_key: str):
    """Позначити ключ як вичерпаний та перемкнутися на наступний ключ у пулі."""
    global _active_key_idx, _exhausted_keys
    _exhausted_keys.add(exhausted_key)
    keys = get_gemini_keys()
    if len(keys) > 1:
        _active_key_idx = (_active_key_idx + 1) % len(keys)
        logger.warning(f"Ключ Gemini вичерпав ліміт. Перемкнуто на ключ #{_active_key_idx + 1} з {len(keys)}")


async def analyze_lecture_transcript(transcript_text: str, video_title: str = "") -> dict | None:
    """
    Проаналізувати транскрипт лекції за допомогою Gemini Flash (повністю асинхронно).
    Повертає структурований словник з конспектом та анонсами.
    """
    client, key = get_gemini_client()
    if not client:
        logger.warning("GEMINI_API_KEY не вказаний. Аналіз лекцій пропущено.")
        return None

    prompt_content = f"Назва відео: {video_title}\n\nТранскрипт пари з таймкодами:\n{transcript_text}"
    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
    ]
    seen = set()
    models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    for m in models:
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=m,
                    contents=prompt_content,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.2,
                    ),
                ),
                timeout=50.0,
            )
            if response and response.text:
                return json.loads(response.text)
        except asyncio.TimeoutError:
            logger.warning(f"Модель {m} перевищила таймаут 50с при аналізі транскрипту")
            continue
        except Exception as e_m:
            err_str = str(e_m)
            logger.warning(f"Модель {m} повернула помилку при аналізі транскрипту: {err_str}")
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                rotate_key(key)
                client, key = get_gemini_client()
                continue
            await asyncio.sleep(1)
            continue

    return None


async def analyze_lecture_video(video_url: str, video_title: str = "") -> dict | None:
    """
    Прямий асинхронний аналіз відео з YouTube через мультимодальні можливості Gemini.
    Працює без парсингу субтитрів та без потреби в проксі (Google сам отримує відео на своїх серверах).
    """
    client, key = get_gemini_client()
    if not client:
        logger.warning("GEMINI_API_KEY не вказаний. Прямий аналіз відео пропущено.")
        return None

    prompt_parts = [
        types.Part.from_uri(file_uri=video_url, mime_type="video/mp4"),
        f"Назва відео: {video_title}\n\nПроаналізуй це навчальне заняття відповідно до системної інструкції та поверни структурований JSON."
    ]

    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
        "gemini-flash-latest",
    ]
    seen = set()
    models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    for m in models:
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=m,
                    contents=prompt_parts,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.2,
                    ),
                ),
                timeout=80.0,
            )
            if response and response.text:
                return json.loads(response.text)
        except asyncio.TimeoutError:
            logger.warning(f"Модель {m} перевищила таймаут 80с при прямому аналізі відео")
            continue
        except Exception as e_m:
            err_str = str(e_m)
            logger.warning(f"Модель {m} повернула помилку при аналізі відео: {err_str}")
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                rotate_key(key)
                client, key = get_gemini_client()
                continue
            if "503" in err_str or "UNAVAILABLE" in err_str:
                logger.warning("Gemini черга обробки відео перевантажена (503 UNAVAILABLE). Переходимо до контекстного аналізу розкладу.")
                break
            await asyncio.sleep(1)
            continue

    return None


def parse_date_from_title_or_published(title: str, published_at_str: str | None = None) -> datetime.date | None:
    """
    Визначити точну дату пари за назвою відео (наприклад '10.16. Назва' чи '16.10. Назва')
    або за метаданими публікації YouTube. Захищено від помилкового спрацювання на номери робіт ('Лаб 1.2').
    """
    pub_date = None
    if published_at_str:
        try:
            pub_date = datetime.datetime.fromisoformat(published_at_str.replace("Z", "+00:00")).date()
        except Exception:
            pass

    year = pub_date.year if pub_date else datetime.date.today().year

    # Патерн дати: на початку рядка ('10.16.' чи '[10.16]') або з крапкою/пробілом (' 10.16. ')
    m = re.search(r'^\s*\[?(\d{1,2})\.(\d{1,2})\]?\.?', title)
    if not m:
        m = re.search(r'(?:^|\s)\[?(\d{1,2})\.(\d{1,2})\]?\.(?:\s|$)', title)

    if m:
        p1, p2 = int(m.group(1)), int(m.group(2))
        if 1 <= p1 <= 31 and 1 <= p2 <= 31:
            try:
                if p1 > 12 and p2 <= 12:
                    return datetime.date(year, p2, p1)  # DD.MM
                elif p1 <= 12 and p2 > 12:
                    return datetime.date(year, p1, p2)  # MM.DD
                elif p1 <= 12 and p2 <= 12:
                    if pub_date:
                        if pub_date.month == p1 and pub_date.day == p2:
                            return datetime.date(year, p1, p2)
                        elif pub_date.month == p2 and pub_date.day == p1:
                            return datetime.date(year, p2, p1)
                    curr_m = datetime.date.today().month
                    if p1 == curr_m:
                        return datetime.date(year, p1, p2)
                    elif p2 == curr_m:
                        return datetime.date(year, p2, p1)
                    return datetime.date(year, p1, p2)
            except ValueError:
                pass

    return pub_date


async def analyze_lecture_with_schedule_context(video_title: str, video_url: str, published_at_str: str | None = None) -> dict | None:
    """
    Резервний семантичний аналіз: використовує розклад пар групи ІП-66 за дату заняття.
    Створює чітку картку пари навіть якщо 90-хвилинне відео тимчасово не аналізується Gemini (503).
    """
    from config import KPI_GROUP_ID
    from kpi_api import get_lessons_for_date

    parsed_date = parse_date_from_title_or_published(video_title, published_at_str)
    target_date = parsed_date or datetime.date.today()

    matched_lesson = None
    all_lessons = []
    try:
        _, _, lessons = await get_lessons_for_date(KPI_GROUP_ID, target_date)
        all_lessons = lessons
        clean_title = re.sub(r'[^\w\s]', '', video_title.lower())
        for l in lessons:
            lname = l.get("name", "")
            clean_lname = re.sub(r'[^\w\s]', '', lname.lower())
            words = [w for w in clean_lname.split() if len(w) > 3]
            if any(w in clean_title for w in words):
                matched_lesson = l
                break
    except Exception as e_sched:
        logger.debug(f"Помилка зіставлення з розкладом КПІ: {e_sched}")

    subject_detected = (
        matched_lesson.get("name") if matched_lesson
        else re.split(r'[(.]', video_title)[0].strip() or "Університетська пара"
    )
    lecturer = matched_lesson.get("lecturer") if matched_lesson else "Викладач кафедри"
    ltype = matched_lesson.get("type") if matched_lesson else "Заняття"

    # Спроба легкого текстового аналізу через Gemini Flash (текст майже не витрачає квоту і ніколи не дає 503)
    client, key = get_gemini_client()
    if client:
        prompt_text = f"""
        Склади структуровану картку пари для студентів групи ІП-66 КПІ:
        Назва відеозапису: "{video_title}"
        Посилання: {video_url}
        Дисципліна за розкладом: {subject_detected}
        Викладач: {lecturer}
        Тип заняття: {ltype}
        Дата: {target_date.strftime('%d.%m.%Y')}

        Завдання:
        1. Вкажи точну назву дисципліни в "subject_detected".
        2. Сформуй тему заняття ("topic"), наприклад: "{ltype} ({target_date.strftime('%d.%m')})".
        3. Сформуй 2-3 практичні тези в "summary_points" про публікацію відео та виконання завдань.
        Поверни валідний JSON за системною інструкцією.
        """
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        system_instruction=SYSTEM_INSTRUCTION,
                        temperature=0.2,
                    ),
                ),
                timeout=25.0,
            )
            if response and response.text:
                return json.loads(response.text)
        except Exception as e_text:
            logger.debug(f"Текстова генерація картки повернула помилку: {e_text}")

    # Повний офлайн-шаблон на випадок відсутності інтернету або повного блекауту API
    summary_pts = [
        f"Відеозапис ({ltype}) опубліковано на каналі групи.",
        f"Викладач: {lecturer}."
    ]
    if matched_lesson and matched_lesson.get("location"):
        loc = matched_lesson["location"]
        loc_str = loc.get("title") if isinstance(loc, dict) else str(loc)
        if loc_str:
            summary_pts.append(f"Аудиторія / платформа: {loc_str}")

    return {
        "subject_detected": subject_detected,
        "topic": f"{ltype} ({target_date.strftime('%d.%m')})",
        "summary_points": summary_pts,
        "teacher_announcements": [],
        "deadlines_mentioned": []
    }


ASSIGNMENT_SUMMARY_INSTRUCTION = """
Ти — академічний аналітичний AI-помічник для студентів КПІ.
Твоє завдання — стисло і чітко сформулювати СУТЬ завдання з опису викладача для компактної картки дедлайну в Telegram.

Критичні правила:
1. Максимум 1-2 короткі, місткі речення (до 150-200 символів).
2. Чітко виділи:
   - Що конкретно треба зробити (наприклад: "Опрацювати Past Tenses за відео та пройти квіз на сайті" або "Реалізувати алгоритм Дейкстри для вагового графа").
   - Формат / місце здачі (якщо згадано: "Звіт у PDF в Classroom" або "В Classroom не здавати, захист на парі").
3. ПОВНІСТЮ ВИДАЛИ: вітання ("Шановні студенти"), воду, повтори назви курсу, довгі посилання URL (заміни просто на "за посиланням"), інструкції як встановити софт, якщо це не суть завдання.
4. Якщо в тексті є формули — запиши їх у простому вигляді.
5. Відповідай українською мовою, без лапок і без вступних слів на зразок "Суть завдання:" або "Вимоги:".
"""


async def summarize_assignment_requirements(title: str, description: str, course_name: str = "") -> str:
    """
    Аналізує довгий сирий опис викладача з Classroom та формує лаконічну вижимку вимог у 1-2 речення.
    Працює через Gemini Flash, практично без витрат квот.
    """
    if not description or len(description.strip()) < 35:
        return description.strip() if description else ""

    client, key = get_gemini_client()
    if not client:
        # Швидкий локальний фолбек без API
        clean = re.sub(r'https?://\S+', '', description.strip())
        clean = re.sub(r'\s+', ' ', clean).strip()
        first_part = clean.split('\n')[0].strip()
        return first_part[:180] + ("..." if len(first_part) > 180 else "")

    prompt = f"Предмет: {course_name}\nНазва завдання: {title}\n\nОпис від викладача:\n{description.strip()}"

    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
    ]
    seen = set()
    models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    for m in models:
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=ASSIGNMENT_SUMMARY_INSTRUCTION,
                        temperature=0.2,
                        max_output_tokens=150,
                    ),
                ),
                timeout=12.0,
            )
            if response and response.text:
                summary = response.text.strip().replace('"', '')
                summary = re.sub(r'^(Суть(:|\s)|Вимоги(:|\s)|Завдання(:|\s))\s*', '', summary, flags=re.IGNORECASE)
                return summary.strip()
        except Exception as e:
            logger.debug(f"Помилка створення AI-вижимки завдання ({m}): {e}")
            continue

    # Резервний локальний варіант при недоступності API
    clean = re.sub(r'https?://\S+', '', description.strip())
    clean = re.sub(r'\s+', ' ', clean).strip()
    first_part = clean.split('\n')[0].strip()
    return first_part[:180] + ("..." if len(first_part) > 180 else "")




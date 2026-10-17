import asyncio
import datetime
import json
import logging
import os
import re
import httpx
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


def get_gemini_keys() -> list[str]:
    """Отримати список доступних ключів Gemini (підтримка пулу ключів через кому/крапку з комою або один ключ)."""
    raw = os.getenv("GEMINI_API_KEYS", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not raw:
        return []
    return [k.strip().strip('"\'') for k in re.split(r"[\n,;]", raw) if k.strip().strip('"\'')]


def get_ordered_gemini_keys() -> list[str]:
    """
    Повертає список ключів Gemini у порядку ротації, починаючи з поточного активного індексу.
    """
    global _active_key_idx
    keys = get_gemini_keys()
    if not keys:
        return []
    n = len(keys)
    start = _active_key_idx % n
    return [keys[(start + i) % n] for i in range(n)]


def mark_key_success(api_key: str):
    """Позначити ключ як робочий (встановити його активним для наступних запитів)."""
    global _active_key_idx
    keys = get_gemini_keys()
    if api_key in keys:
        _active_key_idx = keys.index(api_key)


def advance_to_next_key():
    """Перемкнути активний покажчик на наступний ключ у пулі."""
    global _active_key_idx
    keys = get_gemini_keys()
    if keys:
        _active_key_idx = (_active_key_idx + 1) % len(keys)
        logger.warning(f"🔄 Перемкнуто активний ключ Gemini на індекс #{_active_key_idx + 1} з {len(keys)}")


def get_gemini_client() -> tuple[genai.Client | None, str]:
    """Сумісність: отримати клієнт для поточного активного ключа."""
    keys = get_gemini_keys()
    if not keys:
        return None, ""
    k = keys[_active_key_idx % len(keys)]
    return genai.Client(api_key=k), k


def rotate_key(exhausted_key: str = ""):
    """Сумісність: перемкнутися на наступний ключ."""
    advance_to_next_key()


async def analyze_lecture_transcript_groq(transcript_text: str, video_title: str = "") -> dict | None:
    """
    Резервний аналіз транскрипту через Groq API (Llama-3.3-70b-versatile).
    Викликається якщо всі ключі Gemini вичерпані або Google повертає 500/503.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json"
    }
    groq_models = [
        os.getenv("GROQ_MODEL", "").strip(),
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
    ]
    seen_g = set()
    candidate_groq_models = [gm for gm in groq_models if gm and not (gm in seen_g or seen_g.add(gm))]

    for gm in candidate_groq_models:
        payload = {
            "model": gm,
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": f"Назва відео: {video_title}\n\nТранскрипт пари з таймкодами:\n{transcript_text}"}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    logger.info(f"✅ Успішно отримано AI-конспект через резервний Groq API ({gm})")
                    return json.loads(content)
                else:
                    logger.warning(f"Groq API ({gm}) повернув помилку {resp.status_code}: {resp.text[:150]}")
        except Exception as e_groq:
            logger.warning(f"Збій запиту до Groq API ({gm}): {e_groq}")
            continue
    return None


async def analyze_lecture_transcript(transcript_text: str, video_title: str = "") -> dict | None:
    """
    Проаналізувати транскрипт лекції.
    Цикл перебору ключів Gemini до талого при помилках 500/503/429/timeout,
    з автоматичним перемиканням на Groq (Llama-3.3-70B) при відмові всіх ключів Google.
    """
    keys = get_ordered_gemini_keys()
    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
    ]
    seen = set()
    models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    prompt_content = f"Назва відео: {video_title}\n\nТранскрипт пари з таймкодами:\n{transcript_text}"

    # 1. Цикл по ключах Gemini (перебір до талого)
    for key_idx, key in enumerate(keys, 1):
        client = genai.Client(api_key=key)
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
                    mark_key_success(key)
                    return json.loads(response.text)
            except asyncio.TimeoutError:
                logger.warning(f"[Ключ #{key_idx} ({key[:8]}...)] Модель {m} перевищила таймаут 50с")
                continue
            except Exception as e_m:
                err_str = str(e_m)
                logger.warning(f"[Ключ #{key_idx} ({key[:8]}...)] Модель {m} повернула помилку: {err_str}")
                continue
        # Якщо обидві моделі на цьому ключі дали збій — перемикаємось на наступний ключ
        advance_to_next_key()

    # 2. Якщо всі ключі Gemini відмовили — звертаємось до резервного Groq (Llama-3.3-70B)
    logger.warning("Усі ключі Gemini вичерпано або вони недоступні. Викликаємо резервний Groq API...")
    groq_result = await analyze_lecture_transcript_groq(transcript_text, video_title=video_title)
    if groq_result:
        return groq_result

    return None


async def analyze_lecture_video(video_url: str, video_title: str = "") -> dict | None:
    """
    Прямий асинхронний аналіз відео з YouTube через мультимодальні можливості Gemini.
    Перебирає всі доступні ключі Gemini до талого при помилках 500, 503, 429.
    """
    keys = get_ordered_gemini_keys()
    if not keys:
        logger.warning("Жодного ключа Gemini не вказано. Прямий аналіз відео пропущено.")
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

    for key_idx, key in enumerate(keys, 1):
        client = genai.Client(api_key=key)
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
                    mark_key_success(key)
                    return json.loads(response.text)
            except asyncio.TimeoutError:
                logger.warning(f"[Відео / Ключ #{key_idx} ({key[:8]}...)] Модель {m} перевищила таймаут 80с")
                continue
            except Exception as e_m:
                err_str = str(e_m)
                logger.warning(f"[Відео / Ключ #{key_idx} ({key[:8]}...)] Модель {m} повернула помилку: {err_str}")
                continue
        advance_to_next_key()

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


async def summarize_assignment_requirements_groq(title: str, description: str, course_name: str = "") -> str | None:
    """
    Резервне створення вижимки завдання через Groq API (Llama-3.3-70b-versatile).
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json"
    }
    prompt = f"Предмет: {course_name}\nНазва завдання: {title}\n\nОпис від викладача:\n{description.strip()}"
    groq_models = [
        os.getenv("GROQ_MODEL", "").strip(),
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
    ]
    seen_g = set()
    candidate_groq_models = [gm for gm in groq_models if gm and not (gm in seen_g or seen_g.add(gm))]

    for gm in candidate_groq_models:
        payload = {
            "model": gm,
            "messages": [
                {"role": "system", "content": ASSIGNMENT_SUMMARY_INSTRUCTION},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 150
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    summary = data["choices"][0]["message"]["content"].strip().replace('"', '')
                    summary = re.sub(r'^(Суть(:|\s)|Вимоги(:|\s)|Завдання(:|\s))\s*', '', summary, flags=re.IGNORECASE)
                    logger.info(f"✅ Створено вижимку завдання через резервний Groq API ({gm})")
                    return summary.strip()
                else:
                    logger.warning(f"Groq API ({gm}) помилка при вижимці завдання ({resp.status_code}): {resp.text[:150]}")
        except Exception as e_groq:
            logger.warning(f"Збій Groq API ({gm}) при вижимці завдання: {e_groq}")
            continue
    return None


async def summarize_assignment_requirements(title: str, description: str, course_name: str = "") -> str:
    """
    Аналізує довгий сирий опис викладача з Classroom та формує лаконічну вижимку вимог у 1-2 речення.
    Працює через Gemini Flash з перебором пулу ключів до талого, а при відмові — перемикається на Groq.
    """
    if not description or len(description.strip()) < 35:
        return description.strip() if description else ""

    prompt = f"Предмет: {course_name}\nНазва завдання: {title}\n\nОпис від викладача:\n{description.strip()}"

    keys = get_ordered_gemini_keys()
    candidate_models = [
        os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip(),
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
    ]
    seen = set()
    models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

    # 1. Спроба через Gemini з перебором усіх ключів
    for key_idx, key in enumerate(keys, 1):
        client = genai.Client(api_key=key)
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
                    mark_key_success(key)
                    summary = response.text.strip().replace('"', '')
                    summary = re.sub(r'^(Суть(:|\s)|Вимоги(:|\s)|Завдання(:|\s))\s*', '', summary, flags=re.IGNORECASE)
                    return summary.strip()
            except Exception as e:
                logger.debug(f"[Завдання / Ключ #{key_idx}] Помилка моделі {m}: {e}")
                continue
        advance_to_next_key()

    # 2. Якщо всі ключі Gemini відмовили — резервний Groq API (Llama-3.3-70B)
    groq_summary = await summarize_assignment_requirements_groq(title, description, course_name)
    if groq_summary:
        return groq_summary

    # 3. Резервний локальний варіант при недоступності API
    clean = re.sub(r'https?://\S+', '', description.strip())
    clean = re.sub(r'\s+', ' ', clean).strip()
    first_part = clean.split('\n')[0].strip()
    return first_part[:180] + ("..." if len(first_part) > 180 else "")




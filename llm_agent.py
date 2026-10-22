import asyncio
import datetime
import json
import logging
import os
import re
import time
import httpx
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """
Ти — провідний академічний AI-конспектер та технічний аналітик для студентської групи ІП-66 КПІ (комп'ютерні науки та інженерія програмного забезпечення).
Твоє завдання — детально і глибоко проаналізувати стенограму (субтитри з таймкодами) або відеозапис університетської пари та скласти повний, змістовний технічний конспект заняття.

Студент, який пропустив пару або повторює матеріал перед іспитом чи лабораторною, повинен отримати вичерпне розуміння всієї теми, розібраних алгоритмів, математичних формул, архітектурних рішень та вимог викладача.

КРИТИЧНО ВАЖЛИВІ ПРАВИЛА:

1. СУВОРА ФІЛЬТРАЦІЯ ОРГАНІЗАЦІЙНОГО ШУМУ:
   - КАТЕГОРИЧНО ЗАБОРОНЕНО переносити в "summary_points" побутові та організаційні балачки з початку чи кінця пари (привітання, перевірка звуку/мікрофона, організація спільного дзвінка з іншими групами на зразок ІП-65, обговорення накладок у розкладі, визначення черговості здачі робіт).
   - Якщо викладач озвучив ОФІЦІЙНЕ важливе рішення для всієї групи (перенесення пари, дата контрольної роботи, формат заліку, додаткова консультація) — занеси це ВИКЛЮЧНО в поле "teacher_announcements".
   - У "summary_points" має потрапити ТІЛЬКИ НАВЧАЛЬНИЙ, ТЕОРЕТИЧНИЙ ТА ПРАКТИЧНИЙ МАТЕРІАЛ заняття!

2. ГЛИБИНА ТА ОБСЯГ "summary_points" (ДЕТАЛЬНИЙ РОЗБІР ЗАНЯТТЯ):
   - Сформуй від 5 до 10 розгорнутих, інформативних пунктів, які послідовно охоплюють УСЮ тривалість заняття від початку навчальної частини до кінця пари.
   - Кожен пункт обов'язково повинен містити:
     а) Орієнтовний таймкод [MM:SS] (якщо в транскрипті є таймкоди).
     б) Чітку технічну назву підтеми/концепції жирним шрифтом (наприклад, **Бінарне дерево пошуку:** або **Метод інтегрування частинами:**).
     в) Детальне змістовне пояснення (2-4 насичені речення):
        * Які саме визначення, правила, теореми, алгоритми чи формули пояснював викладач?
        * Як працює механізм, яка логіка кроків, часова або просторова складність O(...)?
        * Які конкретні приклади коду або математичні задачі розбиралися на екрані?
        * Які типові помилки студентів та практичні нюанси підкреслив викладач?
   - КАТЕГОРИЧНО ЗАБОРОНЕНО писати порожні фрази без конкретики (наприклад: "Викладач розповів про алгоритми", "Обговорення головної тези", "Розглянуто практичні завдання", "Визначення черговості"). Пиши ТЕХНІЧНУ СУТЬ.

3. СПЕЦИФІКА РІЗНИХ ТИПІВ ЗАНЯТЬ:
   - Лекція: системний розбір теорії, алгоритмів, математичних концепцій, класифікацій і доведень.
   - Практика / Лабораторна: розбір завдань, покрокові вимоги до виконання лаб, особливості реалізації, які функції/класи писати, що викладач вимагатиме на захисті.
   - Захист робіт: якщо на парі студенти показували свої програми/звіти, обов'язково зафіксуй у "summary_points", які запитання ставив викладач, які спільні помилки в коді знайшов і як вимагав їх виправляти.

4. ДЕДЛАЙНИ ТА ЗДАЧІ:
   - "deadlines_mentioned": вкажи точну назву роботи, дату дедлайну та точну цитату викладача з таймкодом.
   - "defenses_detected": якщо викладач зарахував роботу студенту (наприклад: "Сінчіневіч зараховано", "Іванов, лабу 2 прийняв"), зафіксуй прізвище, номер лаби, статус "passed", таймкод і цитату.

Відповідай СТРОГО валідним JSON-об'єктом за наступною схемою:
{
  "subject_detected": "Повна офіційна назва дисципліни (наприклад: Алгоритми та структури даних, Основи програмування, Комп'ютерна дискретна математика, Математичний аналіз, Філософія)",
  "topic": "Точна та інформативна тема пари (наприклад: Алгоритми сортування: QuickSort, MergeSort та аналіз складності O(n log n))",
  "summary_points": [
    "[05:20] **Теоретичні основи та визначення:** Детальне пояснення суті концепції, ключові математичні або програмні визначення, навіщо це потрібно...",
    "[18:45] **Алгоритм та логіка роботи:** Покроковий розбір принципу дії, часова складність у найкращому, середньому та найгіршому випадках, граничні умови...",
    "[34:10] **Практичний приклад та аналіз коду:** Як викладач реалізував це на практиці, які структури даних використав, які функції написав...",
    "[52:00] **Типові помилки та підводні камені:** На що звернути увагу при захисті лабораторної, які часті баги виникають, як їх уникати..."
  ],
  "teacher_announcements": [
    "Важливі організаційні оголошення викладача (перенесення пар, контрольні, вимоги до атестації)"
  ],
  "deadlines_mentioned": [
    {
      "task_title": "Назва роботи/лабораторної",
      "date": "Дата дедлайну (якщо названа)",
      "exact_quote": "[MM:SS] Точна фраза викладача про терміни здачі"
    }
  ],
  "defenses_detected": [
    {
      "student_raw_name": "Прізвище або ім'я студента",
      "lab_number": "Лабораторна 1",
      "status": "passed",
      "confidence": 0.95,
      "timestamp": "00:42:15",
      "exact_quote": "Точна фраза викладача про зарахування"
    }
  ]
}
"""

_key_cooldowns: dict[str, float] = {}  # api_key -> timestamp коли спливає кулдаун
DEFAULT_COOLDOWN_SECONDS = 90.0


def parse_retry_delay(err_str: str) -> float:
    """Витягує рекомендований час очікування (retryDelay) з повідомлення про помилку 429 від Google."""
    m = re.search(r'retry in\s+([\d\.]+)\s*s', err_str, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1)) + 5.0
        except ValueError:
            pass
    m2 = re.search(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+)s?['\"]", err_str)
    if m2:
        try:
            return float(m2.group(1)) + 5.0
        except ValueError:
            pass
    return DEFAULT_COOLDOWN_SECONDS


def mark_key_exhausted(api_key: str, cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS):
    """Позначити ключ як такий, що тимчасово вичерпав ліміт, з таймером автоматичного відновлення."""
    global _key_cooldowns
    now = time.time()
    _key_cooldowns[api_key] = now + cooldown_seconds
    masked = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else api_key
    logger.warning(
        f"⏳ Ключ Gemini [{masked}] отримав кулдаун на {int(cooldown_seconds)}с. "
        f"Після завершення таймера бот автоматично повернеться до нього."
    )


def mark_key_success(api_key: str):
    """Позначити ключ як повністю робочий (скинути кулдаун)."""
    global _key_cooldowns
    _key_cooldowns.pop(api_key, None)


def get_gemini_keys() -> list[str]:
    """Отримати список доступних ключів Gemini (підтримка пулу ключів через кому/крапку з комою або один ключ)."""
    raw = os.getenv("GEMINI_API_KEYS", "").strip() or os.getenv("GEMINI_API_KEY", "").strip()
    if not raw:
        return []
    return [k.strip().strip('"\'') for k in re.split(r"[\n,;]", raw) if k.strip().strip('"\'')]


def get_ordered_gemini_keys() -> list[str]:
    """
    Повертає список ключів Gemini у порядку пріоритету:
    1. Спочатку ключі в природному порядку (Ключ 1, Ключ 2, Ключ 3), кулдаун яких уже минув.
    2. Потім ключі, що ще на кулдауні (відсортовані за часом найшвидшого завершення очікування).
    Таким чином, щойно час ліміту спливає (60-90с або після обробки пари), бот завжди автоматично повертається на перший ключ!
    """
    keys = get_gemini_keys()
    if not keys:
        return []

    now = time.time()
    healthy_keys = []
    cooling_keys = []

    for k in keys:
        exp_time = _key_cooldowns.get(k, 0.0)
        if now >= exp_time:
            healthy_keys.append(k)
        else:
            cooling_keys.append((exp_time, k))

    # Сортуємо ті, що охолоджуються, за часом закінчення блокування
    cooling_keys.sort(key=lambda x: x[0])
    return healthy_keys + [k for _, k in cooling_keys]


def advance_to_next_key():
    """Сумісність: викликається якщо всі моделі на ключі вичерпали спроби."""
    pass


def get_gemini_client() -> tuple[genai.Client | None, str]:
    """Сумісність: отримати клієнт для першого доступного ключа."""
    keys = get_ordered_gemini_keys()
    if not keys:
        return None, ""
    k = keys[0]
    return genai.Client(api_key=k), k


def rotate_key(exhausted_key: str = ""):
    """Сумісність: перемкнутися на наступний ключ."""
    if exhausted_key:
        mark_key_exhausted(exhausted_key)


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
                {"role": "user", "content": (
                    f"Назва відеозапису: {video_title}\n\n"
                    f"Транскрипт пари з таймкодами:\n{transcript_text}\n\n"
                    "ВАЖЛИВО:\n"
                    "1. Обов'язково проаналізуй УСЮ пару від початку до кінця (не зупиняйся на перших хвилинах)!\n"
                    "2. Проігноруй вступні організаційні балачки (хто за ким здає, накладки, мікрофони) у 'summary_points'.\n"
                    "3. Склади ДЕТАЛЬНИЙ навчальний конспект у 'summary_points' (5-10 змістовних розгорнутих пунктів із таймкодами [MM:SS], "
                    "назвами підтем жирним шрифтом та конкретним поясненням алгоритмів, формул та прикладів викладача).\n"
                    "4. Офіційні організаційні рішення винеси в 'teacher_announcements'."
                )}
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

    prompt_content = (
        f"Назва відеозапису: {video_title}\n\n"
        f"Транскрипт пари з таймкодами:\n{transcript_text}\n\n"
        "ВАЖЛИВО:\n"
        "1. Обов'язково проаналізуй УСЮ пару від початку до кінця (не зупиняйся на перших хвилинах)!\n"
        "2. Проігноруй вступні організаційні балачки (хто за ким здає, накладки, мікрофони) у 'summary_points'.\n"
        "3. Склади ДЕТАЛЬНИЙ навчальний конспект у 'summary_points' (5-10 змістовних розгорнутих пунктів із таймкодами [MM:SS], "
        "назвами підтем жирним шрифтом та конкретним поясненням алгоритмів, формул та прикладів викладача).\n"
        "4. Офіційні організаційні рішення винеси в 'teacher_announcements'."
    )

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
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    delay = parse_retry_delay(err_str)
                    mark_key_exhausted(key, delay)
                    break
                elif "500" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                    mark_key_exhausted(key, 60.0)
                    break
                continue

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
        (
            f"Назва відеозапису: {video_title}\n\n"
            "Проаналізуй це навчальне заняття відповідно до системної інструкції:\n"
            "1. Обов'язково проаналізуй УСЮ пару від початку до кінця навчальної частини.\n"
            "2. Повністю проігноруй вступні організаційні балачки (спільні заняття, черги здач, мікрофони) у 'summary_points'.\n"
            "3. Склади ДЕТАЛЬНИЙ навчальний конспект у 'summary_points' (5-10 змістовних розгорнутих пунктів із таймкодами, "
            "назвами підтем жирним шрифтом та конкретним поясненням алгоритмів, теорії і прикладів викладача).\n"
            "4. Офіційні рішення щодо перенесень чи контрольних занеси в 'teacher_announcements'.\n"
            "Поверни валідний JSON."
        )
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
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    delay = parse_retry_delay(err_str)
                    mark_key_exhausted(key, delay)
                    break
                elif "500" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                    mark_key_exhausted(key, 60.0)
                    break
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
                err_str = str(e)
                logger.debug(f"[Завдання / Ключ #{key_idx}] Помилка моделі {m}: {err_str}")
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    delay = parse_retry_delay(err_str)
                    mark_key_exhausted(key, delay)
                    break
                elif "500" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                    mark_key_exhausted(key, 60.0)
                    break
                continue

    # 2. Якщо всі ключі Gemini відмовили — резервний Groq API (Llama-3.3-70B)
    groq_summary = await summarize_assignment_requirements_groq(title, description, course_name)
    if groq_summary:
        return groq_summary

    # 3. Резервний локальний варіант при недоступності API
    clean = re.sub(r'https?://\S+', '', description.strip())
    clean = re.sub(r'\s+', ' ', clean).strip()
    first_part = clean.split('\n')[0].strip()
    return first_part[:180] + ("..." if len(first_part) > 180 else "")

# =========================================================================
# 🇬🇧 ENGLISH PRESENTATION Q&A GENERATOR (v3.2)
# =========================================================================

ENGLISH_QA_SYSTEM_INSTRUCTION = """
You are an expert English language coach and academic evaluator preparing KPI university students for technical presentations and defense (English Q&A).
Given a presentation topic and text/slides content, generate 5 to 6 realistic, challenging, and insightful questions that a professor or classmates might ask.
For each question, provide an articulate, well-structured answer in professional English (CEFR B2-C1 level) and a concise, practical tip (in Ukrainian) on how the student should deliver or emphasize this point.

Strictly respond with a valid JSON object following this schema:
{
  "qa_pairs": [
    {
      "question": "Clear and realistic question in English?",
      "answer": "Professional, natural, and comprehensive answer in English (2-4 sentences).",
      "tip": "Практична порада українською мовою щодо інтонації, слайду чи ключових аргументів."
    }
  ]
}
"""


async def generate_english_presentation_qa(topic_title: str, content_text: str) -> list[dict]:
    """
    Генерує 5-6 ймовірних запитань викладача та відповідей на англійській мові (B2-C1)
    з практичними порадами (tips) для захисту презентації.
    Використовує Gemini Key Pool -> Groq API -> розумний демонстраційний фоллбэк.
    """
    topic = (topic_title or "Technical Presentation").strip()
    content = (content_text or "").strip()
    if len(content) > 12000:
        content = content[:12000] + "... [truncated]"

    prompt = f"Topic: {topic}\n\nPresentation / Speech Content:\n{content if content else 'General technical overview.'}"

    # 1. Спроба через пул ключів Gemini
    ordered_keys = get_ordered_gemini_keys()
    candidate_models = [
        "gemini-flash-lite-latest",
        "gemini-flash-latest",
        "gemini-2.5-flash",
    ]

    for key_idx, key in enumerate(ordered_keys, 1):
        client = genai.Client(api_key=key)
        for m in candidate_models:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=ENGLISH_QA_SYSTEM_INSTRUCTION,
                            response_mime_type="application/json",
                            temperature=0.3,
                            max_output_tokens=2048,
                        ),
                    ),
                    timeout=18.0,
                )
                if response and response.text:
                    mark_key_success(key)
                    raw_text = response.text.strip()
                    # Чистимо можливі markdown-блоки
                    raw_text = re.sub(r"^```(json)?\s*", "", raw_text, flags=re.MULTILINE)
                    raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE).strip()
                    parsed = json.loads(raw_text)
                    pairs = parsed.get("qa_pairs") if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
                    if pairs and isinstance(pairs, list):
                        return pairs
            except Exception as e:
                err_str = str(e)
                logger.debug(f"[English Q&A / Key #{key_idx}] Error model {m}: {err_str}")
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    delay = parse_retry_delay(err_str)
                    mark_key_exhausted(key, delay)
                    break
                elif "500" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                    mark_key_exhausted(key, 60.0)
                    break
                continue

    # 2. Резервний виклик через Groq API (Llama-3.3-70B)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            groq_url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": ENGLISH_QA_SYSTEM_INSTRUCTION + "\nReturn ONLY JSON."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
                "max_tokens": 2048
            }
            async with httpx.AsyncClient(timeout=20.0) as http_client:
                r = await http_client.post(groq_url, headers=headers, json=payload)
                if r.status_code == 200:
                    data = r.json()
                    content_str = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content_str)
                    pairs = parsed.get("qa_pairs") if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [])
                    if pairs and isinstance(pairs, list):
                        return pairs
        except Exception as e:
            logger.warning(f"Groq English Q&A fallback error: {e}")

    # 3. Надійний інтелектуальний фоллбек на випадок відсутності або лімітів API
    return [
        {
            "question": f"Could you elaborate on the core problem statement addressed in your presentation on {topic}?",
            "answer": f"Our primary goal is to address the practical limitations of conventional workflows regarding {topic}. By systematically analyzing both theoretical principles and experimental results, we demonstrate that modern architectural patterns yield superior throughput and maintainability.",
            "tip": "Впевнено почніть із вступної тези: чітко зв'яжіть проблему з першим слайдом вашої презентації."
        },
        {
            "question": "What criteria did you use to evaluate the performance or feasibility of the proposed approach?",
            "answer": "We focused on key performance metrics such as latency, computational complexity, and resource utilization. Comparative evaluation against baseline benchmarks confirmed notable efficiency gains without sacrificing code readability.",
            "tip": "Зверніть увагу екзаменатора на порівняльні графіки або таблиці з результатами тестів."
        },
        {
            "question": "What trade-offs or technical constraints did you have to consider during implementation?",
            "answer": "The most significant trade-off involved memory consumption versus processing speed. In our design, we opted for an optimized indexing strategy that slightly increased upfront memory allocation in exchange for constant-time lookup capabilities.",
            "tip": "Використовуйте конструкції ввічливості: «That's a very perceptive question. Indeed, we had to balance...»"
        },
        {
            "question": "How does your solution handle potential edge cases or unexpected input anomalies?",
            "answer": "We incorporated strict validation pipelines and fallback strategies at every boundary layer. When an anomalous pattern is detected, the system degrades gracefully and logs diagnostic metrics for root-cause analysis.",
            "tip": "Поясніть надійність системи та захист від помилок (graceful degradation, fallback, input sanitization)."
        },
        {
            "question": "If you were given additional time to extend this project, what would be your next priority?",
            "answer": "Our immediate next step would be deploying micro-benchmarks across distributed nodes and conducting user studies to refine interactive ergonomics and API ergonomics.",
            "tip": "Завершіть на позитивній ноті про масштабування та подальший розвиток проекту."
        }
    ]


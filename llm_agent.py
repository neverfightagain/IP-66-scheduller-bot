import asyncio
import json
import logging
import os
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

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


async def analyze_lecture_transcript(transcript_text: str, video_title: str = "") -> dict | None:
    """
    Проаналізувати транскрипт лекції за допомогою Gemini Flash (повністю асинхронно).
    Повертає структурований словник з конспектом та анонсами.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY не вказаний у .env. Аналіз лекцій пропущено.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt_content = f"Назва відео: {video_title}\n\nТранскрипт пари з таймкодами:\n{transcript_text}"

        candidate_models = [
            os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
        ]
        # Видаляємо дублікати зберігаючи порядок
        seen = set()
        models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

        response = None
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
                    break
            except asyncio.TimeoutError:
                logger.warning(f"Модель {m} перевищила таймаут 50с при аналізі транскрипту")
                continue
            except Exception as e_m:
                logger.warning(f"Модель {m} повернула помилку при аналізі транскрипту: {e_m}")
                await asyncio.sleep(2)
                continue

        if not response or not response.text:
            return None

        result_json = json.loads(response.text)
        return result_json
    except Exception as e:
        logger.error(f"Помилка при аналізі лекції через Gemini API: {e}")
        return None


async def analyze_lecture_video(video_url: str, video_title: str = "") -> dict | None:
    """
    Прямий асинхронний аналіз відео з YouTube через мультимодальні можливості Gemini.
    Працює без парсингу субтитрів та без потреби в проксі (Google сам отримує відео на своїх серверах).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY не вказаний у .env. Прямий аналіз відео пропущено.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt_parts = [
            types.Part.from_uri(file_uri=video_url, mime_type="video/mp4"),
            f"Назва відео: {video_title}\n\nПроаналізуй це навчальне заняття відповідно до системної інструкції та поверни структурований JSON."
        ]

        candidate_models = [
            os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
        ]
        seen = set()
        models = [m for m in candidate_models if m and not (m in seen or seen.add(m))]

        response = None
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
                    timeout=85.0,
                )
                if response and response.text:
                    break
            except asyncio.TimeoutError:
                logger.warning(f"Модель {m} перевищила таймаут 85с при прямому аналізі відео")
                continue
            except Exception as e_m:
                logger.warning(f"Модель {m} повернула помилку при аналізі відео: {e_m}")
                await asyncio.sleep(2)
                continue

        if not response or not response.text:
            return None

        result_json = json.loads(response.text)
        return result_json
    except Exception as e:
        logger.error(f"Помилка при прямому аналізі відео {video_url} через Gemini: {e}")
        return None



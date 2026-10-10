import json
import logging
import os
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

SYSTEM_INSTRUCTION = """
Ти — академічний аналітичний AI-асистент для студентської групи ІП-66 КПІ.
Твоє завдання — уважно проаналізувати стенограму (субтитри з таймкодами) університетської пари та скласти чітку структуровану вижимку для одногрупників.

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
    Проанализировать транскрипт лекции с помощью Gemini Flash.
    Возвращает структурированный словарь с конспектом и анонсами.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY не вказаний у .env. Аналіз лекцій пропущено.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        prompt_content = f"Назва відео: {video_title}\n\nТранскрипт пари з таймкодами:\n{transcript_text}"

        # Используем Gemini 2.5 Flash с принудительным форматом JSON
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_content,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
            ),
        )

        result_json = json.loads(response.text)
        return result_json
    except Exception as e:
        logger.error(f"Помилка при аналізі лекції через Gemini API: {e}")
        return None

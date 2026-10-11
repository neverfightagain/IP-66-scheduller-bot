# Шедулєр ІП-66 (KPI Schedule & AI Assistant Bot v2.0) 🎓🤖

Сучасний асинхронний Telegram-бот для студентської групи **ІП-66** ФІОТ КПІ ім. Ігоря Сікорського. Поєднує офіційний розклад пар КПІ, інтеграцію з **Google Classroom**, моніторинг лекцій на **YouTube** з автоматичними AI-конспектами на базі **Google Gemini**, а також щоденні адаптивні підсумки.

---

## ✨ Основні можливості

* 📅 **Офіційний розклад КПІ**:
  * Пряма інтеграція з API розкладу КПІ (`schedule.kpi.ua`) для групи `ІП-66` (ID: `6084`).
  * Підтримка розкладу на сьогодні, на завтра та визначення навчального тижня (чисельник/знаменник).
  * Збережені постійні посилання на Zoom, Google Meet та Microsoft Teams.

* 🔔 **Розумні автоматичні сповіщення**:
  * ☀️ **08:00 (Пн–Сб)** — ранковий дайджест пар на день із кнопками швидкого переходу.
  * ⏰ **За 20 хв та 5 хв** до початку кожної пари — сповіщення з посиланням на заняття.
  * 🧹 **Автоматичне очищення**: нагадування перед парою автоматично видаляються через 20 хвилин, щоб не засмічувати чат групи.

* 📚 **Інтеграція з Google Classroom**:
  * Фоновий моніторинг курсів групи кожні **15 хвилин**.
  * Миттєві сповіщення в чат при появі нового завдання від викладача з прямим посиланням.
  * **Радар дедлайнів (`/deadlines`)**: структуроване сортування залишку часу (палаючі, на тиждень, довгострокові та завдання без фіксованого терміну).
  * Команда `/sync` та інлайн-кнопка для миттєвої ручної синхронізації.

* 🎬 **YouTube-лекторій + Gemini AI конспекти**:
  * Моніторинг студентського каналу [`@ip-66_studio`](https://www.youtube.com/@ip-66_studio) кожні **30 хвилин**.
  * Автоматичне вилучення субтитрів (`youtube-transcript-api`).
  * Нейромережевий аналіз через **Google Gemini** (`gemini-3.5-flash-lite` / `gemini-3.8-flash`):
    * Тема та стислі тези лекції.
    * Оголошення викладача.
    * Згадані дедлайни та вимоги до робіт.
  * Публікація естетичної картки-конспекту в чат із кнопкою перегляду відео.

* 🌙 **Адаптивний підсумок дня (`/summary`)**:
  * Автопостинг о **21:00** у будні (пари, що пройшли, що задали, анонси та палаючі дедлайни).
  * Автопостинг о **10:00** у вихідні (статус відпочинку, розклад на понеділок та дедлайни на наступний тиждень).

* 🗄 **Надійна база даних (SQLite + aiosqlite)**:
  * Повна заміна JSON-файлів на транзакційну SQLite базу даних з WAL-режимом.
  * Таблиці: курси, налаштування чатів, завдання Classroom, оброблені відео YouTube, оголошення викладачів.

* 🌐 **Cloud-Ready (Render / Azure / Koyeb)**:
  * Вбудований легкозважений HTTP health-check сервер на порті `$PORT` (10000) для запобігання засинанню на безкоштовних тарифах хмарних хостингів.

---

## 📋 Повний список команд бота

| Команда | Опис |
| :--- | :--- |
| **`/today`** | Розклад пар на сьогодні з кнопками швидкого переходу на пару |
| **`/tomorrow`** | Розклад пар на завтра |
| **`/week`** | Поточний навчальний тиждень (1 чи 2) та київський час |
| **`/links`** | Список збережених посилань на дистанційні заняття (Zoom/Meet/Teams) |
| **`/deadlines`** | Радар активних дедлайнів із Google Classroom та ручних завдань |
| **`/summary`** *(або `/evening`)* | Розумний підсумок дня (пари, завдання, оголошення та статус дедлайнів) |
| **`/sync`** | Ручна синхронізація з Google Classroom та звіт про стан курсів |
| **`/adddeadline`** | Додати власне завдання: `Предмет \| Назва \| РРРР-ММ-ДД HH:MM \| Опис` |
| **`/deldeadline`** | Видалити або позначити завдання як виконане: `/deldeadline <id>` |
| **`/subscribe`** | Увімкнути автоматичні сповіщення для поточного чату/групи |
| **`/unsubscribe`** | Призупинити автоматичні сповіщення для цього чату |
| **`/help`** | Повна довідка з описом усіх можливостей |

---

## ⚙️ Змінні середовища (Environment Variables)

Створіть файл `.env` у корені проєкту (або додайте змінні в розділі **Environment** на хмарному хостингу):

```env
# 1. Токен вашого Telegram-бота від @BotFather
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# 2. ID групи в базі розкладу КПІ (6084 = ІП-66)
KPI_GROUP_ID=6084

# 3. ID основного групового чату в Telegram
CHAT_ID=-1001234567890

# 4. Часовий пояс (для розрахунку пар та сповіщень)
TIMEZONE=Europe/Kyiv

# 5. Час надсилання ранкового дайджесту
MORNING_DIGEST_TIME=08:00

# 6. За скільки хвилин до пари надсилати нагадування
NOTIFY_MINUTES_BEFORE=5

# 7. Google AI Studio API-ключ для аналізу лекцій
GEMINI_API_KEY=AIzaSy...your_gemini_api_key_here

# 8. Модель Gemini (рекомендовано: gemini-3.5-flash-lite)
GEMINI_MODEL=gemini-3.5-flash-lite

# 9. ID YouTube-каналу зі збереженими лекціями (@ip-66_studio)
YOUTUBE_CHANNEL_ID=UC8pccc2zKBP6vrOlA1hWFBw

# 10. Повний JSON токена OAuth2 для Google Classroom (для роботи в хмарі без локального token.json)
GOOGLE_TOKEN_JSON={"token": "ya29...", "refresh_token": "1//03...", ...}
```

---

## 🚀 Встановлення та запуск

### Варіант 1: Локальний запуск (Windows / Linux / macOS)

1. **Клонуйте репозиторій:**
   ```bash
   git clone https://github.com/neverfightagain/IP-66-scheduller-bot.git
   cd IP-66-scheduller-bot
   ```

2. **Створіть віртуальне оточення та встановіть залежності:**
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Створіть та налаштуйте `.env`** (за прикладом вище).

4. **Запустіть бота:**
   ```bash
   python bot.py
   ```

---

### Варіант 2: Розгортання на Render (Cloud Web Service)

1. Створіть новий **Web Service** на [Render.com](https://render.com).
2. Підключіть репозиторій `IP-66-scheduller-bot`.
3. Налаштування збірки:
   * **Runtime**: `Python 3`
   * **Build Command**: `pip install -r requirements.txt`
   * **Start Command**: `python bot.py`
4. У розділі **Environment** додайте змінні середовища із таблиці вище (включаючи `GOOGLE_TOKEN_JSON`).
5. Натисніть **Deploy Web Service**. Вбудований health-check на порті `10000` забезпечить стабільну роботу сервісу.

---

### Варіант 3: Розгортання на Azure VM (Ubuntu Linux)

Для постійного хостингу без обмежень безкоштовного тарифу (збереження локальної SQLite БД без скидання диска):

1. Створіть віртуальну машину **Ubuntu 24.04 LTS** (наприклад, розмір `Standard_B1s`).
2. Підключіться по SSH та встановіть необхідні пакети:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git
   ```
3. Клонуйте проєкт і встановіть оточення:
   ```bash
   git clone https://github.com/neverfightagain/IP-66-scheduller-bot.git /opt/kpi_bot
   cd /opt/kpi_bot
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   cp .env.example .env # вкажіть ваші змінні
   ```
4. Налаштуйте автозапуск через **systemd**:
   Створіть `/etc/systemd/system/kpi_bot.service`:
   ```ini
   [Unit]
   Description=KPI Schedule & AI Assistant Bot (IP-66)
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/opt/kpi_bot
   ExecStart=/opt/kpi_bot/venv/bin/python bot.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```
5. Запустіть сервіс:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now kpi_bot
   ```

---

## 📂 Структура проєкту

```text
├── bot.py                  # Точка входу: ініціалізація aiogram 3, HTTP health-check, запуск поллінгу
├── config.py               # Завантаження та валідація конфігурацій і токенів із .env
├── handlers.py             # Обробники команд Telegram (/today, /deadlines, /summary, /sync тощо)
├── scheduler.py            # Планувальник APScheduler: ранкові дайджести, нагадування, моніторинг
├── database.py             # Асинхронний шар SQLite (aiosqlite) з автоматичними міграціями
├── classroom_sync.py       # Модуль інтеграції з Google Classroom API (курси, завдання, дедлайни)
├── youtube_processor.py    # Моніторинг YouTube RSS, субтитри та інтеграція конспектів
├── llm_agent.py            # AI-агент на Google GenAI SDK (Gemini 3.5 Flash Lite)
├── formatters.py           # Форматування красивих повідомлень, радарів та карток для Telegram
├── kpi_api.py              # Клієнт до офіційного API розкладу КПІ
├── links_manager.py        # Менеджер збережених посилань на пари
├── requirements.txt        # Список бібліотек Python
└── README.md               # Документація проєкту
```

---

## 👥 Спільнота та підтримка

Бот розроблено спеціально для студентів групи **ІП-66** ФІОТ НТУУ «КПІ ім. Ігоря Сікорського».  
З питаннями щодо роботи чи пропозиціями звертайтесь до старости або розробників бота в груповому чаті.

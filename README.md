# Quiz Telegram Bot

Telegram-бот для подготовки к экзаменам и проверки знаний.

## 🚀 Возможности

* 📝 Обычный тест по темам
* 🧪 Режим экзамена
* 🎯 Выбор категории, темы, сложности и количества вопросов
* 📊 Статистика пользователя
* 💾 Сохранение результатов в JSON
* 📚 Поддержка разных направлений:

  * Программирование
  * Медицина

## 🛠 Стек

* Python
* python-telegram-bot
* JSON

## 📁 Структура проекта

* `bot.py` — основной код бота
* `questions.json` — база вопросов
* `user_stats.json` — статистика пользователей
* `attempts.json` — история попыток
* `admins.json` — список Telegram ID админов
* `requirements.txt` — зависимости

## ▶️ Локальный запуск

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Установить токен бота

❗ Токен не хранится в коде — используется переменная окружения

#### Windows CMD

```cmd
set BOT_TOKEN=YOUR_BOT_TOKEN
python bot.py
```

#### PowerShell

```powershell
$env:BOT_TOKEN="YOUR_BOT_TOKEN"
python bot.py
```

#### Linux / macOS

```bash
export BOT_TOKEN=YOUR_BOT_TOKEN
python bot.py
```

## ☁️ Деплой (Railway)

1. Загрузить проект на GitHub
2. Подключить репозиторий к Railway
3. Указать команду запуска:

```bash
python bot.py
```

4. Добавить переменную окружения:

```text
BOT_TOKEN=YOUR_BOT_TOKEN
```

## 🔒 Безопасность

* Токен бота НЕ хранится в коде
* Используются переменные окружения
* JSON-файлы не содержат чувствительных данных

## 📌 Автор

Проект для обучения и практики.

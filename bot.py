import json
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

QUESTIONS_FILE = Path("questions.json")
USER_STATS_FILE = Path("user_stats.json")
ATTEMPTS_FILE = Path("attempts.json")
ADMINS_FILE = Path("admins.json")

EXAM_QUESTION_COUNT = 10
EXAM_DURATION_MINUTES = 15


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        logging.exception("Failed to load file: %s", path)
        return default


def save_json_file(path: Path, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except OSError:
        logging.exception("Failed to save file: %s", path)


def load_admin_ids() -> set[int]:
    raw = load_json_file(ADMINS_FILE, [])
    if not isinstance(raw, list):
        return set()

    result = set()
    for item in raw:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return result


ADMIN_IDS = load_admin_ids()


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id in ADMIN_IDS)


def load_questions() -> dict[str, dict[str, list[dict[str, Any]]]]:
    raw = load_json_file(QUESTIONS_FILE, {})

    if not isinstance(raw, dict):
        return {}

    valid_data: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for category, topics in raw.items():
        if not isinstance(category, str) or not isinstance(topics, dict):
            continue

        valid_topics: dict[str, list[dict[str, Any]]] = {}

        for topic, questions in topics.items():
            if not isinstance(topic, str) or not isinstance(questions, list):
                continue

            valid_questions = []
            for item in questions:
                if not isinstance(item, dict):
                    continue

                question = item.get("question")
                options = item.get("options")
                answer = item.get("answer")
                difficulty = item.get("difficulty", "easy")

                if (
                    isinstance(question, str)
                    and isinstance(options, list)
                    and all(isinstance(opt, str) for opt in options)
                    and isinstance(answer, str)
                    and answer in options
                    and isinstance(difficulty, str)
                    and difficulty in {"easy", "medium", "hard"}
                    and len(options) >= 2
                ):
                    valid_questions.append(
                        {
                            "question": question,
                            "options": options,
                            "answer": answer,
                            "difficulty": difficulty,
                        }
                    )

            if valid_questions:
                valid_topics[topic] = valid_questions

        if valid_topics:
            valid_data[category] = valid_topics

    return valid_data


def save_questions(data: dict[str, dict[str, list[dict[str, Any]]]]) -> None:
    save_json_file(QUESTIONS_FILE, data)


QUESTIONS = load_questions()


def get_category_names() -> list[str]:
    return list(QUESTIONS.keys())


def get_topic_names(category: str) -> list[str]:
    return list(QUESTIONS.get(category, {}).keys())


def get_category_by_index(index_str: str) -> str | None:
    try:
        index = int(index_str)
    except ValueError:
        return None

    categories = get_category_names()
    if 0 <= index < len(categories):
        return categories[index]
    return None


def get_topic_by_index(category: str, index_str: str) -> str | None:
    try:
        index = int(index_str)
    except ValueError:
        return None

    topics = get_topic_names(category)
    if 0 <= index < len(topics):
        return topics[index]
    return None


def get_user_key(update: Update) -> str:
    user = update.effective_user
    return str(user.id) if user else "unknown"


def get_user_display_name(update: Update) -> str:
    user = update.effective_user
    if not user:
        return "Unknown User"
    return user.full_name or user.username or str(user.id)


def load_all_user_stats() -> dict[str, Any]:
    data = load_json_file(USER_STATS_FILE, {})
    return data if isinstance(data, dict) else {}


def save_all_user_stats(data: dict[str, Any]) -> None:
    save_json_file(USER_STATS_FILE, data)


def load_attempts() -> list[dict[str, Any]]:
    data = load_json_file(ATTEMPTS_FILE, [])
    return data if isinstance(data, list) else []


def save_attempts(data: list[dict[str, Any]]) -> None:
    save_json_file(ATTEMPTS_FILE, data)


def ensure_user_stats_record(user_id: str, user_name: str) -> dict[str, Any]:
    all_stats = load_all_user_stats()

    if user_id not in all_stats:
        all_stats[user_id] = {
            "user_name": user_name,
            "tests_completed": 0,
            "questions_answered": 0,
            "correct_answers": 0,
            "current_streak": 0,
            "best_streak": 0,
            "topics": {},
            "exams_completed": 0,
            "exam_questions_answered": 0,
            "exam_correct_answers": 0,
            "best_exam_percent": 0,
        }
    else:
        all_stats[user_id]["user_name"] = user_name

    save_all_user_stats(all_stats)
    return all_stats[user_id]


def ensure_topic_stats_record(stats: dict[str, Any], topic: str) -> None:
    if "topics" not in stats:
        stats["topics"] = {}

    if topic not in stats["topics"]:
        stats["topics"][topic] = {
            "answered": 0,
            "correct": 0,
            "tests_completed": 0,
        }


def update_answer_stats_persistent(
    user_id: str,
    user_name: str,
    topic: str,
    is_correct: bool,
) -> None:
    all_stats = load_all_user_stats()
    user_stats = all_stats.get(user_id)

    if not user_stats:
        user_stats = {
            "user_name": user_name,
            "tests_completed": 0,
            "questions_answered": 0,
            "correct_answers": 0,
            "current_streak": 0,
            "best_streak": 0,
            "topics": {},
            "exams_completed": 0,
            "exam_questions_answered": 0,
            "exam_correct_answers": 0,
            "best_exam_percent": 0,
        }
        all_stats[user_id] = user_stats

    user_stats["user_name"] = user_name
    ensure_topic_stats_record(user_stats, topic)

    topic_stats = user_stats["topics"][topic]
    user_stats["questions_answered"] += 1
    topic_stats["answered"] += 1

    if is_correct:
        user_stats["correct_answers"] += 1
        topic_stats["correct"] += 1
        user_stats["current_streak"] += 1
        if user_stats["current_streak"] > user_stats["best_streak"]:
            user_stats["best_streak"] = user_stats["current_streak"]
    else:
        user_stats["current_streak"] = 0

    save_all_user_stats(all_stats)


def update_completed_test_stats_persistent(
    user_id: str,
    user_name: str,
    topic: str,
) -> None:
    all_stats = load_all_user_stats()
    user_stats = all_stats.get(user_id)

    if not user_stats:
        user_stats = {
            "user_name": user_name,
            "tests_completed": 0,
            "questions_answered": 0,
            "correct_answers": 0,
            "current_streak": 0,
            "best_streak": 0,
            "topics": {},
            "exams_completed": 0,
            "exam_questions_answered": 0,
            "exam_correct_answers": 0,
            "best_exam_percent": 0,
        }
        all_stats[user_id] = user_stats

    user_stats["user_name"] = user_name
    ensure_topic_stats_record(user_stats, topic)

    user_stats["tests_completed"] += 1
    user_stats["topics"][topic]["tests_completed"] += 1

    save_all_user_stats(all_stats)


def update_exam_answer_stats_persistent(
    user_id: str,
    user_name: str,
    is_correct: bool,
) -> None:
    all_stats = load_all_user_stats()
    user_stats = all_stats.get(user_id)

    if not user_stats:
        user_stats = {
            "user_name": user_name,
            "tests_completed": 0,
            "questions_answered": 0,
            "correct_answers": 0,
            "current_streak": 0,
            "best_streak": 0,
            "topics": {},
            "exams_completed": 0,
            "exam_questions_answered": 0,
            "exam_correct_answers": 0,
            "best_exam_percent": 0,
        }
        all_stats[user_id] = user_stats

    user_stats["user_name"] = user_name
    user_stats["exam_questions_answered"] += 1
    if is_correct:
        user_stats["exam_correct_answers"] += 1

    save_all_user_stats(all_stats)


def update_completed_exam_stats_persistent(
    user_id: str,
    user_name: str,
    percent: int,
) -> None:
    all_stats = load_all_user_stats()
    user_stats = all_stats.get(user_id)

    if not user_stats:
        user_stats = {
            "user_name": user_name,
            "tests_completed": 0,
            "questions_answered": 0,
            "correct_answers": 0,
            "current_streak": 0,
            "best_streak": 0,
            "topics": {},
            "exams_completed": 0,
            "exam_questions_answered": 0,
            "exam_correct_answers": 0,
            "best_exam_percent": 0,
        }
        all_stats[user_id] = user_stats

    user_stats["user_name"] = user_name
    user_stats["exams_completed"] += 1
    if percent > user_stats.get("best_exam_percent", 0):
        user_stats["best_exam_percent"] = percent

    save_all_user_stats(all_stats)


def save_attempt_record(
    user_id: str,
    user_name: str,
    category: str,
    topic: str,
    difficulty: str,
    score: int,
    total: int,
    percent: int,
    grade: str,
    mode: str = "test",
) -> None:
    attempts = load_attempts()

    attempts.append(
        {
            "user_id": user_id,
            "user_name": user_name,
            "category": category,
            "topic": topic,
            "difficulty": difficulty,
            "score": score,
            "total": total,
            "percent": percent,
            "grade": grade,
            "mode": mode,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )

    save_attempts(attempts)


def get_user_stats(user_id: str, user_name: str) -> dict[str, Any]:
    all_stats = load_all_user_stats()

    if user_id not in all_stats:
        all_stats[user_id] = {
            "user_name": user_name,
            "tests_completed": 0,
            "questions_answered": 0,
            "correct_answers": 0,
            "current_streak": 0,
            "best_streak": 0,
            "topics": {},
            "exams_completed": 0,
            "exam_questions_answered": 0,
            "exam_correct_answers": 0,
            "best_exam_percent": 0,
        }
        save_all_user_stats(all_stats)

    all_stats[user_id]["user_name"] = user_name
    save_all_user_stats(all_stats)
    return all_stats[user_id]


def get_best_and_worst_topics(stats: dict[str, Any]) -> tuple[str, str]:
    topics = stats.get("topics", {})

    if not topics:
        return "—", "—"

    topic_percents = []
    for topic, data in topics.items():
        answered = data.get("answered", 0)
        correct = data.get("correct", 0)
        percent = round((correct / answered) * 100) if answered > 0 else 0
        topic_percents.append((topic, percent))

    best_topic = max(topic_percents, key=lambda x: x[1])[0]
    worst_topic = min(topic_percents, key=lambda x: x[1])[0]

    return best_topic, worst_topic


def build_topic_stats_text(stats: dict[str, Any]) -> str:
    topics = stats.get("topics", {})

    if not topics:
        return "Пока нет данных по темам."

    lines = []
    for topic, data in topics.items():
        answered = data.get("answered", 0)
        correct = data.get("correct", 0)
        tests_completed = data.get("tests_completed", 0)
        percent = round((correct / answered) * 100) if answered > 0 else 0

        lines.append(
            f"• {topic.capitalize()}: {correct}/{answered} ({percent}%), тестов: {tests_completed}"
        )

    return "\n".join(lines)


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📝 Обычный тест", callback_data="menu:test")],
        [InlineKeyboardButton("🧪 Экзамен", callback_data="menu:exam")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu:stats")],
        [InlineKeyboardButton("📚 Темы", callback_data="menu:topics")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_finish_keyboard(mode: str = "test") -> InlineKeyboardMarkup:
    restart_callback = "menu:exam" if mode == "exam" else "menu:test"

    keyboard = [
        [InlineKeyboardButton("🔁 Пройти ещё раз", callback_data=restart_callback)],
        [InlineKeyboardButton("📚 Другая тема", callback_data="menu:test")],
        [InlineKeyboardButton("📊 Статистика", callback_data="menu:stats")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_categories_keyboard(prefix: str = "category") -> InlineKeyboardMarkup:
    keyboard = []
    for index, category in enumerate(get_category_names()):
        keyboard.append(
            [InlineKeyboardButton(category, callback_data=f"{prefix}:{index}")]
        )
    return InlineKeyboardMarkup(keyboard)


def build_topics_keyboard(category: str, prefix: str = "topic") -> InlineKeyboardMarkup:
    keyboard = []
    for index, topic in enumerate(get_topic_names(category)):
        keyboard.append(
            [InlineKeyboardButton(topic.capitalize(), callback_data=f"{prefix}:{index}")]
        )

    keyboard.append(
        [InlineKeyboardButton("⬅️ Назад к категориям", callback_data=f"back:categories|{prefix}")]
    )
    return InlineKeyboardMarkup(keyboard)


def build_difficulty_keyboard(category: str, topic: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Easy", callback_data="difficulty:easy")],
        [InlineKeyboardButton("Medium", callback_data="difficulty:medium")],
        [InlineKeyboardButton("Hard", callback_data="difficulty:hard")],
        [InlineKeyboardButton("All", callback_data="difficulty:all")],
        [InlineKeyboardButton("⬅️ Назад к темам", callback_data="back:topics")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_question_count_keyboard(category: str, topic: str, difficulty: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("5", callback_data="count:5")],
        [InlineKeyboardButton("10", callback_data="count:10")],
        [InlineKeyboardButton("15", callback_data="count:15")],
        [InlineKeyboardButton("Все доступные", callback_data="count:all")],
        [InlineKeyboardButton("⬅️ Назад к сложности", callback_data="back:difficulty")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(option, callback_data=f"answer:{option}")]
        for option in options
    ]
    return InlineKeyboardMarkup(keyboard)


def get_grade(percent: int) -> str:
    if percent >= 90:
        return "Отлично"
    if percent >= 75:
        return "Хорошо"
    if percent >= 60:
        return "Зачёт"
    return "Незачёт"


def clear_quiz_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    keys_to_remove = [
        "category",
        "topic",
        "difficulty",
        "questions",
        "current_index",
        "score",
        "answered_message_ids",
        "quiz_active",
        "question_limit",
        "mode",
        "exam_end_time",
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)


def clear_add_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    keys_to_remove = [
        "add_state",
        "new_question_category",
        "new_question_topic",
        "new_question_text",
        "new_question_options",
        "new_question_answer",
        "new_question_difficulty",
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)


def filter_questions_by_difficulty(
    questions: list[dict[str, Any]],
    difficulty: str,
) -> list[dict[str, Any]]:
    if difficulty == "all":
        return questions[:]
    return [q for q in questions if q.get("difficulty") == difficulty]


def exam_time_left_text(end_time_iso: str) -> str:
    try:
        end_time = datetime.fromisoformat(end_time_iso)
        remaining = end_time - datetime.now()
        if remaining.total_seconds() <= 0:
            return "0 мин 0 сек"
        minutes = int(remaining.total_seconds() // 60)
        seconds = int(remaining.total_seconds() % 60)
        return f"{minutes} мин {seconds} сек"
    except Exception:
        return "—"


async def finish_exam_due_timeout(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    score = context.user_data.get("score", 0)
    questions = context.user_data.get("questions", [])
    total = len(questions)
    percent = round((score / total) * 100) if total > 0 else 0
    grade = get_grade(percent)

    category = context.user_data.get("category", "Неизвестно")
    topic = context.user_data.get("topic", "unknown")
    user_id = str(context.user_data.get("telegram_user_id", "unknown"))
    user_name = context.user_data.get("telegram_user_name", "Unknown User")

    update_completed_exam_stats_persistent(user_id, user_name, percent)
    save_attempt_record(
        user_id=user_id,
        user_name=user_name,
        category=category,
        topic=topic,
        difficulty="exam",
        score=score,
        total=total,
        percent=percent,
        grade=grade,
        mode="exam",
    )

    context.user_data["quiz_active"] = False

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "⏰ *Время экзамена вышло!*\n\n"
            f"📂 Категория: {category}\n"
            f"📘 Тема: {topic.capitalize()}\n"
            f"✅ Правильных ответов: {score}/{total}\n"
            f"📊 Результат: {percent}%\n"
            f"🎓 Оценка: *{grade}*"
        ),
        parse_mode="Markdown",
        reply_markup=build_finish_keyboard("exam"),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_quiz_session(context)
    clear_add_state(context)

    if not QUESTIONS:
        await update.message.reply_text(
            "⚠️ Вопросы пока не загружены.\nПроверь файл questions.json и попробуй снова."
        )
        return

    user_id = get_user_key(update)
    user_name = get_user_display_name(update)
    ensure_user_stats_record(user_id, user_name)

    text = (
        "👋 Добро пожаловать в *Quiz Telegram Bot*!\n\n"
        "Я помогу тебе:\n"
        "• проверить знания в формате теста\n"
        "• пройти экзаменационный режим\n"
        "• посмотреть статистику результатов\n\n"
        "Выбери, что хочешь сделать:"
    )

    await update.message.reply_text(
        text,
        reply_markup=build_main_menu_keyboard(),
        parse_mode="Markdown",
    )


async def exam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_quiz_session(context)
    clear_add_state(context)

    if not QUESTIONS:
        await update.message.reply_text(
            "⚠️ Вопросы пока не загружены.\nПроверь файл questions.json и попробуй снова."
        )
        return

    user_id = get_user_key(update)
    user_name = get_user_display_name(update)
    ensure_user_stats_record(user_id, user_name)

    context.user_data["mode"] = "exam"

    text = (
        "🧪 *Режим экзамена*\n\n"
        f"• Количество вопросов: {EXAM_QUESTION_COUNT}\n"
        f"• Время: {EXAM_DURATION_MINUTES} минут\n"
        "• Сброс во время экзамена запрещён\n\n"
        "🏫 Выбери категорию:"
    )

    await update.message.reply_text(
        text,
        reply_markup=build_categories_keyboard("examcategory"),
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📌 *Команды бота*\n\n"
        "📝 /start — открыть главное меню\n"
        "🧪 /exam — начать экзамен\n"
        "📊 /stats — посмотреть статистику\n"
        "🔄 /reset — сбросить текущую сессию\n"
        "ℹ️ /help — помощь\n"
        "❌ /cancel — отменить добавление вопроса\n\n"
        "*Админ-команды:*\n"
        "➕ /add — добавить вопрос\n"
        "📚 /topics — список категорий и тем\n"
        "📊 /questions — количество вопросов"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("quiz_active") and context.user_data.get("mode") == "exam":
        await update.message.reply_text(
            "⛔ Во время экзамена нельзя использовать /reset.\n"
            "Заверши экзамен или дождись окончания времени."
        )
        return

    was_active = context.user_data.get("quiz_active", False)
    clear_quiz_session(context)

    if was_active:
        await update.message.reply_text(
            "🔄 Текущая сессия сброшена.\nНажми /start, чтобы начать заново."
        )
    else:
        await update.message.reply_text(
            "ℹ️ Активной сессии не было.\nНажми /start, чтобы начать тест."
        )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_key(update)
    user_name = get_user_display_name(update)
    stats = get_user_stats(user_id, user_name)

    total_answered = stats.get("questions_answered", 0)
    total_correct = stats.get("correct_answers", 0)
    total_tests = stats.get("tests_completed", 0)
    total_percent = round((total_correct / total_answered) * 100) if total_answered > 0 else 0

    exam_answered = stats.get("exam_questions_answered", 0)
    exam_correct = stats.get("exam_correct_answers", 0)
    exam_percent = round((exam_correct / exam_answered) * 100) if exam_answered > 0 else 0

    best_topic, worst_topic = get_best_and_worst_topics(stats)
    topic_stats_text = build_topic_stats_text(stats)

    text = (
        "📊 Твоя статистика\n\n"
        "📝 Тесты\n"
        f"• Пройдено тестов: {total_tests}\n"
        f"• Всего отвечено вопросов: {total_answered}\n"
        f"• Правильных ответов: {total_correct}\n"
        f"• Общий процент: {total_percent}%\n"
        f"• Текущая серия: {stats.get('current_streak', 0)}\n"
        f"• Лучшая серия: {stats.get('best_streak', 0)}\n"
        f"• Лучшая тема: {best_topic.capitalize() if best_topic != '—' else '—'}\n"
        f"• Слабая тема: {worst_topic.capitalize() if worst_topic != '—' else '—'}\n\n"
        "🧪 Экзамены\n"
        f"• Пройдено экзаменов: {stats.get('exams_completed', 0)}\n"
        f"• Отвечено экзаменационных вопросов: {exam_answered}\n"
        f"• Правильных в экзаменах: {exam_correct}\n"
        f"• Процент по экзаменам: {exam_percent}%\n"
        f"• Лучший результат экзамена: {stats.get('best_exam_percent', 0)}%\n\n"
        f"📚 По темам:\n{topic_stats_text}"
    )

    await update.message.reply_text(text)


async def topics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not QUESTIONS:
        await update.message.reply_text("⚠️ Вопросы пока не загружены.")
        return

    lines = ["📚 Категории и темы:\n"]
    for category, topics in QUESTIONS.items():
        lines.append(f"📂 {category}")
        for topic in topics.keys():
            lines.append(f"   • {topic.capitalize()}")
        lines.append("")

    await update.message.reply_text("\n".join(lines).strip())


async def questions_count_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not QUESTIONS:
        await update.message.reply_text("⚠️ Вопросы пока не загружены.")
        return

    lines = ["📊 Количество вопросов:\n"]
    for category, topics in QUESTIONS.items():
        lines.append(f"📂 {category}")
        for topic, questions in topics.items():
            lines.append(f"   • {topic.capitalize()}: {len(questions)}")
        lines.append("")

    await update.message.reply_text("\n".join(lines).strip())


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ У тебя нет доступа к этой команде.")
        return

    clear_add_state(context)
    context.user_data["add_state"] = "waiting_category"

    await update.message.reply_text(
        "➕ Добавление нового вопроса\n\n"
        "Шаг 1 из 6.\n"
        "Введите категорию.\n"
        "Например: Программирование, Медицина, Математика\n\n"
        "Для отмены: /cancel"
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("add_state"):
        clear_add_state(context)
        await update.message.reply_text("❌ Добавление вопроса отменено.")
    else:
        await update.message.reply_text("ℹ️ Сейчас нечего отменять.")


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    action = (query.data or "").split(":", maxsplit=1)[1]

    if action == "test":
        clear_quiz_session(context)
        context.user_data["mode"] = "test"
        await query.edit_message_text(
            "🏫 Выбери категорию для обычного теста:",
            reply_markup=build_categories_keyboard(),
        )
        return

    if action == "exam":
        clear_quiz_session(context)
        context.user_data["mode"] = "exam"
        await query.edit_message_text(
            f"🧪 Режим экзамена\n\n"
            f"• Количество вопросов: {EXAM_QUESTION_COUNT}\n"
            f"• Время: {EXAM_DURATION_MINUTES} минут\n"
            f"• Сброс во время экзамена запрещён\n\n"
            f"🏫 Выбери категорию:",
            reply_markup=build_categories_keyboard("examcategory"),
        )
        return

    if action == "stats":
        user_id = str(query.from_user.id)
        user_name = query.from_user.full_name or query.from_user.username or str(query.from_user.id)
        stats = get_user_stats(user_id, user_name)

        total_answered = stats.get("questions_answered", 0)
        total_correct = stats.get("correct_answers", 0)
        total_tests = stats.get("tests_completed", 0)
        total_percent = round((total_correct / total_answered) * 100) if total_answered > 0 else 0

        exam_answered = stats.get("exam_questions_answered", 0)
        exam_correct = stats.get("exam_correct_answers", 0)
        exam_percent = round((exam_correct / exam_answered) * 100) if exam_answered > 0 else 0

        best_topic, worst_topic = get_best_and_worst_topics(stats)
        topic_stats_text = build_topic_stats_text(stats)

        text = (
            "📊 *Твоя статистика*\n\n"
            f"📝 Тестов пройдено: {total_tests}\n"
            f"✅ Правильных ответов: {total_correct}/{total_answered} ({total_percent}%)\n"
            f"🔥 Текущая серия: {stats.get('current_streak', 0)}\n"
            f"🏆 Лучшая серия: {stats.get('best_streak', 0)}\n"
            f"💪 Лучшая тема: {best_topic.capitalize() if best_topic != '—' else '—'}\n"
            f"📉 Слабая тема: {worst_topic.capitalize() if worst_topic != '—' else '—'}\n\n"
            f"🧪 Экзамены: {stats.get('exams_completed', 0)}\n"
            f"📘 Экзаменационные ответы: {exam_correct}/{exam_answered} ({exam_percent}%)\n"
            f"⭐ Лучший экзамен: {stats.get('best_exam_percent', 0)}%\n\n"
            f"📚 По темам:\n{topic_stats_text}"
        )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=build_main_menu_keyboard(),
        )
        return

    if action == "topics":
        if not QUESTIONS:
            await query.edit_message_text("⚠️ Вопросы пока не загружены.")
            return

        lines = ["📚 *Категории и темы*\n"]
        for category, topics in QUESTIONS.items():
            lines.append(f"\n📂 *{category}*")
            for topic in topics.keys():
                lines.append(f"• {topic.capitalize()}")

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=build_main_menu_keyboard(),
        )
        return


async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data or ""
    category_index = data.split(":", maxsplit=1)[1]
    category = get_category_by_index(category_index)

    if not category or category not in QUESTIONS:
        await query.edit_message_text("⚠️ Такая категория не найдена.")
        return

    context.user_data["category"] = category
    context.user_data["mode"] = "test"

    await query.edit_message_text(
        f"📂 Категория: {category}\n\nТеперь выбери тему:",
        reply_markup=build_topics_keyboard(category, "topic"),
    )


async def exam_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data or ""
    category_index = data.split(":", maxsplit=1)[1]
    category = get_category_by_index(category_index)

    if not category or category not in QUESTIONS:
        await query.edit_message_text("⚠️ Такая категория не найдена.")
        return

    context.user_data["category"] = category
    context.user_data["mode"] = "exam"

    await query.edit_message_text(
        f"🧪 Экзамен\n\n📂 Категория: {category}\n\nТеперь выбери тему:",
        reply_markup=build_topics_keyboard(category, "examtopic"),
    )


async def topic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    topic_index = (query.data or "").split(":", maxsplit=1)[1]
    category = context.user_data.get("category")

    if not category:
        await query.edit_message_text("⚠️ Сначала выбери категорию.")
        return

    topic = get_topic_by_index(category, topic_index)
    category_data = QUESTIONS.get(category, {})

    if not topic or topic not in category_data:
        await query.edit_message_text("⚠️ Такая тема не найдена.")
        return

    context.user_data["category"] = category
    context.user_data["topic"] = topic
    context.user_data["mode"] = "test"

    await query.edit_message_text(
        f"📂 Категория: {category}\n"
        f"📘 Тема: {topic.capitalize()}\n\n"
        f"Выбери сложность:",
        reply_markup=build_difficulty_keyboard(category, topic),
    )


async def exam_topic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    topic_index = (query.data or "").split(":", maxsplit=1)[1]
    category = context.user_data.get("category")

    if not category:
        await query.edit_message_text("⚠️ Сначала выбери категорию.")
        return

    topic = get_topic_by_index(category, topic_index)
    category_data = QUESTIONS.get(category, {})
    questions = category_data.get(topic, []).copy() if topic else []

    if not topic or not questions:
        await query.edit_message_text("⚠️ Для этой темы пока нет вопросов.")
        return

    if len(questions) < EXAM_QUESTION_COUNT:
        await query.edit_message_text(
            f"⚠️ Для экзамена в теме {topic.capitalize()} нужно минимум {EXAM_QUESTION_COUNT} вопросов.\n"
            f"Сейчас доступно: {len(questions)}"
        )
        return

    random.shuffle(questions)
    selected_questions = questions[:EXAM_QUESTION_COUNT]

    user = update.effective_user
    context.user_data["telegram_user_id"] = user.id if user else "unknown"
    context.user_data["telegram_user_name"] = user.full_name if user else "Unknown User"

    context.user_data["category"] = category
    context.user_data["topic"] = topic
    context.user_data["difficulty"] = "exam"
    context.user_data["questions"] = selected_questions
    context.user_data["question_limit"] = str(EXAM_QUESTION_COUNT)
    context.user_data["current_index"] = 0
    context.user_data["score"] = 0
    context.user_data["answered_message_ids"] = set()
    context.user_data["quiz_active"] = True
    context.user_data["mode"] = "exam"
    context.user_data["exam_end_time"] = (
        datetime.now() + timedelta(minutes=EXAM_DURATION_MINUTES)
    ).isoformat(timespec="seconds")

    await query.edit_message_text(
        f"🧪 Экзамен начат!\n\n"
        f"📂 Категория: {category}\n"
        f"📘 Тема: {topic.capitalize()}\n"
        f"❓ Вопросов: {EXAM_QUESTION_COUNT}\n"
        f"⏰ Время: {EXAM_DURATION_MINUTES} минут\n\n"
        f"Удачи!"
    )

    await send_next_question(query.message.chat_id, context)


async def difficulty_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    difficulty = (query.data or "").split(":", maxsplit=1)[1]
    category = context.user_data.get("category")
    topic = context.user_data.get("topic")

    if not category or not topic:
        await query.edit_message_text("⚠️ Сначала выбери категорию и тему.")
        return

    all_questions = QUESTIONS.get(category, {}).get(topic, [])
    filtered_questions = filter_questions_by_difficulty(all_questions, difficulty)

    if not filtered_questions:
        await query.edit_message_text(
            f"⚠️ Для темы {topic.capitalize()} нет вопросов уровня {difficulty}.\n"
            f"Выбери другую сложность.",
            reply_markup=build_difficulty_keyboard(category, topic),
        )
        return

    context.user_data["category"] = category
    context.user_data["topic"] = topic
    context.user_data["difficulty"] = difficulty
    context.user_data["mode"] = "test"

    await query.edit_message_text(
        f"📂 Категория: {category}\n"
        f"📘 Тема: {topic.capitalize()}\n"
        f"🎚 Сложность: {difficulty}\n\n"
        f"Выбери количество вопросов:",
        reply_markup=build_question_count_keyboard(category, topic, difficulty),
    )


async def count_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    count_raw = (query.data or "").split(":", maxsplit=1)[1]
    category = context.user_data.get("category")
    topic = context.user_data.get("topic")
    difficulty = context.user_data.get("difficulty", "all")

    if not category or not topic:
        await query.edit_message_text("⚠️ Сначала выбери категорию и тему.")
        return

    all_questions = QUESTIONS.get(category, {}).get(topic, [])
    filtered_questions = filter_questions_by_difficulty(all_questions, difficulty)

    if not filtered_questions:
        await query.edit_message_text("⚠️ Вопросы не найдены.")
        return

    random.shuffle(filtered_questions)

    if count_raw == "all":
        selected_questions = filtered_questions
        question_limit_text = "Все доступные"
    else:
        count = int(count_raw)
        selected_questions = filtered_questions[:count]
        question_limit_text = str(min(count, len(filtered_questions)))

    context.user_data["category"] = category
    context.user_data["topic"] = topic
    context.user_data["difficulty"] = difficulty
    context.user_data["questions"] = selected_questions
    context.user_data["question_limit"] = question_limit_text
    context.user_data["current_index"] = 0
    context.user_data["score"] = 0
    context.user_data["answered_message_ids"] = set()
    context.user_data["quiz_active"] = True
    context.user_data["mode"] = "test"

    user = update.effective_user
    context.user_data["telegram_user_id"] = user.id if user else "unknown"
    context.user_data["telegram_user_name"] = user.full_name if user else "Unknown User"

    await query.edit_message_text(
        f"✅ Категория: {category}\n"
        f"✅ Тема: {topic.capitalize()}\n"
        f"✅ Сложность: {difficulty}\n"
        f"✅ Количество вопросов: {question_limit_text}\n\n"
        f"Начинаем тест!"
    )

    await send_next_question(query.message.chat_id, context)


async def back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data or ""
    payload = data.split(":", maxsplit=1)[1]

    if payload.startswith("categories|"):
        mode_prefix = payload.split("|", maxsplit=1)[1]
        if mode_prefix == "examtopic":
            await query.edit_message_text(
                "🧪 Экзамен\n\n🏫 Выбери категорию:",
                reply_markup=build_categories_keyboard("examcategory"),
            )
        else:
            await query.edit_message_text(
                "🏫 Выбери категорию:",
                reply_markup=build_categories_keyboard(),
            )
        return

    if payload == "topics":
        category = context.user_data.get("category")
        mode = context.user_data.get("mode", "test")

        if not category:
            await query.edit_message_text(
                "🏫 Выбери категорию:",
                reply_markup=build_categories_keyboard("examcategory" if mode == "exam" else "category"),
            )
            return

        prefix = "examtopic" if mode == "exam" else "topic"
        await query.edit_message_text(
            f"📂 Категория: {category}\n\nТеперь выбери тему:",
            reply_markup=build_topics_keyboard(category, prefix),
        )
        return

    if payload == "difficulty":
        category = context.user_data.get("category")
        topic = context.user_data.get("topic")

        if not category or not topic:
            await query.edit_message_text("⚠️ Сначала выбери категорию и тему.")
            return

        await query.edit_message_text(
            f"📂 Категория: {category}\n"
            f"📘 Тема: {topic.capitalize()}\n\n"
            f"Выбери сложность:",
            reply_markup=build_difficulty_keyboard(category, topic),
        )
        return


async def send_next_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    questions = context.user_data.get("questions", [])
    current_index = context.user_data.get("current_index", 0)
    category = context.user_data.get("category", "Неизвестно")
    topic = context.user_data.get("topic", "unknown")
    difficulty = context.user_data.get("difficulty", "all")
    score = context.user_data.get("score", 0)
    mode = context.user_data.get("mode", "test")

    if mode == "exam":
        end_time_iso = context.user_data.get("exam_end_time")
        if end_time_iso:
            try:
                end_time = datetime.fromisoformat(end_time_iso)
                if datetime.now() >= end_time:
                    await finish_exam_due_timeout(chat_id, context)
                    return
            except Exception:
                pass

    if current_index >= len(questions):
        total = len(questions)
        percent = round((score / total) * 100) if total > 0 else 0
        grade = get_grade(percent)

        user_id = str(context.user_data.get("telegram_user_id", "unknown"))
        user_name = context.user_data.get("telegram_user_name", "Unknown User")

        if mode == "exam":
            update_completed_exam_stats_persistent(user_id, user_name, percent)
            save_attempt_record(
                user_id=user_id,
                user_name=user_name,
                category=category,
                topic=topic,
                difficulty="exam",
                score=score,
                total=total,
                percent=percent,
                grade=grade,
                mode="exam",
            )

            result_text = (
                "🧪 *Экзамен завершён!*\n\n"
                f"📂 Категория: {category}\n"
                f"📘 Тема: {topic.capitalize()}\n"
                f"✅ Правильных ответов: {score}/{total}\n"
                f"📊 Результат: {percent}%\n"
                f"🎓 Оценка: *{grade}*"
            )

            reply_markup = build_finish_keyboard("exam")
        else:
            update_completed_test_stats_persistent(user_id, user_name, topic)
            save_attempt_record(
                user_id=user_id,
                user_name=user_name,
                category=category,
                topic=topic,
                difficulty=difficulty,
                score=score,
                total=total,
                percent=percent,
                grade=grade,
                mode="test",
            )

            result_text = (
                "🏁 *Тест завершён!*\n\n"
                f"📂 Категория: {category}\n"
                f"📘 Тема: {topic.capitalize()}\n"
                f"🎚 Сложность: {difficulty}\n"
                f"✅ Правильных ответов: {score}/{total}\n"
                f"📊 Результат: {percent}%\n"
                f"🎓 Оценка: *{grade}*"
            )

            reply_markup = build_finish_keyboard("test")

        context.user_data["quiz_active"] = False
        await context.bot.send_message(
            chat_id=chat_id,
            text=result_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        return

    question_data = questions[current_index]
    options = question_data["options"][:]
    random.shuffle(options)

    mode_title = "🧪 Экзамен" if mode == "exam" else "📝 Обычный тест"
    time_text = ""

    if mode == "exam":
        end_time_iso = context.user_data.get("exam_end_time", "")
        time_text = f"\n⏰ Осталось: {exam_time_left_text(end_time_iso)}"

    difficulty_line = "" if mode == "exam" else f"\n🎚 Сложность: {difficulty}"

    question_text = (
        f"{mode_title}\n\n"
        f"📂 Категория: {category}\n"
        f"📘 Тема: {topic.capitalize()}"
        f"{difficulty_line}"
        f"{time_text}\n"
        f"🔢 Вопрос {current_index + 1} из {len(questions)}\n\n"
        f"*{question_data['question']}*"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=question_text,
        parse_mode="Markdown",
        reply_markup=build_options_keyboard(options),
    )


async def answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()

    user = update.effective_user
    context.user_data["telegram_user_id"] = user.id if user else "unknown"
    context.user_data["telegram_user_name"] = (
        user.full_name if user else "Unknown User"
    )

    if not context.user_data.get("quiz_active"):
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        await query.answer("Тест не активен. Нажми /start", show_alert=True)
        return

    mode = context.user_data.get("mode", "test")
    if mode == "exam":
        end_time_iso = context.user_data.get("exam_end_time")
        if end_time_iso:
            try:
                end_time = datetime.fromisoformat(end_time_iso)
                if datetime.now() >= end_time:
                    try:
                        await query.edit_message_reply_markup(reply_markup=None)
                    except BadRequest:
                        pass
                    await finish_exam_due_timeout(query.message.chat_id, context)
                    return
            except Exception:
                pass

    message_id = query.message.message_id
    answered_ids = context.user_data.get("answered_message_ids", set())

    if message_id in answered_ids:
        await query.answer("На этот вопрос уже был дан ответ.", show_alert=False)
        return

    selected_answer = (query.data or "").split(":", maxsplit=1)[1]

    questions = context.user_data.get("questions", [])
    current_index = context.user_data.get("current_index", 0)

    if current_index >= len(questions):
        await query.answer("Тест уже завершён.", show_alert=False)
        return

    current_question = questions[current_index]
    correct_answer = current_question["answer"]
    topic = context.user_data.get("topic", "unknown")

    answered_ids.add(message_id)
    context.user_data["answered_message_ids"] = answered_ids

    user_id = str(context.user_data.get("telegram_user_id", "unknown"))
    user_name = context.user_data.get("telegram_user_name", "Unknown User")

    if selected_answer == correct_answer:
        context.user_data["score"] = context.user_data.get("score", 0) + 1
        if mode == "exam":
            update_exam_answer_stats_persistent(user_id, user_name, True)
        else:
            update_answer_stats_persistent(user_id, user_name, topic, True)
        feedback = "✅ Верно! Отличный ответ."
    else:
        if mode == "exam":
            update_exam_answer_stats_persistent(user_id, user_name, False)
        else:
            update_answer_stats_persistent(user_id, user_name, topic, False)
        feedback = f"❌ Неверно.\nПравильный ответ: *{correct_answer}*"

    context.user_data["current_index"] = current_index + 1

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest:
        pass

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=feedback,
        parse_mode="Markdown",
    )
    await send_next_question(query.message.chat_id, context)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    add_state = context.user_data.get("add_state")

    if add_state:
        if not is_admin(update):
            clear_add_state(context)
            await update.message.reply_text("⛔ У тебя нет доступа к добавлению вопросов.")
            return

        text = update.message.text.strip()

        if add_state == "waiting_category":
            context.user_data["new_question_category"] = text
            context.user_data["add_state"] = "waiting_topic"
            await update.message.reply_text(
                "Шаг 2 из 6.\n"
                "Введите тему.\n"
                "Например: python, анатомия, высшая математика"
            )
            return

        if add_state == "waiting_topic":
            context.user_data["new_question_topic"] = text.lower()
            context.user_data["add_state"] = "waiting_question"
            await update.message.reply_text("Шаг 3 из 6.\nВведите текст вопроса.")
            return

        if add_state == "waiting_question":
            context.user_data["new_question_text"] = text
            context.user_data["add_state"] = "waiting_options"
            await update.message.reply_text(
                "Шаг 4 из 6.\n"
                "Введите варианты ответа, каждый с новой строки.\n"
                "Минимум 2 варианта.\n\n"
                "Пример:\n"
                "вариант 1\n"
                "вариант 2\n"
                "вариант 3\n"
                "вариант 4"
            )
            return

        if add_state == "waiting_options":
            options = [line.strip() for line in text.splitlines() if line.strip()]
            if len(options) < 2:
                await update.message.reply_text(
                    "⚠️ Нужно минимум 2 варианта ответа. Попробуй ещё раз."
                )
                return

            context.user_data["new_question_options"] = options
            context.user_data["add_state"] = "waiting_answer"

            options_text = "\n".join(
                [f"{idx + 1}. {option}" for idx, option in enumerate(options)]
            )

            await update.message.reply_text(
                f"Шаг 5 из 6.\n"
                f"Выбери правильный ответ, отправив номер.\n\n{options_text}"
            )
            return

        if add_state == "waiting_answer":
            if not text.isdigit():
                await update.message.reply_text("⚠️ Отправь номер правильного ответа.")
                return

            answer_index = int(text) - 1
            options = context.user_data.get("new_question_options", [])

            if answer_index < 0 or answer_index >= len(options):
                await update.message.reply_text("⚠️ Такого варианта нет. Попробуй ещё раз.")
                return

            context.user_data["new_question_answer"] = options[answer_index]
            context.user_data["add_state"] = "waiting_difficulty"
            await update.message.reply_text(
                "Шаг 6 из 6.\n"
                "Введите сложность: easy, medium или hard"
            )
            return

        if add_state == "waiting_difficulty":
            difficulty = text.lower()
            if difficulty not in {"easy", "medium", "hard"}:
                await update.message.reply_text(
                    "⚠️ Сложность должна быть: easy, medium или hard."
                )
                return

            context.user_data["new_question_difficulty"] = difficulty

            category = context.user_data["new_question_category"]
            topic = context.user_data["new_question_topic"]
            question_text = context.user_data["new_question_text"]
            options = context.user_data["new_question_options"]
            answer = context.user_data["new_question_answer"]

            global QUESTIONS

            if category not in QUESTIONS:
                QUESTIONS[category] = {}

            if topic not in QUESTIONS[category]:
                QUESTIONS[category][topic] = []

            QUESTIONS[category][topic].append(
                {
                    "question": question_text,
                    "options": options,
                    "answer": answer,
                    "difficulty": difficulty,
                }
            )

            save_questions(QUESTIONS)
            clear_add_state(context)

            await update.message.reply_text(
                "✅ Вопрос успешно добавлен.\n\n"
                f"📂 Категория: {category}\n"
                f"📘 Тема: {topic.capitalize()}\n"
                f"🎚 Сложность: {difficulty}\n"
                f"📊 Теперь в теме вопросов: {len(QUESTIONS[category][topic])}"
            )
            return

    await update.message.reply_text(
        "ℹ️ Используй кнопки или команды.\n"
        "Нажми /start, чтобы открыть главное меню."
    )


def main() -> None:
    if not BOT_TOKEN:
        raise ValueError("Не найден BOT_TOKEN в переменных окружения.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("exam", exam_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("topics", topics_command))
    app.add_handler(CommandHandler("questions", questions_count_command))

    app.add_handler(CallbackQueryHandler(menu_handler, pattern=r"^menu:"))
    app.add_handler(CallbackQueryHandler(category_handler, pattern=r"^category:"))
    app.add_handler(CallbackQueryHandler(exam_category_handler, pattern=r"^examcategory:"))
    app.add_handler(CallbackQueryHandler(topic_handler, pattern=r"^topic:"))
    app.add_handler(CallbackQueryHandler(exam_topic_handler, pattern=r"^examtopic:"))
    app.add_handler(CallbackQueryHandler(difficulty_handler, pattern=r"^difficulty:"))
    app.add_handler(CallbackQueryHandler(count_handler, pattern=r"^count:"))
    app.add_handler(CallbackQueryHandler(back_handler, pattern=r"^back:"))
    app.add_handler(CallbackQueryHandler(answer_handler, pattern=r"^answer:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
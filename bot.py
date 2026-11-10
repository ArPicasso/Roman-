"""Telegram-бот, который отвечает на вопросы с помощью Claude Haiku 5.5.

Запуск:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...      # ключ Anthropic API
    export TELEGRAM_BOT_TOKEN=...     # токен от @BotFather
    python bot.py
"""

import logging
import os

import anthropic
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

MODEL = "claude-haiku-5-5"  # лёгкая и дешёвая модель
MAX_HISTORY_MESSAGES = 20  # сколько последних сообщений помнить в каждом чате
TELEGRAM_LIMIT = 4096  # максимальная длина одного сообщения в Telegram

SYSTEM_PROMPT = (
    "Ты дружелюбный и терпеливый помощник в Telegram. "
    "Отвечай на том языке, на котором тебе пишут (обычно по-русски). "
    "Пиши простыми словами, коротко и по делу, без сложных терминов. "
    "Если вопрос неясен, вежливо уточни. "
    "Не используй Markdown-разметку (звёздочки, решётки), пиши обычным текстом."
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
for noisy in ("httpx", "httpx2"):  # иначе токен бота попадает в лог
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("bot")

claude = anthropic.AsyncAnthropic()  # берёт ANTHROPIC_API_KEY из окружения


def split_text(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Режет длинный ответ на куски, которые помещаются в одно сообщение Telegram."""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["history"] = []
    await update.message.reply_text(
        "Здравствуйте! Я ваш помощник. Задайте любой вопрос — я постараюсь помочь.\n\n"
        "Команда /new — начать разговор заново."
    )


async def new_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["history"] = []
    await update.message.reply_text("Хорошо, начинаем новый разговор. Спрашивайте!")


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = update.message.text
    history: list[dict] = context.chat_data.setdefault("history", [])

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    messages = history + [{"role": "user", "content": question}]
    try:
        response = await claude.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},  # для простого чата хватает
            messages=messages,
        )
    except anthropic.RateLimitError:
        await update.message.reply_text("Слишком много вопросов сразу. Подождите минутку.")
        return
    except anthropic.APIStatusError as e:
        log.error("Ошибка API %s: %s", e.status_code, e.message)
        await update.message.reply_text("Не получилось ответить. Попробуйте ещё раз позже.")
        return
    except anthropic.APIConnectionError:
        log.exception("Нет связи с API")
        await update.message.reply_text("Нет связи с сервером. Попробуйте ещё раз.")
        return

    if response.stop_reason == "refusal":
        await update.message.reply_text("На этот вопрос я ответить не могу.")
        return

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        text = "Извините, не получилось сформулировать ответ. Спросите по-другому."

    # Запоминаем разговор, чтобы бот понимал уточняющие вопросы.
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": text})
    del history[:-MAX_HISTORY_MESSAGES]

    for part in split_text(text):
        await update.message.reply_text(part)


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    log.info("Бот запущен, модель %s", MODEL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

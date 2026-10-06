import asyncio
import os
import requests
import json
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup, KeyboardButton,
    BufferedInputFile,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from aiohttp import web

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN не задан в Environment!")

GIGACHAT_KEY = os.environ.get("GIGACHAT_KEY")
if not GIGACHAT_KEY:
    raise Exception("GIGACHAT_KEY не задан в Environment!")
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

giga = GigaChat(
    credentials=GIGACHAT_KEY,
    scope="GIGACHAT_API_PERS",
    model="GigaChat-2",
    verify_ssl_certs=False,
)


# ==================== КЛАВИАТУРЫ ====================
def main_kb():
    kb = [
        [KeyboardButton(text="💬 Спросить AI")],
        [KeyboardButton(text="🎨 Нарисовать картинку")],
        [KeyboardButton(text="ℹ️ О боте")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


# ==================== FSM ====================
class GenStates(StatesGroup):
    waiting_ai = State()
    waiting_draw = State()


# ==================== СТАРТ ====================
# ==================== ПОИСК В ИНТЕРНЕТЕ (TAVILY) ====================
def search_web(query):
    """Ищет в интернете через Tavily. Возвращает строку с результатами."""
    try:
        TAVILY_KEY = os.environ.get("TAVILY_KEY", "")
        if not TAVILY_KEY:
            print("TAVILY_KEY не задан")
            return ""

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
            "include_answer": False,
        }
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code != 200:
            print(f"Tavily ошибка: {resp.status_code} {resp.text[:200]}")
            return ""

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return ""

        text = "Актуальная информация из интернета:\n\n"
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "")
            content = r.get("content", "")[:300]
            url_link = r.get("url", "")
            text += f"{i}. {title}\n{content}\nИсточник: {url_link}\n\n"
        return text
    except Exception as e:
        print(f"Ошибка поиска: {e}")
        return ""
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "🤖 <b>Привет! Я — AI-бот на GigaChat!</b>\n\n"
        "Я умею:\n"
        "💬 Отвечать на любые вопросы\n"
        "🎨 Рисовать картинки по описанию\n\n"
        "━━━━━━━━━━━━━━━\n"
        "Просто напиши мне что угодно — я отвечу!\n"
        "Или выбери действие 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_kb())


# ==================== О БОТЕ ====================
@dp.message(F.text == "ℹ️ О боте")
async def about(message: Message):
    await message.answer(
        "ℹ️ <b>О боте</b>\n\n"
        "Этот бот использует нейросеть GigaChat от Сбера.\n\n"
        "💬 <b>Спросить AI</b> — задай любой вопрос.\n"
        "🎨 <b>Нарисовать картинку</b> — опиши, что нарисовать.\n"
        "💭 Или просто напиши сообщение — я отвечу!",
        parse_mode="HTML",
    )


# ==================== ТЕКСТОВЫЙ AI (по кнопке) ====================
@dp.message(F.text == "💬 Спросить AI")
async def ask_ai(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>Напиши свой вопрос</b>\n\n"
        "Например: «Придумай смешную шутку про котов»\n\n"
        "❌ /cancel — отменить",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(GenStates.waiting_ai)


@dp.message(GenStates.waiting_ai, F.text == "❌ Отмена")
async def cancel_ai(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


@dp.message(GenStates.waiting_ai)
async def process_ai(message: Message, state: FSMContext):
    prompt = message.text.strip()
    if len(prompt) < 2:
        await message.answer("❌ Слишком коротко. Напиши что-то ещё:")
        return

    await state.clear()

    await message.answer(
        "🤔 <b>Ищу информацию и думаю...</b>\n\n⏳ Обычно 5-15 секунд",
        parse_mode="HTML",
        reply_markup=main_kb(),
    )

    try:
        search_results = search_web(prompt)

        if search_results:
            system_text = (
                "Ты — современный AI-ассистент. Отвечай на русском языке, кратко. "
                "Используй ТОЛЬКО актуальную информацию из интернета, которую тебе дали ниже. "
                "Если в данных есть даты и события 2025-2026 — используй их, не отвечай старыми данными. "
                "НЕ используй LaTeX, символы $ и $$."
            )
            user_text = f"Вопрос: {prompt}\n\n{search_results}\n\nОтветь на вопрос, используя эти данные."
        else:
            system_text = (
                "Ты — современный AI-ассистент. Отвечай на русском языке, кратко. "
                "НЕ используй LaTeX, символы $ и $$."
            )
            user_text = prompt

        payload = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=system_text),
                Messages(role=MessagesRole.USER, content=user_text),
            ],
        )

        response = giga.chat(payload)
        answer = response.choices[0].message.content

        import re
        answer = re.sub(r'\$\$.*?\$\$', '', answer, flags=re.DOTALL)
        answer = re.sub(r'\$.*?\$', '', answer, flags=re.DOTALL)
        answer = answer.replace('$', '')
        answer = re.sub(r'\n\s*\n\s*\n', '\n\n', answer)
        answer = answer.strip()

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000])
        else:
            await message.answer(answer)

    except Exception as e:
        await message.answer(
            f"😔 <b>Не получилось</b>\n\n"
            f"Ошибка: <code>{e}</code>",
            parse_mode="HTML",
        )


# ==================== ГЕНЕРАЦИЯ КАРТИНОК ====================
@dp.message(F.text == "🎨 Нарисовать картинку")
async def ask_draw(message: Message, state: FSMContext):
    await message.answer(
        "🎨 <b>Опиши, что нарисовать</b>\n\n"
        "Например: «Кот в космосе, реализм»\n\n"
        "❌ /cancel — отменить",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(GenStates.waiting_draw)


@dp.message(GenStates.waiting_draw, F.text == "❌ Отмена")
async def cancel_draw(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


@dp.message(GenStates.waiting_draw)
async def process_draw(message: Message, state: FSMContext):
    prompt = message.text.strip()
    if len(prompt) < 3:
        await message.answer("❌ Слишком короткое описание:")
        return

    await state.clear()

    await message.answer(
        "🎨 <b>Рисую...</b>\n\n⏳ Это может занять 1-3 минуты (бесплатный сервис)",
        parse_mode="HTML",
        reply_markup=main_kb(),
    )

    try:
        # 1. Отправляем задачу в Stable Horde
        url = "https://stablehorde.net/api/v2/generate/async"
        headers = {
            "Content-Type": "application/json",
            "apikey": "0000000000",  # анонимный ключ
        }
        payload = {
            "prompt": prompt + " ### realistic, high quality, 4k",
            "params": {
                "width": 512,
                "height": 512,
                "steps": 20,
                "n": 1,
            },
            "models": ["stable_diffusion"],
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)

        if resp.status_code != 202:
            await message.answer(
                f"⚠️ Stable Horde вернул {resp.status_code}.\n"
                f"Подожди минуту и попробуй ещё раз."
            )
            return

        job_id = resp.json().get("id")

        # 2. Ждём готовности (до 3 минут)
        check_url = f"https://stablehorde.net/api/v2/generate/check/{job_id}"

        for _ in range(60):
            await asyncio.sleep(3)
            check = requests.get(check_url, timeout=15)
            status = check.json()

            if status.get("done"):
                # 3. Получаем ссылку на картинку
                status_url = f"https://stablehorde.net/api/v2/generate/status/{job_id}"
                result = requests.get(status_url, timeout=15).json()
                generations = result.get("generations", [])
                if not generations:
                    break

                img_url = generations[0].get("img")
                img = requests.get(img_url, timeout=30)

                if img.status_code == 200 and len(img.content) > 1000:
                    photo = BufferedInputFile(img.content, filename="image.jpg")
                    await message.answer_photo(
                        photo,
                        caption=f"🎨 <b>Готово!</b>\n\n<i>{prompt}</i>",
                        parse_mode="HTML",
                    )
                    return
                break

        await message.answer("⚠️ Сервис перегружен. Попробуй другой промпт или позже.")

    except Exception as e:
        await message.answer(
            f"😔 <b>Не получилось нарисовать</b>\n\n"
            f"Ошибка: <code>{e}</code>",
            parse_mode="HTML",
        )
# ==================== ОТМЕНА ====================
@dp.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


# ==================== СВОБОДНЫЙ ЧАТ (в самом конце!) ====================
@dp.message(F.text & ~F.text.startswith("/"))
async def free_chat(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    prompt = message.text.strip()
    if not prompt:
        return

    menu_buttons = [
        "💬 Спросить AI",
        "🎨 Нарисовать картинку",
        "ℹ️ О боте",
        "❌ Отмена",
    ]
    if prompt in menu_buttons:
        return

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        search_results = search_web(prompt)

        if search_results:
            system_text = (
                "Ты — современный AI-ассистент. Отвечай на русском языке, кратко. "
                "Используй ТОЛЬКО актуальную информацию из интернета, которую тебе дали ниже. "
                "Если в данных есть даты и события 2025-2026 — используй их, не отвечай старыми данными. "
                "НЕ используй LaTeX, символы $ и $$."
            )
            user_text = f"Вопрос: {prompt}\n\n{search_results}\n\nОтветь на вопрос, используя эти данные."
        else:
            system_text = (
                "Ты — современный AI-ассистент. Отвечай на русском языке, кратко. "
                "НЕ используй LaTeX, символы $ и $$."
            )
            user_text = prompt

        payload = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=system_text),
                Messages(role=MessagesRole.USER, content=user_text),
            ],
        )

        response = giga.chat(payload)
        answer = response.choices[0].message.content

        import re
        answer = re.sub(r'\$\$.*?\$\$', '', answer, flags=re.DOTALL)
        answer = re.sub(r'\$.*?\$', '', answer, flags=re.DOTALL)
        answer = answer.replace('$', '')
        answer = re.sub(r'\n\s*\n\s*\n', '\n\n', answer)
        answer = answer.strip()

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000])
        else:
            await message.answer(answer)

    except Exception as e:
        await message.answer(
            f"😔 <b>Не получилось</b>\n\n"
            f"Ошибка: <code>{e}</code>",
            parse_mode="HTML",
        )

# ==================== ЗАПУСК ====================
async def main():
    print("AI-бот на GigaChat запущен...")
    asyncio.create_task(start_web())
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())

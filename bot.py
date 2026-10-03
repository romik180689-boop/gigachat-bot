import asyncio
import uuid
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from aiohttp import web

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8765909727:AAG7zLQsce6_eoKjXBqTWHVX7IJ7wKf-kVw"
GIGACHAT_KEY = os.environ.get("GIGACHAT_KEY") or "MDFhMTAzN2YtNDljZi03YzA5LThjZGQtODg4ZjFhZDgzZjk5OmQ2NDkyNGU2LTkxNzItNGQ3Ni1iYzQwLWNhYjliNjA5OTI2NA=="
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
    waiting_prompt = State()


# ==================== ХЕНДЛЕРЫ ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "🤖 <b>Привет! Я — AI-бот на GigaChat!</b>\n\n"
        "Я умею:\n"
        "💬 Отвечать на любые вопросы\n"
        "🎨 Рисовать картинки по описанию\n\n"
        "━━━━━━━━━━━━━━━\n"
        "Выбери действие 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_kb())


@dp.message(F.text == "ℹ️ О боте")
async def about(message: Message):
    await message.answer(
        "ℹ️ <b>О боте</b>\n\n"
        "Этот бот использует нейросеть GigaChat от Сбера.\n\n"
        "💬 <b>Спросить AI</b> — задай любой вопрос, бот ответит.\n"
        "🎨 <b>Нарисовать картинку</b> — опиши, что нарисовать.\n\n"
        "━━━━━━━━━━━━━━━\n"
        "Работает бесплатно для физических лиц 🎉",
        parse_mode="HTML",
    )


# ==================== ТЕКСТОВЫЙ AI ====================
@dp.message(F.text == "💬 Спросить AI")
async def ask_ai(message: Message, state: FSMContext):
    await message.answer(
        "✍️ <b>Напиши свой вопрос</b>\n\n"
        "Например: «Придумай смешную шутку про котов»\n\n"
        "❌ /cancel — отменить",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(GenStates.waiting_prompt)


@dp.message(GenStates.waiting_prompt, F.text == "❌ Отмена")
async def cancel_gen(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


@dp.message(GenStates.waiting_prompt)
async def process_ai(message: Message, state: FSMContext):
    prompt = message.text.strip()
    if len(prompt) < 2:
        await message.answer("❌ Слишком коротко. Напиши что-то ещё:")
        return

    await state.clear()

    status = await message.answer(
        "🤔 <b>Думаю...</b>\n\n⏳ Обычно это занимает 3-10 секунд",
        parse_mode="HTML",
        reply_markup=main_kb(),
    )

    try:
        # Отправляем запрос в GigaChat
        payload = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content="Ты — полезный и дружелюбный помощник. Отвечай на русском языке."),
                Messages(role=MessagesRole.USER, content=prompt),
            ],
        )

        response = giga.chat(payload)
        answer = response.choices[0].message.content

        # Убираем лишние теги <img> если есть
        import re
        answer = re.sub(r'<img[^>]*>', '', answer).strip()

        # Разбиваем на части, если ответ слишком длинный (лимит Telegram — 4096)
        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000], parse_mode="HTML")
        else:
            await message.answer(answer, parse_mode="HTML")

    except Exception as e:
        await message.answer(
            f"😔 <b>Не получилось</b>\n\n"
            f"Ошибка: <code>{e}</code>\n\n"
            f"Попробуй ещё раз.",
            parse_mode="HTML",
        )


# ==================== ГЕНЕРАЦИЯ КАРТИНОК ====================
@dp.message(F.text == "🎨 Нарисовать картинку")
async def ask_draw(message: Message, state: FSMContext):
    await message.answer(
        "🎨 <b>Опиши, что нарисовать</b>\n\n"
        "Например: «Кот в космосе, реализм»\n\n"
        "⚠️ Генерация картинок может быть недоступна на бесплатном тарифе.\n\n"
        "❌ /cancel — отменить",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await state.set_state(GenStates.waiting_prompt)


@dp.message(GenStates.waiting_prompt)
async def process_draw(message: Message, state: FSMContext):
    prompt = message.text.strip()

    if len(prompt) < 3:
        await message.answer("❌ Слишком короткое описание. Напиши подробнее:")
        return

    await state.clear()

    await message.answer(
        "🎨 <b>Рисую...</b>\n\n⏳ Это может занять 10-30 секунд",
        parse_mode="HTML",
        reply_markup=main_kb(),
    )

    try:
        payload = Chat(
            messages=[
                Messages(role=MessagesRole.SYSTEM, content="Ты — художник. Если пользователь просит нарисовать, используй встроенную функцию text2image."),
                Messages(role=MessagesRole.USER, content=f"Нарисуй: {prompt}"),
            ],
            function_call="auto",
        )

        response = giga.chat(payload)
        content = response.choices[0].message.content

        # Ищем ID картинки в ответе
        import re
        match = re.search(r'<img src=\\"([^\\"]+)\\"', content)
        if not match:
            match = re.search(r'<img src="([^"]+)"', content)

        if match:
            file_id = match.group(1)

            # Скачиваем картинку
            image_data = giga.get_image(file_id=file_id)

            from aiogram.types import BufferedInputFile
            photo = BufferedInputFile(image_data.content, filename="image.jpg")

            await message.answer_photo(
                photo,
                caption=f"🎨 <b>Готово!</b>\n\n<i>{prompt}</i>",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                "⚠️ GigaChat ответил, но картинка не сгенерировалась.\n\n"
                "Скорее всего, генерация картинок недоступна на бесплатном тарифе.\n\n"
                f"Ответ AI: <i>{content[:500]}</i>",
                parse_mode="HTML",
            )

    except Exception as e:
        await message.answer(
            f"😔 <b>Не получилось нарисовать</b>\n\n"
            f"Ошибка: <code>{e}</code>\n\n"
            f"Возможно, генерация картинок недоступна на бесплатном тарифе.",
            parse_mode="HTML",
        )


@dp.message(Command("cancel"))
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_kb())


# ==================== ЗАПУСК ====================
from aiohttp import web
import os

async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()


async def main():
    print("🤖 AI-бот на GigaChat запущен...")
    asyncio.create_task(start_web())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

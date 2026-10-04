import asyncio
import os
import requests
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
        "🤔 <b>Думаю...</b>\n\n⏳ Обычно это занимает 3-10 секунд",
        parse_mode="HTML",
        reply_markup=main_kb(),
    )

    try:
        payload = Chat(
            messages=[
                Messages(
                    role=MessagesRole.SYSTEM,
                    content="Ты — полезный и дружелюбный помощник. Отвечай на русском языке.",
                ),
                Messages(role=MessagesRole.USER, content=prompt),
            ],
        )

        response = giga.chat(payload)
        answer = response.choices[0].message.content

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
        "🎨 <b>Рисую...</b>\n\n⏳ Это может занять 10-40 секунд",
        parse_mode="HTML",
        reply_markup=main_kb(),
    )

    try:
        HF_TOKEN = os.environ.get("HF_TOKEN", "")
        if not HF_TOKEN:
            await message.answer("⚠️ HF_TOKEN не настроен в Render Environment.")
            return

        url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        payload = {"inputs": prompt}

        response = requests.post(url, headers=headers, json=payload, timeout=120)

        if response.status_code != 200:
            await message.answer(
                f"⚠️ Hugging Face вернул {response.status_code}.\n"
                f"Подожди 30 секунд и попробуй ещё раз."
            )
            return

        photo = BufferedInputFile(response.content, filename="image.jpg")

        await message.answer_photo(
            photo,
            caption=f"🎨 <b>Готово!</b>\n\n<i>{prompt}</i>",
            parse_mode="HTML",
        )

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
        payload = Chat(
            messages=[
                Messages(
                    role=MessagesRole.SYSTEM,
                    content="Ты — полезный и дружелюбный AI-помощник. Отвечай на русском языке.",
                ),
                Messages(role=MessagesRole.USER, content=prompt),
            ],
        )

        response = giga.chat(payload)
        answer = response.choices[0].message.content

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


# ==================== ВЕБ-СЕРВЕР ДЛЯ RENDER ====================
async def handle(request):
    return web.Response(text="Bot is alive!")


async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 8080)))
    await site.start()


# ==================== ЗАПУСК ====================
async def main():
    print("AI-бот на GigaChat запущен...")
    asyncio.create_task(start_web())
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())

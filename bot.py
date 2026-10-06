import asyncio
import os
import requests
import json
import re
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
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
    raise Exception("BOT_TOKEN не задан!")

GIGACHAT_KEY = os.environ.get("GIGACHAT_KEY")
if not GIGACHAT_KEY:
    raise Exception("GIGACHAT_KEY не задан!")

TAVILY_KEY = os.environ.get("TAVILY_KEY", "")
HORDE_API_KEY = os.environ.get("HORDE_API_KEY", "0000000000")
DB_PATH = "manicure.db"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

giga = GigaChat(
    credentials=GIGACHAT_KEY,
    scope="GIGACHAT_API_PERS",
    model="GigaChat-2-Max",
    verify_ssl_certs=False,
)


# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_message(user_id, role, content):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )
    conn.commit()
    conn.close()


def get_history(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT role, content FROM history WHERE user_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))


def clear_history(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ==================== ПОИСК В ИНТЕРНЕТЕ ====================
def search_web(query):
    if not TAVILY_KEY:
        return ""
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": TAVILY_KEY,
            "query": query,
            "search_depth": "basic",
            "max_results": 3,
            "include_answer": False,
        }
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            print(f"Tavily ошибка: {resp.status_code}")
            return ""
        results = resp.json().get("results", [])
        if not results:
            return ""
        text = "Актуальные данные из интернета:\n\n"
        for i, r in enumerate(results[:3], 1):
            text += f"{i}. {r.get('title', '')}\n{r.get('content', '')[:250]}\n\n"
        return text
    except Exception as e:
        print(f"Ошибка поиска: {e}")
        return ""


# ==================== УЛУЧШЕНИЕ ПРОМПТА ====================
def enhance_image_prompt(prompt):
    try:
        sys_text = (
            "Ты — эксперт по промптам для Stable Diffusion. "
            "Твоя задача: перевести промпт на английский и добавить детали. "
            "Ответь ТОЛЬКО английским промптом, без пояснений, без кавычек. "
            "Пример: 'яблоко' → 'red juicy apple on wooden table, realistic, detailed, 4k'"
        )
        payload = Chat(messages=[
            Messages(role=MessagesRole.SYSTEM, content=sys_text),
            Messages(role=MessagesRole.USER, content=f"Улучши промпт: {prompt}"),
        ])
        resp = giga.chat(payload)
        enhanced = resp.choices[0].message.content.strip()
        enhanced = enhanced.replace('"', '').replace("'", "").strip()
        if len(enhanced) > 5:
            return enhanced
        return prompt
    except Exception as e:
        print(f"Ошибка улучшения промпта: {e}")
        return prompt


# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    kb = [
        [InlineKeyboardButton(text="💬 Спросить AI", callback_data="menu_ai")],
        [InlineKeyboardButton(text="🎨 Нарисовать картинку", callback_data="menu_draw")],
        [InlineKeyboardButton(text="🗑 Очистить диалог", callback_data="menu_clear")],
        [InlineKeyboardButton(text="ℹ️ О боте", callback_data="menu_about")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def cancel_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")],
    ])


# ==================== FSM ====================
class GenStates(StatesGroup):
    waiting_ai = State()
    waiting_draw = State()


# ==================== СТАРТ ====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    text = (
        "✨ <b>Привет! Я — AI-бот на GigaChat</b> ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🧠 <b>Что я умею:</b>\n"
        "  💬 Отвечать на любые вопросы\n"
        "  🔍 Искать актуальную информацию\n"
        "  🎨 Рисовать картинки\n"
        "  📚 Помнить историю диалога\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Просто напиши сообщение — я отвечу!</i>\n"
        "👇 <i>Или выбери действие в меню:</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu())


# ==================== О БОТЕ ====================
@dp.callback_query(F.data == "menu_about")
async def cb_about(call: CallbackQuery):
    text = (
        "ℹ️ <b>О боте</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🧠 <b>Модель:</b> GigaChat-2-Max\n"
        "🔍 <b>Поиск:</b> Tavily\n"
        "🎨 <b>Картинки:</b> AI Horde\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💬 Задавай вопросы на русском.\n"
        "🎨 Описывай картинки подробно.\n"
        "🗑 /clear — очистить историю."
    )
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=main_menu())
    await call.answer()


# ==================== ОЧИСТКА ====================
@dp.callback_query(F.data == "menu_clear")
async def cb_clear(call: CallbackQuery):
    clear_history(call.from_user.id)
    await call.message.edit_text(
        "🗑 <b>История очищена!</b>\n\nНачнём с чистого листа ✨",
        parse_mode="HTML",
        reply_markup=main_menu()
    )
    await call.answer("История очищена")


@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    clear_history(message.from_user.id)
    await message.answer(
        "🗑 <b>История очищена!</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ==================== СТАРТ AI ====================
@dp.callback_query(F.data == "menu_ai")
async def cb_ai(call: CallbackQuery, state: FSMContext):
    await call.message.answer(
        "💬 <b>Напиши свой вопрос</b>\n\n"
        "🧠 Я поищу в интернете и дам актуальный ответ.\n\n"
        "❌ Отмена — кнопка ниже",
        parse_mode="HTML",
        reply_markup=cancel_menu()
    )
    await state.set_state(GenStates.waiting_ai)
    await call.answer()


@dp.callback_query(F.data == "cancel_action")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Отменено.", reply_markup=main_menu())
    await call.answer()


# ==================== ОТВЕТ AI ====================
async def generate_ai_answer(user_id, prompt):
    search_results = search_web(prompt)
    history = get_history(user_id, limit=10)

    system_text = (
        "Ты — современный AI-ассистент. Отвечай на русском, кратко, "
        "с эмодзи для живости. Используй актуальную информацию из интернета. "
        "Если есть данные 2025-2026 — используй их. "
        "НЕ используй LaTeX, символы $ и $$."
    )

    messages = [Messages(role=MessagesRole.SYSTEM, content=system_text)]

    for role, content in history:
        if role == "user":
            messages.append(Messages(role=MessagesRole.USER, content=content))
        else:
            messages.append(Messages(role=MessagesRole.ASSISTANT, content=content))

    if search_results:
        current = "Вопрос: " + prompt + "\n\n" + search_results + "\n\nОтветь, используя эти данные."
    else:
        current = prompt

    messages.append(Messages(role=MessagesRole.USER, content=current))

    payload = Chat(messages=messages)
    response = giga.chat(payload)
    answer = response.choices[0].message.content

    answer = re.sub(r'\$\$.*?\$\$', '', answer, flags=re.DOTALL)
    answer = re.sub(r'\$.*?\$', '', answer, flags=re.DOTALL)
    answer = answer.replace('$', '')
    answer = re.sub(r'\n\s*\n\s*\n', '\n\n', answer)
    answer = answer.strip()

    save_message(user_id, "user", prompt)
    save_message(user_id, "assistant", answer)

    return answer


@dp.message(GenStates.waiting_ai)
async def process_ai(message: Message, state: FSMContext):
    prompt = message.text.strip()
    if len(prompt) < 2:
        await message.answer("❌ Слишком коротко:")
        return

    await state.clear()

    status = await message.answer(
        "🧠 <b>Думаю...</b>\n🔍 <i>Ищу информацию</i>",
        parse_mode="HTML"
    )

    try:
        answer = await generate_ai_answer(message.from_user.id, prompt)
        await status.delete()

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000], reply_markup=main_menu() if i == 0 else None)
        else:
            await message.answer(answer, reply_markup=main_menu())

    except Exception as e:
        await status.delete()
        await message.answer(
            f"😔 <b>Ошибка</b>\n\n<code>{e}</code>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )


# ==================== СТАРТ РИСОВАНИЯ ====================
@dp.callback_query(F.data == "menu_draw")
async def cb_draw(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "🎨 <b>Опиши, что нарисовать</b>\n\n"
        "💡 Чем подробнее — тем лучше!\n"
        "📝 Например: «Кот в космосе, реализм»\n\n"
        "❌ Отмена — кнопка ниже",
        parse_mode="HTML",
        reply_markup=cancel_menu()
    )
    await state.set_state(GenStates.waiting_draw)
    await call.answer()


# ==================== ГЕНЕРАЦИЯ КАРТИНОК ====================
@dp.message(GenStates.waiting_draw)
async def process_draw(message: Message, state: FSMContext):
    prompt = message.text.strip()
    if len(prompt) < 3:
        await message.answer("❌ Слишком короткое описание:")
        return

    await state.clear()

    status = await message.answer(
        "🎨 <b>Готовлю картинку...</b>\n\n"
        "🧠 Улучшаю промпт\n"
        "📤 Отправляю в AI Horde\n"
        "⏳ Ожидание 1-3 минуты",
        parse_mode="HTML"
    )

    try:
        enhanced = enhance_image_prompt(prompt)
        print(f"Оригинал: {prompt}\nУлучшено: {enhanced}")

        url = "https://stablehorde.net/api/v2/generate/async"
        headers = {
            "Content-Type": "application/json",
            "apikey": HORDE_API_KEY,
        }
        payload = {
            "prompt": enhanced + " ### realistic, high quality, 4k, detailed, professional",
            "params": {
                "width": 512,
                "height": 512,
                "steps": 30,
                "n": 1,
                "sampler_name": "k_euler_a",
            },
            "models": ["stable_diffusion"],
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)

        if resp.status_code != 202:
            await status.delete()
            await message.answer(
                f"⚠️ AI Horde вернул {resp.status_code}.",
                reply_markup=main_menu()
            )
            return

        job_id = resp.json().get("id")
        check_url = f"https://stablehorde.net/api/v2/generate/check/{job_id}"

        for attempt in range(90):
            await asyncio.sleep(3)
            check = requests.get(check_url, timeout=15).json()

            if check.get("done"):
                status_url = f"https://stablehorde.net/api/v2/generate/status/{job_id}"
                result = requests.get(status_url, timeout=15).json()
                generations = result.get("generations", [])
                if not generations:
                    break

                img_url = generations[0].get("img")
                img = requests.get(img_url, timeout=30)

                if img.status_code == 200 and len(img.content) > 1000:
                    await status.delete()
                    photo = BufferedInputFile(img.content, filename="image.jpg")
                    await message.answer_photo(
                        photo,
                        caption=f"🎨 <b>Готово!</b>\n\n📝 <i>{prompt}</i>\n\n✨ <i>{enhanced[:100]}</i>",
                        parse_mode="HTML",
                        reply_markup=main_menu()
                    )
                    return
                break

            if attempt % 5 == 0 and attempt > 0:
                try:
                    await status.edit_text(
                        f"🎨 <b>Рисую...</b>\n\n"
                        f"⏳ Прошло: {attempt * 3} сек\n"
                        f"📊 Очередь: {check.get('queue_position', '?')}",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        await status.delete()
        await message.answer(
            "⚠️ Сервис перегружен. Попробуй другой промпт.",
            reply_markup=main_menu()
        )

    except Exception as e:
        await status.delete()
        await message.answer(
            f"😔 <b>Ошибка</b>\n\n<code>{e}</code>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )


# ==================== СВОБОДНЫЙ ЧАТ ====================
@dp.message(F.text & ~F.text.startswith("/"))
async def free_chat(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        return

    prompt = message.text.strip()
    if not prompt:
        return

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        answer = await generate_ai_answer(message.from_user.id, prompt)

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000], reply_markup=main_menu() if i == 0 else None)
        else:
            await message.answer(answer, reply_markup=main_menu())

    except Exception as e:
        await message.answer(
            f"😔 <b>Ошибка</b>\n\n<code>{e}</code>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

# ==================== ОБРАБОТКА ФОТО ====================
@dp.message(F.photo)
async def handle_photo(message: Message):
    await bot.send_chat_action(message.chat.id, "typing")

    status = await message.answer(
        "📸 <b>Смотрю на фото...</b>\n\n⏳ Анализирую",
        parse_mode="HTML"
    )

    try:
        # 1. Скачиваем фото
        photo = message.photo[-1]  # самое большое
        file_info = await bot.get_file(photo.file_id)

        # Скачиваем в память
        from io import BytesIO
        file_bytes = BytesIO()
        await bot.download_file(file_info.file_path, file_bytes)
        file_bytes.seek(0)

        # 2. Сохраняем во временный файл (GigaChat требует файл или base64)
        import base64
        img_base64 = base64.b64encode(file_bytes.read()).decode("utf-8")

        # 3. Отправляем в GigaChat
        user_text = message.caption or "Что на этом фото? Опиши подробно."

        # GigaChat Vision через attachments
        import uuid
        from gigachat.models import Chat, Messages, MessagesRole

        # Временное сохранение для GigaChat
        img_filename = f"/tmp/{uuid.uuid4()}.jpg"
        with open(img_filename, "wb") as f:
            file_bytes.seek(0)
            f.write(file_bytes.read())

        # Загружаем файл в GigaChat
        with open(img_filename, "rb") as f:
            uploaded = giga.upload_file(f)

        # Формируем запрос
        payload = Chat(messages=[
            Messages(
                role=MessagesRole.USER,
                content=user_text,
                attachments=[uploaded.id_]
            ),
        ])

        response = giga.chat(payload)
        answer = response.choices[0].message.content

        # Чистим LaTeX
        import re
        answer = re.sub(r'\$\$.*?\$\$', '', answer, flags=re.DOTALL)
        answer = re.sub(r'\$.*?\$', '', answer, flags=re.DOTALL)
        answer = answer.replace('$', '')
        answer = answer.strip()

        await status.delete()

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000], reply_markup=main_menu() if i == 0 else None)
        else:
            await message.answer(answer, reply_markup=main_menu())

        # Удаляем временный файл
        import os as _os
        try:
            _os.remove(img_filename)
        except Exception:
            pass

    except Exception as e:
        await status.delete()
        await message.answer(
            f"😔 <b>Ошибка</b>\n\n<code>{e}</code>\n\n"
            f"<i>Возможно, твой тариф GigaChat не поддерживает работу с изображениями.</i>",
            parse_mode="HTML",
            reply_markup=main_menu()
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
    init_db()
    print("✨ AI-бот запущен...")
    asyncio.create_task(start_web())
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())

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

GIGACHAT_KEY = os.environ.get("GIGACHAT_KEY")if not GIGACHAT_KEY:
    raise Exception("GIGACHAT_KEY не задан!")

TAVILY_KEY = os.environ.get("TAVILY_KEY", "")
HORDE_API_KEY = os.environ.get("HORDE_API_KEY", "0000000000")
DB_PATH = "manicure.db"
# ===================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# GigaChat-2-Max
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


# ==================== ПОИСК ====================
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


# ==================== УЛУЧШЕНИЕ ПРОМПТА ДЛЯ КАРТИНОК ====================
def enhance_image_prompt(prompt):
    """Переводит на английский и улучшает промпт через GigaChat."""
    try:
        sys_text = (
            "Ты — эксперт по промптам для Stable Diffusion. "
            "Твоя задача: перевести промпт на английский и добавить детали. "
            "Ответь ТОЛЬКО английским промптом, без пояснений, без кавычек, без точек. "
            "Пример: 'яблоко' → 'red juicy apple on wooden table, realistic, detailed, 4k, professional photography'"
        )
        user_text = f"Улучши промпт: {prompt}"
        payload = Chat(messages=[
            Messages(role=MessagesRole.SYSTEM, content=sys_text),
            Messages(role=MessagesRole.USER, content=user_text),
        ])
        resp = giga.chat(payload)
        enhanced = resp.choices[0].message.content.strip()
        # Очистка
        enhanced = enhanced.replace('"', '').replace("'", "").strip()
        if len(enhanced) > 5:
            return enhanced
        return prompt
    except Exception as e:
        print(f"Ошибка улучшения промпта: {e}")
        return prompt


# ==================== КЛАВИАТУРЫ (INLINE) ====================
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
        "🎨 <b>Картинки:</b> AI Horde (Stable Diffusion)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "💬 Задавай вопросы на русском.\n"
        "🎨 Описывай картинки подробно.\n"
        "🗑 /clear — очистить историю диалога."
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
    await call.message.edit_text(
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
    await call.message.edit_text(
        "❌ Отменено.",
        reply_markup=main_menu()
    )
    await call.answer()


# ==================== ОТВЕТ AI ====================
async def generate_ai_answer(user_id, prompt):
    """Генерирует ответ GigaChat с поиском и историей."""
    # Поиск в интернете
    search_results = search_web(prompt)

    # История диалога
    history = get_history(user_id, limit=10)

    # Системный промпт
    system_text = (
        "Ты — современный AI-ассистент. Отвечай на русском, кратко, "
        "с эмодзи для живости. Используй актуальную информацию из интернета. "
        "Если есть данные 2025-2026 — используй их. "
        "НЕ используй LaTeX, символы $ и $$."
    )

    # Собираем сообщения
    messages = [Messages(role=MessagesRole.SYSTEM, content=system_text)]

    # Добавляем историю
    for role, content in history:
        if role == "user":
            messages.append(Messages(role=MessagesRole.USER, content=content))
        else:
            messages.append(Messages(role=MessagesRole.ASSISTANT, content=content))

    # Текущий промпт
    if search_results:
        current = f"

#!/usr/bin/env python3
"""
Бот Историка - универсальная версия
Отправляет посты во все чаты, куда его добавят
"""

import os
import asyncio
import json
import random
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Set
import aiohttp
from pathlib import Path

# Импорты aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import executor
from aiogram.dispatcher.filters import Command

# ============================================================================
# НАСТРОЙКИ
# ============================================================================

# Токен бота из переменных окружения BotHost
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
if not TELEGRAM_TOKEN:
    print("❌ ОШИБКА: Установите TELEGRAM_TOKEN в настройках BotHost!")
    exit(1)

# Имя бота (можно изменить)
BOT_NAME = os.environ.get('BOT_NAME', 'Бот Историка')

# API ключи (опционально)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
HF_TOKEN = os.environ.get('HF_TOKEN', '')

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot_history.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# БАЗА ДАННЫХ ДЛЯ ХРАНЕНИЯ ЧАТОВ
# ============================================================================

class ChatDatabase:
    """Управление базой данных чатов"""
    
    def __init__(self, db_path: str = 'chats.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Инициализация базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица чатов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    chat_title TEXT,
                    chat_type TEXT,
                    added_date TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_post_date TEXT,
                    settings TEXT DEFAULT '{}'
                )
            ''')
            
            # Таблица отправленных постов (чтобы не дублировать)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sent_posts (
                    post_date TEXT,
                    chat_id INTEGER,
                    post_hash TEXT,
                    PRIMARY KEY (post_date, chat_id)
                )
            ''')
            
            conn.commit()
    
    def add_chat(self, chat_id: int, chat_title: str, chat_type: str):
        """Добавить чат в базу"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Проверяем, существует ли уже чат
            cursor.execute(
                'SELECT chat_id FROM chats WHERE chat_id = ?',
                (chat_id,)
            )
            
            if cursor.fetchone():
                # Обновляем информацию
                cursor.execute('''
                    UPDATE chats 
                    SET chat_title = ?, is_active = 1 
                    WHERE chat_id = ?
                ''', (chat_title, chat_id))
            else:
                # Добавляем новый чат
                cursor.execute('''
                    INSERT INTO chats (chat_id, chat_title, chat_type, added_date)
                    VALUES (?, ?, ?, ?)
                ''', (chat_id, chat_title, chat_type, datetime.now().isoformat()))
            
            conn.commit()
    
    def remove_chat(self, chat_id: int):
        """Удалить чат (деактивировать)"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE chats SET is_active = 0 WHERE chat_id = ?',
                (chat_id,)
            )
            conn.commit()
    
    def get_all_active_chats(self) -> List[Dict]:
        """Получить все активные чаты"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM chats 
                WHERE is_active = 1 
                ORDER BY added_date DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_chat_count(self) -> int:
        """Получить количество активных чатов"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM chats WHERE is_active = 1')
            return cursor.fetchone()[0]
    
    def mark_post_sent(self, chat_id: int, post_date: str, post_hash: str = None):
        """Пометить пост как отправленный"""
        if not post_hash:
            post_hash = str(hash(f"{post_date}_{chat_id}"))
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO sent_posts (post_date, chat_id, post_hash)
                VALUES (?, ?, ?)
            ''', (post_date, chat_id, post_hash))
            
            # Обновляем дату последнего поста в чате
            cursor.execute('''
                UPDATE chats 
                SET last_post_date = ? 
                WHERE chat_id = ?
            ''', (datetime.now().isoformat(), chat_id))
            
            conn.commit()
    
    def was_post_sent_today(self, chat_id: int) -> bool:
        """Проверка, отправлялся ли сегодня пост в этот чат"""
        today = datetime.now().strftime('%Y-%m-%d')
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 1 FROM sent_posts 
                WHERE chat_id = ? AND post_date = ?
            ''', (chat_id, today))
            return cursor.fetchone() is not None
    
    def clear_old_records(self, days: int = 30):
        """Очистка старых записей"""
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM sent_posts WHERE post_date < ?',
                (cutoff_date,)
            )
            conn.commit()

# Инициализация базы данных
db = ChatDatabase()

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================================================

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ============================================================================
# ЛИЧНОСТЬ БОТА
# ============================================================================

BOT_PERSONALITY = f"""{BOT_NAME} - цифровой историк с ироничным взглядом.

Я генерирую исторические посты каждый день в 9:00 по Москве!

Мой стиль:
🔥 Ироничный, но дружелюбный
🎭 С отсылками к истории и литературе
💫 Эмоциональный и восторженный
📚 Всегда нахожу параллели с прошлым

Добавь меня в чат, и я буду радовать участников ежедневными историческими открытиями!
"""

# ============================================================================
# ГЕНЕРАТОР ТЕКСТОВ
# ============================================================================

class TextGenerator:
    """Генератор текстов с несколькими стратегиями"""
    
    def __init__(self):
        self.templates = self._load_templates()
        self.history = self._load_historical_data()
        self.use_api = bool(OPENAI_API_KEY or HF_TOKEN)
        logger.info(f"Генератор готов. API: {'доступно' if self.use_api else 'шаблоны'}")
    
    def _load_templates(self) -> Dict:
        """Загрузка шаблонов"""
        return {
            'morning': [
                "Доброе утро! {event} было примерно в это время. Интересные параллели, правда?",
                "Эх, {figure} сегодня бы сказал: '{quote}'. Мудро! Хорошего дня!",
                "Историческая справка: {fact}. Пусть это вдохновит вас на великие дела!"
            ],
            'birthday': [
                "🎂 С днём рождения! {figure} как-то сказал: '{quote}'. Думаю, это про вас!",
                "Ого, вы отмечаете! Помните, как {event}? Вот это было событие!"
            ],
            'holiday': [
                "🎉 {holiday}! {parallel}. Отмечаем как исторические личности!",
                "В этот день {event}. А мы сегодня {holiday}! Какие параллели!"
            ]
        }
    
    def _load_historical_data(self) -> Dict:
        """Исторические данные"""
        return {
            'figures': [
                {"name": "Цицерон", "quote": "О времена, о нравы!"},
                {"name": "Пётр I", "quote": "Все люди — лжецы и лицемеры."},
                {"name": "Екатерина II", "quote": "Побольше действий, поменьше слов."},
                {"name": "Наполеон", "quote": "Воображение правит миром."},
                {"name": "Пушкин", "quote": "А счастье было так возможно..."},
                {"name": "Ленин", "quote": "Учиться, учиться и учиться."},
            ],
            'events': [
                "Цезарь переходил Рубикон",
                "Наполеон отступал из России",
                "Гагарин летел в космос",
                "Пушкин дописывал 'Евгения Онегина'",
                "Суворов переходил Альпы"
            ],
            'facts': [
                "В 1812 году началось Бородинское сражение",
                "Первый телефонный звонок был в 1876 году",
                "Древние римляне знали про центральное отопление"
            ]
        }
    
    def _get_random_history(self) -> Dict:
        """Случайные исторические данные"""
        return {
            'figure': random.choice(self.history['figures'])['name'],
            'quote': random.choice(self.history['figures'])['quote'],
            'event': random.choice(self.history['events']),
            'fact': random.choice(self.history['facts'])
        }
    
    async def generate_daily_post(self) -> str:
        """Генерация ежедневного поста"""
        history = self._get_random_history()
        template = random.choice(self.templates['morning'])
        
        # Получаем праздники на сегодня
        holiday = self._get_today_holiday()
        
        if holiday:
            # Если есть праздник, добавляем его
            holiday_template = random.choice(self.templates['holiday'])
            holiday_text = holiday_template.format(
                holiday=holiday,
                parallel=f"Напоминает {history['event'].lower()}",
                event=history['event']
            )
            main_text = template.format(**history)
            return f"{main_text}\n\n{holiday_text}"
        else:
            # Обычный день
            return template.format(**history)
    
    def _get_today_holiday(self) -> str:
        """Получить праздник на сегодня"""
        holidays = {
            "01-01": "Новый год",
            "01-07": "Рождество",
            "01-14": "Старый Новый год",
            "02-23": "День защитника Отечества",
            "03-08": "Международный женский день",
            "05-01": "Праздник весны и труда",
            "05-09": "День Победы",
            "06-12": "День России",
            "11-04": "День народного единства",
        }
        
        today = datetime.now().strftime("%m-%d")
        return holidays.get(today, "")
    
    async def generate_with_api(self, prompt: str) -> str:
        """Генерация через API (если доступно)"""
        if not self.use_api:
            return None
        
        try:
            # OpenAI
            if OPENAI_API_KEY:
                async with aiohttp.ClientSession() as session:
                    data = {
                        "model": "gpt-3.5-turbo",
                        "messages": [
                            {"role": "system", "content": BOT_PERSONALITY},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 150,
                        "temperature": 0.8
                    }
                    
                    async with session.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                        json=data,
                        timeout=10
                    ) as response:
                        
                        if response.status == 200:
                            result = await response.json()
                            return result['choices'][0]['message']['content'].strip()
            
            # Hugging Face
            elif HF_TOKEN:
                async with aiohttp.ClientSession() as session:
                    data = {
                        "inputs": f"{BOT_PERSONALITY}\n\n{prompt}",
                        "parameters": {"max_length": 200, "temperature": 0.9}
                    }
                    
                    async with session.post(
                        "https://api-inference.huggingface.co/models/microsoft/phi-2",
                        headers={"Authorization": f"Bearer {HF_TOKEN}"},
                        json=data,
                        timeout=10
                    ) as response:
                        
                        if response.status == 200:
                            result = await response.json()
                            return result[0]['generated_text'].split('\n')[0].strip()
        
        except Exception as e:
            logger.warning(f"API ошибка: {e}")
        
        return None

# Инициализация генератора
generator = TextGenerator()

# ============================================================================
# ОСНОВНАЯ ЛОГИКА РАССЫЛКИ
# ============================================================================

async def send_post_to_all_chats():
    """Отправка поста во все активные чаты"""
    
    # Проверяем московское время (UTC+3)
    utc_now = datetime.utcnow()
    moscow_time = utc_now + timedelta(hours=3)
    
    # Только в 9:00 по Москве
    if moscow_time.hour != 9 or moscow_time.minute != 0:
        return
    
    logger.info(f"🕘 {moscow_time.strftime('%H:%M')} МСК - начинаем рассылку")
    
    # Получаем все активные чаты
    chats = db.get_all_active_chats()
    if not chats:
        logger.info("Нет активных чатов для рассылки")
        return
    
    logger.info(f"Найдено {len(chats)} активных чатов")
    
    # Генерируем пост один раз для всех чатов
    post_text = await generate_daily_post()
    
    if not post_text:
        logger.error("Не удалось сгенерировать пост")
        return
    
    # Форматируем пост
    formatted_post = f"📜 *{BOT_NAME}* 📜\n\n{post_text}\n\n_{moscow_time.strftime('%d.%m.%Y')}_\n#история #цитатадня"
    
    # Отправляем во все чаты
    success_count = 0
    fail_count = 0
    
    for chat in chats:
        chat_id = chat['chat_id']
        chat_title = chat['chat_title']
        
        # Проверяем, не отправляли ли уже сегодня
        if db.was_post_sent_today(chat_id):
            logger.info(f"↪️ Пропускаем {chat_title} - уже отправляли сегодня")
            continue
        
        try:
            # Пытаемся отправить
            await bot.send_message(
                chat_id=chat_id,
                text=formatted_post,
                parse_mode="Markdown",
                disable_notification=False
            )
            
            # Помечаем как отправленное
            db.mark_post_sent(chat_id, moscow_time.strftime('%Y-%m-%d'))
            
            logger.info(f"✅ Отправлено в: {chat_title} (ID: {chat_id})")
            success_count += 1
            
            # Небольшая пауза между отправками
            await asyncio.sleep(0.5)
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Анализируем ошибку
            if "chat not found" in error_msg or "bot was kicked" in error_msg:
                logger.warning(f"🗑️ Удаляем чат {chat_title} - бота исключили")
                db.remove_chat(chat_id)
            elif "not enough rights" in error_msg:
                logger.warning(f"⚠️ Нет прав в чате {chat_title}")
            elif "Too Many Requests" in error_msg:
                logger.warning(f"⏳ Лимит запросов, ждем...")
                await asyncio.sleep(5)
            else:
                logger.error(f"❌ Ошибка отправки в {chat_title}: {e}")
            
            fail_count += 1
    
    # Итоги рассылки
    logger.info(f"📊 Итоги рассылки: {success_count} успешно, {fail_count} ошибок")
    
    # Очистка старых записей раз в неделю
    if moscow_time.weekday() == 0:  # Понедельник
        db.clear_old_records()
        logger.info("🧹 Выполнена очистка старых записей")

async def generate_daily_post() -> str:
    """Генерация поста с приоритетом API"""
    
    # Пытаемся использовать API
    if generator.use_api:
        api_prompt = "Напиши короткий ироничный исторический пост на утро. 1-2 предложения."
        api_text = await generator.generate_with_api(api_prompt)
        
        if api_text:
            return api_text
    
    # Используем шаблоны как запасной вариант
    return await generator.generate_daily_post()

# ============================================================================
# КОМАНДЫ БОТА
# ============================================================================

@dp.message_handler(Command('start', 'help'))
async def cmd_start(message: types.Message):
    """Приветственное сообщение"""
    welcome_text = f"""
🤖 *{BOT_NAME}*

Привет! Я бот, который каждый день в 9:00 по Москве присылаю интересные исторические посты с ироничным взглядом.

*Как использовать:*
1. Добавьте меня в группу или канал
2. Дайте права на отправку сообщений
3. Я автоматически начну отправлять ежедневные посты!

*Доступные команды:*
/start или /help - это сообщение
/chats - список всех чатов, где я работаю
/test - тестовая отправка поста
/stop - остановить рассылку в этом чате
/stats - статистика бота
/post_now - отправить пост прямо сейчас (только для админов)
/settings - настройки (в разработке)

Добавляйте меня в чаты и наслаждайтесь историческими открытиями! 📜
"""
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message_handler(Command('chats'))
async def cmd_chats(message: types.Message):
    """Показать все чаты"""
    chats = db.get_all_active_chats()
    
    if not chats:
        await message.answer("📭 Я ещё не добавлен ни в один чат.")
        return
    
    response = f"📋 *Чаты, где я работаю:* ({len(chats)})\n\n"
    
    for i, chat in enumerate(chats[:20], 1):  # Ограничиваем 20 чатами
        last_post = chat['last_post_date']
        if last_post:
            last_post = datetime.fromisoformat(last_post).strftime('%d.%m.%Y')
        else:
            last_post = "ещё не было"
        
        response += f"{i}. {chat['chat_title']}\n"
        response += f"   ID: `{chat['chat_id']}`\n"
        response += f"   Последний пост: {last_post}\n\n"
    
    if len(chats) > 20:
        response += f"\n... и ещё {len(chats) - 20} чатов"
    
    await message.answer(response, parse_mode="Markdown")

@dp.message_handler(Command('test'))
async def cmd_test(message: types.Message):
    """Тестовая отправка поста в этот чат"""
    if message.chat.type == 'private':
        await message.answer("Эта команда работает только в группах и каналах!")
        return
    
    await message.answer("🧪 Генерирую тестовый пост...")
    
    post_text = await generate_daily_post()
    formatted_post = f"📜 *Тестовый пост от {BOT_NAME}* 📜\n\n{post_text}\n\n#тест"
    
    try:
        await bot.send_message(
            chat_id=message.chat.id,
            text=formatted_post,
            parse_mode="Markdown"
        )
        await message.answer("✅ Тестовый пост отправлен!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message_handler(Command('stop'))
async def cmd_stop(message: types.Message):
    """Остановить рассылку в этом чате"""
    if message.chat.type == 'private':
        await message.answer("Эта команда работает только в группах и каналах!")
        return
    
    db.remove_chat(message.chat.id)
    await message.answer(
        "✅ Рассылка остановлена в этом чате.\n"
        "Чтобы возобновить, просто напишите /start"
    )

@dp.message_handler(Command('stats'))
async def cmd_stats(message: types.Message):
    """Статистика бота"""
    chat_count = db.get_chat_count()
    utc_now = datetime.utcnow()
    moscow_time = utc_now + timedelta(hours=3)
    
    stats_text = f"""
📊 *Статистика {BOT_NAME}*

*Общее:*
• Активных чатов: {chat_count}
• Время (МСК): {moscow_time.strftime('%H:%M:%S')}
• Дата: {moscow_time.strftime('%d.%m.%Y')}
• Режим генерации: {'API' if generator.use_api else 'Шаблоны'}

*Ближайшая рассылка:*
• Ежедневно в 9:00 по Москве
• Следующая через: {_next_post_in(moscow_time)}

*Команды управления:*
/chats - список чатов
/test - тест в этом чате  
/stop - остановить здесь
/post_now - срочный пост (админы)
"""
    
    await message.answer(stats_text, parse_mode="Markdown")

def _next_post_in(moscow_time: datetime) -> str:
    """Время до следующей рассылки"""
    next_post = moscow_time.replace(hour=9, minute=0, second=0, microsecond=0)
    
    if moscow_time >= next_post:
        next_post += timedelta(days=1)
    
    delta = next_post - moscow_time
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    return f"{hours}ч {minutes}м"

@dp.message_handler(Command('post_now'))
async def cmd_post_now(message: types.Message):
    """Отправить пост прямо сейчас (для админов)"""
    # Проверка на админа (можно настроить список ID)
    admin_ids = os.environ.get('ADMIN_IDS', '').split(',')
    admin_ids = [int(id.strip()) for id in admin_ids if id.strip()]
    
    if message.from_user.id not in admin_ids and not admin_ids:
        # Если не админ, проверяем что команда в личке
        if message.chat.type != 'private':
            await message.answer("Эта команда только для администраторов.")
            return
    
    await message.answer("🚀 Отправляю пост во все чаты...")
    
    # Запускаем рассылку
    await send_post_to_all_chats()
    
    await message.answer("✅ Рассылка завершена!")

@dp.message_handler(content_types=['new_chat_members'])
async def on_new_chat_members(message: types.Message):
    """Когда бота добавляют в чат"""
    new_members = message.new_chat_members
    
    for member in new_members:
        if member.id == bot.id:
            # Бота добавили в чат
            chat_title = message.chat.title or f"Чат {message.chat.id}"
            
            # Добавляем чат в базу
            db.add_chat(
                chat_id=message.chat.id,
                chat_title=chat_title,
                chat_type=message.chat.type
            )
            
            # Приветственное сообщение
            welcome_msg = (
                f"📜 *{BOT_NAME} добавлен в чат!* 📜\n\n"
                f"Приветствую, {chat_title}! 🎉\n\n"
                f"Я буду присылать исторические посты каждый день в 9:00 по Москве.\n\n"
                f"*Команды в этом чате:*\n"
                f"/test - тестовый пост\n"
                f"/stop - остановить рассылку\n\n"
                f"До завтрашнего утра! ✨"
            )
            
            try:
                await bot.send_message(
                    chat_id=message.chat.id,
                    text=welcome_msg,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить приветствие: {e}")

@dp.message_handler(content_types=['left_chat_member'])
async def on_left_chat_member(message: types.Message):
    """Когда бота исключают из чата"""
    left_member = message.left_chat_member
    
    if left_member.id == bot.id:
        # Бота исключили из чата
        db.remove_chat(message.chat.id)
        logger.info(f"Бота исключили из чата {message.chat.id}")

# ============================================================================
# ФОНОВЫЙ ПЛАНИРОВЩИК
# ============================================================================

async def background_scheduler():
    """Фоновый планировщик для рассылки"""
    logger.info("⏰ Планировщик запущен")
    
    while True:
        try:
            await send_post_to_all_chats()
            await asyncio.sleep(55)  # Проверяем каждые 55 секунд
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")
            await asyncio.sleep(60)

# ============================================================================
# ЗАПУСК И ОСТАНОВКА
# ============================================================================

async def on_startup(_):
    """Действия при запуске"""
    logger.info("=" * 50)
    logger.info(f"🚀 {BOT_NAME} запускается...")
    logger.info(f"📊 Активных чатов: {db.get_chat_count()}")
    logger.info(f"⚙️ Режим генерации: {'API' if generator.use_api else 'Шаблоны'}")
    logger.info("=" * 50)
    
    # Запускаем планировщик
    asyncio.create_task(background_scheduler())

async def on_shutdown(_):
    """Действия при остановке"""
    logger.info("Останавливаем бота...")
    await bot.close()

# ============================================================================
# ТОЧКА ВХОДА
# ============================================================================

if __name__ == '__main__':
    logger.info("Запуск универсального бота...")
    
    try:
        executor.start_polling(
            dp,
            skip_updates=True,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            timeout=60,
            relax=0.1
        )
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)

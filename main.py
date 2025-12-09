#!/usr/bin/env python3
"""
Бот Историка - автономный генератор исторических постов
Работает на BotHost без .env файла
"""

import os
import asyncio
import json
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import aiohttp

# Импортируем aiogram
try:
    from aiogram import Bot, Dispatcher, types
    from aiogram.contrib.fsm_storage.memory import MemoryStorage
    from aiogram.utils import executor
except ImportError:
    print("Ошибка: Установите aiogram: pip install aiogram")
    exit(1)

# ============================================================================
# НАСТРОЙКИ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ BOTHOST (НЕТ .env ФАЙЛА!)
# ============================================================================

# Получаем переменные из настроек BotHost
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
GROUP_ID = os.environ.get('GROUP_ID', '')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')  # Опционально
HF_TOKEN = os.environ.get('HF_TOKEN', '')  # Опционально, для Hugging Face
BOT_NAME = os.environ.get('BOT_NAME', 'Бот Историка')

# Проверка обязательных переменных
if not TELEGRAM_TOKEN:
    print("ОШИБКА: Установите переменную TELEGRAM_TOKEN в настройках BotHost!")
    exit(1)

if not GROUP_ID:
    print("ПРЕДУПРЕЖДЕНИЕ: GROUP_ID не установлен. Использую тестовый режим.")
    TEST_MODE = True
    GROUP_ID = None
else:
    TEST_MODE = False
    try:
        GROUP_ID = int(GROUP_ID)
    except ValueError:
        print("ОШИБКА: GROUP_ID должен быть числом!")
        exit(1)

# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================

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
# ИНИЦИАЛИЗАЦИЯ БОТА
# ============================================================================

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ============================================================================
# ЛИЧНОСТЬ БОТА И СТИЛЬ
# ============================================================================

BOT_PERSONALITY = f"""{BOT_NAME} - цифровой гуру с ироничным взглядом на историю.

Стиль общения:
🔥 Ироничный, но дружелюбный
🎭 С отсылками к историческим событиям и классической литературе
🤯 Современный сленг + уважение к классике
💫 Восторженный, эмоциональный, иногда драматичный
📚 Всегда находит параллели с прошлым
🎉 Праздничный и позитивный

Примеры стиля:
- "Как говаривал Цицерон на тусовке в Сенате: 'Братан, даже Цезарь бы ахуел!'"
- "Сегодня, подобно Наполеону, входящему в Москву, ты вступаешь в новый год!"
- "Эх, Пётр I рубил окно в Европу, а ты сегодня просто рубишь!"
"""

# ============================================================================
# ГЕНЕРАТОР ТЕКСТОВ (АДАПТИРОВАН ДЛЯ BOTHOST)
# ============================================================================

class TextGenerator:
    """Умный генератор текстов с несколькими стратегиями"""
    
    def __init__(self):
        self.cache = {}
        self.use_api = bool(OPENAI_API_KEY or HF_TOKEN)
        self.api_providers = self._setup_api_providers()
        self.templates = self._load_templates()
        self.historical_data = self._load_historical_data()
        logger.info(f"Генератор инициализирован, API: {'доступно' if self.use_api else 'недоступно'}")
    
    def _setup_api_providers(self) -> List[Dict]:
        """Настройка доступных API провайдеров"""
        providers = []
        
        if OPENAI_API_KEY:
            providers.append({
                'name': 'OpenAI',
                'url': 'https://api.openai.com/v1/chat/completions',
                'headers': {'Authorization': f'Bearer {OPENAI_API_KEY}'},
                'model': 'gpt-3.5-turbo'
            })
        
        if HF_TOKEN:
            providers.append({
                'name': 'HuggingFace',
                'url': 'https://api-inference.huggingface.co/models/microsoft/phi-2',
                'headers': {'Authorization': f'Bearer {HF_TOKEN}'},
                'model': 'phi-2'
            })
        
        # Бесплатные альтернативы (меньше вероятность работать)
        providers.append({
            'name': 'FreeAI',
            'url': 'https://free.churchless.tech/v1/chat/completions',
            'headers': {},
            'model': 'gpt-3.5-turbo'
        })
        
        return providers
    
    def _load_templates(self) -> Dict:
        """Загрузка шаблонов для генерации"""
        return {
            'birthday': [
                "🎂 {name}, с днём рождения! {historical_figure} как-то сказал: '{quote}'. Думаю, это как раз про тебя сегодня!",
                "Ого-го! {name} отмечает! Помнишь, как {historical_event}? Вот это было событие! Желаю такого же масштаба!",
                "{name}, ты сегодня как {historical_figure} в день своей победы! Поздравляю, пусть будет эпично!"
            ],
            'holiday': [
                "🎉 {holiday}! {historical_parallel}. Отмечаем как настоящие исторические личности!",
                "В этот день {historical_event}. А мы сегодня {holiday}! Какие параллели, а?",
                "{holiday} — отличный повод вспомнить, как {historical_figure} {historical_action}. Веселимся!"
            ],
            'daily': [
                "Доброе утро! {historical_event} было примерно в это время. А мы? Мы делаем историю сегодня!",
                "Эх, {historical_figure} сегодня бы сказал: '{quote}'. Мудро, правда? Хорошего дня!",
                "Историческая справка на сегодня: {historical_fact}. Пусть это вдохновит вас!"
            ],
            'fallback': [
                "Эх, сегодня даже Архимед не нашёл бы повода для 'Эврика!'... Но день всё равно прекрасен!",
                "История молчит о сегодняшнем дне... значит, мы сами её создадим!",
                "Как говорил Суворов: 'Тяжело в ученье — легко в понедельник!' Вперёд!"
            ]
        }
    
    def _load_historical_data(self) -> Dict:
        """База исторических данных для генерации"""
        return {
            'figures': [
                {"name": "Цицерон", "quote": "О времена, о нравы!", "era": "Древний Рим"},
                {"name": "Пётр I", "quote": "Все люди — лжецы и лицемеры.", "era": "Российская империя"},
                {"name": "Екатерина II", "quote": "Побольше действий, поменьше слов.", "era": "Российская империя"},
                {"name": "Наполеон", "quote": "Воображение правит миром.", "era": "Наполеоновские войны"},
                {"name": "Пушкин", "quote": "А счастье было так возможно...", "era": "Золотой век"},
                {"name": "Ленин", "quote": "Учиться, учиться и учиться.", "era": "СССР"},
                {"name": "Черчилль", "quote": "Успех — это движение от неудачи к неудаче.", "era": "XX век"}
            ],
            'events': [
                "Цезарь перешёл Рубикон",
                "Наполеон отступил из России", 
                "Гагарин полетел в космос",
                "Пушкин дописал 'Евгения Онегина'",
                "Суворов перешёл Альпы",
                "Толстой закончил 'Войну и мир'",
                "Был основан Санкт-Петербург",
                "Состоялась Бородинская битва"
            ],
            'facts': [
                "В этот день в 1812 году началось Бородинское сражение",
                "Ровно 100 лет назад люди ещё не знали про интернет",
                "В XIX веке утренний кофе был настоящим ритуалом",
                "Первый телефонный звонок состоялся в 1876 году",
                "Древние римляне уже знали про центральное отопление"
            ]
        }
    
    def _get_random_historical(self) -> Dict:
        """Получить случайные исторические данные"""
        figure = random.choice(self.historical_data['figures'])
        event = random.choice(self.historical_data['events'])
        fact = random.choice(self.historical_data['facts'])
        
        return {
            'figure': figure['name'],
            'quote': figure['quote'],
            'event': event,
            'fact': fact,
            'era': figure['era']
        }
    
    async def generate_via_api(self, prompt: str, provider: Dict) -> str:
        """Генерация через внешний API"""
        try:
            async with aiohttp.ClientSession() as session:
                if provider['name'] == 'OpenAI':
                    data = {
                        "model": provider['model'],
                        "messages": [
                            {"role": "system", "content": BOT_PERSONALITY},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 150,
                        "temperature": 0.8
                    }
                else:
                    data = {
                        "inputs": f"{BOT_PERSONALITY}\n\n{prompt}",
                        "parameters": {"max_length": 200, "temperature": 0.9}
                    }
                
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.post(
                    provider['url'],
                    headers=provider['headers'],
                    json=data,
                    timeout=timeout
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        
                        if provider['name'] == 'OpenAI':
                            text = result['choices'][0]['message']['content'].strip()
                        else:
                            text = result[0]['generated_text'].split('\n')[0].strip()
                        
                        return text[:500]
                    
        except Exception as e:
            logger.warning(f"API {provider['name']} ошибка: {e}")
        
        return None
    
    async def generate_template_text(self, template_type: str, **kwargs) -> str:
        """Генерация по шаблону"""
        templates = self.templates.get(template_type, self.templates['fallback'])
        template = random.choice(templates)
        
        # Добавляем исторические данные
        history = self._get_random_historical()
        
        # Заполняем шаблон
        result = template.format(
            **kwargs,
            historical_figure=history['figure'],
            historical_event=history['event'],
            historical_fact=history['fact'],
            quote=history['quote'],
            historical_parallel=f"Напоминает {history['event'].lower()}",
            historical_action=random.choice(["торжествовал", "размышлял", "сражался", "творил"])
        )
        
        return result
    
    async def generate(self, context: Dict) -> str:
        """
        Основной метод генерации текста
        context: {'type': 'birthday/holiday/daily', 'data': {...}}
        """
        cache_key = f"{context['type']}_{json.dumps(context['data'], sort_keys=True)}"
        
        # Проверяем кэш
        if cache_key in self.cache:
            logger.info("Используем кэшированный текст")
            return self.cache[cache_key]
        
        text = None
        
        # Пытаемся использовать API
        if self.use_api:
            for provider in self.api_providers:
                prompt = self._create_prompt(context)
                text = await self.generate_via_api(prompt, provider)
                if text:
                    logger.info(f"Сгенерировано через {provider['name']}")
                    break
        
        # Если API не сработало, используем шаблоны
        if not text:
            text = await self.generate_template_text(
                context['type'],
                **context['data']
            )
            logger.info("Сгенерировано по шаблону")
        
        # Кэшируем результат (на сутки)
        self.cache[cache_key] = text
        self._clean_cache()
        
        return text
    
    def _create_prompt(self, context: Dict) -> str:
        """Создание промпта для API"""
        if context['type'] == 'birthday':
            return f"Сгенерируй ироничное поздравление с днём рождения для {context['data'].get('names', 'друга')}. Добавь историческую параллель. Текст должен быть коротким (1-2 предложения)."
        elif context['type'] == 'holiday':
            return f"Напиши короткий ироничный пост о празднике {context['data'].get('holiday', 'этом дне')} с исторической отсылкой."
        else:
            return f"Придумай короткое ироничное утреннее сообщение с исторической параллелью на сегодня."
    
    def _clean_cache(self):
        """Очистка старого кэша (сохраняем только 100 записей)"""
        if len(self.cache) > 100:
            # Удаляем самые старые записи
            keys = list(self.cache.keys())[:-50]
            for key in keys:
                del self.cache[key]

# ============================================================================
# МЕНЕДЖЕР ПРАЗДНИКОВ И СОБЫТИЙ
# ============================================================================

class EventManager:
    """Управление праздниками и событиями"""
    
    def __init__(self):
        self.holidays = self._load_default_holidays()
        self.birthdays = self._load_default_birthdays()
        self.sent_dates = set()
        logger.info("Менеджер событий инициализирован")
    
    def _load_default_holidays(self) -> Dict:
        """Загрузка праздников по умолчанию"""
        return {
            "01-01": "Новый год",
            "01-07": "Рождество",
            "01-14": "Старый Новый год",
            "01-25": "День студента",
            "02-23": "День защитника Отечества", 
            "03-08": "Международный женский день",
            "05-01": "Праздник весны и труда",
            "05-09": "День Победы",
            "06-01": "День защиты детей",
            "06-12": "День России",
            "11-04": "День народного единства",
            "12-31": "Канун Нового года"
        }
    
    def _load_default_birthdays(self) -> Dict:
        """Загрузка дней рождения по умолчанию"""
        return {
            "01-15": ["Иван Грозный", "Арина Родионовна"],
            "02-08": ["Жюль Верн", "Дмитрий Менделеев"],
            "03-31": ["Рене Декарт"],
            "04-15": ["Леонардо да Винчи"],
            "05-24": ["Иосиф Бродский"],
            "06-06": ["Александр Пушкин"],
            "07-18": ["Уильям Теккерей"],
            "08-19": ["Билл Клинтон"],
            "09-08": ["Лев Толстой"],
            "10-31": ["Иоганн Кеплер"],
            "11-22": ["Шарль де Голль"],
            "12-05": ["Уолт Дисней"]
        }
    
    def get_today_events(self) -> Dict:
        """Получить события на сегодня"""
        today_key = datetime.now().strftime("%m-%d")
        today_full = datetime.now().strftime("%Y-%m-%d")
        
        # Проверяем, не отправляли ли уже сегодня
        if today_full in self.sent_dates:
            return {'already_sent': True}
        
        events = {
            'date': datetime.now().strftime("%d %B %Y"),
            'holidays': [],
            'birthdays': [],
            'already_sent': False
        }
        
        # Добавляем праздники
        if today_key in self.holidays:
            events['holidays'].append(self.holidays[today_key])
        
        # Добавляем дни рождения
        if today_key in self.birthdays:
            events['birthdays'].extend(self.birthdays[today_key])
        
        # Помечаем как отправленное
        self.sent_dates.add(today_full)
        
        return events
    
    def add_birthday(self, date: str, names: List[str]):
        """Добавить день рождения (для команд)"""
        if date in self.birthdays:
            self.birthdays[date].extend(names)
        else:
            self.birthdays[date] = names
    
    def clear_sent_dates(self):
        """Очистить историю отправок (на случай перезапуска)"""
        self.sent_dates.clear()

# ============================================================================
# ОСНОВНАЯ ЛОГИКА БОТА
# ============================================================================

# Инициализация компонентов
text_generator = TextGenerator()
event_manager = EventManager()

async def generate_daily_post():
    """Главная функция генерации ежедневного поста"""
    
    # Получаем московское время (UTC+3)
    utc_now = datetime.utcnow()
    moscow_time = utc_now + timedelta(hours=3)
    
    # Проверяем, 9:00 ли по Москве
    if moscow_time.hour != 9 or moscow_time.minute != 0:
        return False
    
    logger.info(f"=== Начинаем генерацию поста на {moscow_time.strftime('%d.%m.%Y %H:%M')} ===")
    
    # Получаем события дня
    events = event_manager.get_today_events()
    
    if events.get('already_sent', False):
        logger.info("Пост уже отправлен сегодня")
        return False
    
    # Определяем тип контекста
    if events['birthdays']:
        context_type = 'birthday'
        context_data = {'names': ', '.join(events['birthdays'])}
    elif events['holidays']:
        context_type = 'holiday'
        context_data = {'holiday': ', '.join(events['holidays'])}
    else:
        context_type = 'daily'
        context_data = {}
    
    context = {
        'type': context_type,
        'data': context_data
    }
    
    # Генерируем текст
    try:
        generated_text = await text_generator.generate(context)
        
        # Формируем финальный пост
        post = f"📜 *{BOT_NAME.upper()}* 📜\n\n"
        post += f"{generated_text}\n\n"
        
        # Добавляем информацию о событиях
        if events['birthdays']:
            post += f"🎂 Дни рождения: {', '.join(events['birthdays'])}\n"
        if events['holidays']:
            post += f"🎉 Праздник: {', '.join(events['holidays'])}\n"
        
        post += f"\n_{events['date']}_\n"
        post += "#история #цитатадня #историческиепараллели"
        
        # Отправляем пост
        if not TEST_MODE:
            await bot.send_message(
                chat_id=GROUP_ID,
                text=post,
                parse_mode="Markdown",
                disable_notification=False
            )
            logger.info(f"Пост отправлен в группу {GROUP_ID}")
        else:
            # Тестовый вывод
            print("\n" + "="*50)
            print("ТЕСТОВЫЙ ПОСТ (не отправлен):")
            print(post)
            print("="*50 + "\n")
            logger.info("Пост сгенерирован (тестовый режим)")
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при генерации поста: {e}", exc_info=True)
        return False

# ============================================================================
# КОМАНДЫ БОТА
# ============================================================================

@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    """Справка по командам"""
    help_text = f"""
🤖 *{BOT_NAME}*

Я автоматически генерирую исторические посты каждый день в 9:00 по Москве!

*Доступные команды:*
/start или /help - это сообщение
/test - тестовая генерация поста
/status - статус бота
/today - события сегодняшнего дня
/simulate - симулировать генерацию (только для админов)
/add_birthday - добавить день рождения (формат: 01-15 Иван)
/clear_cache - очистить кэш генератора

*Настройки в BotHost:*
TELEGRAM_TOKEN - токен бота
GROUP_ID - ID группы/канала
OPENAI_API_KEY - ключ OpenAI (опционально)
HF_TOKEN - токен HuggingFace (опционально)
"""
    await message.answer(help_text, parse_mode="Markdown")

@dp.message_handler(commands=['test'])
async def cmd_test(message: types.Message):
    """Тестовая генерация"""
    await message.answer("🧪 Генерирую тестовый пост...")
    
    test_context = {
        'type': 'birthday',
        'data': {'names': 'Тестовый Пользователь'}
    }
    
    try:
        text = await text_generator.generate(test_context)
        await message.answer(f"📜 *Тестовый пост:*\n\n{text}", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message_handler(commands=['status'])
async def cmd_status(message: types.Message):
    """Статус бота"""
    utc_now = datetime.utcnow()
    moscow_time = utc_now + timedelta(hours=3)
    
    status_text = f"""
📊 *Статус {BOT_NAME}*

*Время:*
• UTC: {utc_now.strftime('%H:%M:%S')}
• Москва: {moscow_time.strftime('%H:%M:%S')}
• Дата: {moscow_time.strftime('%d.%m.%Y')}

*Режим работы:*
• Режим: {'ТЕСТОВЫЙ' if TEST_MODE else 'РАБОЧИЙ'}
• Группа: {f'ID {GROUP_ID}' if not TEST_MODE else 'не указана'}
• API доступно: {'Да' if text_generator.use_api else 'Нет'}

*Статистика:*
• Размер кэша: {len(text_generator.cache)}
• Событий в базе: {len(event_manager.holidays)} праздников, {len(event_manager.birthdays)} ДР

*Следующий пост:* 9:00 МСК
"""
    await message.answer(status_text, parse_mode="Markdown")

@dp.message_handler(commands=['today'])
async def cmd_today(message: types.Message):
    """События сегодня"""
    events = event_manager.get_today_events()
    
    today_text = f"""
📅 *События на сегодня*

*Дата:* {events['date']}

*Праздники:*
{chr(10).join(f'• {h}' for h in events['holidays']) if events['holidays'] else '• Нет праздников'}

*Дни рождения:*
{chr(10).join(f'• {b}' for b in events['birthdays']) if events['birthdays'] else '• Нет дней рождения'}

*Статус:* {'Пост уже отправлен' if events.get('already_sent') else 'Ожидается отправка в 9:00'}
"""
    await message.answer(today_text, parse_mode="Markdown")

@dp.message_handler(commands=['simulate'])
async def cmd_simulate(message: types.Message):
    """Симуляция генерации (только для админа)"""
    # Простая проверка на админа (можно улучшить)
    if message.from_user.id != message.chat.id:  # Только в личке
        await message.answer("Эта команда только в личных сообщениях")
        return
    
    await message.answer("🎭 Симулирую генерацию поста...")
    success = await generate_daily_post()
    
    if success:
        await message.answer("✅ Генерация завершена успешно!")
    else:
        await message.answer("❌ Генерация не выполнена (возможно, не время или уже отправляли)")

@dp.message_handler(commands=['clear_cache'])
async def cmd_clear_cache(message: types.Message):
    """Очистка кэша"""
    text_generator.cache.clear()
    event_manager.clear_sent_dates()
    await message.answer("✅ Кэш очищен!")

@dp.message_handler(commands=['add_birthday'])
async def cmd_add_birthday(message: types.Message):
    """Добавить день рождения"""
    args = message.get_args().strip()
    
    if not args:
        await message.answer(
            "Формат: /add_birthday ММ-ДД Имя\n"
            "Пример: /add_birthday 01-15 Иван Иванов\n\n"
            "Текущие дни рождения:\n" +
            "\n".join([f"{date}: {', '.join(names)}" 
                      for date, names in event_manager.birthdays.items()])
        )
        return
    
    try:
        parts = args.split(' ', 1)
        if len(parts) != 2:
            raise ValueError
        
        date_str, name = parts
        event_manager.add_birthday(date_str, [name])
        
        await message.answer(f"✅ Добавлен день рождения: {date_str} - {name}")
    except:
        await message.answer("❌ Неверный формат. Используйте: ММ-ДД Имя")

# ============================================================================
# ФОНОВЫЙ ПЛАНИРОВЩИК
# ============================================================================

async def background_scheduler():
    """Фоновая задача для планировщика"""
    logger.info("Фоновый планировщик запущен")
    
    while True:
        try:
            await generate_daily_post()
            await asyncio.sleep(55)  # Проверяем каждые 55 секунд
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            await asyncio.sleep(60)

# ============================================================================
# ЗАПУСК И ОСТАНОВКА
# ============================================================================

async def on_startup(_):
    """Действия при запуске"""
    logger.info("=" * 50)
    logger.info(f"{BOT_NAME} запускается...")
    logger.info(f"Режим: {'ТЕСТОВЫЙ' if TEST_MODE else 'РАБОЧИЙ'}")
    logger.info(f"Версия: 2.0 (без .env файла)")
    logger.info(f"Время UTC: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)
    
    # Запускаем фоновый планировщик
    asyncio.create_task(background_scheduler())
    
    # Приветственное сообщение
    if not TEST_MODE:
        try:
            await bot.send_message(
                GROUP_ID,
                f"📜 *{BOT_NAME} активирован!* 📜\n\n"
                f"Завтра в 9:00 ждите первый иронично-исторический пост!\n\n"
                f"#запуск #история #бот",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить приветствие: {e}")

async def on_shutdown(_):
    """Действия при остановке"""
    logger.info("Останавливаем бота...")
    await bot.close()

# ============================================================================
# ТОЧКА ВХОДА ДЛЯ BOTHOST
# ============================================================================

if __name__ == '__main__':
    logger.info("Запуск бота...")
    
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
        print(f"\n❌ Критическая ошибка: {e}")
        print("Проверьте переменные окружения в BotHost!")

import re
import asyncio
import sys
import aiohttp
from datetime import datetime
from collections import Counter
from typing import Optional, Dict
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

BOT_TOKEN = "ыаыа"
SERVER_URL = "http://localhost:8000"
INTERNAL_TOKEN = "geiT9nAGihufIwAQaW3A6zw70Hx51F16mX8wMgxdQIY"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher(storage=MemoryStorage())
username_to_id: Dict[str, int] = {}

# Глобальное хранилище активных сборов времени
active_collections: Dict[int, dict] = {}

class EventCreation(StatesGroup):
    waiting_for_title = State()
    waiting_for_participants = State()
    waiting_for_participant_times = State()
    waiting_for_confirmation = State()

class ServerAPI:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip('/')
        self.headers = {'X-Internal-Token': token, 'Content-Type': 'application/json'}
    
    async def request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=self.headers, **kwargs) as resp:
                    if resp.status == 204:
                        return {'success': True}
                    data = await resp.json() if resp.status != 204 else {}
                    if resp.status in [200, 201]:
                        return data
                    return {'error': True, 'status': resp.status, 'detail': data}
        except Exception as e:
            return {'error': True, 'detail': str(e)}
    
    async def upsert_user(self, tg_id: int, username: str, first_name: str = "", last_name: str = ""):
        return await self.request('POST', '/api/v1/tg-users/upsert/', json={
            'tg_id': tg_id, 'username': username,
            'first_name': first_name, 'last_name': last_name
        })
    
    async def create_event(self, organizer_tg_id: int, title: str):
        return await self.request('POST', '/api/v1/events/', json={
            'organizer_tg_id': organizer_tg_id,
            'title': title,
            'timezone': 'Europe/Moscow'
        })
    
    async def get_event(self, event_id: str):
        return await self.request('GET', f'/api/v1/events/{event_id}/')
    
    async def get_events(self, organizer_tg_id: int = None):
        params = {'organizer_tg_id': organizer_tg_id} if organizer_tg_id else {}
        return await self.request('GET', '/api/v1/events/', params=params)
    
    async def open_event(self, event_id: str, organizer_tg_id: int):
        return await self.request('POST', f'/api/v1/events/{event_id}/open/', json={
            'organizer_tg_id': organizer_tg_id
        })
    
    async def add_option(self, event_id: str, start_utc: str, end_utc: str, organizer_tg_id: int):
        return await self.request('POST', f'/api/v1/events/{event_id}/options/add/', json={
            'start_at_utc': start_utc,
            'end_at_utc': end_utc,
            'organizer_tg_id': organizer_tg_id
        })
    
    async def finalize_event(self, event_id: str, organizer_tg_id: int, option_id: int = None):
        data = {'organizer_tg_id': organizer_tg_id}
        if option_id:
            data['option_id'] = option_id
        return await self.request('POST', f'/api/v1/events/{event_id}/finalize/', json=data)
    
    async def cancel_event(self, event_id: str, organizer_tg_id: int):
        return await self.request('POST', f'/api/v1/events/{event_id}/cancel/', json={
            'organizer_tg_id': organizer_tg_id
        })
    
    async def add_participant(self, event_id: str, tg_id: int, organizer_tg_id: int):
        return await self.request('POST', f'/api/v1/events/{event_id}/participants/add/', json={
            'tg_id': tg_id,
            'organizer_tg_id': organizer_tg_id
        })
    
    async def get_votes(self, event_id: str):
        return await self.request('GET', f'/api/v1/events/{event_id}/votes/')

api = ServerAPI(SERVER_URL, INTERNAL_TOKEN)

def parse_date(date_str: str) -> Optional[datetime]:
    match = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})$', date_str)
    if match:
        day, month, year, hour, minute = map(int, match.groups())
        try:
            return datetime(year, month, day, hour, minute)
        except ValueError:
            return None
    match = re.match(r'^(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})$', date_str)
    if match:
        day, month, hour, minute = map(int, match.groups())
        try:
            return datetime(datetime.now().year, month, day, hour, minute)
        except ValueError:
            return None
    return None

def format_datetime(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")

def datetime_to_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

# ============ КОМАНДЫ ============

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    username = f"@{user.username}" if user.username else "без username"
    
    if user.username:
        username_to_id[username] = user.id
    
    await api.upsert_user(user.id, username, user.first_name or "", user.last_name or "")
    
    welcome = (
        f"👋 *Добро пожаловать, {user.first_name or 'пользователь'}!*\n\n"
        f"Я бот для группового планирования встреч.\n"
        f"Помогу согласовать удобное время с участниками.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Ваш профиль:*\n"
        f"├ ID: `{user.id}`\n"
        f"└ Username: {username}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 *Основные команды:*\n\n"
        f"*/create* — создать новую встречу\n"
        f"├ Укажите название\n"
        f"├ Добавьте участников (@username)\n"
        f"└ Участники предложат время\n\n"
        f"*/events* — список ваших встреч\n"
        f"└ Детали: /event <id>\n\n"
        f"*/help* — подробная справка\n"
        f"*/cancel* — отменить действие\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 *Пример:* /create\n"
        f"💡 *Справка:* /help"
    )
    await message.answer(welcome)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        f"📚 *Справка по использованию*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🕒 *Формат времени:*\n"
        f"├ `15.04.2025 15:00` — полный формат\n"
        f"├ `15.04 15:00` — без года (текущий)\n"
        f"└ `25.12 10:00` — день.месяц часы:минуты\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 *Создание встречи:*\n"
        f"1️⃣ /create — начать\n"
        f"2️⃣ Введите название\n"
        f"3️⃣ Укажите участников: @user1 @user2\n"
        f"4️⃣ Каждый участник пишет своё время\n"
        f"5️⃣ Бот выберет лучшее время\n"
        f"6️⃣ Подтвердите создание\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 *Команды:*\n"
        f"├ /start — главное меню\n"
        f"├ /create — создать встречу\n"
        f"├ /events — список встреч\n"
        f"├ /event <id> — детали встречи\n"
        f"├ /help — эта справка\n"
        f"└ /cancel — отмена действия\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Статусы встреч:*\n"
        f"├ 📝 DRAFT — черновик\n"
        f"├ 🔓 OPEN — голосование\n"
        f"├ ✅ FINALIZED — завершено\n"
        f"└ ❌ CANCELED — отменено\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 *Совет:* участники должны написать /start боту"
    )
    await message.answer(help_text)

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    if not await state.get_state():
        await message.answer("❌ Нет активных действий для отмены")
        return
    await state.clear()
    if message.chat.id in active_collections:
        del active_collections[message.chat.id]
    await message.answer("✅ Действие отменено")

# ============ СОЗДАНИЕ ВСТРЕЧИ ============

@dp.message(Command("create"))
async def cmd_create(message: types.Message, state: FSMContext):
    await state.set_state(EventCreation.waiting_for_title)
    await message.answer(
        "📝 *Шаг 1/3: Название встречи*\n\n"
        "Введите название встречи.\n"
        "Например: «Встреча команды», «Обсуждение проекта»"
    )

@dp.message(EventCreation.waiting_for_title)
async def step_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(EventCreation.waiting_for_participants)
    await message.answer(
        "👥 *Шаг 2/3: Участники*\n\n"
        "Введите @username участников через пробел.\n\n"
        "*Пример:*\n"
        "`@ivanov @petrov @sidorov`\n\n"
        "Или нажмите /skip если участников нет"
    )

@dp.message(Command("skip"))
@dp.message(EventCreation.waiting_for_participants)
async def step_participants(message: types.Message, state: FSMContext):
    participants = []
    if not message.text.startswith('/skip'):
        participants = re.findall(r'@\w+', message.text)
        if not participants:
            await message.answer(
                "❌ *Неверный формат*\n\n"
                "Введите @username через пробел:\n"
                "`@user1 @user2 @user3`\n\n"
                "Или /skip чтобы пропустить"
            )
            return
    
    creator_username = f"@{message.from_user.username}" if message.from_user.username else ""
    
    await state.update_data(participants=participants, creator_username=creator_username)
    
    if not participants:
        await state.update_data(dates=[])
        data = await state.get_data()
        preview = f"📅 *Подтверждение*\n\n📝 {data['title']}\n👥 Без участников\n\n⚠️ Нет вариантов времени"
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Подтвердить", callback_data="confirm")
        builder.button(text="❌ Отмена", callback_data="cancel")
        await message.answer(preview, reply_markup=builder.as_markup())
        await state.set_state(EventCreation.waiting_for_confirmation)
    else:
        active_collections[message.chat.id] = {
            'remaining': participants.copy(),
            'collected': {},
            'organizer_id': message.from_user.id,
            'organizer_state': state,
            'title': (await state.get_data()).get('title', '')
        }
        
        await state.update_data(collected_times={}, remaining_participants=participants.copy())
        await state.set_state(EventCreation.waiting_for_participant_times)
        
        participants_list = "\n".join([f"  • {p}" for p in participants])
        
        await message.answer(
            f"⏳ *Ожидание ответов от участников*\n\n"
            f"*Участники ({len(participants)}):*\n"
            f"{participants_list}\n\n"
            f"Осталось ответов: *{len(participants)}*\n\n"
            f"✏️ Напишите время в этот чат:\n"
            f"• `15.04.2025 15:00`\n"
            f"• `15.04 15:00`"
        )

# Глобальный обработчик времени от любого пользователя
@dp.message(F.text.regexp(r'^(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}|\d{2}\.\d{2}\s+\d{2}:\d{2})$'))
async def handle_time_from_any_user(message: types.Message, state: FSMContext):
    username = f"@{message.from_user.username}" if message.from_user.username else None
    
    if not username:
        return
    
    username_to_id[username] = message.from_user.id
    
    collection = active_collections.get(message.chat.id)
    
    if not collection:
        return
    
    if username not in collection['remaining']:
        await message.answer(f"❌ {username}, вы не в списке участников")
        return
    
    parsed = parse_date(message.text.strip())
    if not parsed:
        await message.answer(
            f"❌ {username}, неверный формат времени\n"
            f"Используйте: `15.04.2025 15:00` или `15.04 15:00`"
        )
        return
    
    if username in collection['remaining']:
        collection['collected'][username] = parsed
        collection['remaining'].remove(username)
    
    remaining = collection['remaining']
    
    if remaining:
        remaining_list = "\n".join([f"  • {p}" for p in remaining])
        await message.answer(
            f"✅ *{username}* выбрал: {format_datetime(parsed)}\n\n"
            f"⏳ Осталось ответов: *{len(remaining)}*\n\n"
            f"*Ждём:*\n{remaining_list}"
        )
    else:
        dates = list(collection['collected'].values())
        
        org_state = collection['organizer_state']
        await org_state.update_data(dates=dates)
        
        preview = f"🎉 *Все участники ответили!*\n\n"
        preview += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        preview += f"📝 *{collection['title']}*\n"
        preview += f"👥 *Участники:*\n"
        
        for p, t in collection['collected'].items():
            preview += f"  ✅ {p}: {format_datetime(t)}\n"
        
        preview += f"\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        if dates:
            time_strings = [format_datetime(d) for d in dates]
            most_common = Counter(time_strings).most_common(1)[0]
            preview += f"📅 *Предложенное время:* `{most_common[0]}`\n"
            preview += f"👥 Выбрали {most_common[1]} из {len(dates)} участников\n"
        
        preview += f"\n━━━━━━━━━━━━━━━━━━━━━━"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Подтвердить", callback_data="confirm")
        builder.button(text="🔄 Заново", callback_data="restart")
        builder.button(text="❌ Отмена", callback_data="cancel")
        
        await message.answer(preview, reply_markup=builder.as_markup())
        
        del active_collections[message.chat.id]

@dp.callback_query(EventCreation.waiting_for_confirmation, F.data == "confirm")
async def confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    creator_id = callback.from_user.id
    creator_username = f"@{callback.from_user.username}" if callback.from_user.username else ""
    
    await callback.message.edit_text("⏳ *Создаю встречу на сервере...*")
    
    await api.upsert_user(creator_id, creator_username, callback.from_user.first_name or "", "")
    
    result = await api.create_event(creator_id, data['title'])
    
    if result.get('error'):
        await callback.message.edit_text(f"❌ Ошибка: {result.get('detail')}")
        await state.clear()
        return
    
    event_id = result.get('id', '')
    dates = data.get('dates', [])
    
    for date in dates:
        end_time = datetime.fromtimestamp(date.timestamp() + 3600)
        await api.add_option(event_id, datetime_to_utc(date), datetime_to_utc(end_time), creator_id)
    
    for username in data['participants']:
        clean = username.lstrip('@')
        participant_id = username_to_id.get(username) or username_to_id.get(f"@{clean}")
        if participant_id:
            await api.upsert_user(participant_id, username, "", "")
            await api.add_participant(event_id, participant_id, creator_id)
    
    open_result = await api.open_event(event_id, creator_id)
    
    status_text = "✅ Статус: OPEN" if not open_result.get('error') else "⚠️ Статус: DRAFT"
    
    if dates:
        time_strings = [format_datetime(d) for d in dates]
        best_time = Counter(time_strings).most_common(1)[0][0]
    else:
        best_time = "Не указано"
    
    event_info = (
        f"✅ *Встреча успешно создана!*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 *Название:* {data['title']}\n"
        f"🆔 ID: `{event_id}`\n"
        f"{status_text}\n"
        f"👤 Организатор: {creator_username}\n"
        f"👥 Участников: {len(data['participants'])}\n"
        f"🕒 Вариантов времени: {len(dates)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 *Предложенное время:* `{best_time}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 */event {event_id[:8]}* — детали встречи\n"
        f"💡 */events* — список встреч"
    )
    
    await callback.message.edit_text(event_info)
    await state.clear()

@dp.callback_query(EventCreation.waiting_for_confirmation, F.data == "restart")
async def restart(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EventCreation.waiting_for_title)
    await callback.message.edit_text("🔄 Начинаем заново")
    await callback.message.answer(
        "📝 *Шаг 1/3: Название встречи*\n\n"
        "Введите название встречи:"
    )

@dp.callback_query(EventCreation.waiting_for_confirmation, F.data == "cancel")
async def cancel_create(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание встречи отменено")

# ============ ПРОСМОТР ВСТРЕЧ ============

@dp.message(Command("events"))
async def cmd_events(message: types.Message):
    result = await api.get_events(organizer_tg_id=message.from_user.id)
    events_list = result if isinstance(result, list) else result.get('results', [])
    
    if not events_list:
        await message.answer("📋 *У вас пока нет встреч*\n\nСоздайте первую: /create")
        return
    
    text = "📋 *Мои встречи*\n\n"
    
    for i, e in enumerate(events_list[:10], 1):
        status = e.get('status', '?')
        emoji = {'DRAFT': '📝', 'OPEN': '🔓', 'FINALIZED': '✅', 'CANCELED': '❌'}.get(status, '❓')
        event_id = e.get('id', '?')
        
        text += f"*{i}.* {emoji} *{e.get('title', '—')}*\n"
        text += f"   🆔 `{event_id}`\n"
        
        detail = await api.get_event(event_id)
        if not detail.get('error'):
            participants = detail.get('participants', [])
            options = detail.get('options', [])
            text += f"   👤 Орг: `{detail.get('organizer', '?')}`\n"
            text += f"   👥 Участников: {len(participants)}\n"
            if options:
                start = options[0].get('start_at_utc', '')
                try:
                    dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    text += f"   🕒 {format_datetime(dt)}"
                    if len(options) > 1:
                        text += f" (+{len(options)-1})"
                    text += "\n"
                except:
                    pass
            
            if status == 'OPEN':
                votes = await api.get_votes(event_id)
                if not votes.get('error'):
                    total = sum(o.get('votes_count', 0) for o in votes.get('options', []))
                    text += f"   📊 Голосов: {total}\n"
        
        text += f"   📌 {status}\n"
        text += f"   💡 /event {i}\n\n"
    
    text += "💡 */event <номер>* — подробности\n💡 */create* — новая встреча"
    await message.answer(text)

@dp.message(Command("event"))
async def cmd_event(message: types.Message):
    try:
        event_ref = message.text.split()[1]
    except:
        await message.answer("❌ /event <номер> или /event <id>")
        return
    
    result = await api.get_events(organizer_tg_id=message.from_user.id)
    events_list = result if isinstance(result, list) else result.get('results', [])
    
    if not events_list:
        await message.answer("📋 Нет встреч")
        return
    
    event = None
    
    try:
        num = int(event_ref)
        if 1 <= num <= len(events_list):
            event = events_list[num - 1]
    except:
        pass
    
    if not event:
        for e in events_list:
            if e.get('id', '') == event_ref or e.get('id', '').startswith(event_ref):
                event = e
                break
    
    if not event:
        await message.answer(f"❌ Встреча не найдена")
        return
    
    event_id = event.get('id', '')
    detail = await api.get_event(event_id)
    
    if detail.get('error'):
        await message.answer("❌ Ошибка загрузки")
        return
    
    votes_result = await api.get_votes(event_id)
    
    status = detail.get('status', '?')
    emoji = {'DRAFT': '📝', 'OPEN': '🔓', 'FINALIZED': '✅', 'CANCELED': '❌'}.get(status, '❓')
    
    text = f"📅 *Информация о встрече*\n\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"🆔 `{event_id}`\n"
    text += f"📝 *{detail.get('title', '—')}*\n"
    text += f"👤 Организатор: `{detail.get('organizer', '?')}`\n"
    text += f"📊 Статус: {emoji} {status}\n\n"
    
    participants = detail.get('participants', [])
    if participants:
        text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"👥 *Участники ({len(participants)}):*\n"
        for p in participants:
            text += f"  • `{p.get('tg_id', '?')}`\n"
    
    options = detail.get('options', [])
    if options:
        text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += "🕒 *Варианты времени:*\n"
        for i, opt in enumerate(options, 1):
            start = opt.get('start_at_utc', '')
            try:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                text += f"  {i}. `{format_datetime(dt)}`\n"
            except:
                text += f"  {i}. {start}\n"
        
        if options:
            start = options[0].get('start_at_utc', '')
            try:
                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                text += f"\n📅 *Предложенное время:* `{format_datetime(dt)}`\n"
            except:
                pass
    
    if not votes_result.get('error'):
        votes_data = votes_result.get('options', [])
        if votes_data:
            text += f"\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            text += "📊 *Голосование:*\n"
            max_votes = 0
            best_time = None
            for v in votes_data:
                vcount = v.get('votes_count', 0)
                voters_list = v.get('voters', [])
                text += f"  • Вариант {v.get('option_id')}: {vcount} голосов"
                if voters_list:
                    text += f" ({', '.join(map(str, voters_list))})"
                text += "\n"
                
                if vcount > max_votes:
                    max_votes = vcount
                    for o in options:
                        if o.get('id') == v.get('option_id'):
                            start = o.get('start_at_utc', '')
                            try:
                                dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                                best_time = format_datetime(dt)
                            except:
                                best_time = start
            
            if best_time and max_votes > 0:
                text += f"\n🏆 *Лучшее время:* `{best_time}`\n👥 {max_votes} голосов\n"
    
    if status == 'OPEN':
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Завершить", callback_data=f"finalize_{event_id[:8]}")
        await message.answer(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text)

# ============ ФИНАЛИЗАЦИЯ ============

@dp.callback_query(F.data.startswith("finalize_"))
async def finalize_prompt(callback: types.CallbackQuery):
    short_id = callback.data.split("_")[1]
    
    result = await api.get_events(organizer_tg_id=callback.from_user.id)
    events_list = result if isinstance(result, list) else result.get('results', [])
    
    event_id = None
    for e in events_list:
        if e.get('id', '').startswith(short_id):
            event_id = e.get('id')
            break
    
    if not event_id:
        await callback.answer("❌ Встреча не найдена")
        return
    
    event = await api.get_event(event_id)
    options = event.get('options', [])
    
    if not options:
        await callback.answer("❌ Нет вариантов")
        return
    
    text = f"✅ *Финализация встречи*\n\nВыберите итоговое время:\n"
    
    builder = InlineKeyboardBuilder()
    for opt in options:
        start = opt.get('start_at_utc', '')
        try:
            dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            label = format_datetime(dt)
        except:
            label = start
        builder.button(text=label, callback_data=f"confirm_fin_{event_id[:8]}_{opt['id']}")
    
    builder.adjust(1)
    await callback.message.answer(text, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_fin_"))
async def confirm_finalize(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    short_id = parts[2]
    option_id = int(parts[3])
    
    result = await api.get_events(organizer_tg_id=callback.from_user.id)
    events_list = result if isinstance(result, list) else result.get('results', [])
    
    event_id = None
    for e in events_list:
        if e.get('id', '').startswith(short_id):
            event_id = e.get('id')
            break
    
    result = await api.finalize_event(event_id, callback.from_user.id, option_id)
    
    if result.get('error'):
        await callback.message.edit_text(f"❌ Ошибка: {result.get('detail')}")
    else:
        await callback.message.edit_text(f"✅ Встреча завершена!")
    await callback.answer()

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_event_handler(callback: types.CallbackQuery):
    short_id = callback.data.split("_")[1]
    
    result = await api.get_events(organizer_tg_id=callback.from_user.id)
    events_list = result if isinstance(result, list) else result.get('results', [])
    
    event_id = None
    for e in events_list:
        if e.get('id', '').startswith(short_id):
            event_id = e.get('id')
            break
    
    result = await api.cancel_event(event_id, callback.from_user.id)
    
    if result.get('error'):
        await callback.message.edit_text(f"❌ Ошибка: {result.get('detail')}")
    else:
        await callback.message.edit_text(f"❌ Встреча отменена")
    await callback.answer()

@dp.message()
async def other(message: types.Message):
    if message.from_user.username:
        username_to_id[f"@{message.from_user.username}"] = message.from_user.id

async def main():
    print("=" * 60)
    print("🤖 Бот + Django API")
    print(f"📡 {SERVER_URL}")
    print("=" * 60)
    
    test = await api.get_events()
    if test.get('error'):
        print("⚠️ Сервер недоступен")
    else:
        print("✅ Сервер доступен")
    
    me = await bot.get_me()
    print(f"✅ Бот @{me.username} запущен!")
    print("🚀 Готов!\n")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import SessionLocal, due_habits_now, habits, init_db, users
from db import get_or_create_user

load_dotenv()
TOKEN = os.getenv('TOKEN')

bot = Bot(token=TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

scheduler = AsyncIOScheduler()
init_db()


@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    session = SessionLocal()
    default_tz = user.tz
    user_id = message.from_user.id
    user = get_or_create_user(session, message.from_user.id, 'UTC', user_id, default_tz)
    welcome_text = f"""👋 Привет! Я бот для отслеживания привычек.
    
    Что я умею:
    📝 Создавать новые привычки
    ⏰ Напоминать о них в нужное время

    """
    await message.answer(welcome_text)
    
@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    session = SessionLocal()
    help_text = """🆘 Вот список команд, которые я поддерживаю:
    /start - Запустить бота
    /help - Показать это сообщение
    /add - Создать новую привычку
    /list - Показать все привычки
    /delete - Удалить привычку
    """
    await message.answer(help_text)
    await session.commit()


class AddHabit(StatesGroup):
    name = State()
    time = State()

@dp.message_handler(commands=['add'])
async def cmd_add(message: types.Message):
    session = SessionLocal()
    await message.answer("Введите название привычки:")
    await AddHabit.name.set()
    await session.commit()
    await session.close()

@dp.message_handler(state=AddHabit.name)
async def process_name(message: types.Message, state: AddHabit.name):
    session = SessionLocal()
    await state.update_data(name=message.text)
    await message.answer("Введите время напоминания (в формате HH:MM):")
    await state.time.set()
    await session.commit()
    await session.close()

@dp.message_handler(state=AddHabit.time)
async def process_time(message: types.Message, state: AddHabit.time):
    session = SessionLocal()
    await state.update_data(time=message.text)
    data = await state.get_data()
    name = data.get("name")
    time = data.get("time")
    await message.answer(f"Привычка '{name}' добавлена с напоминанием в {time}.")
    await state.finish()
    await session.commit()
    await session.close()
    
@dp.message_handler(commands=['list'])
async def cmd_list(message: types.Message):
    session = SessionLocal()
    user_habits = get_or_create_user(session, message.from_user.id, 'UTC')
    habits = session.query(habits).filter_by(user_id=user_habits.id).all()
    if not habits:
        await message.answer("Привычек пока нет")
    else:
        for habit in habits:
            await message.answer(f"Привычка: {habit.title}, Напоминание: {habit.remind_time}, Активна: {'Да' if habit.is_active else 'Нет'}")
        print(f"Показаны привычки для пользователя {user_habits.tg_id}")
    await session.commit()
    await session.close()

@dp.message_handler(commands=['done'])
async def cmd_done(message: types.Message):
    session = SessionLocal()
    if message.reply_to_message:
        habit_id = message.reply_to_message.text.split()[1]
        habit = session.query(habits).filter_by(id=habit_id).first()
    else:
        await message.answer("Пожалуйста, ответьте на сообщение с привычкой, которую хотите отметить как выполненную.")
        await message.answer("Привычка не найдена.")
        return
    habit.is_done = True
    await session.commit()
    await message.answer("Привычка отмечена как выполненная.")
    await session.commit()
    await session.close()
    
def tz_user(user_id):
    session = SessionLocal()
    user = session.query(users).filter_by(id=user_id).first()
    return user.tz if user else 'UTC'

async def check_habits(bot):
    utc_now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        day_mask = (1 << utc_now.weekday())
        due_habits = due_habits_now(session, utc_now, day_mask)
        for habit in due_habits:
            user = session.query(users).filter_by(id=habit.user_id).first()
            if user:
                reminder_text = f"""⏰ Напоминание для тебя:
                Привычка: {habit.title}
                Время: {habit.remind_time}
                """
                await bot.send_message(chat_id=user.tg_id, text=reminder_text)
        print(f"Напоминания отправлены для {len(due_habits)} привычек.")
scheduler.add_job(check_habits, 'interval', minutes=1, args=[bot])
dp.start_polling(bot)
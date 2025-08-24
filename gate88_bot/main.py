import os
import csv
import json
import logging
import tempfile
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import List, Optional

from dotenv import load_dotenv
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
    InputFile,
    MessageEntity,
    User,
)

from admin import get_admin_kb, get_export_kb
from models import Base, Feedback, PlaceEnum


class AdminStates(StatesGroup):
    waiting_period = State()
    waiting_broadcast = State()
    waiting_export_format = State()
    broadcast = State()
    waiting_add_admin = State()


# Глобальная переменная для контроля частоты тестов
LAST_TEST_TIME = None


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id in ADMIN_IDS


# Настройки
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///feedback.db")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))
                 ) if os.getenv("ADMIN_IDS") else []
NOTIFICATION_CHANNEL_ID = os.getenv("NOTIFICATION_CHANNEL_ID")


logger.info(f"ID канала для уведомлений: {NOTIFICATION_CHANNEL_ID}")
logger.info(f"Токен бота: {'установлен' if BOT_TOKEN else 'отсутствует'}")


# Инициализация БД
engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Состояния опроса


class SurveyStates(StatesGroup):
    choosing_place = State()
    rate_menu = State()
    rate_staff = State()
    rate_clean = State()
    ask_recommend = State()
    ask_review = State()
    ask_photo = State()


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ========== Клавиатуры ==========


def get_main_menu_kb(user_id: int = None):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🍽 Оставить отзыв",
                                  callback_data="leave_feedback")],
            [InlineKeyboardButton(text="⭐ Наши отзывы",
                                  callback_data="our_feedbacks")],
            [InlineKeyboardButton(
                text="🗺️ Показать на карте", callback_data="show_map")],
            [InlineKeyboardButton(text="ℹ️ О заведениях",
                                  callback_data="about_cafes")]
        ]
    )

    if user_id and user_id in ADMIN_IDS:  # Простая проверка без вызова функции
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(
                text="👑 Админка", callback_data="admin_panel")]
        )

    return keyboard


def get_cafe_selection_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🏢 Победа", callback_data="place_Победа")],
            [InlineKeyboardButton(text="✈️ Парк Взлёт",
                                  callback_data="place_Парк Взлёт")],
            [InlineKeyboardButton(
                text="🔙 Назад", callback_data="back_to_main")]
        ]
    )


def get_rating_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=str(i), callback_data=f"rate_{i}") for i in range(1, 6)
        ]]
    )


def get_yesno_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Да", callback_data="recommend_yes"),
            InlineKeyboardButton(text="Нет", callback_data="recommend_no")
        ]]
    )


def get_skip_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Пропустить", callback_data="skip_photo")
        ]]
    )

# ========== Вспомогательные функции ==========


async def calculate_average_ratings(user_id=None):
    async with async_session() as session:
        query = select(Feedback)
        if user_id:
            query = query.where(Feedback.user_id == user_id)

        feedbacks = (await session.execute(query)).scalars().all()

        if not feedbacks:
            return None

        total = len(feedbacks)
        avg_menu = sum(f.menu_rating for f in feedbacks) / total
        avg_staff = sum(f.staff_rating for f in feedbacks) / total
        avg_clean = sum(f.cleanliness_rating for f in feedbacks) / total
        avg_total = (avg_menu + avg_staff + avg_clean) / 3

        return {
            'total': total,
            'avg_menu': round(avg_menu, 2),
            'avg_staff': round(avg_staff, 2),
            'avg_clean': round(avg_clean, 2),
            'avg_total': round(avg_total, 2)
        }


async def save_feedback(data, photo_data=None, photo_skipped=False):
    async with async_session() as session:
        feedback = Feedback(
            user_id=data["user_id"],
            place=data["place"],
            menu_rating=data["menu_rating"],
            staff_rating=data["staff_rating"],
            cleanliness_rating=data["cleanliness_rating"],
            recommend=data["recommend"],
            review_text=data["review_text"],
            photo_data=photo_data,
            photo_skipped=photo_skipped
        )
        session.add(feedback)
        await session.commit()
        # чтобы гарантированно получить сгенерённый ID
        await session.refresh(feedback)
        return feedback


# ========== Обработчики команд ==========

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🍴 Добро пожаловать в \nсистему отзывов Gate 88!",
        reply_markup=get_main_menu_kb(message.from_user.id)
    )


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=get_main_menu_kb(callback.from_user.id)
    )
    await callback.answer()


# ========== Обработчики главного меню ==========

@dp.callback_query(F.data == "leave_feedback")
async def start_feedback(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🏢 Выберите заведение для отзыва:",
        reply_markup=get_cafe_selection_kb()
    )
    await state.set_state(SurveyStates.choosing_place)
    await callback.answer()


@dp.callback_query(F.data == "my_feedbacks")
async def show_my_feedbacks(callback: types.CallbackQuery):
    ratings = await calculate_average_ratings(callback.from_user.id)

    if not ratings:
        text = "📭 У вас пока нет оставленных отзывов"
    else:
        text = (
            "⭐ Ваша статистика:\n\n"
            f"🍽 Средняя оценка меню: {ratings['avg_menu']}/5\n"
            f"👔 Средняя оценка персонала: {ratings['avg_staff']}/5\n"
            f"🧹 Средняя оценка чистоты: {ratings['avg_clean']}/5\n"
            f"🔢 Общий средний балл: {ratings['avg_total']}/5\n\n"
            f"📊 Всего отзывов: {ratings['total']}"
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔙 Назад", callback_data="back_to_main")
            ]]
        )
    )
    await callback.answer()


@dp.callback_query(F.data == "show_map")
async def show_map(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🗺️ Наши заведения на карте:\n\n",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="🏢 Победа", url="https://yandex.com/maps/org/gate_88/221466389401"),
                InlineKeyboardButton(
                    text="✈️ Парк Взлёт", url="https://yandex.com/maps/org/gate_88/93215603368")
            ], [
                InlineKeyboardButton(
                    text="🔙 Назад", callback_data="back_to_main")
            ]]
        ),
        disable_web_page_preview=True
    )
    await callback.answer()


@dp.callback_query(F.data == "about_cafes")
async def show_about_cafes(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ О наших заведениях:\n\n"
        "🏢 Победа:\n"
        "📍 ул. Площадь 30-летия Победы, 2\n"
        "🕒 10:00-22:00\n\n"
        "✈️ Парк Взлёт:\n"
        "📍 Парк Взлёт, городской округ Домодедово\n"
        "🕒 10:00-22:00",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔙 Назад", callback_data="back_to_main")
            ]]
        )
    )
    await callback.answer()


# ========== Обработчики админ-панели ==========

def register_admin_handlers(dp: Dispatcher, session_maker):
    @dp.callback_query(F.data == "admin_panel")
    async def admin_panel(callback: CallbackQuery):
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔ Доступ запрещен")
            return

        await callback.message.edit_text(
            "👑 Админ-панель:",
            reply_markup=get_admin_kb()
        )
        await callback.answer()


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    await callback.message.edit_text(
        "👑 Админ-панель:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="📊 Статистика", callback_data="admin_stats")],
                [InlineKeyboardButton(
                    text="📝 Все отзывы", callback_data="admin_reviews")],
                [InlineKeyboardButton(
                    text="📤 Экспорт данных", callback_data="admin_export")],
                [InlineKeyboardButton(
                    text="📢 Рассылка", callback_data="admin_broadcast")],
                [InlineKeyboardButton(
                    text="➕ Добавить админа", callback_data="admin_add")],
                [InlineKeyboardButton(
                    text="🔙 В меню", callback_data="back_to_main")]
            ]
        )
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👑 Админ-панель:",
        reply_markup=get_admin_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    await callback.message.edit_text(
        "📢 Введите сообщение для рассылки всем пользователям:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена", callback_data="admin_back")]
            ]
        )
    )

    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()


@dp.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    async with async_session() as session:
        user_ids = (await session.execute(
            select(Feedback.user_id).distinct()
        )).scalars().all()

        success = 0
        for user_id in set(user_ids):
            try:
                await message.copy_to(user_id)
                success += 1
            except:
                continue

        await message.answer(
            f"📢 Рассылка завершена!\n"
            f"Отправлено {success} из {len(set(user_ids))} пользователей",
            reply_markup=get_admin_kb()
        )
    await state.clear()


async def export_to_csv(feedbacks: List[Feedback]):
    filename = "feedbacks.csv"
    with open(filename, 'w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['ID', 'User ID', 'Place', 'Menu',
                        'Staff', 'Clean', 'Recommend', 'Review', 'Date'])
        for fb in feedbacks:
            writer.writerow([
                fb.id,
                fb.user_id,
                fb.place.value,
                fb.menu_rating,
                fb.staff_rating,
                fb.cleanliness_rating,
                'Да' if fb.recommend else 'Нет',
                fb.review_text,
                fb.created_at.strftime('%Y-%m-%d %H:%M')
            ])
    return filename


async def export_to_json(feedbacks: List[Feedback]):
    filename = "feedbacks.json"
    data = [{
        'id': fb.id,
        'user_id': fb.user_id,
        'place': fb.place.value,
        'ratings': {
            'menu': fb.menu_rating,
            'staff': fb.staff_rating,
            'clean': fb.cleanliness_rating
        },
        'recommend': fb.recommend,
        'review': fb.review_text,
        'date': fb.created_at.isoformat()
    } for fb in feedbacks]

    with open(filename, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    return filename


def get_period_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="За день", callback_data="period_day")],
            [InlineKeyboardButton(
                text="За неделю", callback_data="period_week")],
            [InlineKeyboardButton(
                text="За месяц", callback_data="period_month")],
            [InlineKeyboardButton(text="За всё время",
                                  callback_data="period_all")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ]
    )


@dp.callback_query(F.data == "admin_export")
async def admin_export(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    await callback.message.edit_text(
        "📤 Выберите формат экспорта:",
        reply_markup=get_export_kb()
    )
    await callback.answer()


def get_export_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="CSV", callback_data="export_csv")],
            [InlineKeyboardButton(text="JSON", callback_data="export_json")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ]
    )


@dp.callback_query(F.data.startswith("export_"))
async def process_export(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    format = callback.data.split("_")[1]

    async with async_session() as session:
        feedbacks = (await session.execute(
            select(Feedback)
            .order_by(Feedback.created_at.desc())
        )).scalars().all()

        if format == "csv":
            filename = await export_to_csv(feedbacks)
        else:
            filename = await export_to_json(feedbacks)

        await callback.message.answer_document(FSInputFile(filename))
        os.remove(filename)

        await callback.message.answer(
            "✅ Данные успешно экспортированы",
            reply_markup=get_admin_kb()
        )
    await callback.answer()


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    async with async_session() as session:
        total = (await session.execute(select(func.count(Feedback.id)))).scalar()
        avg_menu = (await session.execute(select(func.avg(Feedback.menu_rating)))).scalar() or 0
        avg_staff = (await session.execute(select(func.avg(Feedback.staff_rating)))).scalar() or 0
        avg_clean = (await session.execute(select(func.avg(Feedback.cleanliness_rating)))).scalar() or 0

        text = (
            "📊 Общая статистика:\n\n"
            f"• Всего отзывов: {total}\n"
            f"• Средняя оценка меню: {round(avg_menu, 2)}/5\n"
            f"• Средняя оценка персонала: {round(avg_staff, 2)}/5\n"
            f"• Средняя оценка чистоты: {round(avg_clean, 2)}/5"
        )

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🔙 Назад", callback_data="admin_panel")
                ]]
            )
        )
    await callback.answer()


async def get_stats(session: AsyncSession, period: timedelta = None):
    query = select(Feedback)
    if period:
        start_date = datetime.now() - period
        query = query.where(Feedback.created_at >= start_date)

    result = await session.execute(query)
    feedbacks = result.scalars().all()

    if not feedbacks:
        return None

    stats = {
        'total': len(feedbacks),
        'avg_menu': round(sum(f.menu_rating for f in feedbacks) / len(feedbacks), 2),
        'avg_staff': round(sum(f.staff_rating for f in feedbacks) / len(feedbacks), 2),
        'avg_clean': round(sum(f.cleanliness_rating for f in feedbacks) / len(feedbacks), 2),
        'positive': sum(1 for f in feedbacks if f.recommend),
        'with_photo': sum(1 for f in feedbacks if f.photo_data)
    }
    return stats


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    await callback.message.edit_text(
        "📊 Выберите период для статистики:",
        reply_markup=get_period_kb()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("period_"))
async def show_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    period = callback.data.split("_")[1]
    period_map = {
        'day': timedelta(days=1),
        'week': timedelta(weeks=1),
        'month': timedelta(days=30),
        'all': None
    }

    async with async_session() as session:
        stats = await get_stats(session, period_map.get(period))

        if not stats:
            text = "📭 Нет данных за выбранный период"
        else:
            text = (
                f"📊 Статистика {'за ' + period if period != 'all' else 'за всё время'}:\n\n"
                f"• Всего отзывов: {stats['total']}\n"
                f"• Средняя оценка меню: {stats['avg_menu']}/5\n"
                f"• Средняя оценка персонала: {stats['avg_staff']}/5\n"
                f"• Средняя оценка чистоты: {stats['avg_clean']}/5\n"
                f"• Рекомендуют: {stats['positive']} ({round(stats['positive']/stats['total']*100)}%)\n"
                f"• С фото: {stats['with_photo']}"
            )

        await callback.message.edit_text(
            text,
            reply_markup=get_admin_kb()
        )
    await callback.answer()


@dp.callback_query(F.data == "admin_reviews")
async def admin_reviews(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен")
        return

    async with async_session() as session:
        feedbacks = (await session.execute(
            select(Feedback)
            .order_by(Feedback.created_at.desc())
            .limit(10)
        )).scalars().all()

        if not feedbacks:
            text = "📭 Нет отзывов"
        else:
            text = "📝 Последние 10 отзывов:\n\n"
            for fb in feedbacks:
                text += (
                    f"📅 {fb.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"👤 Пользователь: {fb.user_id}\n"
                    f"🏢 {fb.place.value}\n"
                    f"⭐ Оценки: {fb.menu_rating}/{fb.staff_rating}/{fb.cleanliness_rating}\n"
                    f"📝 {fb.review_text[:100]}{'...' if len(fb.review_text) > 100 else ''}\n\n"
                )

        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="🔙 Назад", callback_data="admin_panel")
                ]]
            )
        )
    await callback.answer()


async def can_leave_feedback(user_id: int, place: PlaceEnum) -> int:

    async with async_session() as session:
        query = (
            select(Feedback)
            .where(Feedback.user_id == user_id, Feedback.place == place)
            .order_by(Feedback.created_at.desc())
            .limit(1)
        )

        last = (await session.execute(query)).scalars().first()

    if not last:
        return 0

    elapsed = (datetime.utcnow() - last.created_at).total_seconds()
    remaining = 600 - int(elapsed)
    return remaining if remaining > 0 else 0


# ========== Обработчики процесса отзыва ==========

@dp.callback_query(F.data.startswith("place_"), SurveyStates.choosing_place)
async def process_place(callback: types.CallbackQuery, state: FSMContext):
    try:
        place_value = callback.data[6:]  # "place_Победа" -> "Победа"
        place = PlaceEnum(place_value)

        await state.update_data(
            user_id=callback.from_user.id,
            place=place
        )

        await callback.message.edit_text(
            f"🏢 Заведение: {place.value}\n"
            "🍽️ Оцените меню от 1 до 5:",
            reply_markup=get_rating_kb()
        )
        await state.set_state(SurveyStates.rate_menu)
    except ValueError:
        await callback.answer("Ошибка выбора заведения")
    finally:
        await callback.answer()


@dp.callback_query(F.data.startswith("rate_"), SurveyStates.rate_menu)
async def process_menu_rating(callback: types.CallbackQuery, state: FSMContext):
    try:
        rating = int(callback.data.split("_")[1])
        await state.update_data(menu_rating=rating)

        await callback.message.edit_text(
            f"🍽️ Меню: {rating}/5\n"
            "👔 Оцените персонал от 1 до 5:",
            reply_markup=get_rating_kb()
        )
        await state.set_state(SurveyStates.rate_staff)
    except Exception as e:
        logger.error(f"Error processing menu rating: {e}")
        await callback.answer("Ошибка обработки оценки")
    finally:
        await callback.answer()


@dp.callback_query(F.data.startswith("rate_"), SurveyStates.rate_staff)
async def process_staff_rating(callback: types.CallbackQuery, state: FSMContext):
    try:
        rating = int(callback.data.split("_")[1])
        await state.update_data(staff_rating=rating)

        await callback.message.edit_text(
            f"👔 Персонал: {rating}/5\n"
            "🧹 Оцените чистоту от 1 до 5:",
            reply_markup=get_rating_kb()
        )
        await state.set_state(SurveyStates.rate_clean)
    except Exception as e:
        logger.error(f"Error processing staff rating: {e}")
        await callback.answer("Ошибка обработки оценки")
    finally:
        await callback.answer()


@dp.callback_query(F.data.startswith("rate_"), SurveyStates.rate_clean)
async def process_clean_rating(callback: types.CallbackQuery, state: FSMContext):
    try:
        rating = int(callback.data.split("_")[1])
        await state.update_data(cleanliness_rating=rating)

        await callback.message.edit_text(
            f"🧹 Чистота: {rating}/5\n"
            "Порекомендуете ли вы нас друзьям?",
            reply_markup=get_yesno_kb()
        )
        await state.set_state(SurveyStates.ask_recommend)
    except Exception as e:
        logger.error(f"Error processing cleanliness rating: {e}")
        await callback.answer("Ошибка обработки оценки")
    finally:
        await callback.answer()


@dp.callback_query(F.data.startswith("recommend_"), SurveyStates.ask_recommend)
async def process_recommend(callback: types.CallbackQuery, state: FSMContext):
    try:
        recommend = callback.data.split("_")[1] == "yes"
        await state.update_data(recommend=recommend)

        await callback.message.edit_text(
            f"👍 Рекомендация: {'Да' if recommend else 'Нет'}\n"
            "📝 Напишите отзыв (или 'нет' если не хотите):"
        )
        await state.set_state(SurveyStates.ask_review)
    except Exception as e:
        logger.error(f"Error processing recommendation: {e}")
        await callback.answer("Ошибка обработки рекомендации")
    finally:
        await callback.answer()


@dp.message(SurveyStates.ask_review)
async def process_review(message: Message, state: FSMContext):
    try:
        review_text = "нет" if message.text.lower() == "нет" else message.text
        await state.update_data(review_text=review_text)

        await message.answer(
            "📸 Прикрепите фото блюда или интерьера (или пропустите):",
            reply_markup=get_skip_kb()
        )
        await state.set_state(SurveyStates.ask_photo)
    except Exception as e:
        logger.error(f"Error processing review: {e}")
        await message.answer("Ошибка обработки отзыва")


@dp.callback_query(F.data == "skip_photo", SurveyStates.ask_photo)
async def skip_photo(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    retry = await can_leave_feedback(data["user_id"], data["place"])
    if retry:
        await callback.answer(
            f"🚫 Спам! Следующий отзыв по этому заведению можно оставить через {retry//60} мин и {retry % 60} сек",
            show_alert=True
        )
        return
    if not is_admin(data["user_id"]):
        retry = await can_leave_feedback(data["user_id"], data["place"])
        if retry:
            await callback.answer(
                f"🚫 Спам! Следующий отзыв по этому заведению можно оставить "
                f"через {retry//60} мин {retry % 60} сек",
                show_alert=True
            )
            return
    try:
        feedback = await save_feedback(
            data=data,
            photo_data=None,
            photo_skipped=True
        )
        logger.info(f"Создан объект Feedback: {feedback.__dict__}")
        logger.info(f"Тип feedback: {type(feedback)}")
        logger.info(f"Атрибуты: {dir(feedback)}")
        logger.info(f"Значения: {feedback.__dict__}")
    except Exception as e:
        logger.error(f"Ошибка создания Feedback: {e}")
        raise
    await send_feedback_notification(feedback)

    await callback.message.edit_text(
        "✅ Спасибо за отзыв!",
        reply_markup=get_main_menu_kb(callback.from_user.id)
    )
    await state.clear()


@dp.message(SurveyStates.ask_photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    # Сразу достаём данные состояния
    data = await state.get_data()

    # Спам-проверка (админы без ограничений)
    if not is_admin(data["user_id"]):
        retry = await can_leave_feedback(data["user_id"], data["place"])
        if retry:
            await message.answer(
                f"🚫 Спам! Следующий отзыв по этому заведению можно оставить "
                f"через {retry//60} мин {retry % 60} сек"
            )
            return

    try:
        logger.info("== Начало обработки фото-отзыва ==")

        # 1. Получаем фото
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        photo_data = await bot.download_file(file.file_path)
        photo_bytes = photo_data.getvalue() if photo_data else None

        # 2. Теперь data уже есть
        logger.info(f"Данные состояния: {data}")

        # 3. Сохраняем отзыв
        feedback = await save_feedback(data=data, photo_data=photo_bytes)
        logger.info(f"Объект Feedback создан: ID {feedback.id}")

        # 4. Отправляем уведомление
        if NOTIFICATION_CHANNEL_ID:
            logger.info(f"Отправка в канал {NOTIFICATION_CHANNEL_ID}")
            try:
                success = await send_feedback_notification(feedback)
                logger.info(
                    f"Уведомление {'отправлено' if success else 'не отправлено'}")
            except Exception as e:
                logger.error(f"Ошибка уведомления: {e}")

        # 5. Подтверждение пользователю
        await message.answer(
            "✅ Ваш отзыв сохранён!",
            reply_markup=get_main_menu_kb(message.from_user.id)
        )

        # 6. Очистка состояния
        await state.clear()
        logger.info("== Обработка завершена успешно ==")

    except Exception as e:
        logger.error(f"!!! ОШИБКА: {e}", exc_info=True)
        await message.answer(
            "⚠️ Произошла ошибка. Попробуйте ещё раз.",
            reply_markup=get_skip_kb()
        )


async def send_feedback_notification(feedback: Feedback):
    if not NOTIFICATION_CHANNEL_ID:
        return False

    try:
        user_chat = await bot.get_chat(feedback.user_id)
        if user_chat.username:
            username_disp = f"@{user_chat.username}"
        else:
            username_disp = user_chat.first_name
    except Exception:
        username_disp = str(feedback.user_id)

    # Проверяем, не тестовый ли это отзыв
    if feedback.id == 999:  # Наш тестовый ID
        logger.info("Отправка ТЕСТОВОГО уведомления")
    else:
        logger.info(f"Отправка реального отзыва ID: {feedback.id}")

    if not NOTIFICATION_CHANNEL_ID:
        logger.warning("❗ ID канала не указан в настройках")
        return False

    # Проверяем доступность канала
    try:
        chat = await bot.get_chat(NOTIFICATION_CHANNEL_ID)
        logger.info(f"Канал найден: {chat.title}")
    except Exception as e:
        logger.error(f"❌ Ошибка доступа к каналу: {str(e)}")
        return False

    moscow_tz = timezone(timedelta(hours=3), name="MSC")
    utc_dt = feedback.created_at.replace(tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(moscow_tz)

    date_line = f"📅 Дата отзыва: {local_dt.strftime('%d.%m.%Y %H:%M')} ({moscow_tz.tzname(None)})"

    user_line = f"👤 Пользователь: {username_disp} / {feedback.user_id}"
    place_line = f"🏢 Заведение: {feedback.place.value}"
    ratings_line = f"⭐️ Оценки: Меню: {feedback.menu_rating}/5, Персонал: {feedback.staff_rating}/5, Чистота: {feedback.cleanliness_rating}/5"
    review_line = f"📝 Отзыв: {feedback.review_text[:100]}"
    photo_line = f"📸 Фото: {'Есть' if feedback.photo_data else 'Нет'}"

    text = "\n".join([
        "📢 Новый отзыв!",
        "",
        date_line,
        "",
        user_line,
        place_line,
        ratings_line,
        review_line,
        photo_line
    ])

    if feedback.photo_data:
        import tempfile
        import os
        from aiogram.types import FSInputFile

        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        try:
            tmp.write(feedback.photo_data)
            tmp.flush()
            tmp.close()

            if os.path.getsize(tmp.name) == 0:
                logger.error("❌ Временный файл пустой!")
                return False

            result = await bot.send_photo(
                chat_id=int(NOTIFICATION_CHANNEL_ID),
                photo=FSInputFile(tmp.name),
                caption=text,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"✅ Фото отправлено, message_id: {result.message_id}")
            return True
        finally:
            os.unlink(tmp.name)

    else:
        await bot.send_message(
            chat_id=int(NOTIFICATION_CHANNEL_ID),
            text=text,
            parse_mode=ParseMode.HTML
        )

    return True


async def calculate_stats_per_place():
    async with async_session() as session:
        q = (
            select(
                Feedback.place,
                func.count(Feedback.id),
                func.avg(Feedback.menu_rating),
                func.avg(Feedback.staff_rating),
                func.avg(Feedback.cleanliness_rating),
            )
            .group_by(Feedback.place)
        )
        result = await session.execute(q)
        records = result.all()  # records — список кортежей

    stats = {}
    total = 0
    for place_enum, cnt, avg_menu, avg_staff, avg_clean in records:
        place_name = place_enum.value
        cnt = cnt or 0
        avg_menu = round(avg_menu or 0, 2)
        avg_staff = round(avg_staff or 0, 2)
        avg_clean = round(avg_clean or 0, 2)
        avg_total = round((avg_menu + avg_staff + avg_clean) / 3, 2)

        stats[place_name] = {
            "count":     cnt,
            "avg_menu":  avg_menu,
            "avg_staff": avg_staff,
            "avg_clean": avg_clean,
            "avg_total": avg_total,
        }
        total += cnt

    # Добавим отсутствующие места
    for place in PlaceEnum:
        if place.value not in stats:
            stats[place.value] = {
                "count":     0,
                "avg_menu":  0.0,
                "avg_staff": 0.0,
                "avg_clean": 0.0,
                "avg_total": 0.0,
            }

    return stats, total


@dp.callback_query(F.data == "our_feedbacks")
async def show_our_feedbacks(callback: CallbackQuery):
    stats, total = await calculate_stats_per_place()

    if not stats:
        text = "📭 Отзывов пока нет"
    else:
        lines = ["⭐ Наша статистика:"]
        # Чтобы порядок был фиксирован (как в enum), пробегаемся по PlaceEnum
        for place in PlaceEnum:
            name = place.value
            s = stats[name]
            lines.append("")
            lines.append(f"<b>{name}:</b>")
            lines.append("")
            lines.append(f"🍽<i>Средняя оценка меню: {s['avg_menu']}/5</i>")
            lines.append(
                f"👔<i>Средняя оценка персонала: {s['avg_staff']}/5</i>")
            lines.append(
                f"🧹 <i>Средняя оценка чистоты: {s['avg_clean']}/5</i>")
            lines.append(f"🔢<i>Общий средний балл: {s['avg_total']}/5</i>")

        lines.append("")
        lines.append(f"📊<b>Всего отзывов: {total}</b>")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text=text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(
                text="🔙 Назад", callback_data="back_to_main")]]
        )
    )
    await callback.answer()


TEST_COUNTER = 0


@dp.message(Command("test_notify"))
async def test_notification(message: Message, state: FSMContext):
    global TEST_COUNTER
    if TEST_COUNTER >= 3:
        await message.answer("🚫 Лимит тестов исчерпан")
        return
    TEST_COUNTER += 1
    # Разрешаем только админам
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для администраторов")
        return
    """Безопасная тестовая команда с защитой от спама"""
    global LAST_TEST_TIME

    try:
        # Защита от спама (не чаще 1 раза в 2 минуты)
        if LAST_TEST_TIME and (datetime.now() - LAST_TEST_TIME).total_seconds() < 120:
            await message.answer("🛑 Тестировать можно не чаще чем раз в 2 минуты")
            return

        LAST_TEST_TIME = datetime.now()

        # Создаем ТОЛЬКО ОДНО тестовое уведомление
        test_feedback = Feedback(
            id=999,
            user_id=message.from_user.id,  # Используем реальный ID
            place=PlaceEnum.POBEDA,
            menu_rating=5,
            staff_rating=4,
            cleanliness_rating=5,
            recommend=True,
            review_text=f"Тестовый отзыв от {datetime.now().strftime('%H:%M')}",
            photo_data=None,
            photo_skipped=True,
            created_at=datetime.now()
        )

        # Отправляем только одно уведомление
        success = await send_feedback_notification(test_feedback)

        # Очищаем состояние, если было активно
        current_state = await dp.storage.get_state(user=message.from_user.id)
        if current_state:
            await dp.storage.delete_data(chat=message.chat.id, user=message.from_user.id)

        await message.answer(
            f"Тестовое уведомление {'отправлено' if success else 'не отправлено'}\n"
            f"Канал: {NOTIFICATION_CHANNEL_ID or 'не указан'}"
        )

    except Exception as e:
        await message.answer(f"Ошибка теста: {str(e)}")
        logger.error(f"Тестовая ошибка: {str(e)}", exc_info=True)


@dp.message(Command("show_config"))
async def show_config(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Только для администраторов")
        return

    config = f"""
    Текущие настройки:
    BOT_TOKEN: {'установлен' if BOT_TOKEN else 'отсутствует'}
    CHANNEL_ID: {NOTIFICATION_CHANNEL_ID or 'не указан'}
    """
    await message.answer(config)


async def alternative_send():
    try:
        await bot.send_message(
            chat_id=int(NOTIFICATION_CHANNEL_ID),
            text="Тестовое сообщение другим методом"
        )
        return True
    except Exception as e:
        logger.error(f"Альтернативная отправка: {str(e)}")
        return False


# ========== Запуск бота ==========

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

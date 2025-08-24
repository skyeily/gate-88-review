import os
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, LargeBinary
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
import enum
import datetime
from typing import Dict, Any, Optional
from aiogram import Bot  # Добавьте этот импорт
import logging
from aiogram import types


# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base = declarative_base()

# Получаем ID администраторов из переменных окружения
ADMIN_IDS = [int(id_) for id_ in os.getenv("ADMIN_IDS", "").split(",") if id_]
NOTIFICATION_CHANNEL_ID = os.getenv("NOTIFICATION_CHANNEL_ID")


class PlaceEnum(str, enum.Enum):
    """Перечисление для местоположений"""
    POBEDA = "Победа"
    PARK_VZLYOT = "Парк Взлёт"


class Feedback(Base):
    """Модель для хранения отзывов"""
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    place = Column(Enum(PlaceEnum), nullable=False)
    menu_rating = Column(Integer, nullable=False)
    staff_rating = Column(Integer, nullable=False)
    cleanliness_rating = Column(Integer, nullable=False)
    recommend = Column(Boolean, nullable=False)
    review_text = Column(Text, nullable=False)
    photo_data = Column(LargeBinary, nullable=True)
    photo_skipped = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует отзыв в словарь"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "place": self.place.value,
            "menu_rating": self.menu_rating,
            "staff_rating": self.staff_rating,
            "cleanliness_rating": self.cleanliness_rating,
            "recommend": self.recommend,
            "review_text": self.review_text,
            "has_photo": bool(self.photo_data),
            "created_at": self.created_at.isoformat(),
            "photo_skipped": self.photo_skipped
        }


async def init_db():
    """Инициализирует таблицы в базе данных"""
    engine = create_async_engine("sqlite+aiosqlite:///feedback.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Возвращает асинхронную сессию для работы с БД"""
    engine = create_async_engine("sqlite+aiosqlite:///feedback.db")
    async_session = sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    return async_session()


async def save_feedback(data: dict, photo_data: bytes = None) -> Feedback:
    """Сохраняет отзыв в БД и возвращает объект Feedback"""
    async with await get_session() as session:
        try:
            # Создаем объект отзыва
            feedback = Feedback(
                user_id=data["user_id"],
                place=data["place"],
                menu_rating=data["menu_rating"],
                staff_rating=data["staff_rating"],
                cleanliness_rating=data["cleanliness_rating"],
                recommend=data["recommend"],
                review_text=data["review_text"],
                photo_data=photo_data,
                photo_skipped=photo_data is None
            )

            # Добавляем и сохраняем
            session.add(feedback)
            await session.commit()

            # Обязательно обновляем объект, чтобы получить ID
            await session.refresh(feedback)

            logger.info(f"Отзыв сохранен, ID: {feedback.id}")
            return feedback

        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка сохранения отзыва: {str(e)}", exc_info=True)
            raise  # Пробрасываем исключение дальше


async def send_notification(feedback: Feedback, bot: Bot):
    """Отправляет уведомление в канал"""
    try:
        text = (
            "📢 Новый отзыв!\n\n"
            f"👤 Пользователь: {feedback.user_id}\n"
            f"🏢 Заведение: {feedback.place.value}\n"
            f"⭐ Оценки: Меню {feedback.menu_rating}/5, Персонал {feedback.staff_rating}/5, Чистота {feedback.cleanliness_rating}/5\n"
            f"👍 Рекомендует: {'Да' if feedback.recommend else 'Нет'}\n"
            f"📝 Отзыв: {feedback.review_text}\n"
            f"📸 Фото: {'Есть' if feedback.photo_data else 'Нет'}"
        )

        if feedback.photo_data:
            with open("temp_photo.jpg", "wb") as f:
                f.write(feedback.photo_data)

            await bot.send_photo(
                chat_id=int(NOTIFICATION_CHANNEL_ID),
                photo=types.FSInputFile("temp_photo.jpg"),
                caption=text
            )
            os.remove("temp_photo.jpg")
        else:
            await bot.send_message(
                chat_id=int(NOTIFICATION_CHANNEL_ID),
                text=text
            )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return user_id in ADMIN_IDS

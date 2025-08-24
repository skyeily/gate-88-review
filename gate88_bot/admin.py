from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    Message
)
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta
from models import Feedback, is_admin
import csv
import json
import os
from typing import List, Optional


class AdminStates(StatesGroup):
    waiting_period = State()
    waiting_broadcast = State()
    waiting_export_format = State()


def get_admin_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика",
                                  callback_data="admin_stats")],
            [InlineKeyboardButton(text="📝 Все отзывы",
                                  callback_data="admin_reviews")],
            [InlineKeyboardButton(text="📤 Экспорт данных",
                                  callback_data="admin_export")],
            [InlineKeyboardButton(
                text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(
                text="🔙 В меню", callback_data="back_to_main")]
        ]
    )


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


def get_export_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="CSV", callback_data="export_csv")],
            [InlineKeyboardButton(text="JSON", callback_data="export_json")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ]
    )

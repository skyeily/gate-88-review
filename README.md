# 🍽️ Gate88 Feedback Analysis Bot

**Telegram-бот для сбора и автоматического анализа отзывов посетителей сети кафе Gate 88 на Python.**

Этот проект был разработан в качестве выпускной квалификационной работы. Он представляет собой комплексную систему, которая не только собирает обратную связь через удобный интерфейс в Telegram, но и автоматически анализирует текстовые отзывы с помощью ML, предоставляя бизнесу готовые аналитические выводы и прогнозы.

---

## ✨ Возможности

- **📊 Интерактивный сбор отзывов:** Удобный диалог в Telegram с использованием inline-кнопок для оценки по критериям (меню, персонал, чистота), рекомендации и сбора комментариев.
- **🖼️ Поддержка медиа:** Пользователи могут прикреплять фотографии к своим отзывам.
- **💾 Надежное хранение:** Все данные структурированно сохраняются в реляционной базе данных (SQLite).
- **🔔 Мгновенные уведомления:** Администраторы получают уведомления о новых отзывах в приватный Telegram-канал.
- **🤖 Автоматический NLP-анализ:**
  - Очистка и лемматизация текста (с использованием `spaCy`)
  - Определение тональности (Sentiment Analysis) с помощью модели `LogisticRegression`
  - Тематическое моделирование (LDA) для выявления ключевых тем
- **📈 Прогнозирование:** Построение прогнозов динамики мнений на основе временных рядов с использованием `Facebook Prophet`.
- **📤 Экспорт данных:** Администраторы могут экспортировать все отзывы в формате CSV.

---

## 🛠️ Технологический стек

**Backend:**
![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Aiogram](https://img.shields.io/badge/Aiogram-3.x-green?logo=telegram)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-red)
![SQLite](https://img.shields.io/badge/SQLite-Database-lightgrey?logo=sqlite)

**Data & ML:**
![Scikit-learn](https://img.shields.io/badge/scikit--learn-ML%20Model-orange)
![SpaCy](https://img.shields.io/badge/spaCy-NLP-yellow)
![Pandas](https://img.shields.io/badge/Pandas-Data%20Analysis-darkblue)
![Prophet](https://img.shields.io/badge/Facebook%20Prophet-Forecasting-blue)

---

## 📁 Структура

gate88_bot/  
├── admin.py  
├── gate88.db  
├── main.py  
├── models.py  
├── nlp_pipeline.py  
└── requirements.txt  

---

## 👨‍💻 Автор

Андриевский Г.Д.

Telegram: @skyvins

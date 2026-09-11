from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional
from database.models import Post, RSSSource
from config.settings import AI_MODELS



class Keyboards:
    @staticmethod
    def main_admin_menu():
        keyboard = [
            [InlineKeyboardButton(text="📊 Мои каналы", callback_data="my_channels")],
            [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def channel_menu(channel_id: int):
        keyboard = [
            [InlineKeyboardButton(text="📝 Очередь постов", callback_data=f"queue_{channel_id}")],
            [InlineKeyboardButton(text="📰 RSS источники", callback_data=f"rss_{channel_id}")],
            [InlineKeyboardButton(text="🤖 Настройки AI", callback_data=f"ai_{channel_id}")],
            [InlineKeyboardButton(text="⏰ Расписание", callback_data=f"schedule_{channel_id}")],
            [InlineKeyboardButton(text="✍️ Создать пост", callback_data=f"create_{channel_id}")],
            [InlineKeyboardButton(text="⏸️ Пауза/Старт", callback_data=f"toggle_{channel_id}")],
            [InlineKeyboardButton(text="🗑️ Удалить канал", callback_data=f"delete_{channel_id}")],
            [InlineKeyboardButton(text="◀️ Назад к каналам", callback_data="my_channels")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def rss_sources_menu(channel_id: int, sources: List[RSSSource]):
        keyboard = []
        for source in sources:
            status = "✅" if source.is_active else "❌"
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status} {source.name[:30]}",
                    callback_data=f"source_{source.id}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="➕ Добавить RSS", callback_data=f"add_rss_{channel_id}"),
        ])
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel_{channel_id}")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def schedule_menu(channel_id: int, current_interval: int):
        intervals = {
            "30 минут": 1800,
            "1 час": 3600,
            "2 часа": 7200,
            "4 часа": 14400,
            "8 часов": 28800,
            "24 часа": 86400,
        }
        keyboard = []
        row = []
        for text, seconds in intervals.items():
            prefix = "✅ " if seconds == current_interval else ""
            row.append(InlineKeyboardButton(
                text=prefix + text,
                callback_data=f"set_interval_{channel_id}_{seconds}"
            ))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel_{channel_id}")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def post_queue_menu(channel_id: int, posts: List[Post]):
        keyboard = []
        for post in posts[:10]:
            time_str = post.scheduled_time.strftime("%d.%m %H:%M")
            keyboard.append([
                InlineKeyboardButton(
                    text=f"📝 {time_str} - {post.original_title[:25]}",
                    callback_data=f"post_{post.id}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🚀 Опубликовать первый", callback_data=f"publish_now_{channel_id}"),
            InlineKeyboardButton(text="🗑️ Очистить очередь", callback_data=f"clear_queue_{channel_id}")
        ])
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel_{channel_id}")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def moderation_menu(post_id: int):
        keyboard = [
            [
                InlineKeyboardButton(text="✅ Опубликовать", callback_data=f"approve_{post_id}"),
                InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_{post_id}")
            ],
            [
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{post_id}"),
                InlineKeyboardButton(text="⏭️ Пропустить", callback_data=f"skip_{post_id}")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def ai_settings_menu(channel_id: int, moderation_on: bool):
        moderation_text = "Выключить модерацию 🟢" if moderation_on else "Включить модерацию 🔴"
        keyboard = [
            [InlineKeyboardButton(text="🤖 Изменить модель AI", callback_data=f"ai_model_{channel_id}")],
            [InlineKeyboardButton(text="📝 Изменить промпт", callback_data=f"ai_prompt_{channel_id}")],
            [InlineKeyboardButton(text=moderation_text, callback_data=f"moderation_{channel_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel_{channel_id}")]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def ai_models_menu(channel_id: int, current_model: str):
        keyboard = []
        for model in AI_MODELS:
            text = f"✅ {model}" if model == current_model else model
            keyboard.append([
                InlineKeyboardButton(text=text, callback_data=f"set_model_{channel_id}_{model}")
            ])

        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"ai_{channel_id}")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def confirm_delete(channel_id: int):
        keyboard = [
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{channel_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"channel_{channel_id}")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

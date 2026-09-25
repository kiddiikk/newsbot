from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards import Keyboards
from database.crud import *
from database import crud
from database.models import SessionLocal, Channel, RSSSource, Post, TeamMember, User
from core.publisher import Publisher
from core.ai_processor import AIProcessor
from config.settings import ADMIN_IDS
from datetime import datetime, timedelta
from utils.helpers import generate_post_hash
from aiogram.types import LabeledPrice, PreCheckoutQuery
from sqlalchemy import text
from uuid import uuid4
import random
import logging

logger = logging.getLogger(__name__)

router = Router()
keyboards = Keyboards()


class ChannelStates(StatesGroup):
    waiting_channel_id = State()
    waiting_channel_topic = State()
    waiting_rss_url = State()
    waiting_rss_search = State()
    waiting_post_content = State()
    waiting_ai_prompt = State()
    editing_post = State()
    waiting_manual_rss = State()


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext, command: CommandObject = None):
    await state.clear()
    db = SessionLocal()
    user = get_or_create_user(db, message.from_user.id, message.from_user.username)

    if message.from_user.id in ADMIN_IDS and not user.is_admin:
        user.is_admin = True
        db.commit()

    # 👇 ПРОВЕРКА ИНВАЙТ-ТОКЕНА
    args = command.args if command else None
    if args and args.startswith("team_"):
        token = args[5:]  # "team_abc123" → "abc123"

        # Ищем приглашение
        invite = db.query(TeamMember).filter(
            TeamMember.invite_token == token,
            TeamMember.is_active == True,
        ).first()

        if not invite:
            await message.answer("❌ Приглашение не найдено или устарело.")
            db.close()
            return

        if invite.member_id is not None:
            await message.answer("❌ Приглашение уже использовано.")
            db.close()
            return

        if invite.owner_id == message.from_user.id:
            await message.answer("❌ Это ваше собственное приглашение.")
            db.close()
            return

        # Принимаем инвайт
        accepted = accept_invite(db, token, message.from_user.id)
        if not accepted:
            await message.answer("❌ Не удалось принять приглашение. Попробуйте позже.")
            db.close()
            return

        # Узнаём владельца
        owner = db.query(User).filter(User.telegram_id == invite.owner_id).first()
        owner_username = f"@{owner.username}" if owner and owner.username else f"id{invite.owner_id}"

        await message.answer(
            f"✅ <b>Ты в команде {owner_username}!</b>\n\n"
            f"Твоя роль: <b>Редактор</b>\n\n"
            f"Тебе доступны каналы владельца. Управление правами — у владельца.\n\n"
            f"Нажми /start чтобы открыть меню.",
            parse_mode="HTML"
        )
        db.close()
        return

    db.close()

    is_admin = message.from_user.id in ADMIN_IDS

        # 👇 Проверяем, Бизнес-тариф ли у юзера
    db2 = SessionLocal()
    user2 = get_or_create_user(db2, message.from_user.id)
    plan = user2.subscription_plan or "start"
    is_team_owner = (plan == "business")
    db2.close()

    welcome_text = (
        "👋 <b>Привет! Я бот команды — FEEL IT - AI LAB</b>\n\n"
        "🤖 Я — твой личный контент-менеджер на автопилоте. "
        "Пока ты занимаешься делами, я ищу свежие новости, обрабатываю их через нейросети, "
        "генерирую картинки и публикую в твой Telegram-канал.\n\n"
        "📌 <b>Что я умею:</b>\n"
        "• Автоматически вести канал 24/7\n"
        "• Искать и перерабатывать контент по твоей теме\n"
        "• Создавать уникальные визуалы\n"
        "• Публиковать по расписанию — без твоего участия\n\n"
        "👇 <b>Тыкай на кнопки ниже</b> — я покажу, как всё настроить. "
        "Это займёт 2 минуты, а канал будет жить сам."
    )

    await message.answer(
        welcome_text,
        reply_markup=keyboards.main_menu(is_admin=is_admin, is_team_owner=is_team_owner),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "back_main")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    is_admin = callback.from_user.id in ADMIN_IDS

    # 👇 Проверяем Бизнес-тариф
    db = SessionLocal()
    user = get_or_create_user(db, callback.from_user.id)
    plan = user.subscription_plan or "start"
    is_team_owner = (plan == "business")
    db.close()

    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=keyboards.main_menu(is_admin=is_admin, is_team_owner=is_team_owner)
    )


@router.message(Command("my_channels"))
@router.callback_query(F.data == "my_channels")
async def show_channels(event: Message | CallbackQuery):
    db = SessionLocal()
    user = get_or_create_user(db, event.from_user.id, event.from_user.username)
    owner_id = get_effective_owner_id(db, user.telegram_id)
    channels = get_user_channels(db, owner_id)
    db.close()

    text = "У вас пока нет каналов. Хотите добавить первый?" if not channels else "📊 Ваши каналы:"

    keyboard = []
    if channels:
        for channel in channels:
            status = "🟢" if channel.is_active else "🔴"
            keyboard.append([InlineKeyboardButton(
                text=f"{status} {channel.channel_name}",
                callback_data=f"channel_{channel.id}"
            )])

    keyboard.append([InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")])
    if isinstance(event, CallbackQuery):
        keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    if isinstance(event, Message):
        await event.answer(text, reply_markup=reply_markup)
    else:
        await event.message.edit_text(text, reply_markup=reply_markup)


@router.message(Command("add_channel"))
@router.callback_query(F.data == "add_channel")
async def add_channel_start(event: Message | CallbackQuery, state: FSMContext):
    text = (
        "<b>Шаг 1: Добавление канала</b>\n\n"
        "1. Добавьте этого бота в администраторы вашего канала с правом на публикацию постов.\n"
        "2. Пришлите сюда <code>@username</code>, ссылку <code>https://t.me/channel</code> или просто перешлите любое сообщение из него."
    )
    if isinstance(event, Message):
        await event.answer(text)
    else:
        await event.message.edit_text(text)
    await state.set_state(ChannelStates.waiting_channel_id)


@router.message(StateFilter(ChannelStates.waiting_channel_id))
async def process_channel_id(message: Message, state: FSMContext, bot: Bot):
    channel_id = None
    channel_name = None
    channel_input = None

    if message.forward_from_chat:
        channel_id = str(message.forward_from_chat.id)
        channel_name = message.forward_from_chat.title
    elif message.text:
        if message.text.startswith("@"):
            channel_input = message.text
        elif message.text.startswith("https://t.me/"):
            channel_input = f"@{message.text.split('/')[-1]}"

        if channel_input:
            try:
                chat = await bot.get_chat(channel_input)
                channel_id = str(chat.id)
                channel_name = chat.title
            except Exception:
                await message.answer(
                    "Не удалось найти канал. Убедитесь, что бот добавлен в него с правами администратора, и попробуйте снова.")
                return
        else:
            await message.answer(
                "Неверный формат. Пожалуйста, перешлите сообщение из канала или отправьте его @username / ссылку.")
            return
    else:
        await message.answer(
            "Неверный формат. Пожалуйста, перешлите сообщение из канала или отправьте его @username / ссылку.")
        return

    if channel_id:
        db = SessionLocal()
        existing_channel = db.query(Channel).filter(Channel.channel_id == channel_id).first()
        db.close()
        if existing_channel:
            await message.answer(
                f"Канал '{channel_name}' уже добавлен в систему. Вы можете управлять им через меню /my_channels.")
            await state.clear()
            return

        await state.update_data(channel_id=channel_id, channel_name=channel_name)
        await message.answer(
            "Отлично! Теперь введите основную тему канала (например: 'Новости IT', 'Криптовалюты', 'Маркетинг'):")
        await state.set_state(ChannelStates.waiting_channel_topic)


@router.message(StateFilter(ChannelStates.waiting_channel_topic))
async def process_channel_topic(message: Message, state: FSMContext):
    data = await state.get_data()
    db = SessionLocal()
    user = get_or_create_user(db, message.from_user.id, message.from_user.username)

    # 👇 Editor не может добавлять каналы
    if get_owned_team(db, user.telegram_id):
        await message.answer("❌ Только владелец может добавлять каналы.")
        db.close()
        await state.clear()
        return

    # 👇 ПРОВЕРКА ЛИМИТА КАНАЛОВ
    can, msg = can_add_channel(db, user)
    if not can:
        await message.answer(msg)
        db.close()
        await state.clear()
        return

    channel = create_channel(
        db, user.telegram_id, data['channel_id'],
        data['channel_name'], message.text
    )

    # 👇 АКТИВИРУЕМ ПРОБНЫЙ ПЕРИОД
    from config.settings import ADMIN_IDS, TRIAL_DAYS
    if message.from_user.id not in ADMIN_IDS and not user.trial_used:
        activate_trial(db, channel.id, days=TRIAL_DAYS)
        user.trial_used = True
        db.commit()
        trial_msg = f"\n\n🎁 Вам активирован пробный период на {TRIAL_DAYS} день!"
    else:
        trial_msg = ""

    db.close()
    await state.clear()

    await message.answer(
        f"✅ Канал '{data['channel_name']}' успешно добавлен!{trial_msg}\n\n"
        "Теперь добавьте RSS-источники.",
        reply_markup=keyboards.channel_menu(channel.id)
    )


@router.callback_query(F.data.startswith("channel_"))
async def channel_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    channel_id = int(callback.data.split("_")[1])

    db = SessionLocal()
    channel = db.query(Channel).filter(Channel.id == channel_id).first()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        db.close()
        return

    status = "активен 🟢" if channel.is_active else "на паузе 🔴"
    mode = "с модерацией" if channel.moderation_mode else "автоматический"

    # 👇 Читаем owner, пока сессия ещё открыта
    owner_telegram_id = channel.owner.telegram_id
    trial_until = channel.trial_until
    subscription_until = channel.owner.subscription_until

    db.close()  # 👈 ЗАКРЫВАЕМ ПОСЛЕ ЧТЕНИЯ

    status_extra = ""
    if owner_telegram_id in ADMIN_IDS:
        status_extra = "\n<b>👑 Режим:</b> Администратор (безлимит)"
    elif trial_until and trial_until > datetime.utcnow():
        hours_left = int((trial_until - datetime.utcnow()).total_seconds() // 3600)
        status_extra = f"\n<b>🎁 Пробный:</b> ещё {hours_left} ч."
    elif subscription_until and subscription_until > datetime.utcnow():
        date_str = subscription_until.strftime('%d.%m.%Y')
        status_extra = f"\n<b>💎 Подписка:</b> до {date_str}"
    else:
        status_extra = "\n<b>❌ Доступ:</b> закрыт. Оформите подписку."

    text = (
        f"<b>Управление каналом: {channel.channel_name}</b>\n\n"
        f"<b>Тема:</b> {channel.topic}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Режим AI:</b> {mode} (модель: <code>{channel.ai_model}</code>)\n"
        f"<b>Интервал постов:</b> ~{channel.post_interval // 60} мин."
        f"{status_extra}"
    )

    # ✅ УБРАН дублирующийся edit_text
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.channel_menu(channel_id)
    )


@router.callback_query(F.data.startswith("rss_"))
async def rss_sources_menu(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    sources = db.query(RSSSource).filter(RSSSource.channel_id == channel_id).all()
    db.close()

    text = "📰 У вас пока нет RSS-источников." if not sources else "📰 Ваши RSS-источники:"
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.rss_sources_menu(channel_id, sources)
    )


@router.callback_query(F.data.startswith("source_"))
async def source_menu(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    source = db.query(RSSSource).filter(RSSSource.id == source_id).first()
    db.close()

    if not source:
        await callback.answer("Источник не найден!", show_alert=True)
        return

    status = "активен ✅" if source.is_active else "отключен ❌"
    text = (
        f"<b>Управление источником: {source.name}</b>\n\n"
        f"<b>URL:</b> {source.url}\n"
        f"<b>Статус:</b> {status}\n"
        f"<b>Ошибок:</b> {source.error_count}"
    )

    keyboard = [
        [InlineKeyboardButton(text=f"{'Отключить' if source.is_active else 'Включить'}", callback_data=f"toggle_source_{source_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_source_confirm_{source_id}")],
        [InlineKeyboardButton(text="◀️ Назад к источникам", callback_data=f"rss_{source.channel_id}")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("toggle_source_"))
async def toggle_source_active(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    source = toggle_rss_source(db, source_id)
    db.close()

    if source:
        status = "включен" if source.is_active else "отключен"
        await callback.answer(f"Источник {status}")
        # Refresh меню источников
        callback.data = f"rss_{source.channel_id}"
        await rss_sources_menu(callback)
    else:
        await callback.answer("Ошибка при переключении!", show_alert=True)


@router.callback_query(F.data.startswith("delete_source_confirm_"))
async def delete_source_confirm(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    source = db.query(RSSSource).filter(RSSSource.id == source_id).first()
    db.close()

    if not source:
        await callback.answer("Источник не найден!", show_alert=True)
        return

    text = f"Вы уверены, что хотите удалить источник '{source.name}'?"

    keyboard = [
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_source_{source_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"source_{source_id}")
        ]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("confirm_delete_source_"))
async def delete_source_execute(callback: CallbackQuery):
    source_id = int(callback.data.split("_")[3])
    db = SessionLocal()
    source = db.query(RSSSource).filter(RSSSource.id == source_id).first()
    channel_id = source.channel_id if source else None
    deleted = delete_rss_source(db, source_id)
    db.close()

    if deleted:
        await callback.answer("Источник успешно удален", show_alert=True)
        if channel_id:
            callback.data = f"rss_{channel_id}"
            await rss_sources_menu(callback)
    else:
        await callback.answer("Ошибка при удалении!", show_alert=True)


@router.callback_query(F.data.startswith("add_rss_"))
async def add_rss_manual_start(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[2])

    # 👇 ПРОВЕРКА ПРАВА
    db = SessionLocal()
    if not check_permission(db, callback.from_user.id, "manage_rss"):
        await callback.answer("❌ Нет права управлять RSS", show_alert=True)
        db.close()
        return
    db.close()

    await state.update_data(channel_id=channel_id)
    await callback.message.edit_text(
        "📡 Введите URL RSS-ленты напрямую.\n\n"
        "Примеры популярных RSS:\n"
        "• <code>https://habr.com/ru/rss/all/all/</code> - Хабр\n"
        "• <code>https://vc.ru/rss</code> - VC.ru\n"
        "• <code>https://www.vedomosti.ru/rss/news</code> - Ведомости\n"
        "• <code>https://lenta.ru/rss</code> - Лента.ру"
    )
    await state.set_state(ChannelStates.waiting_manual_rss)


@router.message(StateFilter(ChannelStates.waiting_manual_rss))
async def process_manual_rss(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data['channel_id']

    url_input = message.text.strip()
    if not url_input.startswith(('http://', 'https://')):
        formatted_url = f"https://{url_input}"
    else:
        formatted_url = url_input

    import feedparser
    feed = feedparser.parse(formatted_url)

    if feed.entries:
        db = SessionLocal()
        title = feed.feed.get('title', formatted_url[:50])

        # 👇 ОПРЕДЕЛЯЕМ ТИП ИСТОЧНИКА
        fun_domains = [
            "reddit.com/r/ChatGPTPromptGenius",
            "reddit.com/r/PromptEngineering",
            "reddit.com/r/ChatGPT",
            "reddit.com/r/weirdGPT",
            "reddit.com/r/artificial",
        ]
        source_type = "fun" if any(d in formatted_url for d in fun_domains) else "news"

        add_rss_source(db, channel_id, formatted_url, title, source_type)
        sources = db.query(RSSSource).filter_by(channel_id=channel_id).all()
        db.close()

        type_label = "🎉 Развлекательный" if source_type == "fun" else "📰 Новостной"
        await message.answer(
            f"✅ RSS источник '{title}' добавлен как {type_label}!",
            reply_markup=keyboards.rss_sources_menu(channel_id, sources)
        )
    else:
        await message.answer(
            "❌ Не удалось прочитать RSS по указанному URL. Проверьте правильность ссылки."
        )

    await state.clear()


@router.callback_query(F.data.startswith("create_"))
async def create_post_start(callback: CallbackQuery, bot: Bot):
    channel_id = int(callback.data.split("_")[1])

    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    sources = db.query(RSSSource).filter_by(channel_id=channel_id, is_active=True).all()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        db.close()
        return

    # 👇 ПРОВЕРКА ДОСТУПА
    from config.settings import ADMIN_IDS
    from database.crud import has_access

    if not has_access(db, channel_id, ADMIN_IDS):
        await callback.answer(
            "❌ Подписка неактивна. Оформите в меню «💎 Подписка».",
            show_alert=True
        )
        db.close()
        return

    sources = db.query(RSSSource).filter_by(channel_id=channel_id, is_active=True).all()

    if not sources:
        await callback.answer("Сначала добавьте RSS источники!", show_alert=True)
        db.close()
        return

    msg = await callback.message.edit_text("⏳ Ищу свежие новости...")

    try:
        from core.rss_parser import RSSParser
        ai_processor = AIProcessor()
        publisher = Publisher(bot)

        # 👇 СЧЕТЧИК ЧЕРЕДОВАНИЯ
        settings = channel.settings or {}
        post_counter = settings.get("post_counter", 0)
        use_fun = post_counter >= 3  # каждые 3 поста — развлекательный

        # Разделяем источники
        fun_sources = [s for s in sources if getattr(s, 'source_type', 'news') == "fun"]
        news_sources = [s for s in sources if getattr(s, 'source_type', 'news') != "fun"]

        if use_fun and fun_sources:
            active_sources = fun_sources
            is_fun_post = True
        else:
            active_sources = news_sources if news_sources else sources
            is_fun_post = False

        logger.info(f"Счетчик: {post_counter}, развлекательный: {is_fun_post}, источников: {len(active_sources)}")

        # Ключевые слова для AI-фильтрации
        AI_KEYWORDS = [
            'ai', 'ии', 'нейросет', 'нейронн', 'gpt', 'llm', 'chatgpt', 'midjourney',
            'искусственн', 'машинн', 'промпт', 'deepmind', 'openai', 'anthropic',
            'hugging face', 'gemini', 'claude', 'machine learning', 'deep learning',
            'нейро', 'generative', 'генеративн', 'модель', 'model', 'artificial intelligence',
            'chatbot', 'чат-бот', 'нейросеть', 'diffusion', 'диффузи', 'stable diffusion',
            'copilot', 'mistral', 'llama', 'transformer', 'трансформер'
        ]

        def is_ai_related(title: str, content: str) -> bool:
            text = (title + ' ' + content).lower()
            return any(keyword in text for keyword in AI_KEYWORDS)

        parser = RSSParser()
        async with parser:
            all_entries = []
            for source in active_sources:
                entries = await parser.parse_feed(source.url)
                if entries:
                    all_entries.extend(entries[:3])

            # Фильтр только для новостных
            if not is_fun_post:
                all_entries = [
                    e for e in all_entries
                    if is_ai_related(e.get('title', ''), e.get('content', ''))
                ]

            logger.info(f"Всего новостей после фильтра: {len(all_entries)}")

            if not all_entries:
                await msg.edit_text("❌ Не найдено новых постов. Попробуйте позже.")
                db.close()
                return

            await msg.edit_text("🧠 Обрабатываю...")

            # ФИЛЬТРАЦИЯ ДУБЛЕЙ ПО GUID
            filtered_entries = []
            for e in all_entries:
                guid = e.get('guid', e.get('link', ''))
                existing = db.query(Post).filter(
                    Post.channel_id == channel_id,
                    Post.source_url == guid
                ).first()
                if not existing:
                    filtered_entries.append(e)
                else:
                    logger.info(f"Дубль пропущен: {e.get('title', '')[:50]}")

            if not filtered_entries:
                await msg.edit_text("❌ Все новости уже опубликованы.")
                db.close()
                return

            all_entries = filtered_entries
            logger.info(f"После фильтра дублей: {len(all_entries)}")

            entry = random.choice(all_entries)
            # 👇 РАЗНЫЕ ПРОМПТЫ
            if is_fun_post:
                custom_prompt = (
                    "Ты — редактор Telegram-канала про ИИ. Вот пост с Reddit про промпты или фишки ИИ.\n\n"
                    "ЗАДАЧА: переведи суть на русский и оформи как короткий пост.\n\n"
                    "ПРАВИЛА:\n"
                    "1. Длина: 400-500 символов.\n"
                    "2. Заголовок с эмодзи.\n"
                    "3. Если это промпт — оформи его в цитату (используй <code>...</code>).\n"
                    "4. В конце — 2 хештега (#промпты #AI).\n"
                    "5. Стиль: живой, как объясняешь другу."
                )
            else:
                custom_prompt = channel.ai_prompt

            processed_content = await ai_processor.process_content(
                entry,
                {
                    'ai_model': channel.ai_model,
                    'ai_prompt': custom_prompt,
                    'topic': channel.topic
                }
            )

        media_urls = entry.get('media', [])

        # 👇 ГЕНЕРАЦИЯ КАРТИНКИ, ЕСЛИ ЕЁ НЕТ
        if not media_urls:
            await msg.edit_text("🎨 Генерирую картинку...")
            image_prompt = await ai_processor.generate_image_prompt(entry.get('title', ''))
            logger.info(f"Промпт для картинки: {image_prompt}")

            from core.image_generator import generate_image
            generated_path = generate_image(image_prompt)
            if generated_path:
                media_urls = [generated_path]
                logger.info(f"Картинка сгенерирована: {generated_path}")

        await msg.edit_text("✅ Публикую...")
        message_id = await publisher.publish_post(
            channel.channel_id,
            processed_content,
            media_urls
        )

        if message_id:
            new_post = create_post(
                db, channel_id, entry.get('guid', entry.get('link', '')),  # 👈 GUID новости
                entry['title'], entry['content'],
                processed_content, media_urls,
                datetime.utcnow()
            )
            if new_post:
                update_post_status(db, new_post.id, "published", message_id)

            # 👇 ОБНОВЛЯЕМ СЧЕТЧИК
            if is_fun_post:
                settings["post_counter"] = 0
            else:
                settings["post_counter"] = post_counter + 1
            channel.settings = settings
            db.commit()

            type_label = "🎉 Развлекательный" if is_fun_post else "📰 Новостной"
            await msg.edit_text(
                f"✅ {type_label} пост опубликован! (счетчик: {settings['post_counter']}/3)",
                reply_markup=keyboards.channel_menu(channel_id)
            )
        else:
            await msg.edit_text(
                f"❌ Ошибка публикации. Проверьте, что бот админ канала {channel.channel_name}."
            )

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)[:100]}")
    finally:
        db.close()


@router.callback_query(F.data.startswith("queue_"))
async def show_queue(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    posts = get_channel_queue(db, channel_id)
    db.close()

    if not posts:
        await callback.message.edit_text(
            "📭 Очередь постов пуста",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"channel_{channel_id}")]
            ])
        )
    else:
        await callback.message.edit_text(
            f"📝 В очереди {len(posts)} постов",
            reply_markup=keyboards.post_queue_menu(channel_id, posts)
        )


@router.callback_query(F.data.startswith("toggle_"))
async def toggle_channel_active(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = crud.toggle_channel_active(db, channel_id)
    db.close()

    if channel:
        status = "запущен" if channel.is_active else "поставлен на паузу"
        await callback.answer(f"Канал {status}")
        await channel_menu(callback, state)


@router.callback_query(F.data.startswith("schedule_"))
async def schedule_menu(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()
    if not channel:
        await callback.answer("Канал не найден", show_alert=True)
        return

    text = f"⏰ Текущий интервал между постами: ~{channel.post_interval // 60} минут.\n\nВыберите новый интервал:"
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.schedule_menu(channel_id, channel.post_interval)
    )


@router.callback_query(F.data.startswith("set_interval_"))
async def set_schedule(callback: CallbackQuery):
    try:
        _, _, channel_id_str, interval_str = callback.data.split("_")
        channel_id = int(channel_id_str)
        interval = int(interval_str)
    except ValueError:
        await callback.answer("Ошибка данных. Попробуйте снова.", show_alert=True)
        return

    # 👇 ПРОВЕРКА ПРАВА
    db = SessionLocal()
    if not check_permission(db, callback.from_user.id, "change_interval"):
        await callback.answer("❌ Нет права менять интервал", show_alert=True)
        db.close()
        return
    db.close()

    db = SessionLocal()
    update_channel_settings(db, channel_id, post_interval=interval)
    db.close()

    await callback.answer(f"Интервал изменен на ~{interval // 60} минут.", show_alert=True)

    callback.data = f"schedule_{channel_id}"
    await schedule_menu(callback)


@router.callback_query(F.data.startswith("delete_"))
async def delete_channel_confirm(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()
    if not channel:
        await callback.answer("Канал не найден", show_alert=True)
        return

    await callback.message.edit_text(
        f"Вы уверены, что хотите удалить канал «{channel.channel_name}» и все связанные с ним данные?",
        reply_markup=keyboards.confirm_delete(channel_id)
    )


@router.callback_query(F.data.startswith("confirm_delete_"))
async def delete_channel_execute(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    delete_channel(db, channel_id)
    db.close()

    await callback.answer("Канал успешно удален", show_alert=True)
    await show_channels(callback)


@router.callback_query(F.data.regexp(r"^ai_\d+$"))
async def ai_settings_menu(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    text = (
        f"<b>Настройки AI для канала «{channel.channel_name}»</b>\n\n"
        f"<b>Текущая модель:</b> <code>{channel.ai_model}</code>\n"
        f"<b>Режим модерации:</b> {'Включен' if channel.moderation_mode else 'Выключен'}\n\n"
        "Здесь вы можете изменить модель, которая будет обрабатывать тексты, или отредактировать системный промпт."
    )
    await callback.message.edit_text(
        text,
        reply_markup=keyboards.ai_settings_menu(channel_id, channel.moderation_mode)
    )


@router.callback_query(F.data.startswith("ai_model_"))
async def choose_ai_model(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        return

    await callback.message.edit_text(
        "Выберите модель, которую бот будет использовать для обработки новостей:",
        reply_markup=keyboards.ai_models_menu(channel_id, channel.ai_model)
    )


@router.callback_query(F.data.startswith("ai_prompt_"))
async def ai_prompt_change_start(callback: CallbackQuery, state: FSMContext):
    channel_id = int(callback.data.split("_")[2])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        db.close()
        return

    # 👇 Проверка права
    if not check_permission(db, callback.from_user.id, "change_prompt"):
        await callback.answer("❌ Нет права менять промпт", show_alert=True)
        db.close()
        return

    current_prompt = channel.ai_prompt or "Пока не задан. Будет использован стандартный."
    db.close()

    await state.update_data(channel_id=channel_id)
    await callback.message.edit_text(
        f"<b>Текущий промпт:</b>\n<pre>{current_prompt}</pre>\n\n"
        "Отправьте новый текст системного промпта. Используйте `{topic}` для подстановки темы канала."
    )
    await state.set_state(ChannelStates.waiting_ai_prompt)


@router.message(StateFilter(ChannelStates.waiting_ai_prompt))
async def process_ai_prompt(message: Message, state: FSMContext):
    data = await state.get_data()
    channel_id = data['channel_id']

    db = SessionLocal()
    update_channel_settings(db, channel_id, ai_prompt=message.text)
    channel = db.query(Channel).filter_by(id=channel_id).first()
    db.close()

    await message.answer("✅ Системный промпт успешно обновлен!")
    await state.clear()

    from aiogram.types.user import User
    from aiogram.types.chat import Chat

    callback_to_return = CallbackQuery(
        id="return_to_ai_menu",
        from_user=message.from_user,
        chat_instance="dummy",
        message=message,
        data=f"ai_{channel_id}"
    )
    await ai_settings_menu(callback_to_return)


@router.callback_query(F.data.startswith("set_model_"))
async def set_ai_model(callback: CallbackQuery):
    parts = callback.data.split("_")
    channel_id = int(parts[2])
    model = "-".join(parts[3:])

    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        db.close()
        return

    # 👇 ПРОВЕРКА ТАРИФА
    owner = channel.owner
    if not can_use_model(owner, model):
        await callback.answer(
            f"❌ Модель {model} недоступна на вашем тарифе. Обновите тариф в Mini App.",
            show_alert=True
        )
        db.close()
        return

    update_channel_settings(db, channel_id, ai_model=model)
    db.close()

    await callback.answer(f"Модель изменена на {model}", show_alert=True)
    await ai_settings_menu(callback)


@router.callback_query(F.data.startswith("moderation_"))
async def toggle_moderation(callback: CallbackQuery):
    channel_id = int(callback.data.split("_")[1])
    db = SessionLocal()
    channel = db.query(Channel).filter_by(id=channel_id).first()

    if not channel:
        await callback.answer("Канал не найден!", show_alert=True)
        db.close()
        return

    # 👇 ПРОВЕРКА ТАРИФА
    owner = channel.owner
    if not can_use_feature(owner, "moderation"):
        await callback.answer(
            "❌ Премодерация доступна только в тарифах «Про» и «Бизнес»",
            show_alert=True
        )
        db.close()
        return

    # 👇 ПРОВЕРКА ПРАВА EDITOR'А
    if not check_permission(db, callback.from_user.id, "moderate_posts"):
        await callback.answer("❌ Нет права модерировать", show_alert=True)
        db.close()
        return

    new_mode = not channel.moderation_mode
    update_channel_settings(db, channel_id, moderation_mode=new_mode)
    db.close()

    mode_text = "включён" if new_mode else "выключен"
    await callback.answer(f"Режим модерации {mode_text}")
    await ai_settings_menu(callback)


# ============================================================
# ОПЛАТА ПОДПИСКИ ЧЕРЕЗ TELEGRAM STARS
# ============================================================

@router.callback_query(F.data == "subscribe")
async def subscribe_menu(callback: CallbackQuery):
    from config.settings import SUBSCRIPTION_PRICES
    keyboard = []
    for plan_key, plan in SUBSCRIPTION_PRICES.items():
        keyboard.append([InlineKeyboardButton(
            text=f"{plan['name']} — {plan['price']} ⭐",
            callback_data=f"pay_{plan_key}"
        )])
    keyboard.append([InlineKeyboardButton(text="🎁 Пробный период", callback_data="trial_info")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])

    text_lines = ["💎 Выберите тариф подписки:\n"]
    for plan in SUBSCRIPTION_PRICES.values():
        text_lines.append(
            f"{plan['name']} — {plan['channels']} кан., {plan['posts_per_day']} постов/день"
        )

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@router.callback_query(F.data.startswith("pay_"))
async def send_invoice(callback: CallbackQuery):
    from config.settings import SUBSCRIPTION_PRICES
    plan_key = callback.data.split("_")[1]
    plan = SUBSCRIPTION_PRICES[plan_key]

    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Подписка FEEL IT — AI LAB ({plan['name']})",
        description=f"{plan['channels']} канал(ов), {plan['posts_per_day']} постов/день",
        payload=f"sub_{plan_key}",
        currency="XTR",
        prices=[LabeledPrice(label=plan['name'], amount=plan['price'])],
        provider_token=""
    )


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload

    if payload.startswith("sub_"):
        plan_key = payload.split("_")[1]
        days = 30

        db = SessionLocal()
        user = get_or_create_user(db, message.from_user.id)
        user.subscription_until = datetime.utcnow() + timedelta(days=days)
        user.subscription_plan = plan_key
        db.commit()

        # 👇 СИНХРОНИЗАЦИЯ С GRAMKIT — создаём запись в subscriptions
        try:
            from sqlalchemy import text
            from uuid import uuid4

            product_id_map = {
                "start": "FEELIT_START",
                "pro": "FEELIT_PRO",
                "business": "FEELIT_BUSINESS",
            }
            gramkit_product_id = product_id_map.get(plan_key)

            if gramkit_product_id:
                # Найти UUID юзера (gramkit использует UUID, newsbot — Integer id)
                user_uuid_row = db.execute(text("""
                    SELECT id FROM users WHERE telegram_id = :tg LIMIT 1
                """), {"tg": message.from_user.id}).fetchone()

                if user_uuid_row:
                    user_uuid = user_uuid_row[0]
                    db.execute(text("""
                        INSERT INTO subscriptions 
                        (id, user_id, product_id, provider_id, status, currency,
                         start_date, end_date, recurring_details, created_at, updated_at)
                        VALUES 
                        (:id, :uid, :pid, 'TELEGRAM_STARS', 'ACTIVE', 'XTR',
                         :now, :end, '{}', :now, :now)
                    """), {
                        "id": str(uuid4()),
                        "uid": user_uuid,
                        "pid": gramkit_product_id,
                        "now": datetime.utcnow(),
                        "end": user.subscription_until,
                    })
                    db.commit()
                    logger.info(
                        f"✅ Создана запись в subscriptions: "
                        f"tg={message.from_user.id}, product={gramkit_product_id}"
                    )
                else:
                    logger.warning(
                        f"UUID для tg={message.from_user.id} не найден"
                    )
        except Exception as e:
            logger.error(f"Ошибка синхронизации с gramkit: {e}", exc_info=True)
            # НЕ откатываем — подписка в users уже создана

        db.close()

        from config.settings import SUBSCRIPTION_PRICES
        plan = SUBSCRIPTION_PRICES[plan_key]
        await message.answer(
            f"✅ Подписка «{plan['name']}» активирована на {days} дней!\n\n"
            f"📊 Лимиты: {plan['channels']} канал(ов), {plan['posts_per_day']} постов/день"
        )

        from config.settings import SUBSCRIPTION_PRICES
        plan = SUBSCRIPTION_PRICES[plan_key]
        await message.answer(
            f"✅ Подписка «{plan['name']}» активирована на {days} дней!\n\n"
            f"📊 Лимиты: {plan['channels']} канал(ов), {plan['posts_per_day']} постов/день"
        )


# ============================================================
# МОДЕРАЦИЯ ПОСТОВ
# ============================================================

@router.callback_query(F.data.startswith("approve_"))
async def approve_post(callback: CallbackQuery, bot: Bot):
    post_id = int(callback.data.split("_")[1])

    db = SessionLocal()
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        await callback.answer("Пост не найден!", show_alert=True)
        db.close()
        return

    channel = post.channel

    # Публикуем
    publisher = Publisher(bot)
    message_id = await publisher.publish_post(
        channel.channel_id,
        post.processed_content,
        post.media_urls
    )

    if message_id:
        update_post_status(db, post_id, "published", message_id)
        await callback.message.edit_text(
            f"✅ Пост опубликован в канал «{channel.channel_name}»!"
        )
    else:
        await callback.answer("❌ Ошибка публикации", show_alert=True)

    db.close()


@router.callback_query(F.data.startswith("reject_"))
async def reject_post(callback: CallbackQuery):
    post_id = int(callback.data.split("_")[1])

    db = SessionLocal()
    update_post_status(db, post_id, "rejected")
    db.close()

    await callback.message.edit_text("❌ Пост отклонён.")


@router.callback_query(F.data == "what_i_can")
async def what_i_can(callback: CallbackQuery):
    keyboard = [
        [InlineKeyboardButton(text="🤖 Обо мне", callback_data="about_bot")],
        [InlineKeyboardButton(text="💎 О тарифах", callback_data="about_tariffs")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ]
    await callback.message.edit_text(
        "🤖 <b>Что я умею?</b>\n\n"
        "Выбери, что хочешь узнать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "about_bot")
async def about_bot(callback: CallbackQuery):
    await callback.message.edit_text(
        "🤖 <b>FEEL IT — AI LAB</b>\n\n"
        "Я — бот, который <b>сам ведёт твой Telegram-канал</b>.\n\n"
        "🔹 <b>Что я делаю:</b>\n"
        "• Ищу свежие новости по твоей теме\n"
        "• Обрабатываю через нейросети (перевод, рерайт, стиль)\n"
        "• Генерирую уникальные картинки, если их нет\n"
        "• Публикую по расписанию — без твоего участия\n\n"
        "🔹 <b>Почему я:</b>\n"
        "• Не нужно быть контент-менеджером\n"
        "• Канал живёт, пока ты спишь\n"
        "• Всё в одном боте — от RSS до публикации\n\n"
        "🔹 <b>Для кого:</b>\n"
        "• Владельцы каналов, которым нужен контент\n"
        "• Те, кто устал искать новости вручную\n"
        "• Те, кто хочет автоматизировать рутину",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="what_i_can")]
        ]),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "about_tariffs")
async def about_tariffs(callback: CallbackQuery):
    from config.settings import SUBSCRIPTION_PRICES
    text = "💎 <b>Тарифы подписки</b>\n\n"
    for key, plan in SUBSCRIPTION_PRICES.items():
        text += f"<b>{plan['name']}</b> — {plan['price']} ⭐\n"
        text += f"• {plan['channels']} канал(ов)\n"
        text += f"• {plan['posts_per_day']} постов/день\n\n"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="what_i_can")]
        ]),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "contact")
async def contact(callback: CallbackQuery):
    await callback.message.edit_text(
        "📢 <b>Реклама и сотрудничество</b>\n\n"
        "По всем вопросам:\n\n"
        "👤 Telegram: @kiddybesoul\n"
        "📧 Email: tvdusa90@gmail.com",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ]),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "trial_info")
async def trial_info(callback: CallbackQuery):
    keyboard = [
        [InlineKeyboardButton(text="📢 Перейти на канал", url="https://t.me/feelit_ailab")],
        [InlineKeyboardButton(text="✅ Условия выполнены", callback_data="check_trial_subscription")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="subscribe")]
    ]
    await callback.message.edit_text(
        "🎁 <b>Пробный период</b>\n\n"
        "<b>Что входит:</b>\n"
        "• 1 день полного доступа\n"
        "• 1 канал\n"
        "• До 10 постов\n"
        "• Генерация картинок\n\n"
        "<b>Условие для получения:</b>\n"
        "• Подписка на канал <a href='https://t.me/feelit_ailab'>FEEL IT — AI LAB</a>\n\n"
        "После подписки нажми «✅ Условия выполнены».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@router.callback_query(F.data == "check_trial_subscription")
async def check_trial_subscription(callback: CallbackQuery, bot: Bot):
    from config.settings import ADMIN_IDS

    user_id = callback.from_user.id

    try:
        member = await bot.get_chat_member("@feelit_ailab", user_id)
        if member.status in ("creator", "administrator", "member"):
            db = SessionLocal()
            user = get_or_create_user(db, user_id)

            if user.trial_used:
                await callback.answer("❌ Вы уже использовали пробный период!", show_alert=True)
                db.close()
                return

            user.trial_used = True
            db.commit()
            db.close()

            await callback.message.edit_text(
                "✅ <b>Пробный период активирован!</b>\n\n"
                "Теперь добавь канал и настрой RSS — бот начнёт работать.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")]
                ]),
                parse_mode="HTML"
            )
        else:
            await callback.answer("❌ Вы не подписаны на канал!", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка проверки: {str(e)[:50]}", show_alert=True)
# ============================================================
# КОМАНДНЫЙ ДОСТУП — UI
# ============================================================

@router.callback_query(F.data == "team")
async def team_menu(callback: CallbackQuery):
    from database.crud import get_team_members, count_active_team
    from config.settings import SUBSCRIPTION_PRICES

    user_id = callback.from_user.id
    db = SessionLocal()
    user = get_or_create_user(db, user_id)

    # Проверка: Бизнес-тариф
    plan = user.subscription_plan or "start"
    if plan != "business" and user_id not in ADMIN_IDS:
        await callback.answer(
            "❌ Командный доступ доступен только в тарифе «Бизнес»",
            show_alert=True
        )
        db.close()
        return

    # Лимит команды
    max_team = SUBSCRIPTION_PRICES.get("business", {}).get("team_size", 5)
    # TODO: учесть докупленные места
    team_size = count_active_team(db, user_id)
    db.close()

    text = (
        f"👥 <b>Команда</b>\n\n"
        f"Участников: <b>{team_size}/{max_team}</b>\n\n"
        f"Пригласи редактора — он получит доступ к твоим каналам "
        f"в рамках прав, которые ты задашь."
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboards.team_menu(user_id, team_size, max_team),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "team_invite")
async def team_invite(callback: CallbackQuery):
    from database.crud import invite_team_member, count_active_team
    from config.settings import SUBSCRIPTION_PRICES

    user_id = callback.from_user.id
    db = SessionLocal()

    # Проверка лимита
    max_team = SUBSCRIPTION_PRICES.get("business", {}).get("team_size", 5)
    current = count_active_team(db, user_id)

    if current >= max_team and user_id not in ADMIN_IDS:
        await callback.answer(
            f"❌ Лимит команды — {max_team}. Докупите место (скоро).",
            show_alert=True
        )
        db.close()
        return

    # Создаём/получаем приглашение
    invite = invite_team_member(db, user_id)
    token = invite.invite_token
    db.close()

    link = f"https://t.me/feelit_ailab_bot?start=team_{token}"

    text = (
        f"👥 <b>Приглашение в команду</b>\n\n"
        f"Отправь эту ссылку редактору:\n\n"
        f"<code>{link}</code>\n\n"
        f"Он нажмёт → станет редактором твоей команды.\n"
        f"Права можно будет настроить после принятия."
    )

    keyboard = [
        [InlineKeyboardButton(text="◀️ Назад", callback_data="team")]
    ]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "team_list")
async def team_list(callback: CallbackQuery):
    from database.crud import get_team_members

    db = SessionLocal()
    members = get_team_members(db, callback.from_user.id)
    db.close()

    if not members:
        text = "👥 <b>Команда пуста</b>\n\nПригласи первого редактора."
    else:
        text = f"👥 <b>Команда ({len(members)})</b>\n\nВыбери участника:"

    await callback.message.edit_text(
        text,
        reply_markup=keyboards.team_members_menu(members),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("team_member_"))
async def team_member_menu(callback: CallbackQuery):
    team_id = int(callback.data.split("_")[2])

    db = SessionLocal()
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()
    db.close()

    if not member:
        await callback.answer("Участник не найден!", show_alert=True)
        return

    # Проверка: этот участник — в моей команде?
    if member.owner_id != callback.from_user.id and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return

    name = f"@{member.member_id}" if member.member_id else f"id{member.member_id}"
    role_label = "Админ" if member.role == "admin" else "Редактор"

    text = (
        f"👤 <b>Участник</b>\n\n"
        f"ID: <code>{member.member_id}</code>\n"
        f"Роль: <b>{role_label}</b>\n"
        f"Добавлен: {member.accepted_at.strftime('%d.%m.%Y') if member.accepted_at else '—'}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboards.team_member_menu(team_id, member.member_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("team_perms_"))
async def team_perms_menu(callback: CallbackQuery):
    team_id = int(callback.data.split("_")[2])

    db = SessionLocal()
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()
    db.close()

    if not member:
        await callback.answer("Участник не найден!", show_alert=True)
        return

    if member.owner_id != callback.from_user.id and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        f"⚙️ <b>Права редактора</b>\n\n"
        f"Нажми, чтобы включить/выключить:",
        reply_markup=keyboards.team_permissions_menu(team_id, member.permissions or {}),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("team_perm_"))
async def team_perm_toggle(callback: CallbackQuery):
    parts = callback.data.split("_")
    team_id = int(parts[2])
    perm_key = parts[3]

    db = SessionLocal()
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()

    if not member:
        await callback.answer("Участник не найден!", show_alert=True)
        db.close()
        return

    if member.owner_id != callback.from_user.id and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        db.close()
        return

    current_perms = dict(member.permissions or {})
    current_value = current_perms.get(perm_key, False)
    new_value = not current_value

    update_member_permission(db, team_id, perm_key, new_value)
    db.close()

    await callback.answer(f"{'Включено' if new_value else 'Выключено'}")

    # Refresh
    callback.data = f"team_perms_{team_id}"
    await team_perms_menu(callback)


@router.callback_query(F.data.startswith("team_remove_"))
async def team_remove_confirm(callback: CallbackQuery):
    team_id = int(callback.data.split("_")[2])

    db = SessionLocal()
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()
    db.close()

    if not member:
        await callback.answer("Участник не найден!", show_alert=True)
        return

    await callback.message.edit_text(
        f"🗑️ Удалить участника <code>{member.member_id}</code> из команды?",
        reply_markup=keyboards.team_confirm_remove(team_id),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("team_remove_confirm_"))
async def team_remove_execute(callback: CallbackQuery):
    team_id = int(callback.data.split("_")[3])

    db = SessionLocal()
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()

    if not member:
        await callback.answer("Участник не найден!", show_alert=True)
        db.close()
        return

    if member.owner_id != callback.from_user.id and callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        db.close()
        return

    from database.crud import remove_team_member
    remove_team_member(db, team_id)
    db.close()

    await callback.answer("Участник удалён")
    callback.data = "team_list"
    await team_list(callback)

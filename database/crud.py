from sqlalchemy.orm import Session
from database.models import User, Channel, RSSSource, Post, SessionLocal
from datetime import datetime, timedelta
from typing import List, Optional
from utils.helpers import generate_post_hash


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_user(db: Session, telegram_id: int, username: str = None):
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(telegram_id=telegram_id, username=username)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def create_channel(db: Session, owner_telegram_id: int, channel_id: str, channel_name: str, topic: str):
    """owner_telegram_id — Telegram ID владельца (BigInteger), не UUID."""
    channel = Channel(
        channel_id=channel_id,
        channel_name=channel_name,
        topic=topic,
        owner_id=owner_telegram_id
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def get_user_channels(db: Session, owner_telegram_id: int):
    """owner_telegram_id — Telegram ID владельца (BigInteger), не UUID."""
    return db.query(Channel).filter(Channel.owner_id == owner_telegram_id).all()


def add_rss_source(db: Session, channel_id: int, url: str, name: str, source_type: str = "news"):
    source = RSSSource(
        url=url,
        name=name,
        channel_id=channel_id,
        source_type=source_type
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def get_active_sources(db: Session):
    return db.query(RSSSource).filter(RSSSource.is_active == True).all()


def create_post(db: Session, channel_id: int, source_url: str, title: str, content: str, processed: str, media: list,
                scheduled: datetime):

    post_hash = generate_post_hash(title + " " + content)

    existing_post = db.query(Post).filter(
        Post.channel_id == channel_id,
        Post.hash == post_hash
    ).first()

    if existing_post:
        return None

    post = Post(
        channel_id=channel_id,
        source_url=source_url,
        original_title=title,
        original_content=content,
        processed_content=processed,
        media_urls=media,
        scheduled_time=scheduled,
        hash=post_hash  # Сохраняем хэш
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def get_pending_posts(db: Session):
    now = datetime.utcnow()
    return db.query(Post).filter(
        Post.status == "pending",
        Post.scheduled_time <= now
    ).all()


def get_channel_queue(db: Session, channel_id: int):
    return db.query(Post).filter(
        Post.channel_id == channel_id,
        Post.status == "pending"
    ).order_by(Post.scheduled_time).all()


def update_post_status(db: Session, post_id: int, status: str, message_id: int = None):
    post = db.query(Post).filter(Post.id == post_id).first()
    if post:
        post.status = status
        if message_id:
            post.message_id = message_id
        if status == "published":
            post.published_time = datetime.utcnow()
        db.commit()
    return post


def update_source_check(db: Session, source_id: int, last_guid: str = None, error: bool = False):
    source = db.query(RSSSource).filter(RSSSource.id == source_id).first()
    if source:
        source.last_checked = datetime.utcnow()
        if last_guid:
            source.last_guid = last_guid
        if error:
            source.error_count += 1
        else:
            source.error_count = 0
        db.commit()
    return source


def toggle_channel_active(db: Session, channel_id: int):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel:
        channel.is_active = not channel.is_active
        db.commit()
    return channel


def toggle_rss_source(db: Session, source_id: int):
    source = db.query(RSSSource).filter(RSSSource.id == source_id).first()
    if source:
        source.is_active = not source.is_active
        db.commit()
    return source


def update_channel_settings(db: Session, channel_id: int, **kwargs):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel:
        for key, value in kwargs.items():
            if hasattr(channel, key):
                setattr(channel, key, value)
        db.commit()
    return channel


def delete_rss_source(db: Session, source_id: int):
    source = db.query(RSSSource).filter(RSSSource.id == source_id).first()
    if source:
        db.delete(source)
        db.commit()
        return True
    return False


def delete_channel(db: Session, channel_id: int):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel:
        db.query(Post).filter(Post.channel_id == channel_id).delete()
        db.query(RSSSource).filter(RSSSource.channel_id == channel_id).delete()
        db.delete(channel)
        db.commit()
        return True
    return False


def get_moderation_posts(db: Session, channel_id: int):
    return db.query(Post).filter(
        Post.channel_id == channel_id,
        Post.status == "moderation"
    ).all()


def get_user_by_telegram_id(db: Session, telegram_id: int):
    return db.query(User).filter(User.telegram_id == telegram_id).first()


def activate_trial(db: Session, channel_id: int, days: int = 1):
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if channel:
        channel.trial_until = datetime.utcnow() + timedelta(days=days)
        channel.trial_notified = False
        db.commit()
    return channel


def has_access(db: Session, channel_id: int, admin_ids: list) -> bool:
    channel = db.query(Channel).filter(Channel.id == channel_id).first()
    if not channel:
        return False

    owner = channel.owner
    if owner.telegram_id in admin_ids:
        return True

    now = datetime.utcnow()
    if channel.trial_until and channel.trial_until > now:
        return True
    if owner.subscription_until and owner.subscription_until > now:
        return True

    return False
# ============================================================
# ПРОВЕРКА ЛИМИТОВ ПО ТАРИФУ
# ============================================================

from config.settings import SUBSCRIPTION_PRICES, ADMIN_IDS


def get_user_plan(user) -> dict:
    """Возвращает лимиты тарифа юзера. По умолчанию — start."""
    plan_key = user.subscription_plan or "start"
    return SUBSCRIPTION_PRICES.get(plan_key, SUBSCRIPTION_PRICES["start"])


def can_add_channel(db: Session, user) -> tuple[bool, str]:
    """Проверяет лимит каналов. Возвращает (можно, сообщение)."""
    if user.telegram_id in ADMIN_IDS:
        return True, ""

    plan = get_user_plan(user)
    max_channels = plan.get("channels", 1)
    current = len(get_user_channels(db, user.telegram_id))

    if current >= max_channels:
        return False, (
            f"❌ Лимит каналов для тарифа «{plan['name']}» — {max_channels}.\n"
            f"Повысьте тариф в Mini App → Тарифы."
        )
    return True, ""


def can_publish_post(db: Session, channel) -> tuple[bool, str]:
    """Проверяет лимит постов/день для канала."""
    owner = channel.owner
    if owner.telegram_id in ADMIN_IDS:
        return True, ""

    plan = get_user_plan(owner)
    max_posts = plan.get("posts_per_day", 5)

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    posts_today = db.query(Post).filter(
        Post.channel_id == channel.id,
        Post.published_time >= today_start,
        Post.status == "published",
    ).count()

    if posts_today >= max_posts:
        return False, f"Лимит постов/день ({max_posts}) для тарифа «{plan['name']}»"
    return True, ""


def can_use_feature(user, feature: str) -> bool:
    """Проверяет доступ к фиче: moderation, custom_prompt, model_120b, analytics, priority_support."""
    if user.telegram_id in ADMIN_IDS:
        return True
    plan = get_user_plan(user)
    return bool(plan.get(feature, False))


def can_use_model(user, model: str) -> bool:
    """Проверяет доступ к модели (20b / 120b)."""
    if user.telegram_id in ADMIN_IDS:
        return True
    plan = get_user_plan(user)
    allowed = plan.get("models", [])
    return model in allowed


def can_add_team_member(db: Session, user) -> tuple[bool, str]:
    """Проверяет лимит участников команды (для будущего командного доступа)."""
    if user.telegram_id in ADMIN_IDS:
        return True, ""
    plan = get_user_plan(user)
    max_team = plan.get("team_size", 0)
    if max_team == 0:
        return False, "❌ Командный доступ недоступен на вашем тарифе."
    # TODO: подсчёт team_members, когда будет таблица
    return True, ""

# ============================================================
# КОМАНДНЫЙ ДОСТУП (team_members)
# ============================================================

import secrets
from database.models import TeamMember


# Дефолтные права для editor
DEFAULT_EDITOR_PERMISSIONS = {
    "change_prompt": True,
    "moderate_posts": True,
    "manage_rss": True,
    "change_interval": True,
}


def create_invite_token() -> str:
    """Генерирует уникальный токен для инвайт-ссылки."""
    return secrets.token_urlsafe(16)


def invite_team_member(db: Session, owner_id: int) -> TeamMember | None:
    """
    Создаёт приглашение (TeamMember без member_id).
    Возвращает объект с invite_token.
    """
    # Проверяем, что нет висящего приглашения
    existing = db.query(TeamMember).filter(
        TeamMember.owner_id == owner_id,
        TeamMember.member_id.is_(None),
        TeamMember.is_active == True,
    ).first()

    if existing:
        return existing  # уже есть висящее приглашение — используем его

    token = create_invite_token()
    member = TeamMember(
        owner_id=owner_id,
        member_id=None,  # ещё не принял
        role="editor",
        permissions=DEFAULT_EDITOR_PERMISSIONS.copy(),
        invite_token=token,
        is_active=True,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def accept_invite(db: Session, token: str, member_id: int) -> TeamMember | None:
    """Принимает приглашение: привязывает member_id к TeamMember по токену."""
    member = db.query(TeamMember).filter(
        TeamMember.invite_token == token,
        TeamMember.is_active == True,
    ).first()

    if not member:
        return None

    if member.member_id is not None:
        return None  # уже принят

    # Проверка: member_id не уже в этой команде
    existing = db.query(TeamMember).filter(
        TeamMember.owner_id == member.owner_id,
        TeamMember.member_id == member_id,
        TeamMember.is_active == True,
    ).first()
    if existing:
        return None

    member.member_id = member_id
    member.accepted_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    return member


def get_team_members(db: Session, owner_id: int) -> list[TeamMember]:
    """Возвращает всех принятых участников команды владельца."""
    return db.query(TeamMember).filter(
        TeamMember.owner_id == owner_id,
        TeamMember.member_id.isnot(None),
        TeamMember.is_active == True,
    ).all()


def get_member_role(db: Session, owner_id: int, member_id: int) -> TeamMember | None:
    """Возвращает запись TeamMember, если юзер — участник команды владельца."""
    return db.query(TeamMember).filter(
        TeamMember.owner_id == owner_id,
        TeamMember.member_id == member_id,
        TeamMember.is_active == True,
    ).first()


def get_owned_team(db: Session, member_id: int) -> TeamMember | None:
    """Возвращает запись TeamMember, если юзер — чей-то участник (не owner)."""
    return db.query(TeamMember).filter(
        TeamMember.member_id == member_id,
        TeamMember.is_active == True,
    ).first()


def update_member_permission(
    db: Session, team_id: int, permission: str, value: bool
) -> TeamMember | None:
    """Меняет одно право у участника команды."""
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()
    if not member:
        return None

    perms = dict(member.permissions or {})
    perms[permission] = value
    member.permissions = perms
    db.commit()
    db.refresh(member)
    return member


def remove_team_member(db: Session, team_id: int) -> bool:
    """Деактивирует участника команды (не удаляет)."""
    member = db.query(TeamMember).filter(TeamMember.id == team_id).first()
    if not member:
        return False
    member.is_active = False
    db.commit()
    return True


def count_active_team(db: Session, owner_id: int) -> int:
    """Сколько активных участников у владельца (принятых)."""
    return db.query(TeamMember).filter(
        TeamMember.owner_id == owner_id,
        TeamMember.member_id.isnot(None),
        TeamMember.is_active == True,
    ).count()


def can_use_permission(db: Session, user_id: int, permission: str) -> bool:
    """
    Проверяет: есть ли у юзера право permission.

    Логика:
    - Если юзер — admin (в ADMIN_IDS) → True.
    - Если юзер — owner (не в команде) → True (у него все права).
    - Если юзер — member (editor) → смотрим его permissions.
    - Иначе → False.
    """
    from config.settings import ADMIN_IDS

    if user_id in ADMIN_IDS:
        return True

    team = get_owned_team(db, user_id)
    if not team:
        # Не участник команды — значит владелец или чужой.
        # Если у юзера есть свои каналы — он owner.
        # TODO: уточнить логику
        return True  # пока разрешаем всем, кроме участников

    perms = team.permissions or {}
    return bool(perms.get(permission, False))


def is_team_owner(db: Session, user_id: int) -> bool:
    """Проверяет, есть ли у юзера свои каналы (значит он owner, не editor)."""
    count = db.query(Channel).filter(Channel.owner_id == user_id).count()
    return count > 0

def get_effective_owner_id(db: Session, user_id: int) -> int:
    """
    Возвращает effective owner_id:
    - Если юзер — editor (участник команды) → owner_id его владельца.
    - Если юзер — owner → свой user_id.
    """
    team = get_owned_team(db, user_id)
    if team:
        return team.owner_id  # каналы владельца
    return user_id  # свои каналы

def check_permission(db: Session, user_id: int, permission: str) -> bool:
    """
    Проверяет право:
    - Owner → True всегда.
    - Editor → по своему permissions.
    - Admin → True всегда.
    """
    from config.settings import ADMIN_IDS
    
    if user_id in ADMIN_IDS:
        return True
    
    team = get_owned_team(db, user_id)
    if not team:
        # Не editor → owner, права полные
        return True
    
    perms = team.permissions or {}
    return bool(perms.get(permission, False))
# ============================================================
# ДОКУПКА МЕСТ (extra_seats)
# ============================================================

def get_team_limit(db: Session, owner_id: int) -> int:
    """
    Возвращает лимит команды для владельца:
    base (по тарифу) + extra_seats, максимум 10.
    """
    from config.settings import SUBSCRIPTION_PRICES, ADMIN_IDS

    if owner_id in ADMIN_IDS:
        return 999  # админ — безлимит

    user = db.query(User).filter(User.telegram_id == owner_id).first()
    if not user:
        return 0

    plan = user.subscription_plan or "start"
    plan_data = SUBSCRIPTION_PRICES.get(plan, SUBSCRIPTION_PRICES["start"])
    base = plan_data.get("team_size", 0)
    extra = user.extra_seats or 0

    return min(base + extra, 10)  # максимум 10


def can_buy_extra_seat(db: Session, owner_id: int) -> bool:
    """Можно ли ещё докупить место (лимит 10)."""
    current = get_team_limit(db, owner_id)
    return current < 10


def add_extra_seat(db: Session, owner_id: int) -> int:
    """
    Увеличивает extra_seats на 1 (до лимита 10).
    Возвращает новое значение extra_seats, или 0 если максимум.
    """
    user = db.query(User).filter(User.telegram_id == owner_id).first()
    if not user:
        return 0

    current_total = get_team_limit(db, owner_id)
    if current_total >= 10:
        return 0  # максимум достигнут

    user.extra_seats = (user.extra_seats or 0) + 1
    db.commit()
    db.refresh(user)
    return user.extra_seats


def reset_extra_seats(db: Session, owner_id: int) -> int:
    """Сбрасывает extra_seats (при истечении Бизнес-подписки)."""
    user = db.query(User).filter(User.telegram_id == owner_id).first()
    if user:
        user.extra_seats = 0
        db.commit()
    return 0

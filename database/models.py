from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime,
    ForeignKey, Text, JSON, BigInteger
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from config.settings import DATABASE_URL, GRAMKIT_DATABASE_URL, DEFAULT_AI_MODEL
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import text
from sqlalchemy import UniqueConstraint

Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

# Отдельный engine для чтения из gramkit (subscriptions)
gramkit_engine = create_engine(GRAMKIT_DATABASE_URL)
GramkitSessionLocal = sessionmaker(bind=gramkit_engine)

class User(Base):
    __tablename__ = "users"
    # ⚠️ users.id в БД — UUID (управляется gramkit).
    # Бот НЕ создаёт эту таблицу, только читает/обновляет по telegram_id.
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True,
            server_default=text("gen_random_uuid()"))
    telegram_id = Column(BigInteger, unique=True, index=True)
    username = Column(String)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    subscription_until = Column(DateTime(timezone=True), nullable=True)
    trial_used = Column(Boolean, default=False)
    subscription_plan = Column(String, nullable=True)
    extra_seats = Column(Integer, default=0, server_default='0')
    user_type = Column(String, nullable=False, default='REGISTERED', server_default='REGISTERED')

    channels = relationship(
        "Channel",
        back_populates="owner",
        primaryjoin="foreign(Channel.owner_id) == User.telegram_id",
    )

    # Команда: связь как owner (кто пригласил)
    team_as_owner = relationship(
        "TeamMember",
        foreign_keys="TeamMember.owner_id",
        primaryjoin="foreign(TeamMember.owner_id) == User.telegram_id",
        viewonly=True,
    )

    # Команда: связь как member (кого пригласили)
    team_as_member = relationship(
        "TeamMember",
        foreign_keys="TeamMember.member_id",
        primaryjoin="foreign(TeamMember.member_id) == User.telegram_id",
        viewonly=True,
    )


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)          # ← ФИКС: Integer (в БД integer)
    channel_id = Column(String, unique=True)
    channel_name = Column(String)
    topic = Column(String)
    owner_id = Column(BigInteger, index=True)       # BigInteger — как telegram_id
    is_active = Column(Boolean, default=True)
    post_interval = Column(Integer, default=7200)
    moderation_mode = Column(Boolean, default=False)
    ai_model = Column(String, default=DEFAULT_AI_MODEL)
    ai_prompt = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    settings = Column(JSON, default={})
    trial_until = Column(DateTime, nullable=True)
    trial_notified = Column(Boolean, default=False)

    owner = relationship(
        "User",
        back_populates="channels",
        primaryjoin="foreign(Channel.owner_id) == User.telegram_id",
    )
    rss_sources = relationship("RSSSource", back_populates="channel")
    posts = relationship("Post", back_populates="channel")


class RSSSource(Base):
    __tablename__ = "rss_sources"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    url = Column(String)
    name = Column(String)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime)
    last_guid = Column(String)
    error_count = Column(Integer, default=0)
    source_type = Column(String, default="news")

    channel = relationship("Channel", back_populates="rss_sources")


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    source_url = Column(String)
    original_title = Column(String)
    original_content = Column(Text)
    processed_content = Column(Text)
    media_urls = Column(JSON, default=[])
    status = Column(String, default="pending")
    scheduled_time = Column(DateTime)
    published_time = Column(DateTime)
    message_id = Column(Integer)
    hash = Column(String, index=True, nullable=True)

    channel = relationship("Channel", back_populates="posts")

class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    owner_id = Column(BigInteger, index=True)         # владелец (telegram_id)
    member_id = Column(BigInteger, index=True)        # участник (telegram_id)
    role = Column(String, default="editor")           # editor | admin
    permissions = Column(JSON, default={})            # {"change_prompt": True, ...}
    invite_token = Column(String, unique=True)
    invited_at = Column(DateTime, default=datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

class PostMetric(Base):
    __tablename__ = "post_metrics"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id"), index=True)
    channel_id = Column(Integer, index=True)
    
    # Реакции (JSON: {"👍": 5, "❤️": 3, "🔥": 10})
    reactions = Column(JSON, default={})
    reactions_total = Column(Integer, default=0)
    
    # Форварды
    forwards = Column(Integer, default=0)
    
    # Когда обновлено
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChannelStat(Base):
    __tablename__ = "channel_stats"
    __table_args__ = (
        UniqueConstraint('channel_id', 'date', name='uix_channel_date'),
        {'extend_existing': True},
    )

    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, index=True)
    date = Column(DateTime, index=True)
    member_count = Column(Integer, default=0)
    posts_count = Column(Integer, default=0)
    reactions_total = Column(Integer, default=0)

class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    inviter_id = Column(BigInteger, index=True)   # кто пригласил (telegram_id)
    invited_id = Column(BigInteger, unique=True)  # кого пригласили (telegram_id)
    invited_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)     # подписка активна?

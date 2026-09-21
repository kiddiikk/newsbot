from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime,
    ForeignKey, Text, JSON, BigInteger
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
from config.settings import DATABASE_URL, DEFAULT_AI_MODEL

Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"
    # ⚠️ users.id в БД — UUID (управляется gramkit).
    # Бот НЕ создаёт эту таблицу, только читает/обновляет по telegram_id.
    __table_args__ = {'extend_existing': True}

    id = Column(UUID(as_uuid=True), primary_key=True)  # UUID, не Integer — иначе маппинг сломается
    telegram_id = Column(BigInteger, unique=True, index=True)  # BigInteger, т.к. ID Telegram > 2^31
    username = Column(String)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    subscription_until = Column(DateTime(timezone=True), nullable=True)
    trial_used = Column(Boolean, default=False)
    subscription_plan = Column(String, nullable=True)

    # ✅ primaryjoin обязателен с обеих сторон, т.к. FK убран
    channels = relationship(
        "Channel",
        back_populates="owner",
        primaryjoin="foreign(Channel.owner_id) == User.telegram_id",
    )


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True)
    channel_id = Column(String, unique=True)
    channel_name = Column(String)
    topic = Column(String)
    # ⚠️ FK убран: users.id в БД — UUID, несовместим с Integer/BigInteger
    owner_id = Column(BigInteger, index=True)  # BigInteger — как telegram_id
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

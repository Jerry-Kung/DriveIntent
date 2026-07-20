from datetime import datetime

from sqlalchemy import (JSON, DateTime, ForeignKey, Index, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Video(Base):
    __tablename__ = "video"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_video_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    author_name: Mapped[str | None] = mapped_column(String(255))
    account_type: Mapped[str | None] = mapped_column(String(32))
    publish_time: Mapped[datetime | None] = mapped_column(DateTime)
    transcript: Mapped[str | None] = mapped_column(Text)
    preset_brand: Mapped[str | None] = mapped_column(String(64))
    preset_model: Mapped[str | None] = mapped_column(String(64))
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class PlatformUser(Base):
    __tablename__ = "platform_user"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_user_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    nickname: Mapped[str] = mapped_column(String(255), default="")
    avatar_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(64))
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class Comment(Base):
    __tablename__ = "comment"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_comment_ext"),
        Index("ix_comment_video", "video_id"),
        Index("ix_comment_user", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_user.id"))
    content: Mapped[str] = mapped_column(Text)
    comment_time: Mapped[datetime | None] = mapped_column(DateTime)
    like_count: Mapped[int | None] = mapped_column()
    reply_count: Mapped[int | None] = mapped_column()
    is_reply: Mapped[bool | None] = mapped_column()
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)

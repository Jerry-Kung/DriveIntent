from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Lead(Base):
    __tablename__ = "lead"
    __table_args__ = (Index("ix_lead_user", "user_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_user.id"))
    grade: Mapped[str] = mapped_column(String(4))            # H/A/B/C
    is_valid: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    target_brands: Mapped[list | None] = mapped_column(JSON)
    target_models: Mapped[list | None] = mapped_column(JSON)
    # V1.8.0：意向车型识别与分类（阶段二输出，不参与评级；供下游节点使用）
    intent_models: Mapped[list | None] = mapped_column(JSON)
    intent_model_category: Mapped[str | None] = mapped_column(String(4))
    summary: Mapped[str] = mapped_column(Text, default="")
    purchase_stage: Mapped[str | None] = mapped_column(String(64))
    core_needs: Mapped[list | None] = mapped_column(JSON)
    main_concerns: Mapped[list | None] = mapped_column(JSON)
    purchase_time: Mapped[str | None] = mapped_column(String(64))
    usage_scenario: Mapped[str | None] = mapped_column(String(255))
    entry_point: Mapped[str | None] = mapped_column(Text)
    verification_questions: Mapped[list | None] = mapped_column(JSON)
    evidence: Mapped[list | None] = mapped_column(JSON)      # [{comment_id, content}]
    confidence: Mapped[float | None] = mapped_column(Float)
    skill_version: Mapped[str] = mapped_column(String(16), default="")
    review_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    review_tags: Mapped[list | None] = mapped_column(JSON)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

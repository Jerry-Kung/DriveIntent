from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalysisTask(Base):
    __tablename__ = "analysis_task"
    __table_args__ = (
        UniqueConstraint("task_type", "target_type", "target_id",
                         "skill_version", name="uq_task_idem"),
        Index("ix_task_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    skill_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    payload: Mapped[dict | None] = mapped_column(JSON)
    attempt_count: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_result"
    __table_args__ = (
        Index("ix_result_target", "target_type", "target_id", "skill_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    skill_id: Mapped[str] = mapped_column(String(64))
    skill_version: Mapped[str] = mapped_column(String(16))
    model_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(16), default="success")
    result: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class LlmCallLog(Base):
    __tablename__ = "llm_call_log"
    __table_args__ = (Index("ix_llm_call_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String(64), default="")
    skill_version: Mapped[str] = mapped_column(String(16), default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    input_digest: Mapped[str | None] = mapped_column(Text)
    output_text: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)

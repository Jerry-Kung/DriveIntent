from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApiJob(Base):
    __tablename__ = "api_job"
    __table_args__ = (
        Index("ix_api_job_status_order", "status", "attempt_count",
              "created_at"),
        Index("ix_api_job_finished", "finished_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # deferred：payload 可达 MB 级（含 base64 截图），状态轮询/认领查询
    # 不搬运该列，worker 访问属性时才按需加载
    request_payload: Mapped[dict | None] = mapped_column(JSON, deferred=True)
    result: Mapped[dict | None] = mapped_column(JSON)
    # V1.7.3：每账号结果的真实内部 HABC 等级，与 result.results[] 按下标一一
    # 对应。对外 intent_level_code 已变为多对一（H/A→high、B→medium、C→low），
    # 无法据此反推内部等级；本列供内部审计/统计读取，不进对外契约。历史数据为
    # NULL，审计回退按 intent_level_code 反推（旧映射一对一，反推仍准确）。
    lead_grades: Mapped[list | None] = mapped_column(JSON)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

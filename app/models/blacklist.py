from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BlacklistedUser(Base):
    """用户黑名单记录：被加入黑名单的抖音用户（按 douyin_id 唯一识别）。

    供（a）API Worker 在画像分析前做零 LLM 匹配短路，以及
    （b）黑名单管理页使用。nickname/remark 为人工备注，可空。
    """

    __tablename__ = "blacklisted_user"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    douyin_id: Mapped[str] = mapped_column(String(64), unique=True)
    nickname: Mapped[str | None] = mapped_column(String(255))
    remark: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)

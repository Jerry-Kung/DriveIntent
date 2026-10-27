"""V1.10.1 线索汇总表：把 api_job.result 大列里的账号级结果物化到一行一账号。

背景：线索列表页原先在查询期展开 api_job.result（平均 50 KB/作业、全量
346 MB），导致首页 8s、等级筛选 140s。本表把列表所需字段在作业终态时落成
普通列，列表与筛选退化为带索引的普通 SQL（实测等级筛选 0.03s、任意翻页
0.2s 内）。

写入时机：作业终态（含成功与终态失败）时，与终态落库同一事务写入；
历史数据由 scripts/backfill_lead_records.py 回填。本表是 api_job.result 的
派生视图，可随时整表重建，唯一真相仍在 api_job.result。

排序口径与旧 JSON 展开实现一致：finished_at 倒序、作业 id 倒序、作业内
按账号下标升序。列表索引按该顺序声明方向（MySQL 8 降序索引可直接用于
翻页；SQLite 忽略方向，不影响正确性）。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LeadRecord(Base):
    __tablename__ = "lead_record"
    __table_args__ = (
        # 按等级筛选（列表等级下拉、CSV 导出）
        Index("ix_lead_record_grade", "grade", "finished_at", "job_id", "idx"),
    )

    # 来源作业与账号下标（对应 api_job.id / result.results[] 位置）。
    # 二者构成主键：同作业同下标只有一行，重跑写入天然幂等。
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_uid: Mapped[str] = mapped_column(String(256), default="")
    # 内部真实 HABC 等级（口径同 services.lead_results.grade_of）
    grade: Mapped[str] = mapped_column(String(4))
    value_score: Mapped[int | None] = mapped_column(Integer)
    is_car_owner: Mapped[bool | None] = mapped_column()
    has_purchase_intent: Mapped[bool | None] = mapped_column()
    intent_models: Mapped[list | None] = mapped_column(JSON)
    intent_model_category: Mapped[str | None] = mapped_column(String(4))
    profile_summary: Mapped[str] = mapped_column(Text, default="")
    profile_tags: Mapped[list | None] = mapped_column(JSON)
    analysis: Mapped[str] = mapped_column(Text, default="")
    processed_at: Mapped[str | None] = mapped_column(String(64))
    # 该账号自身的处理失败信息；列表不展示，CSV 与详情页使用
    error: Mapped[str | None] = mapped_column(Text)
    # 冗余自作业：列表排序与时间筛选均按它进行
    finished_at: Mapped[datetime] = mapped_column(DateTime)


# 列表主查询索引：与 ORDER BY finished_at DESC, job_id DESC, idx ASC 一致。
# 同 finished_at 的作业按 id 倒序、单作业内按下标升序，与旧 JSON 展开实现
# 的逐作业顺序完全对应，任意页的切分点与旧版一致。方向显式声明（MySQL 8
# 建为降序索引，翻页无需 filesort；SQLite 忽略方向但不影响正确性）。
# 在类外声明是因为需要引用列对象，类体内列尚未绑定。
Index("ix_lead_record_order",
      LeadRecord.finished_at.desc(), LeadRecord.job_id.desc(),
      LeadRecord.idx.asc())

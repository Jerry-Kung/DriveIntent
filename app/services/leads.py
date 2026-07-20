import csv
import io

from sqlalchemy.orm import Session

from app.models import Lead, PlatformUser
from app.schemas.skills import UserLeadResult


def upsert_lead(session: Session, user_id: int, result: UserLeadResult,
                evidence_comments: list[dict], skill_version: str) -> Lead:
    lead = session.query(Lead).filter_by(user_id=user_id).first()
    if lead is None:
        lead = Lead(user_id=user_id, grade=result.lead_grade)
        session.add(lead)
    lead.grade = result.lead_grade
    lead.is_valid = result.is_valid_lead
    lead.summary = result.lead_summary
    lead.purchase_stage = result.purchase_stage
    lead.target_brands = result.target_brands
    lead.target_models = result.target_models
    lead.core_needs = result.core_needs
    lead.main_concerns = result.main_concerns
    lead.purchase_time = result.purchase_time
    lead.usage_scenario = result.usage_scenario
    lead.entry_point = result.recommended_entry_point
    lead.verification_questions = result.verification_questions
    lead.evidence = evidence_comments
    lead.confidence = result.confidence
    lead.skill_version = skill_version
    session.commit()
    return lead


GRADE_ORDER = {"H": 0, "A": 1, "B": 2, "C": 3}


def query_leads(session: Session, *, grade: str | None = None,
                brand: str | None = None, model: str | None = None,
                review_status: str | None = None) -> list[Lead]:
    q = session.query(Lead)
    if grade:
        q = q.filter(Lead.grade == grade)
    if review_status:
        q = q.filter(Lead.review_status == review_status)
    leads = q.all()
    if brand:
        leads = [l for l in leads if brand in (l.target_brands or [])]
    if model:
        leads = [l for l in leads if model in (l.target_models or [])]
    return sorted(leads, key=lambda l: (GRADE_ORDER.get(l.grade, 9),
                                        -(l.confidence or 0)))


def lead_to_dict(session: Session, lead: Lead) -> dict:
    user = session.get(PlatformUser, lead.user_id)
    return {
        "id": lead.id, "nickname": user.nickname if user else "",
        "platform": user.platform if user else "", "grade": lead.grade,
        "target_brands": lead.target_brands or [],
        "target_models": lead.target_models or [],
        "summary": lead.summary, "purchase_stage": lead.purchase_stage,
        "core_needs": lead.core_needs or [],
        "main_concerns": lead.main_concerns or [],
        "purchase_time": lead.purchase_time,
        "usage_scenario": lead.usage_scenario,
        "entry_point": lead.entry_point,
        "verification_questions": lead.verification_questions or [],
        "evidence": lead.evidence or [], "confidence": lead.confidence,
        "review_status": lead.review_status,
        "review_tags": lead.review_tags or [],
        "review_note": lead.review_note,
        "created_at": lead.created_at.isoformat(),
    }


def _csv_safe(value):
    """防止 Excel/表格软件将以 =、+、-、@ 开头的单元格当公式执行。"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def leads_to_csv(session: Session, leads: list[Lead]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["昵称", "平台", "等级", "品牌", "车型", "摘要",
                     "核心需求", "主要顾虑", "购车时间", "销售切入点",
                     "置信度", "审核状态", "分析时间"])
    for lead in leads:
        d = lead_to_dict(session, lead)
        writer.writerow([
            _csv_safe(d["nickname"]), _csv_safe(d["platform"]),
            _csv_safe(d["grade"]),
            _csv_safe("/".join(d["target_brands"])),
            _csv_safe("/".join(d["target_models"])),
            _csv_safe(d["summary"]), _csv_safe("/".join(d["core_needs"])),
            _csv_safe("/".join(d["main_concerns"])),
            _csv_safe(d["purchase_time"] or ""),
            _csv_safe(d["entry_point"] or ""), d["confidence"],
            _csv_safe(d["review_status"]), d["created_at"]])
    return buf.getvalue()

from sqlalchemy.orm import Session

from app.models import Lead
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

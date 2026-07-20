from sqlalchemy.orm import Session

from app.models import AnalysisResult


def save_result(session: Session, *, target_type: str, target_id: str,
                skill_id: str, skill_version: str, result: dict,
                confidence: float | None = None, model_name: str = "",
                prompt_version: str = "") -> AnalysisResult:
    row = AnalysisResult(target_type=target_type, target_id=target_id,
                         skill_id=skill_id, skill_version=skill_version,
                         model_name=model_name, prompt_version=prompt_version,
                         status="success", result=result,
                         confidence=confidence)
    session.add(row)
    session.commit()
    return row


def get_current_result(session: Session, *, target_type: str, target_id: str,
                       skill_id: str,
                       skill_version: str) -> AnalysisResult | None:
    return (session.query(AnalysisResult)
            .filter_by(target_type=target_type, target_id=target_id,
                       skill_id=skill_id, skill_version=skill_version,
                       status="success")
            .order_by(AnalysisResult.id.desc())
            .first())

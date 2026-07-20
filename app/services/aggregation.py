from sqlalchemy.orm import Session

from app.models import AnalysisResult, Comment, PlatformUser
from app.services.results import get_current_result
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL)


def _valid_screenings(session: Session) -> list[AnalysisResult]:
    rows = (session.query(AnalysisResult)
            .filter_by(target_type="comment",
                       skill_id=COMMENT_SCREENING_SKILL,
                       skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                       status="success")
            .order_by(AnalysisResult.id).all())
    # 同评论多条结果取最新
    latest: dict[str, AnalysisResult] = {}
    for r in rows:
        latest[r.target_id] = r
    return [r for r in latest.values()
            if r.result.get("is_purchase_related")
            and not r.result.get("is_suspected_marketing")]


def candidate_user_ids(session: Session) -> list[int]:
    valid = _valid_screenings(session)
    comment_ids = [int(r.target_id) for r in valid]
    if not comment_ids:
        return []
    rows = (session.query(Comment.user_id)
            .filter(Comment.id.in_(comment_ids))
            .distinct().order_by(Comment.user_id).all())
    return [uid for (uid,) in rows]


def build_user_evidence(session: Session, user_id: int) -> dict:
    user = session.get(PlatformUser, user_id)
    valid = {int(r.target_id): r.result for r in _valid_screenings(session)}
    comments = (session.query(Comment)
                .filter(Comment.user_id == user_id,
                        Comment.id.in_(list(valid.keys())))
                .order_by(Comment.comment_time).all())

    items, brands, models = [], [], []
    high_count = 0
    for c in comments:
        screening = valid[c.id]
        ctx = get_current_result(
            session, target_type="video", target_id=str(c.video_id),
            skill_id=VIDEO_CONTEXT_SKILL,
            skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
        items.append({
            "comment_id": str(c.id), "content": c.content,
            "comment_time": (c.comment_time.isoformat()
                             if c.comment_time else None),
            "screening": screening,
            "video_context": ctx.result if ctx else None})
        if screening.get("intent_strength") == "high":
            high_count += 1
        for key, acc in (("target_brand", brands), ("target_model", models)):
            val = screening.get(key)
            if val and val not in acc:
                acc.append(val)

    times = [c.comment_time for c in comments if c.comment_time]
    return {
        "user": {"nickname": user.nickname, "platform": user.platform},
        "comments": items,
        "statistics": {
            "valid_comment_count": len(items),
            "high_intent_comment_count": high_count,
            "related_brands": brands, "related_models": models,
            "first_comment_time": min(times).isoformat() if times else None,
            "last_comment_time": max(times).isoformat() if times else None,
        },
    }

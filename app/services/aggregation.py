from sqlalchemy.orm import Session

from app.models import AnalysisResult, Comment, PlatformUser
from app.services.results import get_current_result
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL)


def _valid_screenings(session: Session,
                      comment_ids: list[int] | None = None) -> list[AnalysisResult]:
    query = (session.query(AnalysisResult)
            .filter_by(target_type="comment",
                       skill_id=COMMENT_SCREENING_SKILL,
                       skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                       status="success"))
    if comment_ids:
        query = query.filter(AnalysisResult.target_id.in_([str(i) for i in comment_ids]))
    rows = query.order_by(AnalysisResult.id).all()
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
    if user is None:
        raise ValueError(f"用户不存在: {user_id}")

    # Get user's comment IDs first
    user_comment_ids = [c[0] for c in session.query(Comment.id)
                        .filter(Comment.user_id == user_id).all()]
    if not user_comment_ids:
        return {
            "user": {"nickname": user.nickname, "platform": user.platform},
            "comments": [],
            "statistics": {
                "valid_comment_count": 0,
                "high_intent_comment_count": 0,
                "related_brands": [], "related_models": [],
                "first_comment_time": None,
                "last_comment_time": None,
            },
        }

    # Get valid screenings scoped to this user's comments
    valid = {int(r.target_id): r.result
             for r in _valid_screenings(session, comment_ids=user_comment_ids)}

    comments = (session.query(Comment)
                .filter(Comment.user_id == user_id,
                        Comment.id.in_(list(valid.keys())))
                .order_by(Comment.comment_time).all())

    items, brands, models = [], [], []
    high_count = 0
    ctx_cache: dict[int, AnalysisResult | None] = {}

    for c in comments:
        screening = valid[c.id]

        # Use cache for video context
        if c.video_id not in ctx_cache:
            ctx_cache[c.video_id] = get_current_result(
                session, target_type="video", target_id=str(c.video_id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])

        ctx = ctx_cache[c.video_id]

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

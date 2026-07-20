from app.models import Comment, PlatformUser, Video
from app.services.aggregation import build_user_evidence, candidate_user_ids
from app.services.results import save_result
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL)


def _screening(cid, purchase, marketing=False, strength="high"):
    return {"comment_id": str(cid), "is_meaningful": True,
            "is_automotive_related": True, "is_purchase_related": purchase,
            "is_suspected_marketing": marketing,
            "intent_signals": ["price_inquiry"] if purchase else [],
            "target_brand": "坦克", "target_model": "坦克300",
            "intent_strength": strength if purchase else "none",
            "reason": "r", "confidence": 0.9}


def _setup(session):
    v = Video(platform="douyin", external_id="v1", title="t")
    u1 = PlatformUser(platform="douyin", external_id="u1", nickname="意向用户")
    u2 = PlatformUser(platform="douyin", external_id="u2", nickname="路人")
    session.add_all([v, u1, u2]); session.flush()
    c1 = Comment(platform="douyin", external_id="c1", video_id=v.id,
                 user_id=u1.id, content="落地多少钱")
    c2 = Comment(platform="douyin", external_id="c2", video_id=v.id,
                 user_id=u2.id, content="厉害")
    session.add_all([c1, c2]); session.flush()
    save_result(session, target_type="video", target_id=str(v.id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result={"brand": "坦克", "model": "坦克300"})
    sv = SKILL_VERSIONS[COMMENT_SCREENING_SKILL]
    save_result(session, target_type="comment", target_id=str(c1.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c1.id, purchase=True))
    save_result(session, target_type="comment", target_id=str(c2.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c2.id, purchase=False))
    return v, u1, u2, c1, c2


def test_candidate_user_ids(session):
    _, u1, u2, _, _ = _setup(session)
    ids = candidate_user_ids(session)
    assert ids == [u1.id]                    # u2 无购车相关评论，不入候选


def test_build_user_evidence(session):
    v, u1, _, c1, _ = _setup(session)
    ev = build_user_evidence(session, u1.id)
    assert ev["user"]["nickname"] == "意向用户"
    assert len(ev["comments"]) == 1
    assert ev["comments"][0]["comment_id"] == str(c1.id)
    assert ev["comments"][0]["video_context"]["brand"] == "坦克"
    assert ev["statistics"]["valid_comment_count"] == 1
    assert ev["statistics"]["high_intent_comment_count"] == 1
    assert ev["statistics"]["related_brands"] == ["坦克"]


def test_valid_screenings_latest_true_wins(session):
    """Test that when multiple results exist for same comment, latest wins.
    First result: not purchase-related, Second: purchase-related → user included."""
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="user")
    session.add_all([v, u]); session.flush()

    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="test")
    session.add(c); session.flush()

    sv = SKILL_VERSIONS[COMMENT_SCREENING_SKILL]

    # First result: not purchase-related
    save_result(session, target_type="comment", target_id=str(c.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c.id, purchase=False))

    # Second result: purchase-related (latest should win)
    save_result(session, target_type="comment", target_id=str(c.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c.id, purchase=True))

    # Since latest (purchase=True) wins, user should be in candidate list
    ids = candidate_user_ids(session)
    assert ids == [u.id]


def test_valid_screenings_latest_false_wins(session):
    """Test that when multiple results exist for same comment, latest wins.
    First result: purchase-related, Second: not purchase-related → user excluded."""
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="user")
    session.add_all([v, u]); session.flush()

    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="test")
    session.add(c); session.flush()

    sv = SKILL_VERSIONS[COMMENT_SCREENING_SKILL]

    # First result: purchase-related
    save_result(session, target_type="comment", target_id=str(c.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c.id, purchase=True))

    # Second result: not purchase-related (latest should win)
    save_result(session, target_type="comment", target_id=str(c.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c.id, purchase=False))

    # Since latest (purchase=False) wins, user should NOT be in candidate list
    ids = candidate_user_ids(session)
    assert ids == []

import json

import pytest
from pydantic import ValidationError


def test_v16_user_filter_result_defaults():
    from app.schemas.skills import UserFilterResult
    r = UserFilterResult()
    assert r.filtered is False
    assert r.filter_category is None
    assert r.filter_reason is None
    assert r.is_car_owner is False
    assert r.has_purchase_intent is False
    assert r.evidence_comment_ids == []
    assert r.profile_tags == []
    assert r.confidence == 0.0


def test_v16_user_filter_result_accepts_all_categories():
    from app.schemas.skills import UserFilterResult
    for cat in ("already_purchased", "promoting_others", "proxy_inquiry",
                "marketing_suspect", "industry_professional", "other"):
        r = UserFilterResult(filtered=True, filter_category=cat,
                             filter_reason="理由")
        assert r.filter_category == cat


def test_v16_user_filter_result_rejects_invalid_category():
    from app.schemas.skills import UserFilterResult
    with pytest.raises(ValidationError):
        UserFilterResult(filtered=True, filter_category="not_a_category")


def test_v16_user_lead_result_has_filter_audit_fields():
    from app.schemas.skills import UserLeadResult
    r = UserLeadResult(lead_grade="C")
    assert r.filter_category is None
    assert r.filter_reason is None
    r2 = UserLeadResult(lead_grade="C", is_valid_lead=False,
                        filter_category="already_purchased",
                        filter_reason='评论"已提车"为已完成购买信号且无新购意向')
    assert r2.filter_category == "already_purchased"

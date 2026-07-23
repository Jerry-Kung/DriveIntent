import pytest
from pydantic import ValidationError

from app.api.schemas import (CommentScreeningRequest, ProfileAnalysisRequest,
                             ScreeningResult, ProfileResult)


def test_comment_request_parses_full_object():
    req = CommentScreeningRequest(comments=[{
        "comment_id": "cm_1",
        "video_title": "试驾体验",
        "video_author": "@老王说车",
        "video_author_fans": 2865000,
        "video_metrics": {"like_count": 1, "comment_count": 2,
                          "share_count": 3, "collect_count": 4},
        "comment_content": "这车不错",
        "comment_author": "用户_7823",
        "comment_author_uid": "MS4w",
        "comment_time": "2026-07-19T14:23:00+08:00",
        "comment_like_count": 234,
    }])
    assert req.comments[0].video_metrics.like_count == 1


def test_comment_request_missing_required_field():
    with pytest.raises(ValidationError):
        CommentScreeningRequest(comments=[{"comment_id": "x"}])


def test_account_screenshot_optional_empty():
    req = ProfileAnalysisRequest(accounts=[{
        "account_uid": "u1",
        "account_name": "用户",
        "account_homepage_screenshot": "",
        "comment_history": [],
    }])
    assert req.accounts[0].account_homepage_screenshot == ""


def test_screening_result_serialization():
    r = ScreeningResult(comment_id="cm_1", passed=True, filter_reason=None,
                        analysis="ok", processed_at="2026-07-19T15:30:00+08:00")
    d = r.model_dump()
    assert d["passed"] is True and d["filter_reason"] is None


def test_profile_result_serialization():
    r = ProfileResult(account_uid="u1", has_value=True, intent_level="高",
                      intent_level_code="high", value_score=92,
                      profile_tags=["已购车主"], profile_summary="...",
                      analysis="...", processed_at="2026-07-19T16:00:00+08:00")
    assert r.model_dump()["intent_level_code"] == "high"

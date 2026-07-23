from typing import Literal

from pydantic import BaseModel


class VideoContextResult(BaseModel):
    brand: str | None = None
    model: str | None = None
    content_type: str | None = None
    main_topics: list[str] = []
    target_audience: str | None = None
    competitor_models: list[str] = []
    commercial_context: str | None = None
    analysis_notes: str | None = None


class CommentScreeningItem(BaseModel):
    comment_id: str
    is_meaningful: bool = False
    is_automotive_related: bool = False
    is_purchase_related: bool = False
    is_suspected_marketing: bool = False
    intent_signals: list[str] = []
    target_brand: str | None = None
    target_model: str | None = None
    intent_strength: Literal["none", "low", "medium", "high"] = "none"
    reason: str = ""
    confidence: float = 0.0


class CommentScreeningResult(BaseModel):
    items: list[CommentScreeningItem]


class UserLeadResult(BaseModel):
    lead_grade: Literal["H", "A", "B", "C"]
    is_valid_lead: bool = True
    lead_summary: str = ""
    purchase_stage: str | None = None
    target_brands: list[str] = []
    target_models: list[str] = []
    core_needs: list[str] = []
    main_concerns: list[str] = []
    purchase_time: str | None = None
    usage_scenario: str | None = None
    recommended_entry_point: str | None = None
    verification_questions: list[str] = []
    evidence_comment_ids: list[str] = []
    profile_tags: list[str] = []
    profile_summary: str = ""
    analysis_text: str = ""
    confidence: float = 0.0

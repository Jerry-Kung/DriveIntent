import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import run_user_analysis
from tests.test_aggregation import _setup
from tests.test_user_filter import NOT_FILTERED_JSON

LEAD_JSON = json.dumps({
    "lead_grade": "H", "is_valid_lead": True,
    "lead_summary": "用户询问落地价，意向明确",
    "purchase_stage": "交易准备阶段",
    "target_brands": ["坦克"], "target_models": ["坦克300"],
    "core_needs": ["越野"], "main_concerns": ["落地价格"],
    "purchase_time": "近期", "usage_scenario": "越野出行",
    "recommended_entry_point": "从当地报价切入",
    "verification_questions": ["预算多少？"],
    "evidence_comment_ids": ["__CID__"],
    "confidence": 0.91}, ensure_ascii=False)

REVIEW_CONFIRMED_JSON = json.dumps({
    "review_action": "confirmed", "reviewed_grade": "H",
    "review_reason": "初步评级与该用户的实际销售价值一致，予以确认",
    "confidence": 0.9}, ensure_ascii=False)


async def test_run_user_analysis_creates_lead(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, LEAD_JSON.replace("__CID__", str(c1.id)))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    lead = session.query(Lead).one()
    assert lead.user_id == u1.id
    assert lead.grade == "H"
    assert lead.evidence == [{"comment_id": str(c1.id),
                              "content": "落地多少钱"}]
    assert lead.confidence == 0.91


async def test_run_user_analysis_upsert(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    cid = str(c1.id)
    provider.queue(NOT_FILTERED_JSON, LEAD_JSON.replace("__CID__", cid),
                   REVIEW_CONFIRMED_JSON,
                   NOT_FILTERED_JSON,
                   LEAD_JSON.replace("__CID__", cid)
                            .replace('"lead_grade": "H"',
                                     '"lead_grade": "A"'),
                   REVIEW_CONFIRMED_JSON)
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)
    await run_user_analysis(session, executor, u1.id)

    lead = session.query(Lead).one()          # 仍是一条
    assert lead.grade == "A"                  # 已更新


async def test_run_user_analysis_filters_hallucinated_evidence_ids(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    payload = json.loads(LEAD_JSON)
    payload["evidence_comment_ids"] = [str(c1.id), "999999"]
    provider.queue(NOT_FILTERED_JSON, json.dumps(payload, ensure_ascii=False))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    lead = session.query(Lead).one()
    assert lead.evidence == [{"comment_id": str(c1.id),
                              "content": "落地多少钱"}]


async def test_run_user_analysis_invalid_lead_creates_no_lead(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    payload = json.loads(LEAD_JSON)
    payload["lead_grade"] = "C"
    payload["is_valid_lead"] = False
    payload["evidence_comment_ids"] = [str(c1.id)]
    provider.queue(NOT_FILTERED_JSON, json.dumps(payload, ensure_ascii=False))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    assert session.query(Lead).count() == 0


async def test_run_user_analysis_valid_lead_all_evidence_hallucinated_creates_no_lead(
        session):
    from app.models import AnalysisResult
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    payload = json.loads(LEAD_JSON)
    payload["is_valid_lead"] = True
    payload["evidence_comment_ids"] = ["888888", "999999"]  # 全部幻觉 ID
    provider.queue(NOT_FILTERED_JSON, json.dumps(payload, ensure_ascii=False))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    assert session.query(Lead).count() == 0
    # AnalysisResult 仍应保存
    assert session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).count() == 1


async def test_v16_run_user_analysis_filtered_no_lead(session):
    from app.models import AnalysisResult
    from tests.test_user_filter import FILTERED_JSON
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(FILTERED_JSON)  # 仅过滤一跳，无定级响应
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    assert session.query(Lead).count() == 0
    res = session.query(AnalysisResult).filter_by(
        target_type="user", target_id=str(u1.id)).one()
    assert res.result["lead_grade"] == "C"
    assert res.result["filter_category"] == "already_purchased"
    assert res.result["filter_reason"]

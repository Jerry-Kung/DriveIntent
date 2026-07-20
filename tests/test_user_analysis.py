import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import run_user_analysis
from tests.test_aggregation import _setup

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


async def test_run_user_analysis_creates_lead(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(LEAD_JSON.replace("__CID__", str(c1.id)))
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
    provider.queue(LEAD_JSON.replace("__CID__", cid),
                   LEAD_JSON.replace("__CID__", cid)
                            .replace('"lead_grade": "H"',
                                     '"lead_grade": "A"'))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)
    await run_user_analysis(session, executor, u1.id)

    lead = session.query(Lead).one()          # 仍是一条
    assert lead.grade == "A"                  # 已更新

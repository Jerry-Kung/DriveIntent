import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import AnalysisTask, Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import advance, schedule_analysis
from app.workflow.worker import Worker
from tests.test_comment_screening import _item
from tests.test_user_analysis import LEAD_JSON
from app.models import Comment, PlatformUser, Video

CONTEXT_JSON = json.dumps({"brand": "坦克", "model": "坦克300",
                           "analysis_notes": ""}, ensure_ascii=False)


async def test_worker_full_pipeline(session):
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="用户")
    session.add_all([v, u]); session.flush()
    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="落地多少钱")
    session.add(c); session.commit()

    provider = MockProvider()
    provider.queue(
        CONTEXT_JSON,
        json.dumps({"items": [_item(c.id)]}, ensure_ascii=False),
        LEAD_JSON.replace("__CID__", str(c.id)))
    worker = Worker(lambda: session,
                    SkillExecutor(LLMGateway(provider)))

    assert schedule_analysis(session) == 1        # 1 个视频语境任务
    while await worker.run_once():                # 逐个执行直到队列空
        pass

    assert session.query(AnalysisTask).filter_by(status="failed").count() == 0
    lead = session.query(Lead).one()
    assert lead.grade == "H" and lead.user_id == u.id

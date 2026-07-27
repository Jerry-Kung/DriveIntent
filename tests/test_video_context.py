from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Video
from app.services.results import get_current_result
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (SKILL_VERSIONS, VIDEO_CONTEXT_SKILL,
                                   run_video_context)

CONTEXT_JSON = ('{"brand": "坦克", "model": "坦克300", '
                '"content_type": "新车发布", "main_topics": ["动力"], '
                '"target_audience": "越野爱好者", "competitor_models": [], '
                '"commercial_context": "汽车媒体", '
                '"analysis_notes": "关注价格类评论"}')


async def test_run_video_context_saves_result(session):
    v = Video(platform="douyin", external_id="v1",
              title="全新坦克300 #SUV", description="8缸版本", tags=["SUV"])
    session.add(v)
    session.commit()

    provider = MockProvider()
    provider.queue(CONTEXT_JSON)
    executor = SkillExecutor(LLMGateway(provider))

    await run_video_context(session, executor, v.id)

    r = get_current_result(session, target_type="video", target_id=str(v.id),
                           skill_id=VIDEO_CONTEXT_SKILL,
                           skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
    assert r is not None
    assert r.result["brand"] == "坦克"
    assert r.result["model"] == "坦克300"
    assert r.prompt_version == "v2"
    assert r.model_name != ""

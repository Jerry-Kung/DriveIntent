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
    # V1.8.3：单值 mock 经 before 校验器归一为单元素数组落库
    assert r.result["brand"] == ["坦克"]
    assert r.result["model"] == ["坦克300"]
    assert r.prompt_version == "v1.8.3"
    assert r.model_name != ""


MULTI_BRAND_JSON = ('{"brand": ["坦克", "方程豹"], '
                    '"model": ["坦克300", "豹5"], '
                    '"content_type": "对比评测", "main_topics": ["价格"], '
                    '"vehicle_category": ["越野"], '
                    '"powertrain": ["燃油", "插混(PHEV)"], '
                    '"price_range_min": 200000, "price_range_max": 400000}')


async def test_run_video_context_multi_brand_array(session):
    """线上事故回归（V1.8.3）：跨品牌对比视频 LLM 输出数组，
    此前触发 4 项 string_type 校验错误致整单作业失败。"""
    v = Video(platform="douyin", external_id="v2",
              title="坦克300 vs 豹5 谁更值", description="", tags=[])
    session.add(v)
    session.commit()

    provider = MockProvider()
    provider.queue(MULTI_BRAND_JSON)
    executor = SkillExecutor(LLMGateway(provider))

    await run_video_context(session, executor, v.id)

    r = get_current_result(session, target_type="video", target_id=str(v.id),
                           skill_id=VIDEO_CONTEXT_SKILL,
                           skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
    assert r is not None
    assert r.result["brand"] == ["坦克", "方程豹"]
    assert r.result["model"] == ["坦克300", "豹5"]
    assert r.result["powertrain"] == ["燃油", "插混(PHEV)"]
    assert r.result["price_range_min"] == 200000

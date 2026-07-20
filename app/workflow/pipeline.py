import json

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Video
from app.schemas.skills import VideoContextResult
from app.services.results import save_result
from app.skills.executor import SkillExecutor, load_skill_config

VIDEO_CONTEXT_SKILL = "video_context_analysis"
COMMENT_SCREENING_SKILL = "comment_lead_screening"
USER_ANALYSIS_SKILL = "user_lead_analysis"

SKILL_VERSIONS = {
    VIDEO_CONTEXT_SKILL: "1.0",
    COMMENT_SCREENING_SKILL: "1.0",
    USER_ANALYSIS_SKILL: "1.0",
}


async def run_video_context(session: Session, executor: SkillExecutor,
                            video_id: int) -> None:
    video = session.get(Video, video_id)
    if video is None:
        raise ValueError(f"视频不存在: {video_id}")
    context = {
        "video_json": json.dumps({
            "title": video.title,
            "description": video.description,
            "tags": video.tags or [],
            "account_type": video.account_type or "未知",
            "transcript": video.transcript or "",
            "preset_brand": video.preset_brand or "",
            "preset_model": video.preset_model or "",
        }, ensure_ascii=False),
    }
    out: VideoContextResult = await executor.run(
        VIDEO_CONTEXT_SKILL, context, VideoContextResult)
    config = load_skill_config(VIDEO_CONTEXT_SKILL)
    save_result(session, target_type="video", target_id=str(video_id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result=out.model_dump(),
                model_name=config.model_name or settings.llm_model,
                prompt_version=config.prompt_version)

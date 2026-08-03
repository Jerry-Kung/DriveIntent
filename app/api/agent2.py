import json
import logging

from app.api.mapping import map_profile_result, now_iso
from app.api.schemas import AccountObject, ProfileAnalysisRequest
from app.llm.base import LLMError
from app.llm.gateway import LLMGateway
from app.matching.loader import build_our_models_summary, load_our_models
from app.schemas.skills import UserLeadResult
from app.skills.executor import extract_json, load_skill_config, render_prompt
from app.skills.vision import build_image_message
from app.workflow.pipeline import GRADING_STANDARD, USER_ANALYSIS_SKILL

logger = logging.getLogger(__name__)

IMAGE_SKILL = "image_recognition"


async def recognize_screenshot(gateway: LLMGateway, screenshot: str) -> str:
    if not screenshot or not screenshot.strip():
        return ""
    config = load_skill_config(IMAGE_SKILL)
    prompt = render_prompt(config, {})
    messages = build_image_message(prompt, screenshot)
    try:
        resp = await gateway.chat(messages, skill_id=IMAGE_SKILL,
                                  skill_version=config.version,
                                  prompt_version=config.prompt_version,
                                  model=config.model_name or None,
                                  temperature=config.temperature)
        return resp.text.strip()
    except LLMError as e:
        logger.warning("主页截图识别失败，降级为无截图: %s", e)
        return ""


def _parse_profile(vision_text: str):
    """把识图文本解析为结构化画像对象；解析失败回退为原始文本。"""
    try:
        return extract_json(vision_text)
    except ValueError:
        return vision_text


def _build_evidence(account: AccountObject, vision_text: str) -> dict:
    comments = [{
        "comment_id": f"{account.account_uid}:{idx}",
        "content": h.comment_content,
        "comment_time": h.comment_time,
        "video_title": h.video_title,
        "comment_like_count": h.comment_like_count,
    } for idx, h in enumerate(account.comment_history)]
    profile = _parse_profile(vision_text) if vision_text else "（无主页截图）"
    return {
        "user": {"nickname": account.account_name,
                 "douyin_id": account.account_douyin_id,
                 "homepage_profile": profile},
        "comments": comments,
        "statistics": {"valid_comment_count": len(comments)},
    }


async def analyze_account(executor, account: AccountObject, vision_text: str,
                          our_models_summary: str) -> UserLeadResult:
    evidence = _build_evidence(account, vision_text)
    ctx = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
        "our_models_summary": our_models_summary,
    }
    return await executor.run(USER_ANALYSIS_SKILL, ctx, UserLeadResult)


async def run_profile_analysis(executor, gateway: LLMGateway,
                               request: ProfileAnalysisRequest,
                               *, progress_cb=None) -> dict:
    results: list[dict] = []
    ts = now_iso()
    done = 0
    # 我方车型摘要与账号无关，整批只加载/构建一次，避免每账号重复加载与告警刷屏
    our_models_summary = build_our_models_summary(load_our_models())
    for account in request.accounts:
        has_comments = len(account.comment_history) > 0
        try:
            if not has_comments:
                out = UserLeadResult(lead_grade="C", is_valid_lead=False)
                shot_available = False
            else:
                vision_text = await recognize_screenshot(
                    gateway, account.account_homepage_screenshot)
                shot_available = bool(vision_text)
                out = await analyze_account(
                    executor, account, vision_text, our_models_summary)
            mapped = map_profile_result(
                out, screenshot_available=shot_available,
                has_comments=has_comments, processed_at=ts)
            d = mapped.model_dump()
            d["account_uid"] = account.account_uid
            results.append(d)
        except Exception as e:
            results.append({
                "account_uid": account.account_uid, "has_value": False,
                "intent_level": None, "intent_level_code": None,
                "value_score": None, "is_car_owner": None,
                "has_purchase_intent": None, "profile_tags": [],
                "profile_summary": "", "analysis": "", "processed_at": ts,
                "error": str(e)[:500]})
        done += 1
        if progress_cb:
            progress_cb(done)
    return {"results": results}

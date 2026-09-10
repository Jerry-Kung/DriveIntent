import json
import logging

from app.api.mapping import (map_profile_result, now_iso,
                             resolve_our_model_intent_level)
from app.api.schemas import AccountObject, ProfileAnalysisRequest
from app.llm.base import LLMError
from app.llm.gateway import LLMGateway, _CURRENT_ACCOUNT
from app.matching.loader import (build_intent_category_standard,
                                 build_our_models_summary,
                                 load_intent_categories, load_our_models,
                                 normalize)
from app.schemas.skills import UserLeadResult
from app.skills.analysis_polish import apply_polish
from app.skills.executor import extract_json, load_skill_config, render_prompt
from app.skills.user_filter import build_filtered_lead_result, run_user_filter
from app.skills.user_review import GRADING_STANDARD, apply_review
from app.skills.vision import build_image_message
from app.workflow.pipeline import USER_ANALYSIS_SKILL

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
                                  multimodal=config.multimodal,
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
                          our_models_summary: str,
                          intent_category_standard: str = "") -> UserLeadResult:
    evidence = _build_evidence(account, vision_text)
    ctx = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
        "our_models_summary": our_models_summary,
        "intent_category_standard": (
            intent_category_standard
            or build_intent_category_standard(None)),
    }
    return await executor.run(USER_ANALYSIS_SKILL, ctx, UserLeadResult)


async def run_profile_analysis(executor, gateway: LLMGateway,
                               request: ProfileAnalysisRequest,
                               *, progress_cb=None,
                               vision_sink: dict | None = None,
                               grade_sink: list | None = None,
                               blacklist: set[str] | frozenset[str] | None = None) -> dict:
    """progress_cb 为 async 可调用（V1.4.4：进度落库经线程池执行）。

    vision_sink：传入 dict 时，按账号下标收集识图文本，供调用方在终态写回
    payload（V1.4.4：库中以纯文本替代 base64 截图）。不参与对外结果。

    grade_sink：传入 list 时，按账号下标收集每账号真实内部 HABC 等级
    （V1.7.3：对外 intent_level_code 已为多对一，不能据此反推 HABC）。
    失败账号补 "C" 保持与 results 对齐。不参与对外结果。

    blacklist：V1.9.0 黑名单命中集合（由 Worker 在作业级经线程池加载一次）。
    None 或空集合时行为与现状一致；命中账号在 per-account 头部短路为 C，
    跳过识图/过滤/定级/复核/润色，即零 LLM 调用。
    """
    results: list[dict] = []
    ts = now_iso()
    done = 0
    # 我方车型摘要与分类标准与账号无关，整批只加载/构建一次，
    # 避免每账号重复加载与告警刷屏
    our_models = load_our_models()
    our_models_summary = build_our_models_summary(our_models)
    intent_category_standard = build_intent_category_standard(
        load_intent_categories())
    # V1.10.0：推荐车型校验映射——别称/正名/品牌前缀组合归一化后回落到正式
    # 车型名；未配置我方车型时为空映射（推荐车型一律置 null）。
    # 品牌前缀组合是必要容错：清单渲染行形如"- 东风猛士 猛士M817：售价…"，
    # 模型照抄前缀时若不剥离会大面积落成 null。normalize 会去掉空白，
    # 故"东风猛士 猛士M817"与"东风猛士猛士M817"归一后同键。
    # setdefault 顺序保证正名优先：正名 > 别称 > 品牌前缀组合。
    ours_configured = bool(our_models and our_models.models)
    models = our_models.models if ours_configured else []
    our_model_names = {normalize(m.model_name): m.model_name for m in models}
    for m in models:
        for alias in m.aliases:
            our_model_names.setdefault(normalize(alias), m.model_name)
    for m in models:
        for name in (m.model_name, *m.aliases):
            our_model_names.setdefault(
                normalize(f"{m.brand}{name}"), m.model_name)
    for idx, account in enumerate(request.accounts):
        has_comments = len(account.comment_history) > 0
        # V1.7.1：本账号处理期间写入 account_uid 上下文，使 LLM 日志精确
        # 归属到该账号（识图/过滤/定级/复核/润色全链路）。循环末尾重置，
        # 防止账号处理抛异常时残留到下一个账号。
        account_token = _CURRENT_ACCOUNT.set(account.account_uid)
        try:
            # V1.9.0：黑名单账号最优先短路——零 LLM 调用，直接定 C。
            # 命中判定须在识图/过滤/定级/复核/润色之前完成。
            # V1.9.2：确认黑名单补对外三字段——is_blacklisted=true、
            # blacklist_type="confirmed"、blacklist_reason 为中文说明。
            if (blacklist and account.account_douyin_id
                    and account.account_douyin_id in blacklist):
                out = UserLeadResult(
                    lead_grade="C", is_valid_lead=False,
                    filter_category="blacklisted",
                    filter_reason="该抖音号已列入系统黑名单",
                    analysis_text=(
                        f"该账号（抖音号 {account.account_douyin_id}）已列入黑名单，"
                        "人工确认为非潜客，直接输出黑名单用户。"),
                    is_car_owner=False, has_purchase_intent=False,
                    is_blacklisted=True, blacklist_type="confirmed",
                    blacklist_reason="该抖音号已列入系统黑名单")
                shot_available = False
            elif not has_comments:
                out = UserLeadResult(lead_grade="C", is_valid_lead=False)
                shot_available = False
            else:
                vision_text = await recognize_screenshot(
                    gateway, account.account_homepage_screenshot)
                shot_available = bool(vision_text)
                if vision_sink is not None and vision_text:
                    vision_sink[str(idx)] = vision_text
                # V1.6：定级前先过无效用户过滤（fail-open），命中直接定 C。
                # V1.9.2：该节点同时识别疑似黑名单（营销号/虚假账号），命中
                # 优先于六类过滤类别直接定 C，不进定级/复核/润色。
                evidence = _build_evidence(account, vision_text)
                filt = await run_user_filter(executor, evidence)
                if filt.is_blacklisted:
                    out = build_filtered_lead_result(filt)
                elif filt.filtered:
                    out = build_filtered_lead_result(filt)
                else:
                    out = await analyze_account(
                        executor, account, vision_text, our_models_summary,
                        intent_category_standard)
                    # V1.6.4：API 路径接入复核+润色，与 V0 流水线对齐
                    await apply_review(
                        executor, json.dumps(evidence, ensure_ascii=False),
                        our_models_summary, out)
                    await apply_polish(executor, out)
            if grade_sink is not None:
                # 与 results 按下标对齐；失败账号在 except 分支补 "C"
                grade_sink.append(out.lead_grade)
            # V1.10.0：对我方在售车型的意向等级与推荐车型。
            # 注意：校验必须无条件执行——定级 LLM 可自判 is_valid_lead=false，
            # 但那时若跳过校验，未在配置内的车型名会经 map_profile_result 的
            # has_value=False 分支原样透出对外契约。无效账号一律置 null。
            # 未配置我方在售车型时等级无事实基础，同样置 null。
            if out.is_valid_lead and ours_configured:
                out.our_model_intent_level = resolve_our_model_intent_level(
                    out.our_model_match or "unknown", out.lead_grade)
                if out.recommend_our_model:
                    out.recommend_our_model = our_model_names.get(
                        normalize(out.recommend_our_model))
            else:
                out.our_model_intent_level = None
                out.recommend_our_model = None
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
                "has_purchase_intent": None,
                "intent_models": [], "intent_model_category": None,
                "recommended_entry_point": None,
                "our_model_intent_level": None, "recommend_our_model": None,
                "is_blacklisted": False, "blacklist_type": None,
                "blacklist_reason": None,
                "profile_tags": [],
                "profile_summary": "", "analysis": "", "processed_at": ts,
                "error": str(e)[:500]})
            if grade_sink is not None:
                grade_sink.append("C")  # 失败账号无有效等级，保持下标对齐
        finally:
            _CURRENT_ACCOUNT.reset(account_token)
        done += 1
        if progress_cb:
            await progress_cb(done)
    return {"results": results}

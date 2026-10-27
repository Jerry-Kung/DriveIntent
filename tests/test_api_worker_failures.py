import json
import pytest

from app.api.jobs import create_job, get_job
from app.api.worker import ApiJobWorker
from app.llm.mock import MockProvider
from app.llm.gateway import LLMGateway
from app.skills.executor import SkillExecutor
from tests.test_analysis_polish import POLISH_OK_JSON, POLISHED
from tests.test_user_analysis import REVIEW_CONFIRMED_JSON
from tests.test_user_filter import NOT_FILTERED_JSON


class _Factory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self._session


@pytest.mark.asyncio
async def test_worker_comment_job_fails_when_llm_keeps_failing(session):
    # 不 queue 任何响应：video_context 调用即失败，重试耗尽后 SkillExecutionError
    provider = MockProvider()
    executor = SkillExecutor(LLMGateway(provider))
    gateway = LLMGateway(provider)

    payload = {"comments": [
        {"comment_id": "cm_1", "video_title": "试驾", "video_author": "@王",
         "video_author_fans": 1, "comment_content": "刚提车",
         "comment_author": "a", "comment_author_uid": "u1",
         "comment_time": "2026-07-19T14:23:00+08:00", "comment_like_count": 1}]}
    job = create_job(session, "comment_screening", payload, total=1)
    job.max_attempts = 1  # 让第一次失败即直接判定为 failed
    session.commit()

    worker = ApiJobWorker(_Factory(session), executor, gateway)
    worked = await worker.run_once()
    assert worked is True

    row = get_job(session, job.id)
    assert row.status == "failed"
    assert row.error


@pytest.mark.asyncio
async def test_worker_profile_analysis_job_partial_when_one_account_fails(session):
    # u1：过滤+定级+复核+润色全套响应齐全，验证完整节点序列真实走到；
    # u2：不再补充响应，队列耗尽 → LLM 持续失败，保持"部分失败"语义
    provider = MockProvider()
    provider.queue(NOT_FILTERED_JSON, json.dumps({
        "lead_grade": "A", "is_valid_lead": True, "lead_summary": "对比中",
        "evidence_comment_ids": ["u1:0"], "confidence": 0.8,
        "profile_tags": ["对比阶段"], "profile_summary": "画像",
        "analysis_text": "分析"}), REVIEW_CONFIRMED_JSON, POLISH_OK_JSON)
    executor = SkillExecutor(LLMGateway(provider))
    gateway = LLMGateway(provider)

    payload = {"accounts": [
        {"account_uid": "u1", "account_name": "用户1",
         "account_homepage_screenshot": "",
         "comment_history": [
             {"video_title": "对比", "comment_content": "在纠结这两款",
              "comment_time": "2026-07-19T14:23:00+08:00",
              "comment_like_count": 5}]},
        {"account_uid": "u2", "account_name": "用户2",
         "account_homepage_screenshot": "",
         "comment_history": [
             {"video_title": "对比", "comment_content": "考虑入手",
              "comment_time": "2026-07-19T14:23:00+08:00",
              "comment_like_count": 3}]},
    ]}
    job = create_job(session, "profile_analysis", payload, total=2)

    worker = ApiJobWorker(_Factory(session), executor, gateway)
    worked = await worker.run_once()
    assert worked is True

    row = get_job(session, job.id)
    assert row.status == "partial"
    results = row.result["results"]
    assert results[0]["account_uid"] == "u1"
    assert not results[0].get("error")
    # 复核+润色真实走到：u1 落库结果 analysis 变为润色后文本
    assert results[0]["analysis"] == POLISHED
    assert results[1]["account_uid"] == "u2"
    assert results[1].get("error")

import asyncio
import logging
import time

from app.config import settings
from app.llm.base import LLMError, LLMProvider, LLMResponse
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.models import LlmCallLog

logger = logging.getLogger(__name__)


class LLMGateway:
    def __init__(self, provider: LLMProvider, *, session_factory=None,
                 max_retries: int | None = None):
        self.provider = provider
        self.session_factory = session_factory
        self.max_retries = max_retries or settings.llm_max_retries

    def _log_sync(self, *, skill_id, skill_version, prompt_version, model,
                  messages, resp: LLMResponse | None, error: str | None,
                  duration_ms: int, retry_count: int) -> None:
        if self.session_factory is None:
            return
        try:
            with self.session_factory() as s:
                s.add(LlmCallLog(
                    skill_id=skill_id, skill_version=skill_version,
                    prompt_version=prompt_version, model_name=model,
                    input_digest=str(messages)[-2000:],
                    output_text=resp.text[:8000] if resp else None,
                    prompt_tokens=resp.prompt_tokens if resp else 0,
                    completion_tokens=resp.completion_tokens if resp else 0,
                    duration_ms=duration_ms, error=error,
                    retry_count=retry_count))
                s.commit()
        except Exception:
            pass  # 日志失败不影响主流程

    async def _log(self, **kw) -> None:
        """落 LLM 调用日志。同步 DB 写入经线程池执行。

        V1.4.5：这是全系统最高频的一处 DB 写入（实测 3 小时 6703 行，
        约为 API 作业数的 27 倍）。原先直接在 `chat` 里同步调用，连接池
        耗尽时 `pool.connect()` 会在事件循环内阻塞满 `pool_timeout`（30s），
        期间所有协程与 HTTP 请求全部停摆，进而让更多请求超时——正反馈。
        且异常被下方 `except` 吞掉，此调用点从不出现在 traceback 里，
        报错全落在 get_job / set_progress_by_id 等受害者身上。
        """
        if self.session_factory is None:
            return
        try:
            await asyncio.to_thread(lambda: self._log_sync(**kw))
        except Exception:
            pass  # 日志失败不影响主流程

    async def chat(self, messages: list[dict], *, skill_id: str = "",
                   skill_version: str = "", prompt_version: str = "",
                   model: str | None = None, multimodal: bool = False,
                   temperature: float | None = None) -> LLMResponse:
        if model is None:
            model = settings.multimodal_model if multimodal else settings.llm_model
        temperature = 0.1 if temperature is None else temperature
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            start = time.monotonic()
            try:
                resp = await self.provider.chat(
                    messages, model=model, temperature=temperature)
                await self._log(skill_id=skill_id, skill_version=skill_version,
                                prompt_version=prompt_version, model=model,
                                messages=messages, resp=resp, error=None,
                                duration_ms=int((time.monotonic() - start) * 1000),
                                retry_count=attempt)
                return resp
            except LLMError as e:
                last_error = e
                logger.warning("LLM 调用失败 skill=%s 第 %d/%d 次: %s",
                               skill_id, attempt + 1, self.max_retries, e)
                await self._log(skill_id=skill_id, skill_version=skill_version,
                                prompt_version=prompt_version, model=model,
                                messages=messages, resp=None, error=str(e),
                                duration_ms=int((time.monotonic() - start) * 1000),
                                retry_count=attempt)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
        raise LLMError(f"LLM 调用重试 {self.max_retries} 次后失败: {last_error}")


def build_gateway(session_factory=None) -> LLMGateway:
    if settings.llm_provider == "openai_compat":
        provider: LLMProvider = OpenAICompatProvider()
    else:
        provider = MockProvider()
    return LLMGateway(provider, session_factory=session_factory)

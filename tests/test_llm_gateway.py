import httpx
import pytest

from app.llm.base import LLMError
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.models import LlmCallLog


class FlakyProvider(MockProvider):
    """前 N 次抛错，之后走 MockProvider 队列。"""

    def __init__(self, fail_times: int):
        super().__init__()
        self.fail_times = fail_times

    async def chat(self, messages, *, model, temperature):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMError("boom")
        return await super().chat(messages, model=model,
                                  temperature=temperature)


async def test_gateway_returns_text():
    provider = MockProvider()
    provider.queue('{"ok": true}')
    gw = LLMGateway(provider)
    resp = await gw.chat([{"role": "user", "content": "hi"}])
    assert resp.text == '{"ok": true}'


async def test_gateway_retries_then_succeeds(session):
    provider = FlakyProvider(fail_times=2)
    provider.queue("done")
    gw = LLMGateway(provider, session_factory=lambda: session,
                    max_retries=3)
    resp = await gw.chat([{"role": "user", "content": "hi"}],
                         skill_id="s1", skill_version="1.0")
    assert resp.text == "done"
    logs = session.query(LlmCallLog).all()
    assert len(logs) == 3                      # 2 失败 + 1 成功
    assert logs[-1].error is None


async def test_gateway_raises_after_max_retries():
    gw = LLMGateway(FlakyProvider(fail_times=99), max_retries=2)
    with pytest.raises(LLMError):
        await gw.chat([{"role": "user", "content": "hi"}])


def _provider_with_transport(handler) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    return OpenAICompatProvider(base_url="https://api.example.com",
                                api_key="sk-test", timeout=5,
                                transport=transport)


async def test_openai_compat_provider_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        })

    provider = _provider_with_transport(handler)
    resp = await provider.chat([{"role": "user", "content": "hi"}],
                               model="gpt", temperature=0.1)
    assert resp.text == "hello"
    assert resp.prompt_tokens == 3
    assert resp.completion_tokens == 5


async def test_openai_compat_provider_non_json_body_raises_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="oops")

    provider = _provider_with_transport(handler)
    with pytest.raises(LLMError):
        await provider.chat([{"role": "user", "content": "hi"}],
                            model="gpt", temperature=0.1)


async def test_openai_compat_provider_empty_content_raises_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": ""}}],
        })

    provider = _provider_with_transport(handler)
    with pytest.raises(LLMError):
        await provider.chat([{"role": "user", "content": "hi"}],
                            model="gpt", temperature=0.1)

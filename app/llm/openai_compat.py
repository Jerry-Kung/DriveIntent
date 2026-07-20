import httpx

from app.config import settings
from app.llm.base import LLMError, LLMProvider, LLMResponse


class OpenAICompatProvider(LLMProvider):
    def __init__(self, base_url: str = "", api_key: str = "",
                 timeout: int = 0, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.timeout = timeout or settings.llm_timeout_seconds
        self.transport = transport

    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": model, "messages": messages,
                   "temperature": temperature}
        try:
            async with httpx.AsyncClient(timeout=self.timeout,
                                         transport=self.transport) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError(f"LLM 请求失败: {e}") from e
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"LLM 响应格式异常: {data}") from e
        if not text:
            raise LLMError("LLM 返回空内容")
        usage = data.get("usage") or {}
        return LLMResponse(text=text,
                           prompt_tokens=usage.get("prompt_tokens", 0),
                           completion_tokens=usage.get("completion_tokens", 0))

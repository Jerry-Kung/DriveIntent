from app.llm.base import LLMError, LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    def __init__(self):
        self._responses: list[str] = []

    def queue(self, *texts: str) -> None:
        self._responses.extend(texts)

    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float) -> LLMResponse:
        if not self._responses:
            raise LLMError("MockProvider: 无预置响应")
        return LLMResponse(text=self._responses.pop(0))

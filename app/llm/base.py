import abc

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0


class LLMError(Exception):
    pass


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float, enable_thinking: bool = False) -> LLMResponse:
        ...

import json
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.llm.base import LLMError
from app.llm.gateway import LLMGateway

CONFIG_DIR = Path(__file__).parent / "configs"
PROMPT_DIR = Path(__file__).parent / "prompts"


class SkillConfig(BaseModel):
    skill_id: str
    version: str
    description: str = ""
    model_name: str = ""
    temperature: float = 0.1
    prompt_file: str
    prompt_version: str


class SkillExecutionError(Exception):
    pass


def load_skill_config(skill_id: str) -> SkillConfig:
    path = CONFIG_DIR / f"{skill_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    model = data.pop("model", {}) or {}
    return SkillConfig(model_name=model.get("name", ""),
                       temperature=model.get("temperature", 0.1), **data)


def render_prompt(config: SkillConfig, context: dict[str, str],
                  template_text: str | None = None) -> str:
    if template_text is None:
        template_text = (PROMPT_DIR / config.prompt_file).read_text(
            encoding="utf-8")
    return Template(template_text).substitute(context)


def extract_json(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise ValueError(f"输出中未找到 JSON: {text[:200]}")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end <= start:
        raise ValueError(f"输出中 JSON 不完整: {text[:200]}")
    return json.loads(cleaned[start:end + 1])


class SkillExecutor:
    def __init__(self, gateway: LLMGateway, max_retries: int | None = None):
        self.gateway = gateway
        self.max_retries = max_retries or settings.llm_max_retries

    async def run(self, skill_id: str, context: dict[str, str],
                  output_model: type[BaseModel]) -> BaseModel:
        config = load_skill_config(skill_id)
        prompt = render_prompt(config, context)
        messages = [{"role": "user", "content": prompt}]
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                resp = await self.gateway.chat(
                    messages, skill_id=config.skill_id,
                    skill_version=config.version,
                    prompt_version=config.prompt_version,
                    model=config.model_name or None,
                    temperature=config.temperature)
            except LLMError as e:
                last_error = e
                continue
            try:
                data = extract_json(resp.text)
                return output_model.model_validate(data)
            except (ValueError, ValidationError) as e:
                last_error = e
                continue
        raise SkillExecutionError(
            f"Skill {skill_id} 执行失败: {last_error}")

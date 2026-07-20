import pytest
from pydantic import BaseModel

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import (SkillConfig, SkillExecutionError,
                                 SkillExecutor, extract_json, render_prompt)


class Out(BaseModel):
    answer: str


def test_extract_json_with_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('前缀 [1, 2] 后缀') == [1, 2]
    with pytest.raises(ValueError):
        extract_json("完全不是 JSON")


def test_render_prompt_keeps_json_braces():
    cfg = SkillConfig(skill_id="t", version="1.0", prompt_file="x.txt",
                      prompt_version="v1")
    tpl = '输出 {"k": "v"} 格式。输入：$data'
    assert render_prompt(cfg, {"data": "abc"}, template_text=tpl) == \
        '输出 {"k": "v"} 格式。输入：abc'


async def test_executor_retries_bad_json(tmp_path, monkeypatch):
    # 准备临时 skill 配置与 prompt
    cfg_dir = tmp_path / "configs"
    prompt_dir = tmp_path / "prompts"
    cfg_dir.mkdir(); prompt_dir.mkdir()
    (cfg_dir / "demo.yaml").write_text(
        'skill_id: demo\nversion: "1.0"\nmodel:\n  name: ""\n'
        '  temperature: 0.1\nprompt_file: demo_v1.txt\n'
        'prompt_version: "v1"\n', encoding="utf-8")
    (prompt_dir / "demo_v1.txt").write_text("回答：$q", encoding="utf-8")
    import app.skills.executor as ex
    monkeypatch.setattr(ex, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ex, "PROMPT_DIR", prompt_dir)

    provider = MockProvider()
    provider.queue("不是JSON", '{"answer": "好"}')   # 第 1 次坏，第 2 次好
    executor = SkillExecutor(LLMGateway(provider))
    out = await executor.run("demo", {"q": "hi"}, Out)
    assert out.answer == "好"


async def test_executor_fails_after_retries(tmp_path, monkeypatch):
    import app.skills.executor as ex
    cfg_dir = tmp_path / "configs"; prompt_dir = tmp_path / "prompts"
    cfg_dir.mkdir(); prompt_dir.mkdir()
    (cfg_dir / "demo.yaml").write_text(
        'skill_id: demo\nversion: "1.0"\nmodel:\n  name: ""\n'
        '  temperature: 0.1\nprompt_file: demo_v1.txt\n'
        'prompt_version: "v1"\n', encoding="utf-8")
    (prompt_dir / "demo_v1.txt").write_text("$q", encoding="utf-8")
    monkeypatch.setattr(ex, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ex, "PROMPT_DIR", prompt_dir)

    provider = MockProvider()
    provider.queue("bad", "bad", "bad")
    executor = SkillExecutor(LLMGateway(provider), max_retries=3)
    with pytest.raises(SkillExecutionError):
        await executor.run("demo", {"q": "hi"}, Out)

import pytest
from pydantic import BaseModel

from app.llm.base import LLMError
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


def test_skill_config_multimodal_defaults_false():
    cfg = SkillConfig(skill_id="t", version="1.0", prompt_file="x.txt",
                      prompt_version="v1")
    assert cfg.multimodal is False


def test_load_skill_config_reads_multimodal(tmp_path, monkeypatch):
    import app.skills.executor as ex
    cfg_dir = tmp_path / "configs"
    cfg_dir.mkdir()
    (cfg_dir / "vis.yaml").write_text(
        'skill_id: vis\nversion: "1.0"\nmodel:\n  name: ""\n'
        '  temperature: 0.1\n  multimodal: true\n'
        'prompt_file: vis_v1.txt\nprompt_version: "v1"\n', encoding="utf-8")
    monkeypatch.setattr(ex, "CONFIG_DIR", cfg_dir)
    cfg = ex.load_skill_config("vis")
    assert cfg.multimodal is True


async def test_executor_passes_multimodal_to_gateway(tmp_path, monkeypatch):
    import app.skills.executor as ex
    cfg_dir = tmp_path / "configs"; prompt_dir = tmp_path / "prompts"
    cfg_dir.mkdir(); prompt_dir.mkdir()
    (cfg_dir / "demo.yaml").write_text(
        'skill_id: demo\nversion: "1.0"\nmodel:\n  name: ""\n'
        '  temperature: 0.1\n  multimodal: true\nprompt_file: demo_v1.txt\n'
        'prompt_version: "v1"\n', encoding="utf-8")
    (prompt_dir / "demo_v1.txt").write_text("$q", encoding="utf-8")
    monkeypatch.setattr(ex, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ex, "PROMPT_DIR", prompt_dir)

    captured = {}

    class Gw:
        async def chat(self, messages, **kwargs):
            captured.update(kwargs)
            from app.llm.base import LLMResponse
            return LLMResponse(text='{"answer": "好"}')

    executor = SkillExecutor(Gw(), max_retries=1)
    await executor.run("demo", {"q": "hi"}, Out)
    assert captured["multimodal"] is True


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


async def test_executor_does_not_retry_on_llm_error(tmp_path, monkeypatch):
    # gateway.chat 内部已重试过；执行器层遇到 LLMError 应立即失败，不再自行
    # 重试（避免 3(执行器) × 3(网关) = 9 次放大调用）。
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

    calls = {"n": 0}

    class AlwaysFailProvider(MockProvider):
        async def chat(self, messages, *, model, temperature):
            calls["n"] += 1
            raise LLMError("boom")

    gateway = LLMGateway(AlwaysFailProvider(), max_retries=3)
    executor = SkillExecutor(gateway, max_retries=3)
    with pytest.raises(SkillExecutionError):
        await executor.run("demo", {"q": "hi"}, Out)
    # gateway 自身重试 3 次（max_retries=3），执行器层不应再叠加重试
    assert calls["n"] == 3


def test_v11_video_context_config_uses_v2():
    from app.skills.executor import load_skill_config
    config = load_skill_config("video_context_analysis")
    assert config.prompt_file == "video_context_analysis_v2.txt"
    assert config.prompt_version == "v2"
    assert config.version == "1.1"


def test_v13_screening_config_uses_v3():
    from app.skills.executor import load_skill_config
    config = load_skill_config("comment_lead_screening")
    assert config.prompt_file == "comment_lead_screening_v3.txt"
    assert config.prompt_version == "v3"
    assert config.version == "1.3"


def test_v11_video_context_prompt_renders_with_new_fields():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("video_context_analysis")
    text = render_prompt(config, {"video_json": "{}"})
    assert "price_range_min" in text
    assert "vehicle_category" in text
    assert "use_case" in text


def test_v13_screening_prompt_renders_with_label_fields():
    from app.skills.executor import load_skill_config, render_prompt
    config = load_skill_config("comment_lead_screening")
    text = render_prompt(config, {"video_context_json": "{}",
                                  "comments_json": "[]",
                                  "comment_count": "0"})
    assert "is_car_owner" in text
    assert "has_purchase_intent" in text
    assert "positive_attitude" in text
    assert "comment_actor" in text
    assert "owner_status" not in text          # 旧枚举字段退场
    # 车主判定反例约束
    assert "准备订" in text or "想下定" in text
    # 车主意向词例与非本人意向规则
    assert "置换" in text
    assert "我朋友想买" in text
    # no_purchase_intent 由代码合成，不得出现在 LLM 输出模板中
    assert "no_purchase_intent" not in text


def test_v13_pipeline_screening_version_bumped():
    from app.workflow.pipeline import COMMENT_SCREENING_SKILL, SKILL_VERSIONS
    assert SKILL_VERSIONS[COMMENT_SCREENING_SKILL] == "1.3"

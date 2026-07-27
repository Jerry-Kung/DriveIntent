import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_our_models import extract_models, write_config  # noqa: E402

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.matching.models import OurModelsConfig

_LLM_OUT = json.dumps({"models": [{
    "model_id": "fz-x7", "brand": "方舟", "model_name": "方舟X7",
    "aliases": ["X7"], "price_min": 350000, "price_max": 420000,
    "vehicle_category": "越野", "powertrain": "PHEV",
    "use_case": ["越野"], "key_features": ["四驱"],
    "target_audience": "户外爱好者"}]}, ensure_ascii=False)


def _gateway(*responses) -> LLMGateway:
    provider = MockProvider()
    provider.queue(*responses)
    return LLMGateway(provider)


@pytest.mark.asyncio
async def test_extract_models_valid():
    cfg = await extract_models(_gateway(_LLM_OUT), "方舟X7，35-42万越野车")
    assert isinstance(cfg, OurModelsConfig)
    assert cfg.models[0].model_name == "方舟X7"
    assert cfg.updated_at  # 自动补今天日期


@pytest.mark.asyncio
async def test_extract_models_invalid_output_raises():
    bad = json.dumps({"models": [{"model_id": "a"}]})  # 缺必填字段
    with pytest.raises(Exception):
        # MockProvider 三条相同响应耗尽执行器风格重试后仍失败
        await extract_models(_gateway(bad, bad, bad), "文本")


def test_write_config_creates_and_backs_up(tmp_path):
    cfg = OurModelsConfig.model_validate(json.loads(_LLM_OUT))
    out = tmp_path / "our_models.json"
    write_config(cfg, out)
    assert out.exists()
    write_config(cfg, out)  # 第二次写触发备份
    assert (tmp_path / "our_models.json.bak").exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["models"][0]["brand"] == "方舟"

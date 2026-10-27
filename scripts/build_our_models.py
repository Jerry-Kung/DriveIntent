"""把我方在售车型的文本描述转换为 config/our_models.json 结构化配置。

用法：
    python scripts/build_our_models.py --input docs/our_models.txt
    python scripts/build_our_models.py --input docs/our_models.txt --dry-run
"""
import argparse
import asyncio
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.gateway import LLMGateway, build_gateway  # noqa: E402
from app.matching.models import OurModelsConfig  # noqa: E402
from app.skills.executor import extract_json  # noqa: E402

_MAX_ATTEMPTS = 3

PROMPT = """你是汽车产品信息结构化专家。请把以下我方在售车型的文本描述转换为结构化 JSON。
文本中可能描述一款或多款车型，每款车型输出一个对象。

车型描述：
{text}

请严格输出以下 JSON（不要输出任何其他内容）：
{{
  "models": [
    {{
      "model_id": "小写短横线标识（拼音或英文），如 fangzhou-x7",
      "brand": "品牌规范名称",
      "model_name": "车型规范名称",
      "aliases": ["常见简称、口语叫法、英文名，尽量丰富以提高评论匹配率"],
      "price_min": 售价区间下限（人民币元，整数）,
      "price_max": 售价区间上限（人民币元，整数）,
      "vehicle_category": "品类：轿车/SUV/MPV/越野/皮卡/微型车",
      "powertrain": "动力形式：燃油/纯电/插混(PHEV)/油混(HEV)/增程",
      "use_case": ["主要用途，如：家用/越野/通勤/商务"],
      "key_features": ["核心卖点，如：四驱/大空间/智驾"],
      "target_audience": "目标人群一句话"
    }}
  ]
}}
要求：
1. 只依据文本内容抽取，缺失的价格等关键信息不得编造。
2. 价格区间取主销版本的官方指导价范围；限量版、特别版、定制改装版价格不计入。"""


async def extract_models(gateway: LLMGateway, text: str) -> OurModelsConfig:
    """LLM 抽取 + Pydantic 校验；解析/校验失败换新输出重试。"""
    last_error: Exception | None = None
    for _ in range(_MAX_ATTEMPTS):
        resp = await gateway.chat(
            [{"role": "user", "content": PROMPT.format(text=text)}],
            skill_id="build_our_models", skill_version="1.0",
            prompt_version="v1")
        try:
            data = extract_json(resp.text)
            data.setdefault("version", "1.0")
            data.setdefault("updated_at", date.today().isoformat())
            return OurModelsConfig.model_validate(data)
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"车型信息抽取失败: {last_error}")


def write_config(config: OurModelsConfig, output: Path) -> None:
    """写入配置；目标已存在时先备份 .bak。"""
    if output.exists():
        shutil.copy2(output, output.with_suffix(output.suffix + ".bak"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="把车型文本描述转换为 our_models.json 结构化配置")
    parser.add_argument("--input", required=True, help="车型文本描述文件路径")
    parser.add_argument("--output", default="config/our_models.json",
                        help="输出配置文件路径")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印结构不写盘")
    args = parser.parse_args()
    text = Path(args.input).read_text(encoding="utf-8")
    try:
        config = await extract_models(build_gateway(), text)
    except Exception as e:
        print(f"转换失败：{e}", file=sys.stderr)
        return 1
    print(json.dumps(config.model_dump(), ensure_ascii=False, indent=2))
    if args.dry_run:
        return 0
    write_config(config, Path(args.output))
    print(f"已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

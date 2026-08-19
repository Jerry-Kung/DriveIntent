#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 模型连通性测试脚本。

读取 .env 中的 LLM 配置（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL /
LLM_MULTIMODAL_MODEL / LLM_MODEL_ADVANCED），对每个已配置的模型发送
最简单的测试问题「你好，请介绍一下你自己」，验证能否正常调用。

用法（在项目根目录执行，保证读到根目录的 .env）:
  python scripts/test_llm_connection.py
"""

import asyncio
import sys
import time
from pathlib import Path

# 保证从任意目录执行时都能 import app 包，且 .env 从项目根目录读取
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
os.chdir(PROJECT_ROOT)

from app.config import settings  # noqa: E402
from app.llm.base import LLMError  # noqa: E402
from app.llm.openai_compat import OpenAICompatProvider  # noqa: E402

TEST_QUESTION = "你好，请介绍一下你自己"


def collect_models() -> list[tuple[str, str, bool]]:
    """收集待测模型：(角色说明, 模型名, 是否强制深度思考)，按模型名去重。"""
    candidates = [
        ("文本模型 LLM_MODEL", settings.llm_model, False),
        ("多模态模型 LLM_MULTIMODAL_MODEL", settings.llm_multimodal_model, False),
        ("高级模型 LLM_MODEL_ADVANCED", settings.llm_model_advanced, True),
    ]
    seen: set[str] = set()
    result = []
    for role, model, thinking in candidates:
        if not model or model in seen:
            continue
        seen.add(model)
        result.append((role, model, thinking))
    return result


async def test_model(provider: OpenAICompatProvider, role: str, model: str,
                     enable_thinking: bool) -> bool:
    print(f"\n🔄 测试 {role}: {model}"
          + ("（enable_thinking=true）" if enable_thinking else ""))
    start = time.monotonic()
    try:
        resp = await provider.chat(
            [{"role": "user", "content": TEST_QUESTION}],
            model=model, temperature=0.1, enable_thinking=enable_thinking)
    except LLMError as e:
        print(f"❌ 调用失败: {e}")
        return False
    elapsed = time.monotonic() - start
    text = resp.text.strip()
    preview = text[:200] + ("…" if len(text) > 200 else "")
    print(f"✅ 调用成功（耗时 {elapsed:.1f}s，"
          f"prompt_tokens={resp.prompt_tokens}, "
          f"completion_tokens={resp.completion_tokens}）")
    print(f"📝 模型回复（前 200 字）: {preview}")
    return True


async def main() -> int:
    print("=" * 60)
    print("LLM 模型连通性测试")
    print("=" * 60)
    print(f"\n📋 当前配置:")
    print(f"  LLM_PROVIDER: {settings.llm_provider}")
    print(f"  LLM_BASE_URL: {settings.llm_base_url or '（未配置）'}")
    print(f"  LLM_API_KEY: "
          + (f"{settings.llm_api_key[:6]}***" if settings.llm_api_key else "（未配置）"))
    print(f"  测试问题: {TEST_QUESTION}")

    if settings.llm_provider != "openai_compat":
        print(f"\n⚠️  LLM_PROVIDER 当前为 '{settings.llm_provider}'，"
              f"非 openai_compat，实际服务不会调用真实模型。")
        print("    本脚本仍按 .env 中的 BASE_URL/API_KEY/模型名直连真实端点测试。")

    if not settings.llm_base_url:
        print("\n❌ .env 中未配置 LLM_BASE_URL，无法测试")
        return 1
    if not settings.llm_api_key:
        print("\n❌ .env 中未配置 LLM_API_KEY，无法测试")
        return 1

    models = collect_models()
    if not models:
        print("\n❌ .env 中未配置任何模型（LLM_MODEL 为空）")
        return 1

    provider = OpenAICompatProvider()
    results = []
    for role, model, thinking in models:
        ok = await test_model(provider, role, model, thinking)
        results.append((role, model, ok))

    print("\n" + "=" * 60)
    print("测试结果汇总:")
    for role, model, ok in results:
        print(f"  {'✅' if ok else '❌'} {role}: {model}")
    all_ok = all(ok for _, _, ok in results)
    print("=" * 60)
    print("✅ 全部模型连通性测试通过" if all_ok else "❌ 存在调用失败的模型")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        sys.exit(130)

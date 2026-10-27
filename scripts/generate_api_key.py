"""生成 DriveIntent 对外 API 的 API Key。

Key 为 URL 安全的随机字符串（32 字节熵），供 .env 的 API_KEYS 使用。
仅依赖标准库，无需安装项目依赖即可运行。

用法：
    python scripts/generate_api_key.py              # 生成 1 个，仅打印
    python scripts/generate_api_key.py -n 3         # 生成 3 个，仅打印
    python scripts/generate_api_key.py --write      # 生成并追加到 .env 的 API_KEYS
    python scripts/generate_api_key.py -n 2 --write --replace
                                                    # 生成 2 个并替换 .env 中原有 API_KEYS
"""
import argparse
import re
import secrets
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent.parent / ".env"
PLACEHOLDER_PREFIX = "change-me"


def generate_key() -> str:
    return f"di_{secrets.token_urlsafe(32)}"


def read_existing_keys(text: str) -> list[str]:
    match = re.search(r"^API_KEYS=(.*)$", text, flags=re.MULTILINE)
    if not match:
        return []
    return [k.strip() for k in match.group(1).split(",")
            if k.strip() and not k.strip().startswith(PLACEHOLDER_PREFIX)]


def write_env(new_keys: list[str], replace: bool) -> list[str]:
    if not ENV_PATH.exists():
        print(f"未找到 {ENV_PATH}，请先执行 copy .env.example .env", file=sys.stderr)
        sys.exit(1)
    text = ENV_PATH.read_text(encoding="utf-8")
    keys = new_keys if replace else read_existing_keys(text) + new_keys
    line = f"API_KEYS={','.join(keys)}"
    if re.search(r"^API_KEYS=", text, flags=re.MULTILINE):
        text = re.sub(r"^API_KEYS=.*$", line, text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 API Key")
    parser.add_argument("-n", "--count", type=int, default=1,
                        help="生成数量（默认 1）")
    parser.add_argument("--write", action="store_true",
                        help="写入 .env 的 API_KEYS（默认追加，占位 key 自动剔除）")
    parser.add_argument("--replace", action="store_true",
                        help="配合 --write：替换而非追加原有 key")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count 必须 >= 1")

    new_keys = [generate_key() for _ in range(args.count)]
    for key in new_keys:
        print(key)

    if args.write:
        keys = write_env(new_keys, replace=args.replace)
        action = "替换" if args.replace else "追加"
        print(f"\n已{action}写入 {ENV_PATH}（当前共 {len(keys)} 个 key），"
              f"重启服务后生效", file=sys.stderr)
    else:
        print("\n请将以上 key 加入 .env 的 API_KEYS（逗号分隔），"
              "或使用 --write 自动写入", file=sys.stderr)


if __name__ == "__main__":
    main()

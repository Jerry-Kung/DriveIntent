"""截图暂存区：base64 原始截图不入库，改以文件形式暂存到落盘目录。

V1.4.4 背景：`request_payload` 里的 base64 截图使单行达 12.98MB（最大 25MB），
worker 认领时必须整条读出——实测远程读取阻塞 3.2s，冻结事件循环，是连接池
耗尽的直接成因。api_job 表 6408MB 中 9520MB 是 payload，result 仅 78MB。

设计要点：
  - 对外 API 契约不变，仍接收 base64；POST 端点抽出截图写入本模块，
    payload 中该字段置空后再落库（KB 级）。
  - Worker 认领后读回 base64 → 识图 → 纯文本参与评级 → 文本写回 payload。
  - 作业进入终态时删除暂存文件；pending/running（含重试）期间保留。
  - 暂存文件缺失时降级为无截图继续（与识图失败同路径），不使作业失败。

暂存目录须挂载到宿主机（docker-compose `./data:/app/data`），否则容器重启
会丢失待处理作业的截图。容量估算见部署文档。
"""
import json
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)

SCREENSHOT_FIELD = "account_homepage_screenshot"
VISION_TEXT_FIELD = "homepage_vision_text"


def staging_dir() -> str:
    return settings.screenshot_staging_dir


def _path(job_id: str) -> str:
    # job_id 由服务端 uuid4 生成，不含路径分隔符；仍取 basename 兜底，
    # 避免任何情况下逃逸出暂存目录
    return os.path.join(staging_dir(), f"{os.path.basename(job_id)}.json")


def ensure_dir() -> None:
    """确保暂存目录存在且可写。启动时调用，问题尽早暴露。"""
    d = staging_dir()
    os.makedirs(d, exist_ok=True)
    if not os.access(d, os.W_OK):
        raise RuntimeError(
            f"截图暂存目录不可写: {d}（docker 部署需挂载 ./data:/app/data）")


def extract_screenshots(payload: dict) -> dict[str, str]:
    """就地摘除 payload 中的 base64 截图，返回 {账号下标: base64}。

    payload 被原地修改：截图字段置为空串。仅处理 profile_analysis 结构。
    """
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return {}
    shots: dict[str, str] = {}
    for idx, acc in enumerate(accounts):
        if not isinstance(acc, dict):
            continue
        shot = acc.get(SCREENSHOT_FIELD)
        if shot and str(shot).strip():
            shots[str(idx)] = shot
            acc[SCREENSHOT_FIELD] = ""
    return shots


def save(job_id: str, shots: dict[str, str]) -> None:
    """写入暂存文件。无截图时不建文件。

    先写临时文件再原子改名，避免 worker 读到写了一半的内容。
    """
    if not shots:
        return
    ensure_dir()
    path = _path(job_id)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(shots, f)
    os.replace(tmp, path)


def load(job_id: str) -> dict[str, str]:
    """读回暂存截图。文件不存在或损坏时返回空 dict（降级为无截图）。"""
    path = _path(job_id)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("截图暂存文件读取失败，降级为无截图: %s (%s)", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def discard(job_id: str) -> None:
    """删除暂存文件（作业进入终态时调用）。缺失视为已完成，不报错。"""
    for p in (_path(job_id), f"{_path(job_id)}.tmp"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("截图暂存文件删除失败: %s (%s)", p, e)


def merge_into_payload(payload: dict, shots: dict[str, str]) -> dict:
    """把暂存截图填回 payload 副本，供执行期使用（不落库）。

    存量作业的 payload 里已内联 base64（V1.4.4 之前提交的 538 个 pending），
    此时 shots 为空，原样返回即可——识图仍能从内联字段取到截图。
    """
    if not shots:
        return payload
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return payload
    merged = []
    for idx, acc in enumerate(accounts):
        shot = shots.get(str(idx))
        if shot and isinstance(acc, dict):
            acc = dict(acc, **{SCREENSHOT_FIELD: shot})
        merged.append(acc)
    return dict(payload, accounts=merged)


def reap_orphans(active_job_ids: set[str]) -> int:
    """删除无对应 pending/running 作业的暂存文件（启动时调用）。

    场景：作业落终态前进程崩溃，暂存文件无人删除。
    """
    d = staging_dir()
    if not os.path.isdir(d):
        return 0
    removed = 0
    for name in os.listdir(d):
        if not name.endswith(".json") and not name.endswith(".json.tmp"):
            continue
        job_id = name.split(".", 1)[0]
        if job_id in active_job_ids:
            continue
        try:
            os.remove(os.path.join(d, name))
            removed += 1
        except OSError as e:
            logger.warning("孤儿暂存文件删除失败: %s (%s)", name, e)
    return removed

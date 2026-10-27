"""DriveIntent 远程 API 冒烟测试。

依次验证：健康检查 → 认证拦截 → 评论初筛（Agent 1）提交与轮询 →
账号画像精筛（Agent 2）提交与轮询。全部通过退出码为 0，否则为 1。

仅依赖 Python 标准库，可在任意装有 Python 3.10+ 的机器上直接运行：
    python scripts/api_smoke_test.py

运行前请修改下方「配置区」的 BASE_URL 与 API_KEY。
"""
import json
import sys
import time
import urllib.error
import urllib.request

# ========================== 配置区（按需修改） ==========================
BASE_URL = "http://118.145.238.50:11238"   # 服务地址，如 http://192.168.1.10:8000
API_KEY = "di_uhy3VL1UMumEUo0zTR6gTPsvAW0c4zcOw8N75uIrAKY"                # .env 中 API_KEYS 里的某个 key
POLL_INTERVAL_SECONDS = 3            # 轮询间隔
POLL_TIMEOUT_SECONDS = 300           # 单个任务轮询超时
# ======================================================================

TERMINAL_STATUSES = {"success", "partial", "failed"}

COMMENT_PAYLOAD = {
    "comments": [
        {
            "comment_id": "smoke_c1",
            "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
            "video_author": "@老王说车",
            "video_author_fans": 2865000,
            "video_metrics": {"like_count": 125000, "comment_count": 3428,
                              "share_count": 8900, "collect_count": 12300},
            "comment_content": "上海落地多少钱，旧车置换有补贴吗？",
            "comment_author": "冒烟测试用户",
            "comment_author_uid": "smoke_u1",
            "comment_time": "2026-07-24T10:00:00+08:00",
            "comment_like_count": 12,
        },
        {
            "comment_id": "smoke_c2",
            "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
            "video_author": "@老王说车",
            "comment_content": "厉害",
            "comment_author": "冒烟测试用户2",
            "comment_author_uid": "smoke_u2",
            "comment_time": "2026-07-24T10:01:00+08:00",
        },
    ]
}

PROFILE_PAYLOAD = {
    "accounts": [
        {
            "account_uid": "smoke_u1",
            "account_name": "冒烟测试用户",
            "account_homepage_screenshot": "",
            "comment_history": [
                {
                    "video_title": "试驾体验｜这台车的智驾系统真的惊艳",
                    "comment_content": "上海落地多少钱，旧车置换有补贴吗？",
                    "comment_time": "2026-07-24T10:00:00+08:00",
                    "comment_like_count": 12,
                },
                {
                    "video_title": "新款上市发布会全程回顾",
                    "comment_content": "和竞品B比哪个空间大？家里俩娃",
                    "comment_time": "2026-07-20T21:30:00+08:00",
                },
            ],
        }
    ]
}


def request(method: str, path: str, body: dict | None = None,
            auth: bool = True) -> tuple[int, dict]:
    """返回 (HTTP状态码, 响应JSON)。网络级错误直接抛异常。"""
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json"})
    if auth:
        req.add_header("Authorization", f"Bearer {API_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        return e.code, payload


def poll_job(job_id: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        code, job = request("GET", f"/api/v1/jobs/{job_id}")
        if code != 200:
            raise AssertionError(f"轮询返回 HTTP {code}: {job}")
        status = job.get("status")
        progress = job.get("progress") or {}
        print(f"    status={status} progress={progress.get('done', '?')}"
              f"/{progress.get('total', '?')}")
        if status in TERMINAL_STATUSES:
            return job
        time.sleep(POLL_INTERVAL_SECONDS)
    raise AssertionError(f"任务 {job_id} 在 {POLL_TIMEOUT_SECONDS}s 内未到终态")


def check(name: str, fn) -> bool:
    print(f"\n[{name}]")
    try:
        fn()
        print(f"  ✔ {name} 通过")
        return True
    except Exception as e:
        print(f"  ✘ {name} 失败: {e}")
        return False


def test_health() -> None:
    code, body = request("GET", "/health", auth=False)
    assert code == 200 and body.get("status") == "ok", \
        f"HTTP {code}, 响应 {body}"
    print(f"  GET /health -> {body}")


def test_auth_rejected() -> None:
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/api/v1/jobs/nonexistent",
        headers={"Authorization": "Bearer invalid-smoke-key"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raise AssertionError(f"无效 key 未被拦截，返回 HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        assert e.code == 401, f"预期 401，实际 {e.code}"
    print("  无效 API Key -> 401（认证拦截正常）")


def run_agent(name: str, path: str, payload: dict, id_field: str) -> None:
    code, body = request("POST", path, body=payload)
    assert code == 202, f"提交返回 HTTP {code}: {body}"
    job_id = body["job_id"]
    print(f"  已提交 POST {path} -> job_id={job_id}")
    job = poll_job(job_id)
    status = job["status"]
    assert status in ("success", "partial"), \
        f"任务终态为 {status}, error={job.get('error')}"
    results = (job.get("result") or {}).get("results", [])
    sent = len(payload[list(payload)[0]])
    assert len(results) == sent, f"提交 {sent} 条但返回 {len(results)} 条结果"
    for r in results:
        summary = {k: r.get(k) for k in (id_field, "passed", "has_value",
                                         "intent_level", "error")
                   if k in r}
        print(f"    结果: {summary}")
    if status == "partial":
        failed = [r[id_field] for r in results if r.get("error")]
        print(f"  ⚠ 任务为 partial，失败条目: {failed}")


def main() -> int:
    print(f"目标服务: {BASE_URL}")
    if API_KEY == "change-me":
        print("请先修改脚本顶部配置区的 API_KEY", file=sys.stderr)
        return 1
    results = [
        check("健康检查", test_health),
        check("认证拦截", test_auth_rejected),
        check("Agent1 评论初筛", lambda: run_agent(
            "Agent1", "/api/v1/comment-screening",
            COMMENT_PAYLOAD, "comment_id")),
        check("Agent2 账号画像", lambda: run_agent(
            "Agent2", "/api/v1/profile-analysis",
            PROFILE_PAYLOAD, "account_uid")),
    ]
    passed = sum(results)
    print(f"\n{'=' * 40}\n结果: {passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

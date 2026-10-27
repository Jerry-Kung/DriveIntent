"""access log 降噪：轮询/健康检查端点的成功请求不打印，错误照常。"""
import logging

from app.logging_filters import EndpointNoiseFilter


def _record(method: str, path: str, status: int) -> logging.LogRecord:
    # 构造与 uvicorn.access 相同结构的日志记录：
    # args = (client_addr, method, full_path, http_version, status_code)
    return logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname="", lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("1.2.3.4:1234", method, path, "1.1", status), exc_info=None)


def test_job_polling_success_suppressed():
    f = EndpointNoiseFilter()
    rec = _record("GET", "/api/v1/jobs/e90fcaf5-443a-402a-adcd-d02d5aaf08ec",
                  200)
    assert f.filter(rec) is False


def test_health_check_success_suppressed():
    f = EndpointNoiseFilter()
    assert f.filter(_record("GET", "/health", 200)) is False


def test_job_polling_error_kept():
    f = EndpointNoiseFilter()
    assert f.filter(_record("GET", "/api/v1/jobs/xxx", 404)) is True
    assert f.filter(_record("GET", "/api/v1/jobs/xxx", 500)) is True


def test_other_endpoints_kept():
    f = EndpointNoiseFilter()
    assert f.filter(_record("POST", "/api/v1/jobs/comment-screening",
                            200)) is True
    assert f.filter(_record("GET", "/tasks", 200)) is True


def test_malformed_record_kept():
    # args 结构不符合预期时不误吞
    f = EndpointNoiseFilter()
    rec = logging.LogRecord(name="uvicorn.access", level=logging.INFO,
                            pathname="", lineno=0, msg="plain", args=None,
                            exc_info=None)
    assert f.filter(rec) is True


def test_filter_installed_on_uvicorn_access():
    # main 模块导入后，uvicorn.access logger 应挂上过滤器
    import importlib
    import app.main
    importlib.reload(app.main)
    names = [type(x).__name__
             for x in logging.getLogger("uvicorn.access").filters]
    assert "EndpointNoiseFilter" in names

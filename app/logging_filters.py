import logging

# 高频轮询/健康检查端点：成功日志无信息量，只在出错时打印
_NOISY_GET_PREFIXES = ("/api/v1/jobs/", "/health")


class EndpointNoiseFilter(logging.Filter):
    """抑制 uvicorn.access 中轮询类端点的成功访问日志。

    uvicorn.access 的记录结构固定为
    args = (client_addr, method, full_path, http_version, status_code)；
    结构不符时一律放行，宁可多打不误吞。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _, method, path, _, status = args
        if method != "GET" or not isinstance(status, int):
            return True
        if status >= 400:
            return True
        return not str(path).startswith(_NOISY_GET_PREFIXES)


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, EndpointNoiseFilter) for f in logger.filters):
        logger.addFilter(EndpointNoiseFilter())

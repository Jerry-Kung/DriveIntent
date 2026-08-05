from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "driveintent"
    # 连接池容量需覆盖 worker_concurrency + api_worker_concurrency
    # + Web 请求与 LLM 日志会话的并发峰值
    db_pool_size: int = 15
    db_max_overflow: int = 15
    db_pool_timeout: int = 30
    # FastAPI 同步端点在 anyio 线程池中执行，每个在途请求经 get_db() 独占一条
    # 连接直到请求结束。anyio 默认 40 槽 > 连接池容量 30，超出的请求会阻塞在
    # pool.connect() 上直到 pool_timeout 抛 QueuePool TimeoutError，并连带
    # 拖垮抢同一个池的 worker。故显式收敛，且必须 ≤ pool_size + max_overflow。
    web_threadpool_slots: int = 20

    llm_provider: str = "mock"          # openai_compat | mock
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "mock-model"       # 文本模型
    llm_multimodal_model: str = ""      # 多模态模型；留空回退文本模型
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 3
    # 深度思考开关（全局）；对 openai_compat 请求注入 enable_thinking
    llm_enable_thinking: bool = False

    worker_enabled: bool = True
    worker_concurrency: int = 3
    worker_poll_interval: float = 1.0
    comment_batch_size: int = 30

    api_keys: str = ""
    api_worker_enabled: bool = True
    api_worker_concurrency: int = 3
    # running 作业超过该分钟数无进度更新即判失败（不重试），兜底
    # worker 崩溃/连接池异常导致的遗弃作业
    api_job_stale_minutes: int = 30

    # 我方在售车型配置（Agent2 评级用）
    our_models_config_path: str = "config/our_models.json"

    @property
    def multimodal_model(self) -> str:
        return self.llm_multimodal_model or self.llm_model

    @property
    def api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def db_url(self) -> str:
        user = quote_plus(self.db_user)
        password = quote_plus(self.db_password)
        return (f"mysql+pymysql://{user}:{password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4")


settings = Settings()

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

    llm_provider: str = "mock"          # openai_compat | mock
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "mock-model"       # 文本模型
    llm_multimodal_model: str = ""      # 多模态模型；留空回退文本模型
    llm_model_advanced: str = ""        # 高级模型；留空回退 llm_model
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

    # V1.8.0 意向车型分类标准配置（定级阶段二识别分类用）
    intent_categories_config_path: str = "config/intent_categories.json"

    # V1.4.4 截图暂存目录：base64 原始截图不入库，提交后暂存于此，
    # worker 认领时读回识图，作业终态删除。docker 部署须挂载到宿主机
    # （./data:/app/data），否则容器重启会丢失待处理作业的截图。
    screenshot_staging_dir: str = "data/staging"

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

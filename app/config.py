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

    llm_provider: str = "mock"          # openai_compat | mock
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "mock-model"
    llm_timeout_seconds: int = 120
    llm_max_retries: int = 3

    worker_enabled: bool = True
    worker_concurrency: int = 3
    worker_poll_interval: float = 1.0
    comment_batch_size: int = 30

    api_keys: str = ""
    api_worker_enabled: bool = True
    api_worker_concurrency: int = 3

    # V1.1 我方车型匹配与降级
    our_models_config_path: str = "config/our_models.json"
    intent_downgrade_enabled: bool = True

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

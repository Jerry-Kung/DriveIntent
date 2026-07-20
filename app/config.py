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

    @property
    def db_url(self) -> str:
        return (f"mysql+pymysql://{self.db_user}:{self.db_password}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4")


settings = Settings()

from app.config import Settings


def test_db_url_from_fields():
    s = Settings(db_host="1.2.3.4", db_port=3307, db_user="u",
                 db_password="p", db_name="di")
    assert s.db_url == "mysql+pymysql://u:p@1.2.3.4:3307/di?charset=utf8mb4"


def test_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "mock"
    assert s.comment_batch_size == 30
    assert s.worker_concurrency == 3


def test_api_keys_list_parsing(monkeypatch):
    from app.config import Settings
    s = Settings(api_keys="k1, k2 ,k3")
    assert s.api_keys_list == ["k1", "k2", "k3"]

def test_api_keys_list_empty():
    from app.config import Settings
    s = Settings(api_keys="")
    assert s.api_keys_list == []

def test_api_worker_defaults():
    from app.config import Settings
    s = Settings()
    assert s.api_worker_enabled is True
    assert s.api_worker_concurrency == 3
    assert s.image_fetch_timeout_seconds == 30

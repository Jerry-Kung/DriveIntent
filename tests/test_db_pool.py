"""连接池显式配置：池容量必须可配置且默认值足够 worker + web 并发使用。"""
from app.config import Settings


def test_pool_settings_defaults():
    s = Settings(_env_file=None)
    assert s.db_pool_size == 15
    assert s.db_max_overflow == 15
    assert s.db_pool_timeout == 30


def test_engine_pool_uses_settings():
    from app.config import settings
    from app.db import engine

    assert engine.pool.size() == settings.db_pool_size
    assert engine.pool._max_overflow == settings.db_max_overflow
    assert engine.pool._timeout == settings.db_pool_timeout

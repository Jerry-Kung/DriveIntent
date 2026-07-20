import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base


@pytest.fixture()
def session():
    # StaticPool + check_same_thread=False：FastAPI 的同步路由会在线程池中
    # 执行，测试用的内存 SQLite 连接需要跨线程可用（TestClient 场景，见
    # tests/test_api_tasks.py）。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import app.models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s

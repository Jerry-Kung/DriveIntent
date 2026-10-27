import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base


@pytest.fixture(autouse=True)
def _isolated_lead_record_marker(tmp_path, monkeypatch):
    """把线索汇总表就绪标记指向临时目录。

    V1.10.1：该标记是磁盘上的文件，若用默认路径，测试结果会取决于开发机
    上是否存在 data/lead_record_ready——生产回填完成后它确实存在，会使
    "就绪前应回退"的测试莫名失败。默认指向不存在的位置，需要标记的用例
    自行 monkeypatch。此隔离同时防止测试在仓库里创建该文件。
    """
    monkeypatch.setattr(settings, "lead_record_ready_marker",
                        str(tmp_path / "lead_record_ready"))


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

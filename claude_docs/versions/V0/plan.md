# DriveIntent V0（MVP）实施计划

> 版本：V0 | 日期：2026-07-20

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 DriveIntent V0 端到端闭环：导入抖音评论 Excel 数据 → 三个 LLM Skill 分析 → 产出 H/A/B/C 销售线索 → 页面查看/审核/导出。

**Architecture:** 模块化单体 FastAPI 应用 + MySQL + 进程内 asyncio 后台 Worker。LLM 通过 Gateway 抽象（OpenAI 兼容 Provider + MockProvider），三个 Skill（视频语境 → 评论批量筛选 → 用户综合分析）由固定工作流经数据库任务表驱动。设计文档：`claude_docs/2026-07-20-v0-design.md`。

**Tech Stack:** Python 3.11+、FastAPI、SQLAlchemy 2.0、Pydantic v2 + pydantic-settings、PyMySQL、Jinja2、pandas + openpyxl、httpx、PyYAML、pytest + pytest-asyncio。

## Global Constraints

- 生产数据库为 MySQL（连接配置全部来自 `.env`，见设计文档第 11 节）；**所有自动化测试用 SQLite 内存库**，不依赖 MySQL 和真实 LLM。
- 幂等键：任务 = `task_type + target_type + target_id + skill_version`；L1 数据 = `platform + external_id`。
- 原始数据不可覆盖：video / platform_user / comment 均保存 `raw_data` JSON；重复导入跳过而非重写。
- 所有 LLM 输出必须通过 Pydantic Schema 校验；失败自动重试（默认最多 3 次）。
- 页面与文案使用简体中文。
- 平台标识常量为 `"douyin"`。
- Skill 版本常量：三个 Skill 首版均为 `"1.0"`，prompt_version 均为 `"v1"`。
- 每个任务完成后立即 commit；测试命令统一 `python -m pytest`（工作目录 `D:\KLH\Projects\dfms\DriveIntent`）。

## 文件结构总览

```
app/
├── __init__.py
├── main.py                  # Task 12：FastAPI 入口 + lifespan
├── config.py                # Task 1：Settings
├── db.py                    # Task 2：engine / Base / SessionLocal / init_db
├── models/
│   ├── __init__.py          # Task 2：re-export 全部模型
│   ├── media.py             # Task 2：Video / PlatformUser / Comment
│   ├── analysis.py          # Task 2：AnalysisTask / AnalysisResult / LlmCallLog
│   └── lead.py              # Task 2：Lead
├── schemas/
│   ├── __init__.py
│   ├── import_data.py       # Task 3：VideoIn / UserIn / CommentIn / ImportBundle
│   └── skills.py            # Task 7/8/10：三个 Skill 的输出 Schema
├── importer/
│   ├── __init__.py
│   ├── tags.py              # Task 3：extract_tags
│   ├── excel.py             # Task 4：parse_excel
│   └── core.py              # Task 4：import_bundle / ImportStats
├── llm/
│   ├── __init__.py
│   ├── base.py              # Task 5：LLMResponse / LLMProvider / LLMError
│   ├── mock.py              # Task 5：MockProvider
│   ├── openai_compat.py     # Task 5：OpenAICompatProvider
│   └── gateway.py           # Task 5：LLMGateway / build_gateway
├── skills/
│   ├── __init__.py
│   ├── executor.py          # Task 6：SkillConfig / SkillExecutor / extract_json
│   ├── configs/             # Task 7/8/10：三个 YAML
│   └── prompts/             # Task 7/8/10：三个 Prompt 模板
├── services/
│   ├── __init__.py
│   ├── results.py           # Task 7：save/get AnalysisResult 帮助函数
│   ├── aggregation.py       # Task 9：候选用户 + 证据包
│   └── leads.py             # Task 10/13：upsert_lead / 查询 / CSV 导出
├── workflow/
│   ├── __init__.py
│   ├── tasks.py             # Task 11：任务表 CRUD / 领取 / 重试 / 恢复
│   ├── pipeline.py          # Task 7/8/10/11：阶段执行函数 + advance
│   └── worker.py            # Task 11：Worker 循环
├── web/
│   ├── __init__.py
│   └── routes.py            # Task 12/13：页面 + JSON API
└── templates/               # Task 12/13：index.html / leads.html / lead_detail.html
scripts/
├── make_annotation_template.py  # Task 14
└── evaluate.py                  # Task 14
tests/                       # 各任务对应 test_*.py
.env.example                 # Task 1
requirements.txt             # Task 1
```

说明：设计文档中执行器"保存结果"职责在实现上归属工作流阶段函数（`pipeline.py` + `services/results.py`），因为评论筛选一次调用产出 N 条结果，执行器无法通用落库。执行器只负责：组装 Prompt → 调 Gateway → 解析 JSON → Schema 校验 → 重试。

---

### Task 1: 项目骨架与配置加载

**Files:**
- Create: `requirements.txt`、`.env.example`、`app/__init__.py`、`app/config.py`、`tests/__init__.py`、`tests/test_config.py`、`pytest.ini`

**Interfaces:**
- Produces: `app.config.Settings`（字段见下方代码）、模块级单例 `settings`、`Settings.db_url` 属性。后续所有任务 `from app.config import settings`。

- [ ] **Step 1: 创建 requirements.txt 并安装依赖**

```text
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy>=2.0
pymysql>=1.1
cryptography>=42
pydantic>=2.7
pydantic-settings>=2.3
jinja2>=3.1
python-multipart>=0.0.9
pandas>=2.2
openpyxl>=3.1
httpx>=0.27
pyyaml>=6.0
pytest>=8.2
pytest-asyncio>=0.23
```

Run: `python -m pip install -r requirements.txt`
Expected: 安装成功无报错。

- [ ] **Step 2: 创建 pytest.ini 与包骨架**

`pytest.ini`：

```ini
[pytest]
testpaths = tests
asyncio_mode = auto
```

创建空文件 `app/__init__.py`、`tests/__init__.py`。

- [ ] **Step 3: 写失败测试 tests/test_config.py**

```python
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
```

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: app.config`）

- [ ] **Step 4: 实现 app/config.py**

```python
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
```

- [ ] **Step 5: 创建 .env.example**

```text
# 数据库（MySQL）
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=driveintent

# LLM（openai_compat | mock）
LLM_PROVIDER=mock
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=3

# Worker
WORKER_ENABLED=true
WORKER_CONCURRENCY=3
WORKER_POLL_INTERVAL=1.0
COMMENT_BATCH_SIZE=30
```

- [ ] **Step 6: 跑测试并提交**

Run: `python -m pytest tests/test_config.py -v`
Expected: 2 passed

```bash
git add requirements.txt pytest.ini .env.example app/ tests/
git commit -m "feat: 项目骨架与 .env 配置加载"
```

---

### Task 2: 数据库层与 ORM 模型（7 张表）

**Files:**
- Create: `app/db.py`、`app/models/__init__.py`、`app/models/media.py`、`app/models/analysis.py`、`app/models/lead.py`、`tests/conftest.py`、`tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.settings`
- Produces:
  - `app.db`: `Base`（DeclarativeBase）、`engine`、`SessionLocal`、`init_db(bind=None)`
  - `app.models`: `Video`、`PlatformUser`、`Comment`、`AnalysisTask`、`AnalysisResult`、`LlmCallLog`、`Lead`（字段见下方代码，后续任务以此为准）
  - `tests/conftest.py`: pytest fixture `session`（SQLite 内存库 Session）

- [ ] **Step 1: 写失败测试 tests/conftest.py + tests/test_models.py**

`tests/conftest.py`：

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    import app.models  # noqa: F401  确保模型已注册
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s
```

`tests/test_models.py`：

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Comment, PlatformUser, Video


def _mk(session):
    v = Video(platform="douyin", external_id="v1", title="t", description="d")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="n")
    session.add_all([v, u])
    session.flush()
    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="hello")
    session.add(c)
    session.flush()
    return v, u, c


def test_create_core_rows(session):
    v, u, c = _mk(session)
    assert v.id and u.id and c.id


def test_video_unique_constraint(session):
    _mk(session)
    session.add(Video(platform="douyin", external_id="v1"))
    with pytest.raises(IntegrityError):
        session.flush()
```

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL（`ModuleNotFoundError: app.db`）

- [ ] **Step 2: 实现 app/db.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.db_url, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None) -> None:
    import app.models  # noqa: F401
    Base.metadata.create_all(bind or engine)
```

- [ ] **Step 3: 实现 app/models/media.py**

```python
from datetime import datetime

from sqlalchemy import (JSON, DateTime, ForeignKey, Index, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Video(Base):
    __tablename__ = "video"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_video_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON)
    author_name: Mapped[str | None] = mapped_column(String(255))
    account_type: Mapped[str | None] = mapped_column(String(32))
    publish_time: Mapped[datetime | None] = mapped_column(DateTime)
    transcript: Mapped[str | None] = mapped_column(Text)
    preset_brand: Mapped[str | None] = mapped_column(String(64))
    preset_model: Mapped[str | None] = mapped_column(String(64))
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class PlatformUser(Base):
    __tablename__ = "platform_user"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_user_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    nickname: Mapped[str] = mapped_column(String(255), default="")
    avatar_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(64))
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class Comment(Base):
    __tablename__ = "comment"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_comment_ext"),
        Index("ix_comment_video", "video_id"),
        Index("ix_comment_user", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_user.id"))
    content: Mapped[str] = mapped_column(Text)
    comment_time: Mapped[datetime | None] = mapped_column(DateTime)
    like_count: Mapped[int | None] = mapped_column()
    reply_count: Mapped[int | None] = mapped_column()
    is_reply: Mapped[bool | None] = mapped_column()
    raw_data: Mapped[dict | None] = mapped_column(JSON)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: 实现 app/models/analysis.py**

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AnalysisTask(Base):
    __tablename__ = "analysis_task"
    __table_args__ = (
        UniqueConstraint("task_type", "target_type", "target_id",
                         "skill_version", name="uq_task_idem"),
        Index("ix_task_status", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    skill_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    payload: Mapped[dict | None] = mapped_column(JSON)
    attempt_count: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisResult(Base):
    __tablename__ = "analysis_result"
    __table_args__ = (
        Index("ix_result_target", "target_type", "target_id", "skill_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    skill_id: Mapped[str] = mapped_column(String(64))
    skill_version: Mapped[str] = mapped_column(String(16))
    model_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(16), default="success")
    result: Mapped[dict | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)


class LlmCallLog(Base):
    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String(64), default="")
    skill_version: Mapped[str] = mapped_column(String(16), default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_version: Mapped[str] = mapped_column(String(16), default="")
    input_digest: Mapped[str | None] = mapped_column(Text)
    output_text: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
```

- [ ] **Step 5: 实现 app/models/lead.py 与 app/models/__init__.py**

`app/models/lead.py`：

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Lead(Base):
    __tablename__ = "lead"
    __table_args__ = (Index("ix_lead_user", "user_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_user.id"))
    grade: Mapped[str] = mapped_column(String(4))            # H/A/B/C
    is_valid: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    target_brands: Mapped[list | None] = mapped_column(JSON)
    target_models: Mapped[list | None] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text, default="")
    purchase_stage: Mapped[str | None] = mapped_column(String(64))
    core_needs: Mapped[list | None] = mapped_column(JSON)
    main_concerns: Mapped[list | None] = mapped_column(JSON)
    purchase_time: Mapped[str | None] = mapped_column(String(64))
    usage_scenario: Mapped[str | None] = mapped_column(String(255))
    entry_point: Mapped[str | None] = mapped_column(Text)
    verification_questions: Mapped[list | None] = mapped_column(JSON)
    evidence: Mapped[list | None] = mapped_column(JSON)      # [{comment_id, content}]
    confidence: Mapped[float | None] = mapped_column(Float)
    skill_version: Mapped[str] = mapped_column(String(16), default="")
    review_status: Mapped[str] = mapped_column(String(16), default="unreviewed")
    review_tags: Mapped[list | None] = mapped_column(JSON)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

`app/models/__init__.py`：

```python
from app.models.analysis import AnalysisResult, AnalysisTask, LlmCallLog
from app.models.lead import Lead
from app.models.media import Comment, PlatformUser, Video

__all__ = ["AnalysisResult", "AnalysisTask", "LlmCallLog", "Lead",
           "Comment", "PlatformUser", "Video"]
```

- [ ] **Step 6: 跑测试并提交**

Run: `python -m pytest tests/test_models.py -v`
Expected: 2 passed

```bash
git add app/db.py app/models/ tests/conftest.py tests/test_models.py
git commit -m "feat: 7 张核心表的 ORM 模型与数据库初始化"
```

---

### Task 3: 话题标签解析与导入 Schema

**Files:**
- Create: `app/schemas/__init__.py`（空）、`app/schemas/import_data.py`、`app/importer/__init__.py`（空）、`app/importer/tags.py`、`tests/test_tags.py`

**Interfaces:**
- Produces:
  - `app.importer.tags.extract_tags(text: str) -> list[str]`（去重、保序）
  - `app.schemas.import_data`: `VideoIn`、`UserIn`、`CommentIn`、`ImportBundle`（字段见代码；Task 4 的 Excel 解析和导入均以此为中间格式）

- [ ] **Step 1: 写失败测试 tests/test_tags.py**

```python
from app.importer.tags import extract_tags


def test_extract_tags_basic():
    text = "全新坦克300 会有8缸版本！ #小报告 #坦克300 #SUV"
    assert extract_tags(text) == ["小报告", "坦克300", "SUV"]


def test_extract_tags_dedup_and_empty():
    assert extract_tags("#a #b #a") == ["a", "b"]
    assert extract_tags("") == []
    assert extract_tags("没有标签") == []
```

Run: `python -m pytest tests/test_tags.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 2: 实现 app/importer/tags.py**

```python
import re

_TAG_RE = re.compile(r"#([^#\s@]+)")


def extract_tags(text: str) -> list[str]:
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _TAG_RE.finditer(text):
        tag = m.group(1).strip()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out
```

- [ ] **Step 3: 实现 app/schemas/import_data.py**

```python
from datetime import datetime

from pydantic import BaseModel


class VideoIn(BaseModel):
    platform: str = "douyin"
    external_id: str
    title: str = ""
    description: str = ""
    cover_url: str | None = None
    raw: dict | None = None


class UserIn(BaseModel):
    platform: str = "douyin"
    external_id: str
    nickname: str = ""
    raw: dict | None = None


class CommentIn(BaseModel):
    platform: str = "douyin"
    external_id: str
    video_external_id: str
    user_external_id: str
    content: str
    comment_time: datetime | None = None
    raw: dict | None = None


class ImportBundle(BaseModel):
    videos: list[VideoIn] = []
    users: list[UserIn] = []
    comments: list[CommentIn] = []
    skipped_empty_comments: int = 0
```

- [ ] **Step 4: 跑测试并提交**

Run: `python -m pytest tests/test_tags.py -v`
Expected: 3 passed

```bash
git add app/schemas/ app/importer/ tests/test_tags.py
git commit -m "feat: 话题标签解析与标准导入格式 Schema"
```

---

### Task 4: Excel 解析与幂等导入

**Files:**
- Create: `app/importer/excel.py`、`app/importer/core.py`、`tests/test_importer.py`

**Interfaces:**
- Consumes: `ImportBundle` 及三个 In-模型（Task 3）、`app.models`（Task 2）、`extract_tags`（Task 3）
- Produces:
  - `app.importer.excel.parse_excel(path: str | Path) -> ImportBundle`
  - `app.importer.core.ImportStats`（Pydantic：`videos_new/videos_skipped/users_new/users_skipped/comments_new/comments_skipped/empty_comments` 均 int 默认 0）
  - `app.importer.core.import_bundle(session, bundle: ImportBundle) -> ImportStats`（幂等，Task 12 的导入 API 调用它）

- [ ] **Step 1: 写失败测试 tests/test_importer.py**

```python
from datetime import datetime

from app.importer.core import import_bundle
from app.models import Comment, PlatformUser, Video
from app.schemas.import_data import CommentIn, ImportBundle, UserIn, VideoIn


def _bundle():
    return ImportBundle(
        videos=[VideoIn(external_id="v1", title="标题 #坦克300",
                        description="文案 #SUV", raw={"aweme_id": "v1"})],
        users=[UserIn(external_id="u1", nickname="用户一")],
        comments=[CommentIn(external_id="c1", video_external_id="v1",
                            user_external_id="u1", content="落地多少钱",
                            comment_time=datetime(2026, 7, 1, 12, 0, 0))],
        skipped_empty_comments=2)


def test_import_bundle_writes_rows(session):
    stats = import_bundle(session, _bundle())
    assert stats.videos_new == 1 and stats.users_new == 1
    assert stats.comments_new == 1 and stats.empty_comments == 2
    v = session.query(Video).one()
    assert v.tags == ["坦克300", "SUV"]          # title+description 中解析
    assert v.raw_data == {"aweme_id": "v1"}
    c = session.query(Comment).one()
    assert c.video_id == v.id
    assert c.user_id == session.query(PlatformUser).one().id


def test_import_bundle_idempotent(session):
    import_bundle(session, _bundle())
    stats = import_bundle(session, _bundle())
    assert stats.videos_new == 0 and stats.videos_skipped == 1
    assert stats.comments_new == 0 and stats.comments_skipped == 1
    assert session.query(Comment).count() == 1
```

Run: `python -m pytest tests/test_importer.py -v`
Expected: FAIL（`ModuleNotFoundError: app.importer.core`）

- [ ] **Step 2: 实现 app/importer/core.py**

```python
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.importer.tags import extract_tags
from app.models import Comment, PlatformUser, Video
from app.schemas.import_data import ImportBundle


class ImportStats(BaseModel):
    videos_new: int = 0
    videos_skipped: int = 0
    users_new: int = 0
    users_skipped: int = 0
    comments_new: int = 0
    comments_skipped: int = 0
    empty_comments: int = 0


def _existing_ids(session: Session, model, platform: str) -> dict[str, int]:
    rows = session.query(model.external_id, model.id).filter(
        model.platform == platform).all()
    return {ext: pk for ext, pk in rows}


def import_bundle(session: Session, bundle: ImportBundle) -> ImportStats:
    stats = ImportStats(empty_comments=bundle.skipped_empty_comments)
    platform = "douyin"

    video_ids = _existing_ids(session, Video, platform)
    for v in bundle.videos:
        if v.external_id in video_ids:
            stats.videos_skipped += 1
            continue
        row = Video(platform=v.platform, external_id=v.external_id,
                    title=v.title, description=v.description,
                    cover_url=v.cover_url,
                    tags=extract_tags(f"{v.title} {v.description}"),
                    raw_data=v.raw)
        session.add(row)
        session.flush()
        video_ids[v.external_id] = row.id
        stats.videos_new += 1

    user_ids = _existing_ids(session, PlatformUser, platform)
    for u in bundle.users:
        if u.external_id in user_ids:
            stats.users_skipped += 1
            continue
        row = PlatformUser(platform=u.platform, external_id=u.external_id,
                           nickname=u.nickname, raw_data=u.raw)
        session.add(row)
        session.flush()
        user_ids[u.external_id] = row.id
        stats.users_new += 1

    existing_comments = set(
        _existing_ids(session, Comment, platform).keys())
    for c in bundle.comments:
        if c.external_id in existing_comments:
            stats.comments_skipped += 1
            continue
        vid = video_ids.get(c.video_external_id)
        uid = user_ids.get(c.user_external_id)
        if vid is None or uid is None:
            stats.comments_skipped += 1
            continue
        session.add(Comment(platform=c.platform, external_id=c.external_id,
                            video_id=vid, user_id=uid, content=c.content,
                            comment_time=c.comment_time, raw_data=c.raw))
        existing_comments.add(c.external_id)
        stats.comments_new += 1

    session.commit()
    return stats
```

- [ ] **Step 3: 跑导入测试通过**

Run: `python -m pytest tests/test_importer.py -v`
Expected: 2 passed

- [ ] **Step 4: 写失败测试（Excel 解析），追加到 tests/test_importer.py**

```python
import pandas as pd

from app.importer.excel import parse_excel


def test_parse_excel(tmp_path):
    df = pd.DataFrame([
        {"aweme_id": "1001", "title": "标题A #SUV", "desc": "文案A",
         "cover_url": "http://x/1.jpg", "nickname": "小明",
         "sec_uid": "sec_1", "comment_id": "9001",
         "content": "落地多少钱", "create_time": 1783783725},
        {"aweme_id": "1001", "title": "标题A #SUV", "desc": "文案A",
         "cover_url": "http://x/1.jpg", "nickname": "小红",
         "sec_uid": "sec_2", "comment_id": "9002",
         "content": None, "create_time": 1783783726},
    ])
    path = tmp_path / "t.xlsx"
    df.to_excel(path, index=False)

    bundle = parse_excel(path)
    assert len(bundle.videos) == 1          # 同视频去重
    assert len(bundle.users) == 2
    assert len(bundle.comments) == 1        # 空评论被跳过
    assert bundle.skipped_empty_comments == 1
    c = bundle.comments[0]
    assert c.external_id == "9001" and c.video_external_id == "1001"
    assert c.comment_time is not None
```

Run: `python -m pytest tests/test_importer.py::test_parse_excel -v`
Expected: FAIL（`ModuleNotFoundError: app.importer.excel`）

- [ ] **Step 5: 实现 app/importer/excel.py**

```python
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.schemas.import_data import CommentIn, ImportBundle, UserIn, VideoIn


def _clean(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def parse_excel(path: str | Path) -> ImportBundle:
    df = pd.read_excel(path, sheet_name=0,
                       dtype={"aweme_id": str, "comment_id": str,
                              "sec_uid": str})
    videos: dict[str, VideoIn] = {}
    users: dict[str, UserIn] = {}
    comments: list[CommentIn] = []
    skipped = 0

    for _, row in df.iterrows():
        d = {k: _clean(v) for k, v in row.to_dict().items()}
        aweme_id = str(d["aweme_id"])
        sec_uid = str(d["sec_uid"])

        if aweme_id not in videos:
            videos[aweme_id] = VideoIn(
                external_id=aweme_id,
                title=str(d.get("title") or ""),
                description=str(d.get("desc") or ""),
                cover_url=d.get("cover_url"),
                raw={"aweme_id": aweme_id, "title": d.get("title"),
                     "desc": d.get("desc"), "cover_url": d.get("cover_url")})
        if sec_uid not in users:
            users[sec_uid] = UserIn(
                external_id=sec_uid,
                nickname=str(d.get("nickname") or ""),
                raw={"sec_uid": sec_uid, "nickname": d.get("nickname")})

        content = d.get("content")
        if content is None or not str(content).strip():
            skipped += 1
            continue
        ts = d.get("create_time")
        comment_time = None
        if ts is not None:
            comment_time = datetime.fromtimestamp(
                int(ts), tz=timezone.utc).replace(tzinfo=None)
        comments.append(CommentIn(
            external_id=str(d["comment_id"]),
            video_external_id=aweme_id,
            user_external_id=sec_uid,
            content=str(content),
            comment_time=comment_time,
            raw={"comment_id": str(d["comment_id"]),
                 "content": str(content), "create_time": ts}))

    return ImportBundle(videos=list(videos.values()),
                        users=list(users.values()),
                        comments=comments,
                        skipped_empty_comments=skipped)
```

- [ ] **Step 6: 跑全部测试并提交**

Run: `python -m pytest -v`
Expected: 全部通过

```bash
git add app/importer/ tests/test_importer.py
git commit -m "feat: Excel 解析与幂等数据导入"
```

---

### Task 5: LLM Gateway（Mock + OpenAI 兼容 + 重试 + 调用日志）

**Files:**
- Create: `app/llm/__init__.py`（空）、`app/llm/base.py`、`app/llm/mock.py`、`app/llm/openai_compat.py`、`app/llm/gateway.py`、`tests/test_llm_gateway.py`

**Interfaces:**
- Consumes: `settings`（Task 1）、`LlmCallLog`（Task 2）
- Produces:
  - `app.llm.base`: `LLMResponse(text, prompt_tokens=0, completion_tokens=0, duration_ms=0)`、`LLMError(Exception)`、抽象类 `LLMProvider.chat(messages, *, model, temperature) -> LLMResponse`
  - `app.llm.mock.MockProvider`：`queue(*texts)` 预置响应，`chat` 依次弹出；队列空抛 `LLMError`
  - `app.llm.gateway.LLMGateway`：`__init__(provider, *, session_factory=None, max_retries=None)`；`async chat(messages, *, skill_id="", skill_version="", prompt_version="", model=None, temperature=None) -> LLMResponse`（重试 + 落 llm_call_log）
  - `app.llm.gateway.build_gateway(session_factory=None) -> LLMGateway`（按 `settings.llm_provider` 选 Provider）

- [ ] **Step 1: 写失败测试 tests/test_llm_gateway.py**

```python
import pytest

from app.llm.base import LLMError
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import LlmCallLog


class FlakyProvider(MockProvider):
    """前 N 次抛错，之后走 MockProvider 队列。"""

    def __init__(self, fail_times: int):
        super().__init__()
        self.fail_times = fail_times

    async def chat(self, messages, *, model, temperature):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise LLMError("boom")
        return await super().chat(messages, model=model,
                                  temperature=temperature)


async def test_gateway_returns_text():
    provider = MockProvider()
    provider.queue('{"ok": true}')
    gw = LLMGateway(provider)
    resp = await gw.chat([{"role": "user", "content": "hi"}])
    assert resp.text == '{"ok": true}'


async def test_gateway_retries_then_succeeds(session):
    provider = FlakyProvider(fail_times=2)
    provider.queue("done")
    gw = LLMGateway(provider, session_factory=lambda: session,
                    max_retries=3)
    resp = await gw.chat([{"role": "user", "content": "hi"}],
                         skill_id="s1", skill_version="1.0")
    assert resp.text == "done"
    logs = session.query(LlmCallLog).all()
    assert len(logs) == 3                      # 2 失败 + 1 成功
    assert logs[-1].error is None


async def test_gateway_raises_after_max_retries():
    gw = LLMGateway(FlakyProvider(fail_times=99), max_retries=2)
    with pytest.raises(LLMError):
        await gw.chat([{"role": "user", "content": "hi"}])
```

注意：`session` fixture 的 Session 在测试里被 gateway 复用，`session_factory=lambda: session` 即可，gateway 内部不得 close 传入的 session（实现里用 try/finally 只 commit）。

Run: `python -m pytest tests/test_llm_gateway.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 2: 实现 app/llm/base.py 与 app/llm/mock.py**

`app/llm/base.py`：

```python
import abc

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0


class LLMError(Exception):
    pass


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float) -> LLMResponse:
        ...
```

`app/llm/mock.py`：

```python
from app.llm.base import LLMError, LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    def __init__(self):
        self._responses: list[str] = []

    def queue(self, *texts: str) -> None:
        self._responses.extend(texts)

    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float) -> LLMResponse:
        if not self._responses:
            raise LLMError("MockProvider: 无预置响应")
        return LLMResponse(text=self._responses.pop(0))
```

- [ ] **Step 3: 实现 app/llm/openai_compat.py**

```python
import httpx

from app.config import settings
from app.llm.base import LLMError, LLMProvider, LLMResponse


class OpenAICompatProvider(LLMProvider):
    def __init__(self, base_url: str = "", api_key: str = "",
                 timeout: int = 0):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.timeout = timeout or settings.llm_timeout_seconds

    async def chat(self, messages: list[dict], *, model: str,
                   temperature: float) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": model, "messages": messages,
                   "temperature": temperature}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(url, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as e:
            raise LLMError(f"LLM 请求失败: {e}") from e
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"LLM 响应格式异常: {data}") from e
        if not text:
            raise LLMError("LLM 返回空内容")
        usage = data.get("usage") or {}
        return LLMResponse(text=text,
                           prompt_tokens=usage.get("prompt_tokens", 0),
                           completion_tokens=usage.get("completion_tokens", 0))
```

- [ ] **Step 4: 实现 app/llm/gateway.py**

```python
import asyncio
import time

from app.config import settings
from app.llm.base import LLMError, LLMProvider, LLMResponse
from app.llm.mock import MockProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.models import LlmCallLog


class LLMGateway:
    def __init__(self, provider: LLMProvider, *, session_factory=None,
                 max_retries: int | None = None):
        self.provider = provider
        self.session_factory = session_factory
        self.max_retries = max_retries or settings.llm_max_retries

    def _log(self, *, skill_id, skill_version, prompt_version, model,
             messages, resp: LLMResponse | None, error: str | None,
             duration_ms: int, retry_count: int) -> None:
        if self.session_factory is None:
            return
        try:
            s = self.session_factory()
            s.add(LlmCallLog(
                skill_id=skill_id, skill_version=skill_version,
                prompt_version=prompt_version, model_name=model,
                input_digest=str(messages)[-2000:],
                output_text=resp.text[:8000] if resp else None,
                prompt_tokens=resp.prompt_tokens if resp else 0,
                completion_tokens=resp.completion_tokens if resp else 0,
                duration_ms=duration_ms, error=error,
                retry_count=retry_count))
            s.commit()
        except Exception:
            pass  # 日志失败不影响主流程

    async def chat(self, messages: list[dict], *, skill_id: str = "",
                   skill_version: str = "", prompt_version: str = "",
                   model: str | None = None,
                   temperature: float | None = None) -> LLMResponse:
        model = model or settings.llm_model
        temperature = 0.1 if temperature is None else temperature
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            start = time.monotonic()
            try:
                resp = await self.provider.chat(
                    messages, model=model, temperature=temperature)
                self._log(skill_id=skill_id, skill_version=skill_version,
                          prompt_version=prompt_version, model=model,
                          messages=messages, resp=resp, error=None,
                          duration_ms=int((time.monotonic() - start) * 1000),
                          retry_count=attempt)
                return resp
            except LLMError as e:
                last_error = e
                self._log(skill_id=skill_id, skill_version=skill_version,
                          prompt_version=prompt_version, model=model,
                          messages=messages, resp=None, error=str(e),
                          duration_ms=int((time.monotonic() - start) * 1000),
                          retry_count=attempt)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(0.1 * (attempt + 1))
        raise LLMError(f"LLM 调用重试 {self.max_retries} 次后失败: {last_error}")


def build_gateway(session_factory=None) -> LLMGateway:
    if settings.llm_provider == "openai_compat":
        provider: LLMProvider = OpenAICompatProvider()
    else:
        provider = MockProvider()
    return LLMGateway(provider, session_factory=session_factory)
```

- [ ] **Step 5: 跑测试并提交**

Run: `python -m pytest tests/test_llm_gateway.py -v`
Expected: 3 passed

```bash
git add app/llm/ tests/test_llm_gateway.py
git commit -m "feat: LLM Gateway（Mock/OpenAI 兼容 Provider、重试、调用日志）"
```

---

### Task 6: Skill 配置加载与执行器

**Files:**
- Create: `app/skills/__init__.py`（空）、`app/skills/executor.py`、`app/skills/configs/.gitkeep`、`app/skills/prompts/.gitkeep`、`tests/test_skill_executor.py`

**Interfaces:**
- Consumes: `LLMGateway`（Task 5）
- Produces:
  - `SkillConfig`（Pydantic）：`skill_id, version, description="", model_name="", temperature=0.1, prompt_file, prompt_version`
  - `load_skill_config(skill_id: str) -> SkillConfig`（读 `app/skills/configs/{skill_id}.yaml`）
  - `render_prompt(config: SkillConfig, context: dict[str, str]) -> str`（`string.Template.substitute`，占位符形如 `$video_json`；模板中的 JSON 花括号无需转义）
  - `extract_json(text: str)`（剥离 ```json 围栏，截取首个 `{`/`[` 到末个 `}`/`]`）
  - `SkillExecutionError(Exception)`
  - `SkillExecutor(gateway)`：`async run(skill_id, context: dict, output_model: type[BaseModel]) -> BaseModel`（解析/校验失败自动重调，最多 `settings.llm_max_retries` 次）

- [ ] **Step 1: 写失败测试 tests/test_skill_executor.py**

```python
import pytest
from pydantic import BaseModel

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.skills.executor import (SkillConfig, SkillExecutionError,
                                 SkillExecutor, extract_json, render_prompt)


class Out(BaseModel):
    answer: str


def test_extract_json_with_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('前缀 [1, 2] 后缀') == [1, 2]
    with pytest.raises(ValueError):
        extract_json("完全不是 JSON")


def test_render_prompt_keeps_json_braces():
    cfg = SkillConfig(skill_id="t", version="1.0", prompt_file="x.txt",
                      prompt_version="v1")
    tpl = '输出 {"k": "v"} 格式。输入：$data'
    assert render_prompt(cfg, {"data": "abc"}, template_text=tpl) == \
        '输出 {"k": "v"} 格式。输入：abc'


async def test_executor_retries_bad_json(tmp_path, monkeypatch):
    # 准备临时 skill 配置与 prompt
    cfg_dir = tmp_path / "configs"
    prompt_dir = tmp_path / "prompts"
    cfg_dir.mkdir(); prompt_dir.mkdir()
    (cfg_dir / "demo.yaml").write_text(
        'skill_id: demo\nversion: "1.0"\nmodel:\n  name: ""\n'
        '  temperature: 0.1\nprompt_file: demo_v1.txt\n'
        'prompt_version: "v1"\n', encoding="utf-8")
    (prompt_dir / "demo_v1.txt").write_text("回答：$q", encoding="utf-8")
    import app.skills.executor as ex
    monkeypatch.setattr(ex, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ex, "PROMPT_DIR", prompt_dir)

    provider = MockProvider()
    provider.queue("不是JSON", '{"answer": "好"}')   # 第 1 次坏，第 2 次好
    executor = SkillExecutor(LLMGateway(provider))
    out = await executor.run("demo", {"q": "hi"}, Out)
    assert out.answer == "好"


async def test_executor_fails_after_retries(tmp_path, monkeypatch):
    import app.skills.executor as ex
    cfg_dir = tmp_path / "configs"; prompt_dir = tmp_path / "prompts"
    cfg_dir.mkdir(); prompt_dir.mkdir()
    (cfg_dir / "demo.yaml").write_text(
        'skill_id: demo\nversion: "1.0"\nmodel:\n  name: ""\n'
        '  temperature: 0.1\nprompt_file: demo_v1.txt\n'
        'prompt_version: "v1"\n', encoding="utf-8")
    (prompt_dir / "demo_v1.txt").write_text("$q", encoding="utf-8")
    monkeypatch.setattr(ex, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ex, "PROMPT_DIR", prompt_dir)

    provider = MockProvider()
    provider.queue("bad", "bad", "bad")
    executor = SkillExecutor(LLMGateway(provider), max_retries=3)
    with pytest.raises(SkillExecutionError):
        await executor.run("demo", {"q": "hi"}, Out)
```

Run: `python -m pytest tests/test_skill_executor.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 2: 实现 app/skills/executor.py**

```python
import json
from pathlib import Path
from string import Template

import yaml
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.llm.base import LLMError
from app.llm.gateway import LLMGateway

CONFIG_DIR = Path(__file__).parent / "configs"
PROMPT_DIR = Path(__file__).parent / "prompts"


class SkillConfig(BaseModel):
    skill_id: str
    version: str
    description: str = ""
    model_name: str = ""
    temperature: float = 0.1
    prompt_file: str
    prompt_version: str


class SkillExecutionError(Exception):
    pass


def load_skill_config(skill_id: str) -> SkillConfig:
    path = CONFIG_DIR / f"{skill_id}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    model = data.pop("model", {}) or {}
    return SkillConfig(model_name=model.get("name", ""),
                       temperature=model.get("temperature", 0.1), **data)


def render_prompt(config: SkillConfig, context: dict[str, str],
                  template_text: str | None = None) -> str:
    if template_text is None:
        template_text = (PROMPT_DIR / config.prompt_file).read_text(
            encoding="utf-8")
    return Template(template_text).substitute(context)


def extract_json(text: str):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise ValueError(f"输出中未找到 JSON: {text[:200]}")
    start = min(starts)
    end = max(cleaned.rfind("}"), cleaned.rfind("]"))
    if end <= start:
        raise ValueError(f"输出中 JSON 不完整: {text[:200]}")
    return json.loads(cleaned[start:end + 1])


class SkillExecutor:
    def __init__(self, gateway: LLMGateway, max_retries: int | None = None):
        self.gateway = gateway
        self.max_retries = max_retries or settings.llm_max_retries

    async def run(self, skill_id: str, context: dict[str, str],
                  output_model: type[BaseModel]) -> BaseModel:
        config = load_skill_config(skill_id)
        prompt = render_prompt(config, context)
        messages = [{"role": "user", "content": prompt}]
        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                resp = await self.gateway.chat(
                    messages, skill_id=config.skill_id,
                    skill_version=config.version,
                    prompt_version=config.prompt_version,
                    model=config.model_name or None,
                    temperature=config.temperature)
            except LLMError as e:
                last_error = e
                continue
            try:
                data = extract_json(resp.text)
                return output_model.model_validate(data)
            except (ValueError, ValidationError) as e:
                last_error = e
                continue
        raise SkillExecutionError(
            f"Skill {skill_id} 执行失败: {last_error}")
```

- [ ] **Step 3: 跑测试并提交**

Run: `python -m pytest tests/test_skill_executor.py -v`
Expected: 4 passed

```bash
git add app/skills/ tests/test_skill_executor.py
git commit -m "feat: Skill 配置加载与执行器（JSON 提取、Schema 校验、重试）"
```

---

### Task 7: Skill 1 视频语境理解（Schema + Prompt + 阶段函数）

**Files:**
- Create: `app/schemas/skills.py`、`app/services/__init__.py`（空）、`app/services/results.py`、`app/workflow/__init__.py`（空）、`app/workflow/pipeline.py`、`app/skills/configs/video_context_analysis.yaml`、`app/skills/prompts/video_context_analysis_v1.txt`、`tests/test_video_context.py`

**Interfaces:**
- Consumes: `SkillExecutor`（Task 6）、`AnalysisResult`/`Video`（Task 2）
- Produces:
  - `app.schemas.skills.VideoContextResult`（字段见代码）
  - `app.services.results.save_result(session, *, target_type, target_id, skill_id, skill_version, result: dict, confidence=None, model_name="", prompt_version="") -> AnalysisResult`
  - `app.services.results.get_current_result(session, *, target_type, target_id, skill_id, skill_version) -> AnalysisResult | None`（同版本取最新一条 success）
  - `app.workflow.pipeline.VIDEO_CONTEXT_SKILL = "video_context_analysis"`、`SKILL_VERSIONS = {"video_context_analysis": "1.0", "comment_lead_screening": "1.0", "user_lead_analysis": "1.0"}`
  - `app.workflow.pipeline.run_video_context(session, executor, video_id: int) -> None`（执行并落库）

- [ ] **Step 1: 实现 app/schemas/skills.py 中的 VideoContextResult**

```python
from pydantic import BaseModel


class VideoContextResult(BaseModel):
    brand: str | None = None
    model: str | None = None
    content_type: str | None = None
    main_topics: list[str] = []
    target_audience: str | None = None
    competitor_models: list[str] = []
    commercial_context: str | None = None
    analysis_notes: str | None = None
```

- [ ] **Step 2: 写失败测试 tests/test_video_context.py**

```python
from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Video
from app.services.results import get_current_result
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (SKILL_VERSIONS, VIDEO_CONTEXT_SKILL,
                                   run_video_context)

CONTEXT_JSON = ('{"brand": "坦克", "model": "坦克300", '
                '"content_type": "新车发布", "main_topics": ["动力"], '
                '"target_audience": "越野爱好者", "competitor_models": [], '
                '"commercial_context": "汽车媒体", '
                '"analysis_notes": "关注价格类评论"}')


async def test_run_video_context_saves_result(session):
    v = Video(platform="douyin", external_id="v1",
              title="全新坦克300 #SUV", description="8缸版本", tags=["SUV"])
    session.add(v)
    session.commit()

    provider = MockProvider()
    provider.queue(CONTEXT_JSON)
    executor = SkillExecutor(LLMGateway(provider))

    await run_video_context(session, executor, v.id)

    r = get_current_result(session, target_type="video", target_id=str(v.id),
                           skill_id=VIDEO_CONTEXT_SKILL,
                           skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
    assert r is not None
    assert r.result["brand"] == "坦克"
    assert r.result["model"] == "坦克300"
```

Run: `python -m pytest tests/test_video_context.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 app/services/results.py**

```python
from sqlalchemy.orm import Session

from app.models import AnalysisResult


def save_result(session: Session, *, target_type: str, target_id: str,
                skill_id: str, skill_version: str, result: dict,
                confidence: float | None = None, model_name: str = "",
                prompt_version: str = "") -> AnalysisResult:
    row = AnalysisResult(target_type=target_type, target_id=target_id,
                         skill_id=skill_id, skill_version=skill_version,
                         model_name=model_name, prompt_version=prompt_version,
                         status="success", result=result,
                         confidence=confidence)
    session.add(row)
    session.commit()
    return row


def get_current_result(session: Session, *, target_type: str, target_id: str,
                       skill_id: str,
                       skill_version: str) -> AnalysisResult | None:
    return (session.query(AnalysisResult)
            .filter_by(target_type=target_type, target_id=target_id,
                       skill_id=skill_id, skill_version=skill_version,
                       status="success")
            .order_by(AnalysisResult.id.desc())
            .first())
```

- [ ] **Step 4: 实现 app/workflow/pipeline.py（首版只含视频语境阶段）**

```python
import json

from sqlalchemy.orm import Session

from app.models import Video
from app.schemas.skills import VideoContextResult
from app.services.results import save_result
from app.skills.executor import SkillExecutor

VIDEO_CONTEXT_SKILL = "video_context_analysis"
COMMENT_SCREENING_SKILL = "comment_lead_screening"
USER_ANALYSIS_SKILL = "user_lead_analysis"

SKILL_VERSIONS = {
    VIDEO_CONTEXT_SKILL: "1.0",
    COMMENT_SCREENING_SKILL: "1.0",
    USER_ANALYSIS_SKILL: "1.0",
}


async def run_video_context(session: Session, executor: SkillExecutor,
                            video_id: int) -> None:
    video = session.get(Video, video_id)
    if video is None:
        raise ValueError(f"视频不存在: {video_id}")
    context = {
        "video_json": json.dumps({
            "title": video.title,
            "description": video.description,
            "tags": video.tags or [],
            "account_type": video.account_type or "未知",
            "transcript": video.transcript or "",
            "preset_brand": video.preset_brand or "",
            "preset_model": video.preset_model or "",
        }, ensure_ascii=False),
    }
    out: VideoContextResult = await executor.run(
        VIDEO_CONTEXT_SKILL, context, VideoContextResult)
    save_result(session, target_type="video", target_id=str(video_id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result=out.model_dump())
```

- [ ] **Step 5: 创建 Skill 配置与 Prompt**

`app/skills/configs/video_context_analysis.yaml`：

```yaml
skill_id: video_context_analysis
version: "1.0"
description: >
  理解短视频语境：识别品牌车型、内容类型、主要话题、受众、竞品与商业属性，
  并给出评论分析注意事项。
model:
  name: ""          # 空则使用 .env 的 LLM_MODEL
  temperature: 0.1
prompt_file: video_context_analysis_v1.txt
prompt_version: "v1"
```

`app/skills/prompts/video_context_analysis_v1.txt`：

```text
你是汽车行业短视频内容分析专家。请分析以下抖音视频信息，输出视频语境，供后续评论分析使用。

视频信息（JSON）：
$video_json

请严格输出以下 JSON 格式（不要输出任何其他内容，不要用 Markdown 代码块）：
{
  "brand": "视频主要涉及的品牌，无法判断则为 null",
  "model": "视频主要涉及的车型，无法判断则为 null",
  "content_type": "内容类型，如：新车发布/评测/对比/用车分享/营销宣传",
  "main_topics": ["主要讨论主题，如价格、动力、空间"],
  "target_audience": "目标受众描述",
  "competitor_models": ["视频中提到或暗示的竞品车型"],
  "commercial_context": "商业属性，如：车企官方宣传/汽车媒体/个人博主",
  "analysis_notes": "针对该视频评论分析的注意事项，一句话"
}

要求：
1. 只依据给出的信息判断，不要编造。
2. 品牌车型尽量使用规范名称（如"坦克300"而不是"坦克三百"）。
```

- [ ] **Step 6: 跑测试并提交**

Run: `python -m pytest tests/test_video_context.py -v`
Expected: 1 passed

```bash
git add app/schemas/skills.py app/services/ app/workflow/ app/skills/configs/ app/skills/prompts/ tests/test_video_context.py
git commit -m "feat: 视频语境理解 Skill 与结果落库"
```

---

### Task 8: Skill 2 评论线索筛选（批次、ID 一致性、拆半重试）

**Files:**
- Modify: `app/schemas/skills.py`（追加两个模型）、`app/workflow/pipeline.py`（追加筛选阶段）
- Create: `app/skills/configs/comment_lead_screening.yaml`、`app/skills/prompts/comment_lead_screening_v1.txt`、`tests/test_comment_screening.py`

**Interfaces:**
- Consumes: `SkillExecutor`、`save_result`/`get_current_result`、`VIDEO_CONTEXT_SKILL`/`SKILL_VERSIONS`（Task 7）
- Produces:
  - `app.schemas.skills.CommentScreeningItem`、`CommentScreeningResult(items: list[CommentScreeningItem])`
  - `app.workflow.pipeline.screen_comment_batch(session, executor, video_id: int, comment_ids: list[int]) -> None`：调 Skill，校验输出 ID 集合与输入一致；不一致时拆半递归重试（单条仍失败则抛 `SkillExecutionError`）；每条评论各存一行 AnalysisResult（`target_type="comment"`, `target_id=str(comment.id)`）

- [ ] **Step 1: 在 app/schemas/skills.py 追加筛选输出模型**

```python
from typing import Literal


class CommentScreeningItem(BaseModel):
    comment_id: str
    is_meaningful: bool = False
    is_automotive_related: bool = False
    is_purchase_related: bool = False
    is_suspected_marketing: bool = False
    intent_signals: list[str] = []
    target_brand: str | None = None
    target_model: str | None = None
    intent_strength: Literal["none", "low", "medium", "high"] = "none"
    reason: str = ""
    confidence: float = 0.0


class CommentScreeningResult(BaseModel):
    items: list[CommentScreeningItem]
```

（`from typing import Literal` 放到文件顶部 import 区。）

- [ ] **Step 2: 写失败测试 tests/test_comment_screening.py**

```python
import json

import pytest

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Comment, PlatformUser, Video
from app.services.results import get_current_result, save_result
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL, screen_comment_batch)


def _setup(session, n_comments=2):
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="n")
    session.add_all([v, u]); session.flush()
    comments = []
    for i in range(n_comments):
        c = Comment(platform="douyin", external_id=f"c{i}", video_id=v.id,
                    user_id=u.id, content=f"评论{i}")
        session.add(c); comments.append(c)
    session.flush()
    save_result(session, target_type="video", target_id=str(v.id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result={"brand": "坦克", "model": "坦克300",
                        "analysis_notes": ""})
    return v, comments


def _item(cid, purchase=True):
    return {"comment_id": str(cid), "is_meaningful": True,
            "is_automotive_related": True, "is_purchase_related": purchase,
            "is_suspected_marketing": False,
            "intent_signals": ["price_inquiry"] if purchase else [],
            "target_brand": "坦克", "target_model": "坦克300",
            "intent_strength": "high" if purchase else "none",
            "reason": "询问价格", "confidence": 0.9}


async def test_screen_batch_saves_per_comment(session):
    v, comments = _setup(session)
    ids = [c.id for c in comments]
    provider = MockProvider()
    provider.queue(json.dumps(
        {"items": [_item(ids[0]), _item(ids[1], purchase=False)]},
        ensure_ascii=False))
    executor = SkillExecutor(LLMGateway(provider))

    await screen_comment_batch(session, executor, v.id, ids)

    r0 = get_current_result(
        session, target_type="comment", target_id=str(ids[0]),
        skill_id=COMMENT_SCREENING_SKILL,
        skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL])
    assert r0.result["is_purchase_related"] is True
    assert r0.confidence == 0.9


async def test_screen_batch_splits_on_id_mismatch(session):
    v, comments = _setup(session, n_comments=2)
    ids = [c.id for c in comments]
    provider = MockProvider()
    # 整批返回错误 ID（3 次重试全失败）→ 拆成两个单条批次，各自成功
    bad = json.dumps({"items": [_item("999")]})
    provider.queue(bad, bad, bad,
                   json.dumps({"items": [_item(ids[0])]}),
                   json.dumps({"items": [_item(ids[1])]}))
    executor = SkillExecutor(LLMGateway(provider), max_retries=3)

    await screen_comment_batch(session, executor, v.id, ids)

    for cid in ids:
        assert get_current_result(
            session, target_type="comment", target_id=str(cid),
            skill_id=COMMENT_SCREENING_SKILL,
            skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL]) is not None
```

说明：`SkillExecutor.run` 内部对"输出 ID 不一致"并不感知（它只做 Schema 校验），因此 ID 校验在 `screen_comment_batch` 中执行；校验失败时对当前批次拆半递归。Mock 序列的含义：executor 第一轮拿到 3 个 bad 响应（Schema 合法但 ID 错，executor 每轮只调一次——ID 校验在外层，所以 3 个 bad 对应外层 3 次整批尝试）。实现时外层整批最多尝试 `settings.llm_max_retries` 次（每次调用 executor 一次），全部 ID 不一致后拆半。

Run: `python -m pytest tests/test_comment_screening.py -v`
Expected: FAIL（`ImportError: screen_comment_batch`）

- [ ] **Step 3: 在 app/workflow/pipeline.py 追加筛选阶段**

在文件顶部补充 import：

```python
from app.models import Comment
from app.schemas.skills import CommentScreeningResult
from app.services.results import get_current_result
from app.skills.executor import SkillExecutionError
from app.config import settings
```

追加函数：

```python
async def _call_screening(session: Session, executor: SkillExecutor,
                          video_context: dict,
                          comments: list[Comment]) -> CommentScreeningResult:
    context = {
        "video_context_json": json.dumps(video_context, ensure_ascii=False),
        "comments_json": json.dumps(
            [{"comment_id": str(c.id), "content": c.content}
             for c in comments], ensure_ascii=False),
        "comment_count": str(len(comments)),
    }
    return await executor.run(
        COMMENT_SCREENING_SKILL, context, CommentScreeningResult)


def _save_screening_items(session: Session,
                          result: CommentScreeningResult) -> None:
    for item in result.items:
        save_result(session, target_type="comment",
                    target_id=item.comment_id,
                    skill_id=COMMENT_SCREENING_SKILL,
                    skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                    result=item.model_dump(), confidence=item.confidence)


async def screen_comment_batch(session: Session, executor: SkillExecutor,
                               video_id: int,
                               comment_ids: list[int]) -> None:
    ctx_row = get_current_result(
        session, target_type="video", target_id=str(video_id),
        skill_id=VIDEO_CONTEXT_SKILL,
        skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
    if ctx_row is None:
        raise SkillExecutionError(f"视频 {video_id} 缺少语境结果")
    comments = (session.query(Comment)
                .filter(Comment.id.in_(comment_ids)).all())
    expected = {str(c.id) for c in comments}

    for _ in range(settings.llm_max_retries):
        result = await _call_screening(session, executor,
                                       ctx_row.result, comments)
        if {i.comment_id for i in result.items} == expected:
            _save_screening_items(session, result)
            return
    # 多次整批失败：拆半递归；单条仍失败则抛错
    if len(comments) == 1:
        raise SkillExecutionError(
            f"评论 {comment_ids} 筛选输出 ID 持续不一致")
    mid = len(comment_ids) // 2
    await screen_comment_batch(session, executor, video_id, comment_ids[:mid])
    await screen_comment_batch(session, executor, video_id, comment_ids[mid:])
```

- [ ] **Step 4: 创建 Skill 配置与 Prompt**

`app/skills/configs/comment_lead_screening.yaml`：

```yaml
skill_id: comment_lead_screening
version: "1.0"
description: >
  结合视频语境批量判断评论是否具有真实购车价值，
  识别无意义评论、营销内容和购车意向信号。
model:
  name: ""
  temperature: 0.1
prompt_file: comment_lead_screening_v1.txt
prompt_version: "v1"
```

`app/skills/prompts/comment_lead_screening_v1.txt`：

```text
你是汽车销售线索分析专家。请结合视频语境，逐条分析以下抖音评论，判断每条评论的购车线索价值。

视频语境（JSON）：
$video_context_json

评论列表（共 $comment_count 条，JSON）：
$comments_json

判断时必须区分以下四个层次：
1. 正面情绪（如"好看""厉害""good"）——不代表购车意向；
2. 产品兴趣（如"内饰不错""颜色好看"）——有兴趣但未进入决策；
3. 潜在购车需求（如"和XX比怎么样""保养贵不贵"）——开始了解或比较；
4. 明确购车意向（如"落地多少钱""哪里能试驾""置换有补贴吗"）——接近交易或行动。

注意事项：
- "厉害""哈哈""排面"等无意义或纯情绪评论：is_meaningful=false；
- 号召他人购买、模板化夸赞等疑似营销内容：is_suspected_marketing=true；
- 负面情绪中包含真实换车需求（如"现在这车售后太差，准备换品牌"）属于有价值线索，不得过滤；
- 与视频和汽车都无关的内容：is_automotive_related=false。

intent_signals 可选值：price_inquiry（询价）、trade_in（置换）、test_drive（试驾）、
finance（金融政策）、store_visit（门店/交付）、comparison（竞品对比）、
config_inquiry（配置咨询）、cost_concern（用车成本）、purchase_plan（购车计划）。

请严格输出以下 JSON（不要输出任何其他内容）。items 数组必须与输入评论一一对应：
数量相同、comment_id 完全一致、不得遗漏或新增：
{
  "items": [
    {
      "comment_id": "输入中的 comment_id，原样返回",
      "is_meaningful": true,
      "is_automotive_related": true,
      "is_purchase_related": true,
      "is_suspected_marketing": false,
      "intent_signals": ["price_inquiry"],
      "target_brand": "评论指向的品牌，没有则用视频语境品牌，无法判断为 null",
      "target_model": "评论指向的车型，同上",
      "intent_strength": "none | low | medium | high",
      "reason": "判断理由，一句话",
      "confidence": 0.9
    }
  ]
}
```

- [ ] **Step 5: 跑测试并提交**

Run: `python -m pytest tests/test_comment_screening.py -v`
Expected: 2 passed

```bash
git add app/schemas/skills.py app/workflow/pipeline.py app/skills/configs/comment_lead_screening.yaml app/skills/prompts/comment_lead_screening_v1.txt tests/test_comment_screening.py
git commit -m "feat: 评论批量筛选 Skill（ID 一致性校验与拆半重试）"
```

---

### Task 9: 用户聚合服务（候选用户 + 证据包）

**Files:**
- Create: `app/services/aggregation.py`、`tests/test_aggregation.py`

**Interfaces:**
- Consumes: `get_current_result`（Task 7）、`COMMENT_SCREENING_SKILL`/`VIDEO_CONTEXT_SKILL`/`SKILL_VERSIONS`（Task 7/8）、模型（Task 2）
- Produces:
  - `app.services.aggregation.candidate_user_ids(session) -> list[int]`：至少 1 条评论满足 `is_purchase_related=true 且 is_suspected_marketing=false` 的用户 id
  - `app.services.aggregation.build_user_evidence(session, user_id: int) -> dict`：结构如下（Task 10 的 Skill 3 输入即此 dict 的 JSON 序列化）：

```python
{
  "user": {"nickname": str, "platform": "douyin"},
  "comments": [{"comment_id": str, "content": str,
                "comment_time": "2026-07-01T12:00:00" | None,
                "screening": dict,          # CommentScreeningItem 落库的 result
                "video_context": dict | None}],
  "statistics": {"valid_comment_count": int,
                 "high_intent_comment_count": int,   # intent_strength == "high"
                 "related_brands": list[str], "related_models": list[str],
                 "first_comment_time": str | None,
                 "last_comment_time": str | None},
}
```

（`comments` 只含通过筛选的评论：`is_purchase_related=true 且 is_suspected_marketing=false`。）

- [ ] **Step 1: 写失败测试 tests/test_aggregation.py**

```python
from app.models import Comment, PlatformUser, Video
from app.services.aggregation import build_user_evidence, candidate_user_ids
from app.services.results import save_result
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL)


def _screening(cid, purchase, marketing=False, strength="high"):
    return {"comment_id": str(cid), "is_meaningful": True,
            "is_automotive_related": True, "is_purchase_related": purchase,
            "is_suspected_marketing": marketing,
            "intent_signals": ["price_inquiry"] if purchase else [],
            "target_brand": "坦克", "target_model": "坦克300",
            "intent_strength": strength if purchase else "none",
            "reason": "r", "confidence": 0.9}


def _setup(session):
    v = Video(platform="douyin", external_id="v1", title="t")
    u1 = PlatformUser(platform="douyin", external_id="u1", nickname="意向用户")
    u2 = PlatformUser(platform="douyin", external_id="u2", nickname="路人")
    session.add_all([v, u1, u2]); session.flush()
    c1 = Comment(platform="douyin", external_id="c1", video_id=v.id,
                 user_id=u1.id, content="落地多少钱")
    c2 = Comment(platform="douyin", external_id="c2", video_id=v.id,
                 user_id=u2.id, content="厉害")
    session.add_all([c1, c2]); session.flush()
    save_result(session, target_type="video", target_id=str(v.id),
                skill_id=VIDEO_CONTEXT_SKILL,
                skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                result={"brand": "坦克", "model": "坦克300"})
    sv = SKILL_VERSIONS[COMMENT_SCREENING_SKILL]
    save_result(session, target_type="comment", target_id=str(c1.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c1.id, purchase=True))
    save_result(session, target_type="comment", target_id=str(c2.id),
                skill_id=COMMENT_SCREENING_SKILL, skill_version=sv,
                result=_screening(c2.id, purchase=False))
    return v, u1, u2, c1, c2


def test_candidate_user_ids(session):
    _, u1, u2, _, _ = _setup(session)
    ids = candidate_user_ids(session)
    assert ids == [u1.id]                    # u2 无购车相关评论，不入候选


def test_build_user_evidence(session):
    v, u1, _, c1, _ = _setup(session)
    ev = build_user_evidence(session, u1.id)
    assert ev["user"]["nickname"] == "意向用户"
    assert len(ev["comments"]) == 1
    assert ev["comments"][0]["comment_id"] == str(c1.id)
    assert ev["comments"][0]["video_context"]["brand"] == "坦克"
    assert ev["statistics"]["valid_comment_count"] == 1
    assert ev["statistics"]["high_intent_comment_count"] == 1
    assert ev["statistics"]["related_brands"] == ["坦克"]
```

Run: `python -m pytest tests/test_aggregation.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 2: 实现 app/services/aggregation.py**

```python
from sqlalchemy.orm import Session

from app.models import AnalysisResult, Comment, PlatformUser
from app.services.results import get_current_result
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL, SKILL_VERSIONS,
                                   VIDEO_CONTEXT_SKILL)


def _valid_screenings(session: Session) -> list[AnalysisResult]:
    rows = (session.query(AnalysisResult)
            .filter_by(target_type="comment",
                       skill_id=COMMENT_SCREENING_SKILL,
                       skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                       status="success")
            .order_by(AnalysisResult.id).all())
    # 同评论多条结果取最新
    latest: dict[str, AnalysisResult] = {}
    for r in rows:
        latest[r.target_id] = r
    return [r for r in latest.values()
            if r.result.get("is_purchase_related")
            and not r.result.get("is_suspected_marketing")]


def candidate_user_ids(session: Session) -> list[int]:
    valid = _valid_screenings(session)
    comment_ids = [int(r.target_id) for r in valid]
    if not comment_ids:
        return []
    rows = (session.query(Comment.user_id)
            .filter(Comment.id.in_(comment_ids))
            .distinct().order_by(Comment.user_id).all())
    return [uid for (uid,) in rows]


def build_user_evidence(session: Session, user_id: int) -> dict:
    user = session.get(PlatformUser, user_id)
    valid = {int(r.target_id): r.result for r in _valid_screenings(session)}
    comments = (session.query(Comment)
                .filter(Comment.user_id == user_id,
                        Comment.id.in_(list(valid.keys())))
                .order_by(Comment.comment_time).all())

    items, brands, models = [], [], []
    high_count = 0
    for c in comments:
        screening = valid[c.id]
        ctx = get_current_result(
            session, target_type="video", target_id=str(c.video_id),
            skill_id=VIDEO_CONTEXT_SKILL,
            skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
        items.append({
            "comment_id": str(c.id), "content": c.content,
            "comment_time": (c.comment_time.isoformat()
                             if c.comment_time else None),
            "screening": screening,
            "video_context": ctx.result if ctx else None})
        if screening.get("intent_strength") == "high":
            high_count += 1
        for key, acc in (("target_brand", brands), ("target_model", models)):
            val = screening.get(key)
            if val and val not in acc:
                acc.append(val)

    times = [c.comment_time for c in comments if c.comment_time]
    return {
        "user": {"nickname": user.nickname, "platform": user.platform},
        "comments": items,
        "statistics": {
            "valid_comment_count": len(items),
            "high_intent_comment_count": high_count,
            "related_brands": brands, "related_models": models,
            "first_comment_time": min(times).isoformat() if times else None,
            "last_comment_time": max(times).isoformat() if times else None,
        },
    }
```

- [ ] **Step 3: 跑测试并提交**

Run: `python -m pytest tests/test_aggregation.py -v`
Expected: 2 passed

```bash
git add app/services/aggregation.py tests/test_aggregation.py
git commit -m "feat: 用户级聚合（候选用户识别与证据包构建）"
```

---

### Task 10: Skill 3 用户综合分析与 Lead 生成

**Files:**
- Modify: `app/schemas/skills.py`（追加 `UserLeadResult`）、`app/workflow/pipeline.py`（追加用户分析阶段）
- Create: `app/services/leads.py`、`app/skills/configs/user_lead_analysis.yaml`、`app/skills/prompts/user_lead_analysis_v1.txt`、`tests/test_user_analysis.py`

**Interfaces:**
- Consumes: `build_user_evidence`（Task 9）、`SkillExecutor`、`save_result`、`SKILL_VERSIONS`
- Produces:
  - `app.schemas.skills.UserLeadResult`（字段见代码）
  - `app.services.leads.upsert_lead(session, user_id: int, result: UserLeadResult, evidence_comments: list[dict], skill_version: str) -> Lead`（按 user_id 唯一 upsert）
  - `app.workflow.pipeline.run_user_analysis(session, executor, user_id: int) -> None`：构建证据包 → 调 Skill → 结果存 `analysis_result`（target_type="user"）→ `is_valid_lead` 为真时 upsert lead

- [ ] **Step 1: 在 app/schemas/skills.py 追加 UserLeadResult**

```python
class UserLeadResult(BaseModel):
    lead_grade: Literal["H", "A", "B", "C"]
    is_valid_lead: bool = True
    lead_summary: str = ""
    purchase_stage: str | None = None
    target_brands: list[str] = []
    target_models: list[str] = []
    core_needs: list[str] = []
    main_concerns: list[str] = []
    purchase_time: str | None = None
    usage_scenario: str | None = None
    recommended_entry_point: str | None = None
    verification_questions: list[str] = []
    evidence_comment_ids: list[str] = []
    confidence: float = 0.0
```

- [ ] **Step 2: 写失败测试 tests/test_user_analysis.py**

```python
import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import run_user_analysis
from tests.test_aggregation import _setup

LEAD_JSON = json.dumps({
    "lead_grade": "H", "is_valid_lead": True,
    "lead_summary": "用户询问落地价，意向明确",
    "purchase_stage": "交易准备阶段",
    "target_brands": ["坦克"], "target_models": ["坦克300"],
    "core_needs": ["越野"], "main_concerns": ["落地价格"],
    "purchase_time": "近期", "usage_scenario": "越野出行",
    "recommended_entry_point": "从当地报价切入",
    "verification_questions": ["预算多少？"],
    "evidence_comment_ids": ["__CID__"],
    "confidence": 0.91}, ensure_ascii=False)


async def test_run_user_analysis_creates_lead(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    provider.queue(LEAD_JSON.replace("__CID__", str(c1.id)))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)

    lead = session.query(Lead).one()
    assert lead.user_id == u1.id
    assert lead.grade == "H"
    assert lead.evidence == [{"comment_id": str(c1.id),
                              "content": "落地多少钱"}]
    assert lead.confidence == 0.91


async def test_run_user_analysis_upsert(session):
    _, u1, _, c1, _ = _setup(session)
    provider = MockProvider()
    cid = str(c1.id)
    provider.queue(LEAD_JSON.replace("__CID__", cid),
                   LEAD_JSON.replace("__CID__", cid)
                            .replace('"lead_grade": "H"',
                                     '"lead_grade": "A"'))
    executor = SkillExecutor(LLMGateway(provider))

    await run_user_analysis(session, executor, u1.id)
    await run_user_analysis(session, executor, u1.id)

    lead = session.query(Lead).one()          # 仍是一条
    assert lead.grade == "A"                  # 已更新
```

Run: `python -m pytest tests/test_user_analysis.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现 app/services/leads.py（upsert 部分）**

```python
from sqlalchemy.orm import Session

from app.models import Lead
from app.schemas.skills import UserLeadResult


def upsert_lead(session: Session, user_id: int, result: UserLeadResult,
                evidence_comments: list[dict], skill_version: str) -> Lead:
    lead = session.query(Lead).filter_by(user_id=user_id).first()
    if lead is None:
        lead = Lead(user_id=user_id, grade=result.lead_grade)
        session.add(lead)
    lead.grade = result.lead_grade
    lead.is_valid = result.is_valid_lead
    lead.summary = result.lead_summary
    lead.purchase_stage = result.purchase_stage
    lead.target_brands = result.target_brands
    lead.target_models = result.target_models
    lead.core_needs = result.core_needs
    lead.main_concerns = result.main_concerns
    lead.purchase_time = result.purchase_time
    lead.usage_scenario = result.usage_scenario
    lead.entry_point = result.recommended_entry_point
    lead.verification_questions = result.verification_questions
    lead.evidence = evidence_comments
    lead.confidence = result.confidence
    lead.skill_version = skill_version
    session.commit()
    return lead
```

- [ ] **Step 4: 在 app/workflow/pipeline.py 追加用户分析阶段**

补充 import：

```python
from app.schemas.skills import UserLeadResult
from app.services.aggregation import build_user_evidence
from app.services.leads import upsert_lead
```

注意：`aggregation.py` 也 import 了 `pipeline` 的常量。为避免循环导入，把 `build_user_evidence`/`upsert_lead` 的 import 放在 `run_user_analysis` 函数体内：

```python
GRADING_STANDARD = """H级（极高意向）：出现明确交易或行动信号——询问价格/落地价、优惠、
置换补贴、金融方案、门店/库存/交付、试驾，或明确表达近期购买换车计划。
A级（较强意向）：进入主动评估对比阶段——对比竞品、讨论优缺点、深入配置差异、
关注养车成本/保值率/售后、讨论真实使用场景。
B级（中等意向）：有产品兴趣但未深度决策——讨论外观内饰、浅层配置咨询、
"有点心动"、未来可能考虑。
C级（较低意向）：与汽车相关但意向弱——普通吐槽、玩梗、浅层情绪表达。
判定以购车决策阶段和行动信号为主要标准；同时符合多级时取最高一级；
没有证据支撑的信息保持未知（null 或空数组），不得推断职业、收入、家庭情况。"""


async def run_user_analysis(session: Session, executor: SkillExecutor,
                            user_id: int) -> None:
    from app.services.aggregation import build_user_evidence
    from app.services.leads import upsert_lead

    evidence = build_user_evidence(session, user_id)
    context = {
        "user_evidence_json": json.dumps(evidence, ensure_ascii=False),
        "grading_standard": GRADING_STANDARD,
    }
    out: UserLeadResult = await executor.run(
        USER_ANALYSIS_SKILL, context, UserLeadResult)
    save_result(session, target_type="user", target_id=str(user_id),
                skill_id=USER_ANALYSIS_SKILL,
                skill_version=SKILL_VERSIONS[USER_ANALYSIS_SKILL],
                result=out.model_dump(), confidence=out.confidence)
    if out.is_valid_lead:
        content_map = {c["comment_id"]: c["content"]
                       for c in evidence["comments"]}
        evidence_comments = [
            {"comment_id": cid, "content": content_map.get(cid, "")}
            for cid in out.evidence_comment_ids]
        upsert_lead(session, user_id, out, evidence_comments,
                    SKILL_VERSIONS[USER_ANALYSIS_SKILL])
```

- [ ] **Step 5: 创建 Skill 配置与 Prompt**

`app/skills/configs/user_lead_analysis.yaml`：

```yaml
skill_id: user_lead_analysis
version: "1.0"
description: >
  基于用户全部有效评论、视频语境与统计特征，综合判断购车意向，
  输出 H/A/B/C 等级、购车画像与销售建议。
model:
  name: ""
  temperature: 0.1
prompt_file: user_lead_analysis_v1.txt
prompt_version: "v1"
```

`app/skills/prompts/user_lead_analysis_v1.txt`：

```text
你是汽车销售线索分析专家。以下是一位抖音用户的全部有效评论及其上下文，
请综合判断该用户的购车意向，形成销售线索。

用户证据包（JSON，包含用户信息、评论列表及各自视频语境、统计特征）：
$user_evidence_json

意向等级标准：
$grading_standard

请严格输出以下 JSON（不要输出任何其他内容）：
{
  "lead_grade": "H | A | B | C",
  "is_valid_lead": true,
  "lead_summary": "线索摘要，销售人员一眼能懂，一到两句话",
  "purchase_stage": "购车阶段，如：初步了解/主动对比/交易准备，无法判断为 null",
  "target_brands": ["关注品牌"],
  "target_models": ["关注车型"],
  "core_needs": ["核心需求，如家庭空间、越野"],
  "main_concerns": ["主要顾虑，如落地价格、售后"],
  "purchase_time": "购车时间，如：近期/半年内/未知，无法判断为 null",
  "usage_scenario": "使用场景，无法判断为 null",
  "recommended_entry_point": "推荐销售切入点，一句话",
  "verification_questions": ["销售需要向用户确认的问题"],
  "evidence_comment_ids": ["支撑结论的评论 comment_id，必须来自输入"],
  "confidence": 0.9
}

要求：
1. 所有结论必须有评论证据支撑，evidence_comment_ids 不得为空；
2. 没有证据的字段输出 null 或空数组，严禁编造；
3. 疑似营销、水军或完全无购车相关信号的用户：is_valid_lead=false。
```

- [ ] **Step 6: 跑测试并提交**

Run: `python -m pytest tests/test_user_analysis.py -v`
Expected: 2 passed

```bash
git add app/schemas/skills.py app/workflow/pipeline.py app/services/leads.py app/skills/configs/user_lead_analysis.yaml app/skills/prompts/user_lead_analysis_v1.txt tests/test_user_analysis.py
git commit -m "feat: 用户综合分析 Skill 与线索 upsert"
```

---

### Task 11: 任务管理与后台 Worker

**Files:**
- Create: `app/workflow/tasks.py`、`app/workflow/worker.py`、`tests/test_tasks.py`、`tests/test_worker.py`
- Modify: `app/workflow/pipeline.py`（追加 `schedule_analysis` 与 `advance`）

**Interfaces:**
- Consumes: `AnalysisTask`（Task 2）、pipeline 阶段函数与常量（Task 7/8/10）、`candidate_user_ids`（Task 9）、`settings`
- Produces:
  - `app.workflow.tasks`:
    - `create_task(session, *, task_type, target_type, target_id, skill_version, payload=None) -> AnalysisTask | None`（幂等：已存在返回 None）
    - `claim_next(session) -> AnalysisTask | None`（最老 pending → running，`attempt_count += 1`）
    - `finish_task(session, task, error: str | None = None) -> None`（无错 → success；有错且 `attempt_count < max_attempts` → 回 pending；否则 failed）
    - `reset_running(session) -> int`（running → pending，返回条数；进程启动时调用）
    - `retry_task(session, task_id: int) -> bool`（failed → pending 且 `attempt_count=0`）
    - `task_counts(session) -> dict`（`{task_type: {status: count}}`）
  - `app.workflow.pipeline`:
    - `schedule_analysis(session) -> int`（为缺少当前版本语境结果的视频建 context 任务，返回新建数）
    - `advance(session) -> int`（推进下游：语境完成→建该视频评论批任务（`target_type="comment_batch"`、`target_id=f"{video_id}:{batch_idx}"`、`payload={"video_id", "comment_ids"}`）；语境+筛选全部完结→为候选用户建用户任务；返回新建任务数）
  - `app.workflow.worker.Worker(session_factory, executor, poll_interval=None)`：`async run_once() -> bool`（领取并执行一个任务，执行后调 `finish_task` + `advance`）、`async run_forever(stop_event)`（并发 `settings.worker_concurrency` 个循环）

- [ ] **Step 1: 写失败测试 tests/test_tasks.py**

```python
from app.models import AnalysisTask
from app.workflow.tasks import (claim_next, create_task, finish_task,
                                reset_running, retry_task, task_counts)


def _mk(session, target_id="1"):
    return create_task(session, task_type="video_context_analysis",
                       target_type="video", target_id=target_id,
                       skill_version="1.0")


def test_create_task_idempotent(session):
    assert _mk(session) is not None
    assert _mk(session) is None
    assert session.query(AnalysisTask).count() == 1


def test_claim_and_finish_success(session):
    _mk(session)
    task = claim_next(session)
    assert task.status == "running" and task.attempt_count == 1
    assert claim_next(session) is None       # 没有第二个 pending
    finish_task(session, task)
    assert task.status == "success"


def test_finish_with_error_retries_then_fails(session):
    _mk(session)
    task = claim_next(session)
    finish_task(session, task, error="超时")      # attempt 1 < 3 → pending
    assert task.status == "pending"
    for _ in range(2):
        task = claim_next(session)
        finish_task(session, task, error="超时")
    assert task.status == "failed"               # attempt 3 == max → failed
    assert retry_task(session, task.id)
    assert task.status == "pending" and task.attempt_count == 0


def test_reset_running_and_counts(session):
    _mk(session, "1"); _mk(session, "2")
    claim_next(session)
    assert reset_running(session) == 1
    counts = task_counts(session)
    assert counts["video_context_analysis"]["pending"] == 2
```

Run: `python -m pytest tests/test_tasks.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 2: 实现 app/workflow/tasks.py**

```python
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AnalysisTask


def create_task(session: Session, *, task_type: str, target_type: str,
                target_id: str, skill_version: str,
                payload: dict | None = None) -> AnalysisTask | None:
    exists = (session.query(AnalysisTask)
              .filter_by(task_type=task_type, target_type=target_type,
                         target_id=target_id, skill_version=skill_version)
              .first())
    if exists:
        return None
    task = AnalysisTask(task_type=task_type, target_type=target_type,
                        target_id=target_id, skill_version=skill_version,
                        payload=payload)
    session.add(task)
    session.commit()
    return task


def claim_next(session: Session) -> AnalysisTask | None:
    task = (session.query(AnalysisTask)
            .filter_by(status="pending")
            .order_by(AnalysisTask.id).first())
    if task is None:
        return None
    task.status = "running"
    task.attempt_count += 1
    session.commit()
    return task


def finish_task(session: Session, task: AnalysisTask,
                error: str | None = None) -> None:
    if error is None:
        task.status = "success"
        task.error = None
    elif task.attempt_count < task.max_attempts:
        task.status = "pending"
        task.error = error
    else:
        task.status = "failed"
        task.error = error
    session.commit()


def reset_running(session: Session) -> int:
    n = (session.query(AnalysisTask)
         .filter_by(status="running")
         .update({"status": "pending"}))
    session.commit()
    return n


def retry_task(session: Session, task_id: int) -> bool:
    task = session.get(AnalysisTask, task_id)
    if task is None or task.status != "failed":
        return False
    task.status = "pending"
    task.attempt_count = 0
    task.error = None
    session.commit()
    return True


def task_counts(session: Session) -> dict:
    rows = (session.query(AnalysisTask.task_type, AnalysisTask.status,
                          func.count(AnalysisTask.id))
            .group_by(AnalysisTask.task_type, AnalysisTask.status).all())
    out: dict[str, dict[str, int]] = {}
    for task_type, status, count in rows:
        out.setdefault(task_type, {})[status] = count
    return out
```

- [ ] **Step 3: 在 app/workflow/pipeline.py 追加调度函数**

补充 import：

```python
from app.models import Video  # 已有则跳过
from app.workflow.tasks import create_task
```

追加：

```python
def schedule_analysis(session: Session) -> int:
    created = 0
    for (vid,) in session.query(Video.id).all():
        ctx = get_current_result(
            session, target_type="video", target_id=str(vid),
            skill_id=VIDEO_CONTEXT_SKILL,
            skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL])
        if ctx is not None:
            continue
        if create_task(session, task_type=VIDEO_CONTEXT_SKILL,
                       target_type="video", target_id=str(vid),
                       skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL]):
            created += 1
    return created


def _upstream_done(session: Session) -> bool:
    from app.models import AnalysisTask
    open_upstream = (session.query(AnalysisTask)
                     .filter(AnalysisTask.task_type.in_(
                         [VIDEO_CONTEXT_SKILL, COMMENT_SCREENING_SKILL]),
                         AnalysisTask.status.in_(["pending", "running"]))
                     .count())
    return open_upstream == 0


def advance(session: Session) -> int:
    from app.models import AnalysisTask
    from app.services.aggregation import candidate_user_ids
    created = 0

    # 1) 语境已完成的视频 → 建评论批次任务（每视频只建一次）
    ctx_rows = (session.query(AnalysisResult)
                .filter_by(target_type="video",
                           skill_id=VIDEO_CONTEXT_SKILL,
                           skill_version=SKILL_VERSIONS[VIDEO_CONTEXT_SKILL],
                           status="success").all())
    for ctx in ctx_rows:
        video_id = int(ctx.target_id)
        has_batch = (session.query(AnalysisTask)
                     .filter(AnalysisTask.task_type == COMMENT_SCREENING_SKILL,
                             AnalysisTask.target_id.like(f"{video_id}:%"))
                     .first())
        if has_batch:
            continue
        comment_ids = [cid for (cid,) in
                       session.query(Comment.id)
                       .filter(Comment.video_id == video_id)
                       .order_by(Comment.id).all()]
        size = settings.comment_batch_size
        for idx in range(0, len(comment_ids), size):
            batch = comment_ids[idx:idx + size]
            if create_task(
                    session, task_type=COMMENT_SCREENING_SKILL,
                    target_type="comment_batch",
                    target_id=f"{video_id}:{idx // size}",
                    skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL],
                    payload={"video_id": video_id, "comment_ids": batch}):
                created += 1

    # 2) 语境+筛选全部完结 → 为候选用户建用户分析任务
    if _upstream_done(session):
        for uid in candidate_user_ids(session):
            if create_task(session, task_type=USER_ANALYSIS_SKILL,
                           target_type="user", target_id=str(uid),
                           skill_version=SKILL_VERSIONS[USER_ANALYSIS_SKILL]):
                created += 1
    return created
```

（`AnalysisResult` 需在 pipeline.py 顶部 import：`from app.models import AnalysisResult, Comment, Video`。）

- [ ] **Step 4: 实现 app/workflow/worker.py**

```python
import asyncio
import logging

from app.config import settings
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import (COMMENT_SCREENING_SKILL,
                                   USER_ANALYSIS_SKILL, VIDEO_CONTEXT_SKILL,
                                   advance, run_user_analysis,
                                   run_video_context, screen_comment_batch)
from app.workflow.tasks import claim_next, finish_task

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, session_factory, executor: SkillExecutor,
                 poll_interval: float | None = None):
        self.session_factory = session_factory
        self.executor = executor
        self.poll_interval = poll_interval or settings.worker_poll_interval

    async def run_once(self) -> bool:
        session = self.session_factory()
        task = claim_next(session)
        if task is None:
            return False
        error: str | None = None
        try:
            if task.task_type == VIDEO_CONTEXT_SKILL:
                await run_video_context(session, self.executor,
                                        int(task.target_id))
            elif task.task_type == COMMENT_SCREENING_SKILL:
                await screen_comment_batch(
                    session, self.executor,
                    int(task.payload["video_id"]),
                    list(task.payload["comment_ids"]))
            elif task.task_type == USER_ANALYSIS_SKILL:
                await run_user_analysis(session, self.executor,
                                        int(task.target_id))
            else:
                error = f"未知任务类型: {task.task_type}"
        except Exception as e:
            logger.exception("任务 %s 执行失败", task.id)
            error = str(e)[:2000]
        finish_task(session, task, error=error)
        advance(session)
        return True

    async def _loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self.poll_interval)

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        loops = [self._loop(stop_event)
                 for _ in range(settings.worker_concurrency)]
        await asyncio.gather(*loops)
```

- [ ] **Step 5: 写失败测试 tests/test_worker.py（端到端推进）**

```python
import json

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.models import AnalysisTask, Lead
from app.skills.executor import SkillExecutor
from app.workflow.pipeline import advance, schedule_analysis
from app.workflow.worker import Worker
from tests.test_comment_screening import _item
from tests.test_user_analysis import LEAD_JSON
from app.models import Comment, PlatformUser, Video

CONTEXT_JSON = json.dumps({"brand": "坦克", "model": "坦克300",
                           "analysis_notes": ""}, ensure_ascii=False)


async def test_worker_full_pipeline(session):
    v = Video(platform="douyin", external_id="v1", title="t")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="用户")
    session.add_all([v, u]); session.flush()
    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="落地多少钱")
    session.add(c); session.commit()

    provider = MockProvider()
    provider.queue(
        CONTEXT_JSON,
        json.dumps({"items": [_item(c.id)]}, ensure_ascii=False),
        LEAD_JSON.replace("__CID__", str(c.id)))
    worker = Worker(lambda: session,
                    SkillExecutor(LLMGateway(provider)))

    assert schedule_analysis(session) == 1        # 1 个视频语境任务
    while await worker.run_once():                # 逐个执行直到队列空
        pass

    assert session.query(AnalysisTask).filter_by(status="failed").count() == 0
    lead = session.query(Lead).one()
    assert lead.grade == "H" and lead.user_id == u.id
```

Run: `python -m pytest tests/test_worker.py -v`
Expected: FAIL（`ModuleNotFoundError: app.workflow.worker`，实现 Step 3/4 后通过）

- [ ] **Step 6: 跑全部测试并提交**

Run: `python -m pytest -v`
Expected: 全部通过

```bash
git add app/workflow/ tests/test_tasks.py tests/test_worker.py
git commit -m "feat: 任务管理、工作流推进与后台 Worker"
```

---

### Task 12: FastAPI 入口、任务页与导入/分析 API

**Files:**
- Create: `app/main.py`、`app/web/__init__.py`（空）、`app/web/routes.py`、`app/templates/index.html`、`tests/test_api_tasks.py`

**Interfaces:**
- Consumes: `parse_excel`/`import_bundle`（Task 4）、`schedule_analysis`/`advance`（Task 11）、`task_counts`/`retry_task`/`reset_running`（Task 11）、`build_gateway`/`SkillExecutor`/`Worker`
- Produces:
  - `app.main.app`（FastAPI 实例；lifespan：`init_db()` → `reset_running` → `settings.worker_enabled` 为真时启动 Worker）
  - `app.web.routes.router`、依赖 `get_db()`（yield SessionLocal；测试用 `app.dependency_overrides[get_db]` 换成 SQLite session）
  - API：`POST /api/import`（multipart 文件）、`POST /api/analysis/start`、`GET /api/analysis/progress`、`POST /api/tasks/{task_id}/retry`；页面 `GET /`

- [ ] **Step 1: 写失败测试 tests/test_api_tasks.py**

```python
import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.models import AnalysisTask, Comment, Video
from app.web.routes import get_db


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)          # 不用 with，避免触发 lifespan/MySQL


def _xlsx(tmp_path):
    df = pd.DataFrame([{
        "aweme_id": "1001", "title": "标题 #SUV", "desc": "文案",
        "cover_url": "http://x/1.jpg", "nickname": "小明",
        "sec_uid": "sec_1", "comment_id": "9001",
        "content": "落地多少钱", "create_time": 1783783725}])
    path = tmp_path / "t.xlsx"
    df.to_excel(path, index=False)
    return path


def test_import_and_start_analysis(tmp_path, session):
    client = _client(session)
    with open(_xlsx(tmp_path), "rb") as f:
        r = client.post("/api/import", files={"file": ("t.xlsx", f)})
    assert r.status_code == 200
    assert r.json()["videos_new"] == 1
    assert session.query(Video).count() == 1
    assert session.query(Comment).count() == 1

    r = client.post("/api/analysis/start")
    assert r.status_code == 200
    assert r.json()["created"] == 1
    assert session.query(AnalysisTask).count() == 1

    r = client.get("/api/analysis/progress")
    assert r.status_code == 200
    assert r.json()["video_context_analysis"]["pending"] == 1


def test_retry_endpoint_404_on_missing(session):
    client = _client(session)
    assert client.post("/api/tasks/999/retry").status_code == 404


def test_index_page(session):
    client = _client(session)
    r = client.get("/")
    assert r.status_code == 200
    assert "DriveIntent" in r.text
```

Run: `python -m pytest tests/test_api_tasks.py -v`
Expected: FAIL（`ModuleNotFoundError: app.main`）

- [ ] **Step 2: 实现 app/web/routes.py（任务部分）**

```python
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.templating import Jinja2Templates

from app.db import SessionLocal
from app.importer.core import import_bundle
from app.importer.excel import parse_excel
from app.workflow.pipeline import advance, schedule_analysis
from app.workflow.tasks import retry_task, task_counts

router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.post("/api/import")
async def api_import(file: UploadFile, db=Depends(get_db)):
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        bundle = parse_excel(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    stats = import_bundle(db, bundle)
    return stats.model_dump()


@router.post("/api/analysis/start")
def api_start(db=Depends(get_db)):
    created = schedule_analysis(db)
    created += advance(db)
    return {"created": created}


@router.get("/api/analysis/progress")
def api_progress(db=Depends(get_db)):
    return task_counts(db)


@router.post("/api/tasks/{task_id}/retry")
def api_retry(task_id: int, db=Depends(get_db)):
    if not retry_task(db, task_id):
        raise HTTPException(404, "任务不存在或不是失败状态")
    return {"ok": True}
```

- [ ] **Step 3: 实现 app/main.py**

```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import SessionLocal, init_db
from app.llm.gateway import build_gateway
from app.skills.executor import SkillExecutor
from app.web.routes import router
from app.workflow.tasks import reset_running
from app.workflow.worker import Worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as s:
        reset_running(s)
    stop_event = asyncio.Event()
    worker_task = None
    if settings.worker_enabled:
        gateway = build_gateway(session_factory=SessionLocal)
        worker = Worker(SessionLocal, SkillExecutor(gateway))
        worker_task = asyncio.create_task(worker.run_forever(stop_event))
    yield
    stop_event.set()
    if worker_task:
        worker_task.cancel()


app = FastAPI(title="DriveIntent", lifespan=lifespan)
app.include_router(router)
```

- [ ] **Step 4: 创建 app/templates/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>DriveIntent - 分析任务</title>
  <style>
    body { font-family: "Microsoft YaHei", sans-serif; margin: 2rem; }
    section { margin-bottom: 2rem; }
    table { border-collapse: collapse; }
    td, th { border: 1px solid #ccc; padding: 4px 10px; }
    button { padding: 4px 12px; }
    #import-result, #start-result { color: #06c; margin-left: 8px; }
  </style>
</head>
<body>
  <h1>DriveIntent 线索获客</h1>
  <p><a href="/leads">→ 线索列表</a></p>

  <section>
    <h2>1. 数据导入</h2>
    <input type="file" id="file" accept=".xlsx">
    <button onclick="doImport()">导入 Excel</button>
    <span id="import-result"></span>
  </section>

  <section>
    <h2>2. 启动分析</h2>
    <button onclick="doStart()">启动分析</button>
    <span id="start-result"></span>
  </section>

  <section>
    <h2>3. 任务进度（每 3 秒刷新）</h2>
    <div id="progress">加载中…</div>
  </section>

<script>
async function doImport() {
  const f = document.getElementById('file').files[0];
  if (!f) { alert('请选择文件'); return; }
  const fd = new FormData();
  fd.append('file', f);
  const r = await fetch('/api/import', {method: 'POST', body: fd});
  const d = await r.json();
  document.getElementById('import-result').textContent =
    `视频新增 ${d.videos_new}，评论新增 ${d.comments_new}，` +
    `跳过 ${d.comments_skipped}，空评论 ${d.empty_comments}`;
}
async function doStart() {
  const r = await fetch('/api/analysis/start', {method: 'POST'});
  const d = await r.json();
  document.getElementById('start-result').textContent =
    `新建任务 ${d.created} 个`;
}
async function refresh() {
  const r = await fetch('/api/analysis/progress');
  const d = await r.json();
  let html = '<table><tr><th>任务类型</th><th>等待</th><th>执行中</th>' +
             '<th>成功</th><th>失败</th></tr>';
  for (const [t, s] of Object.entries(d)) {
    html += `<tr><td>${t}</td><td>${s.pending||0}</td>` +
            `<td>${s.running||0}</td><td>${s.success||0}</td>` +
            `<td>${s.failed||0}</td></tr>`;
  }
  html += '</table>';
  document.getElementById('progress').innerHTML = html;
}
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
```

- [ ] **Step 5: 跑测试并提交**

Run: `python -m pytest tests/test_api_tasks.py -v`
Expected: 3 passed

```bash
git add app/main.py app/web/ app/templates/index.html tests/test_api_tasks.py
git commit -m "feat: FastAPI 入口、任务页与导入/分析 API"
```

---

### Task 13: 线索列表、详情、人工审核与 CSV 导出

**Files:**
- Modify: `app/services/leads.py`（追加查询与导出）、`app/web/routes.py`（追加线索路由）
- Create: `app/templates/leads.html`、`app/templates/lead_detail.html`、`tests/test_api_leads.py`

**Interfaces:**
- Consumes: `Lead`/`PlatformUser`（Task 2）、`build_user_evidence`（Task 9）、`get_db`/`templates`（Task 12）
- Produces:
  - `app.services.leads.query_leads(session, *, grade=None, brand=None, model=None, review_status=None) -> list[Lead]`（按 grade H→A→B→C、confidence 降序）
  - `app.services.leads.leads_to_csv(session, leads) -> str`（UTF-8 内容，首列含用户昵称；调用方加 BOM）
  - API：`GET /api/leads`、`GET /api/leads/{lead_id}`、`POST /api/leads/{lead_id}/review`（body: `{"review_status": "valid|invalid", "review_tags": [...], "review_note": "..."}`）、`GET /api/leads/export`（CSV 下载）；页面 `GET /leads`、`GET /leads/{lead_id}`

- [ ] **Step 1: 写失败测试 tests/test_api_leads.py**

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Lead, PlatformUser
from app.web.routes import get_db


def _client(session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    return TestClient(app)


def _mk_lead(session, grade="H", nickname="意向用户"):
    u = PlatformUser(platform="douyin", external_id=f"u-{nickname}",
                     nickname=nickname)
    session.add(u); session.flush()
    lead = Lead(user_id=u.id, grade=grade, summary="询问落地价",
                target_brands=["坦克"], target_models=["坦克300"],
                core_needs=["越野"], main_concerns=["价格"],
                evidence=[{"comment_id": "1", "content": "落地多少钱"}],
                confidence=0.9, skill_version="1.0")
    session.add(lead); session.commit()
    return lead


def test_list_and_filter(session):
    _mk_lead(session, "H", "甲")
    _mk_lead(session, "B", "乙")
    client = _client(session)
    assert len(client.get("/api/leads").json()) == 2
    data = client.get("/api/leads", params={"grade": "H"}).json()
    assert len(data) == 1 and data[0]["nickname"] == "甲"


def test_review(session):
    lead = _mk_lead(session)
    client = _client(session)
    r = client.post(f"/api/leads/{lead.id}/review", json={
        "review_status": "valid", "review_tags": ["等级偏高"],
        "review_note": "ok"})
    assert r.status_code == 200
    session.refresh(lead)
    assert lead.review_status == "valid"
    assert lead.review_tags == ["等级偏高"]


def test_export_csv(session):
    _mk_lead(session)
    client = _client(session)
    r = client.get("/api/leads/export")
    assert r.status_code == 200
    assert r.text.lstrip("﻿").startswith("昵称,")
    assert "意向用户" in r.text


def test_pages_render(session):
    lead = _mk_lead(session)
    client = _client(session)
    assert "意向用户" in client.get("/leads").text
    assert "询问落地价" in client.get(f"/leads/{lead.id}").text
```

Run: `python -m pytest tests/test_api_leads.py -v`
Expected: FAIL

- [ ] **Step 2: 在 app/services/leads.py 追加查询与导出**

```python
import csv
import io

from app.models import PlatformUser


GRADE_ORDER = {"H": 0, "A": 1, "B": 2, "C": 3}


def query_leads(session: Session, *, grade: str | None = None,
                brand: str | None = None, model: str | None = None,
                review_status: str | None = None) -> list[Lead]:
    q = session.query(Lead)
    if grade:
        q = q.filter(Lead.grade == grade)
    if review_status:
        q = q.filter(Lead.review_status == review_status)
    leads = q.all()
    if brand:
        leads = [l for l in leads if brand in (l.target_brands or [])]
    if model:
        leads = [l for l in leads if model in (l.target_models or [])]
    return sorted(leads, key=lambda l: (GRADE_ORDER.get(l.grade, 9),
                                        -(l.confidence or 0)))


def lead_to_dict(session: Session, lead: Lead) -> dict:
    user = session.get(PlatformUser, lead.user_id)
    return {
        "id": lead.id, "nickname": user.nickname if user else "",
        "platform": user.platform if user else "", "grade": lead.grade,
        "target_brands": lead.target_brands or [],
        "target_models": lead.target_models or [],
        "summary": lead.summary, "purchase_stage": lead.purchase_stage,
        "core_needs": lead.core_needs or [],
        "main_concerns": lead.main_concerns or [],
        "purchase_time": lead.purchase_time,
        "usage_scenario": lead.usage_scenario,
        "entry_point": lead.entry_point,
        "verification_questions": lead.verification_questions or [],
        "evidence": lead.evidence or [], "confidence": lead.confidence,
        "review_status": lead.review_status,
        "review_tags": lead.review_tags or [],
        "review_note": lead.review_note,
        "created_at": lead.created_at.isoformat(),
    }


def leads_to_csv(session: Session, leads: list[Lead]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["昵称", "平台", "等级", "品牌", "车型", "摘要",
                     "核心需求", "主要顾虑", "购车时间", "销售切入点",
                     "置信度", "审核状态", "分析时间"])
    for lead in leads:
        d = lead_to_dict(session, lead)
        writer.writerow([
            d["nickname"], d["platform"], d["grade"],
            "/".join(d["target_brands"]), "/".join(d["target_models"]),
            d["summary"], "/".join(d["core_needs"]),
            "/".join(d["main_concerns"]), d["purchase_time"] or "",
            d["entry_point"] or "", d["confidence"],
            d["review_status"], d["created_at"]])
    return buf.getvalue()
```

- [ ] **Step 3: 在 app/web/routes.py 追加线索路由**

补充 import：

```python
from fastapi.responses import Response
from pydantic import BaseModel

from app.models import Lead
from app.services.aggregation import build_user_evidence
from app.services.leads import lead_to_dict, leads_to_csv, query_leads
```

追加：

```python
class ReviewIn(BaseModel):
    review_status: str
    review_tags: list[str] = []
    review_note: str = ""


@router.get("/leads")
def leads_page(request: Request, grade: str | None = None,
               brand: str | None = None, model: str | None = None,
               review_status: str | None = None, db=Depends(get_db)):
    leads = query_leads(db, grade=grade, brand=brand, model=model,
                        review_status=review_status)
    rows = [lead_to_dict(db, l) for l in leads]
    return templates.TemplateResponse(
        request, "leads.html",
        {"rows": rows, "grade": grade or "",
         "review_status": review_status or ""})


@router.get("/leads/{lead_id}")
def lead_detail_page(request: Request, lead_id: int, db=Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    d = lead_to_dict(db, lead)
    evidence_pack = build_user_evidence(db, lead.user_id)
    return templates.TemplateResponse(
        request, "lead_detail.html", {"lead": d, "pack": evidence_pack})


@router.get("/api/leads")
def api_leads(grade: str | None = None, brand: str | None = None,
              model: str | None = None, review_status: str | None = None,
              db=Depends(get_db)):
    leads = query_leads(db, grade=grade, brand=brand, model=model,
                        review_status=review_status)
    return [lead_to_dict(db, l) for l in leads]


@router.get("/api/leads/export")
def api_leads_export(grade: str | None = None, db=Depends(get_db)):
    leads = query_leads(db, grade=grade)
    csv_text = "﻿" + leads_to_csv(db, leads)
    return Response(csv_text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="leads.csv"'})


@router.get("/api/leads/{lead_id}")
def api_lead_detail(lead_id: int, db=Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    return lead_to_dict(db, lead)


@router.post("/api/leads/{lead_id}/review")
def api_review(lead_id: int, body: ReviewIn, db=Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "线索不存在")
    lead.review_status = body.review_status
    lead.review_tags = body.review_tags
    lead.review_note = body.review_note
    db.commit()
    return {"ok": True}
```

注意路由顺序：`/api/leads/export` 必须注册在 `/api/leads/{lead_id}` 之前，否则 `export` 会被当作 `lead_id` 解析。

- [ ] **Step 4: 创建 app/templates/leads.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>DriveIntent - 线索列表</title>
  <style>
    body { font-family: "Microsoft YaHei", sans-serif; margin: 2rem; }
    table { border-collapse: collapse; width: 100%; }
    td, th { border: 1px solid #ccc; padding: 4px 8px; font-size: 14px; }
    .grade-H { color: #c00; font-weight: bold; }
    .grade-A { color: #e60; font-weight: bold; }
  </style>
</head>
<body>
  <h1>线索列表</h1>
  <p><a href="/">← 任务页</a>
     <a href="/api/leads/export">导出 CSV</a></p>
  <form method="get">
    等级：
    <select name="grade">
      <option value="">全部</option>
      {% for g in ["H", "A", "B", "C"] %}
      <option value="{{ g }}" {% if grade == g %}selected{% endif %}>{{ g }}</option>
      {% endfor %}
    </select>
    审核状态：
    <select name="review_status">
      <option value="">全部</option>
      <option value="unreviewed" {% if review_status == "unreviewed" %}selected{% endif %}>未审核</option>
      <option value="valid" {% if review_status == "valid" %}selected{% endif %}>有效</option>
      <option value="invalid" {% if review_status == "invalid" %}selected{% endif %}>无效</option>
    </select>
    <button type="submit">筛选</button>
  </form>
  <table>
    <tr><th>昵称</th><th>等级</th><th>品牌/车型</th><th>摘要</th>
        <th>核心需求</th><th>主要顾虑</th><th>置信度</th>
        <th>审核状态</th><th>详情</th></tr>
    {% for r in rows %}
    <tr>
      <td>{{ r.nickname }}</td>
      <td class="grade-{{ r.grade }}">{{ r.grade }}</td>
      <td>{{ r.target_brands | join("/") }} {{ r.target_models | join("/") }}</td>
      <td>{{ r.summary }}</td>
      <td>{{ r.core_needs | join("、") }}</td>
      <td>{{ r.main_concerns | join("、") }}</td>
      <td>{{ "%.2f" | format(r.confidence or 0) }}</td>
      <td>{{ r.review_status }}</td>
      <td><a href="/leads/{{ r.id }}">查看</a></td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>
```

- [ ] **Step 5: 创建 app/templates/lead_detail.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>DriveIntent - 线索详情</title>
  <style>
    body { font-family: "Microsoft YaHei", sans-serif; margin: 2rem; }
    .card { border: 1px solid #ccc; padding: 12px; margin-bottom: 16px; }
    .comment { border-left: 3px solid #06c; padding-left: 8px;
               margin: 8px 0; }
    .meta { color: #888; font-size: 13px; }
  </style>
</head>
<body>
  <p><a href="/leads">← 返回列表</a></p>
  <h1>{{ lead.nickname }}
      <span class="grade-{{ lead.grade }}">[{{ lead.grade }}级]</span></h1>

  <div class="card">
    <h3>意向画像</h3>
    <p>{{ lead.summary }}</p>
    <p>购车阶段：{{ lead.purchase_stage or "未知" }}｜
       购车时间：{{ lead.purchase_time or "未知" }}｜
       置信度：{{ "%.2f" | format(lead.confidence or 0) }}</p>
    <p>品牌车型：{{ lead.target_brands | join("/") }}
       {{ lead.target_models | join("/") }}</p>
    <p>核心需求：{{ lead.core_needs | join("、") }}｜
       主要顾虑：{{ lead.main_concerns | join("、") }}</p>
    <p>使用场景：{{ lead.usage_scenario or "未知" }}</p>
    <p><b>销售切入点：</b>{{ lead.entry_point or "-" }}</p>
    <p><b>待确认问题：</b>{{ lead.verification_questions | join("；") }}</p>
  </div>

  <div class="card">
    <h3>证据评论（{{ pack.comments | length }} 条有效）</h3>
    {% for c in pack.comments %}
    <div class="comment">
      <div>{{ c.content }}</div>
      <div class="meta">
        {{ c.comment_time or "" }}｜意向强度 {{ c.screening.intent_strength }}｜
        {{ c.screening.reason }}
        {% if c.video_context %}
        ｜视频：{{ c.video_context.brand or "" }} {{ c.video_context.model or "" }}
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="card">
    <h3>人工审核</h3>
    <p>当前：{{ lead.review_status }}
       {{ lead.review_tags | join("、") }} {{ lead.review_note or "" }}</p>
    <select id="rs">
      <option value="valid">有效</option>
      <option value="invalid">无效</option>
    </select>
    <label><input type="checkbox" class="tag" value="等级偏高">等级偏高</label>
    <label><input type="checkbox" class="tag" value="等级偏低">等级偏低</label>
    <label><input type="checkbox" class="tag" value="疑似水军">疑似水军</label>
    <label><input type="checkbox" class="tag" value="无真实购车需求">无真实购车需求</label>
    <label><input type="checkbox" class="tag" value="画像错误">画像错误</label>
    <label><input type="checkbox" class="tag" value="切入点无价值">切入点无价值</label>
    <br><textarea id="note" rows="2" cols="60"
                  placeholder="备注"></textarea><br>
    <button onclick="submitReview()">提交审核</button>
    <span id="review-result"></span>
  </div>

<script>
async function submitReview() {
  const tags = [...document.querySelectorAll('.tag:checked')]
      .map(x => x.value);
  const r = await fetch('/api/leads/{{ lead.id }}/review', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      review_status: document.getElementById('rs').value,
      review_tags: tags,
      review_note: document.getElementById('note').value})});
  document.getElementById('review-result').textContent =
      r.ok ? '已保存' : '保存失败';
}
</script>
</body>
</html>
```

- [ ] **Step 6: 跑测试并提交**

Run: `python -m pytest tests/test_api_leads.py -v`
Expected: 4 passed（连同全量 `python -m pytest` 全绿）

```bash
git add app/services/leads.py app/web/routes.py app/templates/ tests/test_api_leads.py
git commit -m "feat: 线索列表/详情/人工审核/CSV 导出"
```

---

### Task 14: 端到端集成测试与评测脚手架

**Files:**
- Create: `tests/test_e2e.py`、`scripts/make_annotation_template.py`、`scripts/evaluate.py`
- Modify: `README.md`（末尾追加"快速开始"小节）

**Interfaces:**
- Consumes: 全部前序模块
- Produces:
  - `scripts/make_annotation_template.py`：导出评论 + 筛选结果到 `data/annotation_template.csv` 供人工标注
  - `scripts/evaluate.py`：读取标注 CSV 与库内结果，输出评论筛选指标与线索等级指标

- [ ] **Step 1: 写端到端测试 tests/test_e2e.py**

```python
"""端到端：Excel 导入 → API 启动分析 → Worker 跑完 → 线索可查可导出。"""
import json

import pandas as pd
from fastapi.testclient import TestClient

from app.llm.gateway import LLMGateway
from app.llm.mock import MockProvider
from app.main import app
from app.skills.executor import SkillExecutor
from app.web.routes import get_db
from app.workflow.worker import Worker
from tests.test_comment_screening import _item
from tests.test_user_analysis import LEAD_JSON


def _xlsx(tmp_path):
    rows = [
        {"aweme_id": "1001", "title": "全新坦克300 #SUV", "desc": "8缸",
         "cover_url": "", "nickname": "买家", "sec_uid": "sec_1",
         "comment_id": "9001", "content": "上海落地多少钱",
         "create_time": 1783783725},
        {"aweme_id": "1001", "title": "全新坦克300 #SUV", "desc": "8缸",
         "cover_url": "", "nickname": "路人", "sec_uid": "sec_2",
         "comment_id": "9002", "content": "厉害",
         "create_time": 1783783726},
    ]
    path = tmp_path / "e2e.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


async def test_e2e_pipeline(tmp_path, session):
    def override():
        yield session
    app.dependency_overrides[get_db] = override
    client = TestClient(app)

    # 1. 导入
    with open(_xlsx(tmp_path), "rb") as f:
        r = client.post("/api/import", files={"file": ("e2e.xlsx", f)})
    assert r.json()["comments_new"] == 2

    # 2. 启动分析
    assert client.post("/api/analysis/start").json()["created"] == 1

    # 3. Mock LLM + Worker 跑完全部任务
    from app.models import Comment
    ids = {c.external_id: c.id for c in session.query(Comment).all()}
    provider = MockProvider()
    provider.queue(
        json.dumps({"brand": "坦克", "model": "坦克300",
                    "analysis_notes": ""}, ensure_ascii=False),
        json.dumps({"items": [_item(ids["9001"]),
                              _item(ids["9002"], purchase=False)]},
                   ensure_ascii=False),
        LEAD_JSON.replace("__CID__", str(ids["9001"])))
    worker = Worker(lambda: session, SkillExecutor(LLMGateway(provider)))
    while await worker.run_once():
        pass

    # 4. 线索可查：只有 sec_1 成为线索
    leads = client.get("/api/leads").json()
    assert len(leads) == 1
    assert leads[0]["nickname"] == "买家" and leads[0]["grade"] == "H"

    # 5. 导出 CSV
    assert "买家" in client.get("/api/leads/export").text

    # 6. 进度接口无失败任务
    progress = client.get("/api/analysis/progress").json()
    for counts in progress.values():
        assert counts.get("failed", 0) == 0
```

Run: `python -m pytest tests/test_e2e.py -v`
Expected: PASS（前序任务都完成后应直接通过；失败则按报错修复）

- [ ] **Step 2: 实现 scripts/make_annotation_template.py**

```python
"""导出评论与模型筛选结果，生成人工标注模板 CSV。

用法: python scripts/make_annotation_template.py [输出路径]
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal
from app.models import Comment
from app.services.results import get_current_result
from app.workflow.pipeline import COMMENT_SCREENING_SKILL, SKILL_VERSIONS


def main(out_path: str = "data/annotation_template.csv") -> None:
    with SessionLocal() as session, \
            open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["comment_id", "content",
                         "模型_有意义", "模型_购车相关", "模型_疑似营销",
                         "模型_意向强度",
                         "人工_有意义(1/0)", "人工_购车相关(1/0)",
                         "人工_疑似营销(1/0)", "人工_意向强度(none/low/medium/high)"])
        for c in session.query(Comment).order_by(Comment.id).all():
            r = get_current_result(
                session, target_type="comment", target_id=str(c.id),
                skill_id=COMMENT_SCREENING_SKILL,
                skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL])
            s = r.result if r else {}
            writer.writerow([
                c.id, c.content,
                int(bool(s.get("is_meaningful"))),
                int(bool(s.get("is_purchase_related"))),
                int(bool(s.get("is_suspected_marketing"))),
                s.get("intent_strength", ""), "", "", "", ""])
    print(f"已生成标注模板: {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
```

- [ ] **Step 3: 实现 scripts/evaluate.py**

```python
"""对照人工标注计算评论筛选指标。

用法: python scripts/evaluate.py data/annotation_filled.csv
标注文件即 make_annotation_template.py 的输出，"人工_"列由业务方填写；
未填写的行自动跳过。
"""
import csv
import sys


def _acc(pairs: list[tuple[int, int]]) -> float:
    if not pairs:
        return 0.0
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def main(path: str) -> None:
    meaningful, purchase, marketing, strength_pairs = [], [], [], []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["人工_有意义(1/0)"].strip() == "":
                continue
            meaningful.append((int(row["模型_有意义"]),
                               int(row["人工_有意义(1/0)"])))
            purchase.append((int(row["模型_购车相关"]),
                             int(row["人工_购车相关(1/0)"])))
            marketing.append((int(row["模型_疑似营销"]),
                              int(row["人工_疑似营销(1/0)"])))
            strength_pairs.append(
                (row["模型_意向强度"],
                 row["人工_意向强度(none/low/medium/high)"].strip()))

    n = len(meaningful)
    print(f"已标注样本数: {n}")
    if n == 0:
        return
    print(f"有意义判断准确率:   {_acc(meaningful):.2%}")
    print(f"购车相关判断准确率: {_acc(purchase):.2%}")
    print(f"疑似营销判断准确率: {_acc(marketing):.2%}")
    print(f"意向强度一致率:     {_acc(strength_pairs):.2%}")
    high_pairs = [(a, b) for a, b in strength_pairs if a == "high"]
    if high_pairs:
        hit = sum(1 for a, b in high_pairs if b == "high")
        print(f"模型高意向精确率:   {hit / len(high_pairs):.2%} "
              f"({hit}/{len(high_pairs)})")


if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 4: 在 README.md 末尾追加"快速开始"小节**

```markdown
------

## 15. 快速开始（V0）

\`\`\`bash
# 1. 安装依赖
python -m pip install -r requirements.txt

# 2. 配置环境（复制后填写 MySQL 与 LLM 配置）
copy .env.example .env

# 3. 启动服务（自动建表并启动后台 Worker）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
\`\`\`

打开 http://localhost:8000 ：导入 `data/test_data.xlsx` → 启动分析 →
在 `/leads` 查看、审核和导出线索。

评测：分析完成后运行 `python scripts/make_annotation_template.py`
生成标注模板，人工填写后运行
`python scripts/evaluate.py data/annotation_filled.csv` 查看指标。

设计文档见 `claude_docs/2026-07-20-v0-design.md`。
\`\`\`
```

（追加时去掉围栏转义反斜杠；只加这一节，不改动 README 其他内容。）

- [ ] **Step 5: 全量回归并提交**

Run: `python -m pytest -v`
Expected: 全部通过

```bash
git add tests/test_e2e.py scripts/ README.md
git commit -m "feat: 端到端集成测试与评测脚手架"
```

- [ ] **Step 6: 真实模型联调冒烟（人工步骤，不阻塞合并）**

1. 在 `.env` 配置真实 MySQL 与 `LLM_PROVIDER=openai_compat` + 真实 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`；
2. `python -m uvicorn app.main:app --port 8000`；
3. 页面导入 `data/test_data.xlsx` 中 2—3 个视频的子集（可先用 Excel 另存筛选后的小文件）；
4. 启动分析，观察进度页任务全部 success、无 failed；
5. 检查 `/leads` 产出的 H/A 线索证据是否可信，初步调整 Prompt。

---

## 计划自审记录

已按规格逐项核对：

1. **规格覆盖**：设计文档第 2 节（数据）→ Task 3/4；第 3 节（结构）→ Task 1/2；第 4 节（7 表）→ Task 2；第 5 节（Gateway）→ Task 5；第 6 节（三 Skill）→ Task 6/7/8/10；第 7 节（工作流/Worker/幂等/恢复）→ Task 11;第 8 节（页面/审核/API）→ Task 12/13；第 9 节（错误处理）→ Task 5/6/8/11 分层实现；第 10 节（测试评测）→ 各任务测试 + Task 14；第 11 节（.env）→ Task 1。
2. **无占位符**：所有步骤含完整代码与命令。
3. **类型一致性**：`SKILL_VERSIONS`/三个 Skill 常量、`get_current_result`/`save_result` 签名、`ImportBundle`/`ImportStats` 字段、`Worker.run_once` 语义在各任务间已交叉核对一致。

已知的有意取舍（非缺陷）：

- 评测脚本 V0 只覆盖评论筛选指标；线索等级指标依赖 lead 级人工标注，由审核页 `review_status`/`review_tags` 数据承担，后续版本再加脚本。
- `pipeline.advance` 中评论批任务按 `target_id LIKE "{video_id}:%"` 判断是否已建，要求 `target_id` 格式稳定为 `视频ID:批次号`。
- MockProvider 响应按顺序弹出，测试中队列顺序即任务执行顺序（单 Worker `run_once` 循环保证确定性）。

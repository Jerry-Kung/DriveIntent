"""
V1.4 后端审计：为存量库补聚合查询所需索引（幂等，可重复执行）。

- llm_call_log(created_at) → ix_llm_call_created
- api_job(finished_at)     → ix_api_job_finished

数据库连接从 .env 读取（外部 MySQL）。全新部署时 app 首次启动
create_all 会按最新模型自动建出索引，无需运行本脚本。
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]
INDEXES = [
    ("llm_call_log", "ix_llm_call_created", "(created_at)"),
    ("api_job", "ix_api_job_finished", "(finished_at)"),
]

conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 3306)),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=DB_NAME,
)


def table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema=%s AND table_name=%s LIMIT 1",
        (DB_NAME, table))
    return cur.fetchone() is not None


def index_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name=%s AND index_name=%s LIMIT 1",
        (DB_NAME, table, name))
    return cur.fetchone() is not None


with conn:
    with conn.cursor() as cur:
        for table, name, cols in INDEXES:
            if not table_exists(cur, table):
                print(f"{table} 表不存在，跳过（全新库由 app 启动时自动建表建索引）")
            elif index_exists(cur, table, name):
                print(f"索引 {name} 已存在，无需处理")
            else:
                cur.execute(f"ALTER TABLE {table} ADD INDEX {name} {cols}")
                conn.commit()
                print(f"已创建索引 {table}.{name}")

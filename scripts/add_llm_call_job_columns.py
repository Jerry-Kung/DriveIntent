"""
V1.7.1 补丁：为 llm_call_log 增加 job_id 与 account_uid 列，使 LLM 日志精确归属。

- 历史数据两列为 NULL，详情页回退时间窗近似（兼容旧记录）。
- 幂等（列存在时跳过），可重复执行。
- 数据库连接从 .env 读取。
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]

COLUMNS = [
    ("llm_call_log", "job_id", "VARCHAR(36)"),
    ("llm_call_log", "account_uid", "VARCHAR(256)"),
]
INDEXES = [
    ("llm_call_log", "ix_llm_call_job", "(job_id)"),
]

conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 3306)),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=DB_NAME,
)


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s AND column_name=%s LIMIT 1",
        (DB_NAME, table, column))
    return cur.fetchone() is not None


def index_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name=%s AND index_name=%s LIMIT 1",
        (DB_NAME, table, name))
    return cur.fetchone() is not None


with conn:
    with conn.cursor() as cur:
        for table, column, col_type in COLUMNS:
            if column_exists(cur, table, column):
                print(f"[SKIP] {table}.{column} 已存在")
            else:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                conn.commit()
                print(f"[OK]  {table}.{column} 已添加")
        for table, name, cols in INDEXES:
            if index_exists(cur, table, name):
                print(f"[SKIP] 索引 {name} 已存在")
            else:
                cur.execute(f"ALTER TABLE {table} ADD INDEX {name} {cols}")
                conn.commit()
                print(f"[OK]  索引 {table}.{name} 已创建")
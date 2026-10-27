"""
V1.10.1 补丁：为 api_job / llm_call_log 补建性能索引。

- 背景：模型里声明的 ix_api_job_finished、ix_llm_call_created 在生产库缺失。
  SQLAlchemy 的 create_all 只在建表时创建索引，对已存在的表不会补建；测试
  库是全新建表，故断言索引存在也能通过。结果 leads 页 8s、审计页 10s+。
- 本脚本建立三类索引：
    1. api_job.ix_api_job_finished      —— 模型已声明、库内缺失
    2. llm_call_log.ix_llm_call_created —— 模型已声明、库内缺失
    3. api_job.ix_api_job_leads         —— leads 列表筛选+排序覆盖索引
- 幂等（索引存在时跳过），可重复执行，可在服务运行中执行（InnoDB 在线 DDL）。
- 数据库连接从 .env 读取；用法：python scripts/add_perf_indexes.py
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]

# (表名, 索引名, 列定义) —— 顺序即创建顺序，小表在前
INDEXES = [
    ("api_job", "ix_api_job_finished", "(`finished_at`)"),
    ("api_job", "ix_api_job_leads",
     "(`job_type`, `status`, `finished_at`, `id`)"),
    ("llm_call_log", "ix_llm_call_created", "(`created_at`)"),
]


def index_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name=%s AND index_name=%s LIMIT 1",
        (DB_NAME, table, name))
    return cur.fetchone() is not None


conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 3306)),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=DB_NAME,
)

with conn:
    with conn.cursor() as cur:
        for table, name, cols in INDEXES:
            if index_exists(cur, table, name):
                print(f"[SKIP] {table}.{name} 已存在")
                continue
            cur.execute(f"ALTER TABLE `{table}` ADD INDEX `{name}` {cols}")
            conn.commit()
            print(f"[OK]  {table}.{name} 已添加")
print("完成。如为首次执行，请重启服务后观察 /leads 与 /audit 响应时间。")

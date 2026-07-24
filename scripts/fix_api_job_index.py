"""
修复 api_job 表索引：将单列 status 索引替换为复合索引 (status, attempt_count, created_at)，
解决 claim_next_job 查询触发 MySQL Out of sort memory 的问题。

数据库连接从 .env 读取（外部 MySQL）。仅针对已存在旧索引的现存库；
全新部署时 app 首次启动会按最新模型自动建出正确索引，无需运行本脚本。
"""
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]
OLD_INDEX = "ix_api_job_status"
NEW_INDEX = "ix_api_job_status_order"

conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 3306)),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=DB_NAME,
)


def index_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema=%s AND table_name='api_job' AND index_name=%s LIMIT 1",
        (DB_NAME, name))
    return cur.fetchone() is not None


with conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=%s AND table_name='api_job' LIMIT 1",
            (DB_NAME,))
        if cur.fetchone() is None:
            print("api_job 表不存在，无需处理（全新库由 app 启动时自动建表）")
        elif index_exists(cur, NEW_INDEX):
            print(f"复合索引 {NEW_INDEX} 已存在，无需处理")
        else:
            if index_exists(cur, OLD_INDEX):
                cur.execute(f"ALTER TABLE api_job DROP INDEX {OLD_INDEX}")
                print(f"已删除旧索引 {OLD_INDEX}")
            cur.execute(
                f"ALTER TABLE api_job ADD INDEX {NEW_INDEX} "
                "(status, attempt_count, created_at)")
            conn.commit()
            print(f"已创建复合索引 {NEW_INDEX}")

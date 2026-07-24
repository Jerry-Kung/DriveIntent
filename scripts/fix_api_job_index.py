"""
修复 api_job 表索引：将单列 status 索引替换为复合索引 (status, attempt_count, created_at)，
解决 claim_next_job 查询触发 MySQL Out of sort memory 的问题。
"""
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

conn = pymysql.connect(
    host=os.environ["DB_HOST"],
    port=int(os.environ.get("DB_PORT", 3306)),
    user=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
    database=os.environ["DB_NAME"],
)

with conn:
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE api_job DROP INDEX ix_api_job_status, "
                    "ADD INDEX ix_api_job_status_order (status, attempt_count, created_at)")
    conn.commit()
    print("索引替换完成：ix_api_job_status -> ix_api_job_status_order")

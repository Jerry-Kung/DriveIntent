"""
V1.7.3 补丁：为 api_job 增加 lead_grades 列，落每账号真实内部 HABC 等级。

- 用途：对外 intent_level_code 已改为多对一（H/A→high、B→medium、C→low），
  无法据此反推内部 HABC。lead_grades 与 result.results[] 按下标一一对应，
  供内部审计/统计读取，不进对外契约。
- 历史数据该列为 NULL，审计回退按 intent_level_code 反推（旧映射一对一，
  反推仍准确）。
- 幂等（列存在时跳过），可重复执行。
- 数据库连接从 .env 读取。
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]

COLUMN = ("api_job", "lead_grades", "JSON")


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s AND column_name=%s LIMIT 1",
        (DB_NAME, table, column))
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
        table, column, col_type = COLUMN
        if column_exists(cur, table, column):
            print(f"[SKIP] {table}.{column} 已存在")
        else:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()
            print(f"[OK]  {table}.{column} 已添加")

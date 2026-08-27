"""
V1.8.0：为 lead 表增加意向车型识别与分类两列。

- 用途：阶段二重构后，意向车型（intent_models）与分类档位
  （intent_model_category，A/B/C/D）作为结构化结果落库，供下游查询；
  阶段二不再参与评级调整。
- 历史数据两列为 NULL（旧结果无该信息，不回填）。
- 幂等（列存在时跳过），可重复执行。
- 数据库连接从 .env 读取。
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.environ["DB_NAME"]

COLUMNS = [
    ("lead", "intent_models", "JSON"),
    ("lead", "intent_model_category", "VARCHAR(4)"),
]


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
        for table, column, col_type in COLUMNS:
            if column_exists(cur, table, column):
                print(f"[SKIP] {table}.{column} 已存在")
                continue
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            conn.commit()
            print(f"[OK]  {table}.{column} 已添加")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清空测试库中会被 API Worker 消费的 api_job 存量。

仅删除 status IN ('pending','running') 的行；failed/partial/success
为历史结果记录，不会被 worker 捞取，予以保留。删除前后打印统计。
"""
import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import pymysql

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
load_dotenv(Path(__file__).parent.parent / ".env")

conn = pymysql.connect(
    host=os.getenv("DB_HOST"), port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"), charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor, autocommit=False)


def counts():
    with conn.cursor() as c:
        c.execute("SELECT status, COUNT(*) c FROM api_job GROUP BY status")
        return c.fetchall()


print("== 删除前 api_job 状态统计 ==")
for r in counts():
    print("  ", r)

with conn.cursor() as c:
    n = c.execute("DELETE FROM api_job WHERE status IN ('pending','running')")
conn.commit()
print(f"\n== 已删除 {n} 行（pending+running） ==")

print("\n== 删除后 api_job 状态统计 ==")
for r in counts():
    print("  ", r)

conn.close()

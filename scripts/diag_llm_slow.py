#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断 LLM 慢调用：按模型聚合时长/错误分布，观察 9~14 分钟调用具体特征。"""
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
    cursorclass=pymysql.cursors.DictCursor, autocommit=True)


def q(sql, args=None):
    with conn.cursor() as c:
        c.execute(sql, args)
        return c.fetchall()


def section(label, sql):
    print(f"\n== {label} ==")
    try:
        for r in q(sql):
            print(" ", r)
    except Exception as e:
        print(f"  查询失败: {e}")


print("== 当前 UTC ==")
print(" ", q("SELECT UTC_TIMESTAMP() AS now_utc")[0])

section("按模型聚合（近 24 小时）：调用数/错误数/时长分位",
        """SELECT model_name, COUNT(*) AS calls, COUNT(error) AS errors,
                  ROUND(AVG(duration_ms)/1000,1) AS avg_s,
                  ROUND(MIN(duration_ms)/1000,1) AS min_s,
                  ROUND(MAX(duration_ms)/1000,1) AS max_s,
                  SUM(duration_ms >= 300000) AS ge_5min,
                  SUM(duration_ms >= 540000) AS ge_9min,
                  SUM(retry_count) AS retries
           FROM llm_call_log
           WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
           GROUP BY model_name""")

section("按模型+skill 聚合（近 24 小时）",
        """SELECT model_name, skill_id, COUNT(*) AS calls,
                  COUNT(error) AS errors,
                  ROUND(AVG(duration_ms)/1000,1) AS avg_s,
                  ROUND(MAX(duration_ms)/1000,1) AS max_s
           FROM llm_call_log
           WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
           GROUP BY model_name, skill_id ORDER BY model_name, skill_id""")

section("时长直方图（近 24 小时，按 60s 桶）",
        """SELECT model_name,
                  FLOOR(duration_ms/60000) AS minute_bucket,
                  COUNT(*) AS n, COUNT(error) AS errors
           FROM llm_call_log
           WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
           GROUP BY model_name, minute_bucket
           ORDER BY model_name, minute_bucket""")

section("超过 8 分钟的调用明细（近 24 小时，最多 30 条）",
        """SELECT id, skill_id, model_name,
                  ROUND(duration_ms/1000) AS dur_s, retry_count,
                  prompt_tokens, completion_tokens,
                  LEFT(COALESCE(error,''),200) AS err, created_at
           FROM llm_call_log
           WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
             AND duration_ms >= 480000
           ORDER BY id DESC LIMIT 30""")

section("错误样本（近 24 小时，按错误前缀聚合）",
        """SELECT LEFT(COALESCE(error,''),160) AS err_prefix,
                  COUNT(*) AS n, MAX(created_at) AS latest
           FROM llm_call_log
           WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 24 HOUR
             AND error IS NOT NULL
           GROUP BY err_prefix ORDER BY n DESC LIMIT 15""")

section("最新 15 条调用",
        """SELECT id, skill_id, model_name,
                  ROUND(duration_ms/1000) AS dur_s, retry_count,
                  prompt_tokens, completion_tokens,
                  LEFT(COALESCE(error,''),120) AS err, created_at
           FROM llm_call_log ORDER BY id DESC LIMIT 15""")

conn.close()

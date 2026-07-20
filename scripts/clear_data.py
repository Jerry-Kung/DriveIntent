"""清空当前数据库中所有业务表的数据（表结构保留）。

用法：
    python scripts/clear_data.py          # 交互确认后清空
    python scripts/clear_data.py --yes    # 跳过确认直接清空
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (AnalysisResult, AnalysisTask, Comment, Lead,  # noqa: E402
                        LlmCallLog, PlatformUser, Video)

# 先删引用方，再删被引用方，避免外键约束报错
TABLES = [Lead, AnalysisResult, AnalysisTask, LlmCallLog,
          Comment, PlatformUser, Video]


def main() -> None:
    init_db()
    with SessionLocal() as session:
        counts = {m.__tablename__: session.query(m).count() for m in TABLES}
        total = sum(counts.values())
        print(f"目标数据库: {settings.db_host}:{settings.db_port}/{settings.db_name}")
        for name, n in counts.items():
            print(f"  {name}: {n}")
        if total == 0:
            print("所有表已为空，无需清理")
            return
        if "--yes" not in sys.argv:
            answer = input(f"将删除以上共 {total} 行数据，输入 yes 确认: ")
            if answer.strip().lower() != "yes":
                print("已取消")
                return
        for model in TABLES:
            session.execute(delete(model))
        session.commit()
        print("已清空全部数据表")


if __name__ == "__main__":
    main()

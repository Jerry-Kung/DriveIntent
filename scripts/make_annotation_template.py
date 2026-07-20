"""导出评论与模型筛选结果，生成人工标注模板 CSV。

用法: python scripts/make_annotation_template.py [输出路径]
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import SessionLocal
from app.models import Comment
from app.services.results import get_current_result
from app.workflow.pipeline import COMMENT_SCREENING_SKILL, SKILL_VERSIONS


def main(out_path: str = "data/annotation_template.csv") -> None:
    with SessionLocal() as session, \
            open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["comment_id", "content",
                         "模型_有意义", "模型_购车相关", "模型_疑似营销",
                         "模型_意向强度",
                         "人工_有意义(1/0)", "人工_购车相关(1/0)",
                         "人工_疑似营销(1/0)", "人工_意向强度(none/low/medium/high)"])
        for c in session.query(Comment).order_by(Comment.id).all():
            r = get_current_result(
                session, target_type="comment", target_id=str(c.id),
                skill_id=COMMENT_SCREENING_SKILL,
                skill_version=SKILL_VERSIONS[COMMENT_SCREENING_SKILL])
            s = r.result if r else {}
            writer.writerow([
                c.id, c.content,
                int(bool(s.get("is_meaningful"))),
                int(bool(s.get("is_purchase_related"))),
                int(bool(s.get("is_suspected_marketing"))),
                s.get("intent_strength", ""), "", "", "", ""])
    print(f"已生成标注模板: {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:2])

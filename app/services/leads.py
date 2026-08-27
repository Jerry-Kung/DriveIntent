import csv
import io

from sqlalchemy.orm import Session

from app.api.mapping import screened_out_category, screening_dict_passed
from app.models import AnalysisResult, Comment, Lead, PlatformUser
from app.schemas.skills import UserLeadResult


def upsert_lead(session: Session, user_id: int, result: UserLeadResult,
                evidence_comments: list[dict], skill_version: str) -> Lead:
    lead = session.query(Lead).filter_by(user_id=user_id).first()
    if lead is None:
        lead = Lead(user_id=user_id, grade=result.lead_grade)
        session.add(lead)
    lead.grade = result.lead_grade
    lead.is_valid = result.is_valid_lead
    lead.summary = result.lead_summary
    lead.purchase_stage = result.purchase_stage
    lead.target_brands = result.target_brands
    lead.target_models = result.target_models
    lead.intent_models = result.intent_models
    lead.intent_model_category = result.intent_model_category
    lead.core_needs = result.core_needs
    lead.main_concerns = result.main_concerns
    lead.purchase_time = result.purchase_time
    lead.usage_scenario = result.usage_scenario
    lead.entry_point = result.recommended_entry_point
    lead.verification_questions = result.verification_questions
    lead.evidence = evidence_comments
    lead.confidence = result.confidence
    lead.skill_version = skill_version
    session.commit()
    return lead


GRADE_ORDER = {"H": 0, "A": 1, "B": 2, "C": 3}


def query_leads(session: Session, *, grade: str | None = None,
                brand: str | None = None, model: str | None = None,
                review_status: str | None = None) -> list[Lead]:
    q = session.query(Lead)
    if grade:
        q = q.filter(Lead.grade == grade)
    if review_status:
        q = q.filter(Lead.review_status == review_status)
    leads = q.all()
    if brand:
        leads = [l for l in leads if brand in (l.target_brands or [])]
    if model:
        leads = [l for l in leads if model in (l.target_models or [])]
    return sorted(leads, key=lambda l: (GRADE_ORDER.get(l.grade, 9),
                                        -(l.confidence or 0)))


# 与 app/workflow/pipeline.py 的同名常量一致；
# 不直接 import 以避免 pipeline <-> services 循环依赖
USER_ANALYSIS_SKILL_ID = "user_lead_analysis"
COMMENT_SCREENING_SKILL_ID = "comment_lead_screening"


def _latest_screenings(session: Session) -> dict[int, dict]:
    """每条评论取最新一次初筛结果，返回 {comment_id: 初筛结果}。"""
    results = (session.query(AnalysisResult)
               .filter_by(target_type="comment",
                          skill_id=COMMENT_SCREENING_SKILL_ID,
                          status="success")
               .order_by(AnalysisResult.id).all())
    latest: dict[int, dict] = {}
    for r in results:
        try:
            latest[int(r.target_id)] = r.result or {}
        except ValueError:
            continue
    return latest


def query_screened_out_comments(session: Session) -> list[dict]:
    """返回未通过评论初筛的评论（每条取最新初筛结果），供人工核验初筛效果。

    含三类：疑似营销水军（marketing）、无购买倾向（no_intent）、
    与购车无关（unrelated）。
    """
    dropped = [(cid, res) for cid, res in _latest_screenings(session).items()
               if not screening_dict_passed(res)]

    comment_ids = [cid for cid, _ in dropped]
    comments = ({c.id: c for c in session.query(Comment)
                 .filter(Comment.id.in_(comment_ids)).all()}
                if comment_ids else {})
    user_ids = {c.user_id for c in comments.values()}
    users = ({u.id: u for u in session.query(PlatformUser)
              .filter(PlatformUser.id.in_(user_ids)).all()}
             if user_ids else {})

    rows: list[dict] = []
    for cid, res in dropped:
        c = comments.get(cid)
        if c is None:
            continue
        u = users.get(c.user_id)
        rows.append({
            "comment_id": cid,
            "content": c.content or "",
            "nickname": u.nickname if u else "",
            "platform": u.platform if u else "",
            "category": screened_out_category(res),
            "reason": res.get("reason") or "",
            "confidence": res.get("confidence"),
        })
    # 疑似水军在前（数量少、复核价值高），无购买倾向次之，非购车相关最后
    order = {"marketing": 0, "no_intent": 1, "unrelated": 2}
    return sorted(rows, key=lambda d: (order.get(d["category"], 9),
                                       -(d["confidence"] or 0)))


def query_unclassified_users(session: Session) -> list[dict]:
    """返回已做用户深度分析但未进入 HABC 线索库的用户（每人取最新结果）。

    包含两类：模型判定 is_valid_lead=false（水军、无真实购车需求等），
    以及判定有效但证据评论全部无法核实而被拦下的用户。
    附带该用户进入深度分析时的原始评论内容（即通过初筛的评论），
    供人工复核。全程批量查询，避免逐用户多次数据库往返。
    """
    lead_user_ids = {uid for (uid,) in session.query(Lead.user_id).all()}
    results = (session.query(AnalysisResult)
               .filter_by(target_type="user", skill_id=USER_ANALYSIS_SKILL_ID,
                          status="success")
               .order_by(AnalysisResult.id.desc()).all())
    seen: set[int] = set()
    pending: list[tuple[int, dict]] = []
    for r in results:
        try:
            uid = int(r.target_id)
        except ValueError:
            continue
        if uid in seen:
            continue
        seen.add(uid)
        if uid in lead_user_ids:
            continue
        pending.append((uid, r.result or {}))
    if not pending:
        return []

    uids = [uid for uid, _ in pending]
    users = {u.id: u for u in session.query(PlatformUser)
             .filter(PlatformUser.id.in_(uids)).all()}
    passed_ids = [cid for cid, res in _latest_screenings(session).items()
                  if screening_dict_passed(res)]
    comments_by_user: dict[int, list[str]] = {}
    if passed_ids:
        for c in (session.query(Comment)
                  .filter(Comment.user_id.in_(uids),
                          Comment.id.in_(passed_ids))
                  .order_by(Comment.comment_time).all()):
            comments_by_user.setdefault(c.user_id, []).append(c.content)

    rows: list[dict] = []
    for uid, res in pending:
        user = users.get(uid)
        rows.append({
            "user_id": uid,
            "nickname": user.nickname if user else "",
            "platform": user.platform if user else "",
            "verdict": ("invalid" if not res.get("is_valid_lead")
                        else "no_evidence"),
            "summary": res.get("lead_summary") or "",
            "target_brands": res.get("target_brands") or [],
            "target_models": res.get("target_models") or [],
            "confidence": res.get("confidence"),
            "comments": comments_by_user.get(uid, []),
        })
    return sorted(rows, key=lambda d: -(d["confidence"] or 0))


def leads_to_dicts(session: Session, leads: list[Lead]) -> list[dict]:
    """批量转换线索。一次性取回全部关联用户并显式传入，避免逐条线索
    一次用户查询的 N+1 往返（远程库下每次往返数十毫秒，147 条即数秒）。
    注意不能只靠预取“预热” session：身份映射是弱引用，预取结果一丢弃
    就会被回收，session.get 仍会逐条查库。"""
    uids = list({l.user_id for l in leads})
    users = ({u.id: u for u in session.query(PlatformUser)
              .filter(PlatformUser.id.in_(uids)).all()}
             if uids else {})
    return [lead_to_dict(session, l, user=users.get(l.user_id))
            for l in leads]


def lead_to_dict(session: Session, lead: Lead,
                 user: PlatformUser | None = None) -> dict:
    if user is None:
        user = session.get(PlatformUser, lead.user_id)
    return {
        "id": lead.id, "nickname": user.nickname if user else "",
        "platform": user.platform if user else "", "grade": lead.grade,
        "target_brands": lead.target_brands or [],
        "target_models": lead.target_models or [],
        "intent_models": lead.intent_models or [],
        "intent_model_category": lead.intent_model_category,
        "summary": lead.summary, "purchase_stage": lead.purchase_stage,
        "core_needs": lead.core_needs or [],
        "main_concerns": lead.main_concerns or [],
        "purchase_time": lead.purchase_time,
        "usage_scenario": lead.usage_scenario,
        "entry_point": lead.entry_point,
        "verification_questions": lead.verification_questions or [],
        "evidence": lead.evidence or [], "confidence": lead.confidence,
        "review_status": lead.review_status,
        "review_tags": lead.review_tags or [],
        "review_note": lead.review_note,
        "created_at": lead.created_at.isoformat(),
    }


def _csv_safe(value):
    """防止 Excel/表格软件将以 =、+、-、@ 开头的单元格当公式执行。"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def leads_to_csv(session: Session, leads: list[Lead]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["昵称", "平台", "等级", "品牌", "车型", "摘要",
                     "核心需求", "主要顾虑", "购车时间", "销售切入点",
                     "置信度", "审核状态", "分析时间"])
    for d in leads_to_dicts(session, leads):
        writer.writerow([
            _csv_safe(d["nickname"]), _csv_safe(d["platform"]),
            _csv_safe(d["grade"]),
            _csv_safe("/".join(d["target_brands"])),
            _csv_safe("/".join(d["target_models"])),
            _csv_safe(d["summary"]), _csv_safe("/".join(d["core_needs"])),
            _csv_safe("/".join(d["main_concerns"])),
            _csv_safe(d["purchase_time"] or ""),
            _csv_safe(d["entry_point"] or ""), d["confidence"],
            _csv_safe(d["review_status"]), d["created_at"]])
    return buf.getvalue()

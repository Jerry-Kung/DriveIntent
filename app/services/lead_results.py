"""V1.7.1 线索结果查询：从 api_job 扁平化精筛结果，支持分页/筛选/导出。

数据源为对外 API 异步路径落库的 api_job（job_type='profile_analysis'），
result.results[] 每账号一条，与 request_payload.accounts[] 顺序一致。
本模块只读 api_job 与 llm_call_log，不写库，业务模块不依赖本模块。

V1.10.1：列表/筛选/导出改读 lead_record 汇总表（api_job.result 的物化派生
表，作业终态同事务写入）。此前查询期展开 result 大列（平均 50 KB/作业、
全量 346 MB），首页 8s、等级筛选 140s；改用普通列 + 索引后均为毫秒级。
lead_record 为空时（未回填的旧库）回退原 JSON 展开路径，保证功能可用。
时间口径：库内 finished_at/created_at 为 UTC 朴素时间，日期筛选按东八区
自然日转换。
"""
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session, undefer

from app.config import settings
from app.models import ApiJob, LeadRecord, LlmCallLog

logger = logging.getLogger(__name__)

TZ8 = timezone(timedelta(hours=8))

# 对外 intent_level_code → 内部等级；null/error/未知统一 C（口径同
# docs/20260813-14_精筛定级等级分布统计.md）。
# V1.7.3：前向映射已改多对一（H/A→high、B→medium、C→low），新数据不再依
# 赖本表反推——api_job.lead_grades 记录真实 HABC，见 grade_of()。本表仅作
# 旧数据（lead_grades 为 NULL）回退，旧映射一对一，反推仍准确。
_GRADE_FROM_CODE = {"high": "H", "medium": "A", "low": "B"}


def grade_of(acct: dict, internal_grade: str | None = None) -> str:
    """账号的内部 HABC 等级。

    internal_grade 非空（api_job.lead_grades 提供）时原样返回；为空/缺省
    时回退按对外 intent_level_code 反推（仅历史数据，旧映射一对一）。
    """
    if internal_grade:
        return internal_grade
    return _GRADE_FROM_CODE.get(acct.get("intent_level_code"), "C")


def _account_count(db):
    """SQL 表达式：result->'$.results' 数组长度，按方言分派。"""
    if db.get_bind().dialect.name == "mysql":
        return func.json_length(ApiJob.result, "$.results")
    return func.json_array_length(ApiJob.result, "$.results")


def _iso_utc8(dt):
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc).astimezone(TZ8)
            .isoformat(timespec="seconds"))


def date_bounds(date_str: str) -> tuple[datetime, datetime] | None:
    """'YYYY-MM-DD' 东八区自然日 → UTC [start, end) 朴素时间边界；非法返回 None。"""
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    start_local = d.replace(tzinfo=TZ8)
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None))


def _base_query(session: Session, *, date_from: str | None = None,
                date_to: str | None = None):
    q = (session.query(ApiJob)
         .filter(ApiJob.job_type == "profile_analysis",
                 ApiJob.result.isnot(None),
                 ApiJob.status.in_(["success", "partial"])))
    if date_from:
        b = date_bounds(date_from)
        if b:
            q = q.filter(ApiJob.finished_at >= b[0])
    if date_to:
        b = date_bounds(date_to)
        if b:
            q = q.filter(ApiJob.finished_at < b[1])
    return q.order_by(ApiJob.finished_at.desc(), ApiJob.id.desc())


def _to_row(job: ApiJob, idx: int, acct: dict) -> dict:
    # V1.7.3：优先读 lead_grades 真实 HABC；旧数据为 NULL，回退按 code 反推
    lead_grades = job.lead_grades or []
    internal_grade = (lead_grades[idx] if idx < len(lead_grades) else None)
    return {
        "job_id": job.id,
        "index": idx,
        "account_uid": acct.get("account_uid") or "",
        "grade": grade_of(acct, internal_grade),
        "value_score": acct.get("value_score"),
        "is_car_owner": acct.get("is_car_owner"),
        "has_purchase_intent": acct.get("has_purchase_intent"),
        # V1.8.0：意向车型识别与分类；历史数据无键，回退 []/None
        "intent_models": acct.get("intent_models") or [],
        "intent_model_category": acct.get("intent_model_category"),
        "profile_summary": acct.get("profile_summary") or "",
        "profile_tags": acct.get("profile_tags") or [],
        "analysis": acct.get("analysis") or "",
        "processed_at": acct.get("processed_at"),
        "error": acct.get("error"),
        "finished_at": _iso_utc8(job.finished_at),
    }


def _flatten_job(job: ApiJob) -> list[dict]:
    results = (job.result or {}).get("results") or []
    return [_to_row(job, idx, acct)
            for idx, acct in enumerate(results) if isinstance(acct, dict)]


def _all_rows(session: Session, *, grade: str | None = None,
              date_from: str | None = None,
              date_to: str | None = None) -> list[dict]:
    """全量扁平化行（CSV 导出用）。

    V1.10.1：优先读 lead_record 汇总表；该表为空（未回填的旧库）时回退
    原来的 JSON 展开路径。
    """
    if _summary_ready(session):
        return _all_rows_from_records(session, grade=grade,
                                      date_from=date_from, date_to=date_to)
    rows = []
    for job in _base_query(session, date_from=date_from, date_to=date_to).all():
        for r in _flatten_job(job):
            if grade is None or r["grade"] == grade:
                rows.append(r)
    return rows


def _summary_ready(session: Session) -> bool:
    """汇总表是否可安全作为列表数据源。

    判据是「就绪标记文件存在」，而不是「汇总表有数据」：回填脚本按时间
    升序写入，中途失败会让汇总表只含部分旧作业——若按"有数据"就切换，
    列表会**静默地**只显示一部分（且恰好缺的是最新的那批）。标记由回填
    脚本在完备性自检通过后才写入，故标记不在时一律走 JSON 展开回退路径
    （慢但完整）。

    全新部署无历史可回填，标记由 main 启动时补齐（见 ensure_marker_for_fresh_db），
    新作业随后由 worker 终态持续写入，表天然保持完整。

    session 参数当前未使用，保留以便将来改为按库内状态判定而不破坏调用点。
    """
    try:
        return Path(settings.lead_record_ready_marker).exists()
    except OSError:                     # 路径不可访问时按未就绪处理
        logger.warning("线索汇总表就绪标记检查失败，本次按回退路径处理",
                       exc_info=True)
        return False


def write_ready_marker() -> None:
    """写入汇总表就绪标记，服务随即切换到快路径。

    由回填脚本在完备性自检通过后调用（见 scripts/backfill_lead_records.py）。
    写在此处而非脚本内，是为了让脚本反向依赖应用代码：脚本在模块顶层执行
    load_dotenv()，若由应用或测试导入脚本模块，会把 .env 灌进 os.environ，
    污染同一进程内其它测试/配置读取。应用代码绝不可依赖 scripts/ 下的模块。
    """
    marker = Path(settings.lead_record_ready_marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        datetime.utcnow().isoformat(timespec="seconds") + "\n", encoding="utf-8")
    logger.info("线索汇总表就绪标记已写入: %s", marker)


def ensure_marker_for_fresh_db(session: Session) -> bool:
    """全新库（无任何历史精筛作业）直接标记汇总表就绪，返回是否已就绪。

    没有历史作业就没有回填这回事，若不在此补齐标记，新库会一直停在慢的
    JSON 回退路径上，直到有人想起跑回填脚本——而那时并没有东西可回填。
    已有历史作业时不动标记，交由 scripts/backfill_lead_records.py 自检后写入。
    """
    marker = Path(settings.lead_record_ready_marker)
    try:
        if marker.exists():
            return True
    except OSError:
        return False
    # 有历史作业（含已产生汇总行的情况）→ 等回填脚本写标记
    historical = (session.query(ApiJob.id)
                  .filter(ApiJob.job_type == "profile_analysis",
                          ApiJob.result.isnot(None)).first())
    if historical is not None:
        logger.info("检测到历史精筛作业，线索汇总表待回填；"
                    "请执行 python scripts/backfill_lead_records.py")
        return False
    try:
        write_ready_marker()
    except OSError:
        logger.warning("线索汇总表就绪标记写入失败，列表将走回退路径",
                       exc_info=True)
        return False
    logger.info("全新数据库：线索汇总表已标记就绪，列表走汇总表路径")
    return True


def _record_to_row(rec: LeadRecord) -> dict:
    """lead_record → 对外查询行（键与 _to_row 完全一致）。"""
    return {
        "job_id": rec.job_id,
        "index": rec.idx,
        "account_uid": rec.account_uid or "",
        "grade": rec.grade,
        "value_score": rec.value_score,
        "is_car_owner": rec.is_car_owner,
        "has_purchase_intent": rec.has_purchase_intent,
        "intent_models": rec.intent_models or [],
        "intent_model_category": rec.intent_model_category,
        "profile_summary": rec.profile_summary or "",
        "profile_tags": rec.profile_tags or [],
        "analysis": rec.analysis or "",
        "processed_at": rec.processed_at,
        "error": rec.error,
        "finished_at": _iso_utc8(rec.finished_at),
    }


def _records_query(session: Session, *, grade: str | None = None,
                   date_from: str | None = None,
                   date_to: str | None = None):
    """汇总表查询：筛选与排序全部落到普通列与索引上。

    排序口径与旧 JSON 展开实现一致：finished_at 倒序、作业 id 倒序、
    作业内按账号下标升序（见 models.lead_record 的索引声明）。
    """
    q = session.query(LeadRecord)
    if grade:
        q = q.filter(LeadRecord.grade == grade)
    if date_from:
        b = date_bounds(date_from)
        if b:
            q = q.filter(LeadRecord.finished_at >= b[0])
    if date_to:
        b = date_bounds(date_to)
        if b:
            q = q.filter(LeadRecord.finished_at < b[1])
    return q.order_by(LeadRecord.finished_at.desc(),
                      LeadRecord.job_id.desc(), LeadRecord.idx.asc())


def _all_rows_from_records(session: Session, *, grade: str | None = None,
                           date_from: str | None = None,
                           date_to: str | None = None) -> list[dict]:
    return [_record_to_row(r) for r in _records_query(
        session, grade=grade, date_from=date_from, date_to=date_to)]


def _query_from_records(session: Session, *, grade: str | None,
                        date_from: str | None, date_to: str | None,
                        page: int, size: int) -> dict:
    """汇总表分页：count + 当页 LIMIT/OFFSET，均为普通列查询。"""
    q = _records_query(session, grade=grade, date_from=date_from,
                       date_to=date_to)
    total = q.order_by(None).count()
    rows = q.offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size,
            "rows": [_record_to_row(r) for r in rows]}


def query_lead_results(session: Session, *, grade: str | None = None,
                       date_from: str | None = None,
                       date_to: str | None = None,
                       page: int = 1, size: int = 20) -> dict:
    if _summary_ready(session):
        return _query_from_records(session, grade=grade, date_from=date_from,
                                   date_to=date_to, page=page, size=size)
    # 回退路径：汇总表为空（未回填的旧库），沿用原 JSON 展开实现
    if grade:
        rows = _all_rows(session, grade=grade, date_from=date_from,
                         date_to=date_to)
        total = len(rows)
        return {"total": total, "page": page, "size": size,
                "rows": rows[(page - 1) * size: page * size]}

    base = _base_query(session, date_from=date_from, date_to=date_to)
    counts = base.with_entities(ApiJob.id, _account_count(session)).all()
    total = sum(n or 0 for _, n in counts)
    start = (page - 1) * size
    end = start + size
    cursor = 0
    selected: list[tuple[str, int, int]] = []
    for job_id, n in counts:
        n = n or 0
        if n == 0:
            continue
        job_start = cursor
        job_end = cursor + n
        cursor = job_end
        if job_end <= start or job_start >= end:
            continue
        selected.append((job_id, max(start - job_start, 0),
                         min(job_end, end) - job_start))
        if cursor >= end:
            break
    if not selected:
        return {"total": total, "page": page, "size": size, "rows": []}
    job_ids = [jid for jid, _, _ in selected]
    jobs = {j.id: j for j in session.query(ApiJob)
            .filter(ApiJob.id.in_(job_ids)).all()}
    rows = []
    for job_id, i0, i1 in selected:
        job = jobs.get(job_id)
        if job is None:
            continue
        results = (job.result or {}).get("results") or []
        for idx in range(i0, min(i1, len(results))):
            acct = results[idx]
            if isinstance(acct, dict):
                rows.append(_to_row(job, idx, acct))
    return {"total": total, "page": page, "size": size, "rows": rows}


# 详情页黑名单类型展示：库内 blacklist_type 为对外枚举值（"confirmed"）或
# 中文枚举（"营销号"/"虚假账号"，见 schemas.skills）。confirmed 在审计界面
# 显式写作"确认黑名单"，与过滤节点判定的"疑似"两类区分开——二者同置
# is_blacklisted=true 但来源不同（前者为库内黑名单短路，后者为 LLM 判定）。
_BLACKLIST_TYPE_LABEL = {"confirmed": "确认黑名单"}


def blacklist_label(acct: dict) -> str:
    """详情页「黑名单」一行与标题徽标的展示文本。

    acct 为 api_job.result.results[] 的账号对象。历史数据（V1.9 之前）无
    这三个键，一律回退"-"。命中但类型缺失/为空时展示"是"，避免出现
    "已命中黑名单却显示 -"的自相矛盾读法。
    """
    if not acct.get("is_blacklisted"):
        return "-"
    t = (acct.get("blacklist_type") or "").strip()
    if not t:
        return "是"
    return _BLACKLIST_TYPE_LABEL.get(t, t)


def _call_dict(c) -> dict:
    return {"created_at": _iso_utc8(c.created_at), "skill_id": c.skill_id,
            "skill_version": c.skill_version,
            "prompt_version": c.prompt_version, "model_name": c.model_name,
            "prompt_tokens": c.prompt_tokens,
            "completion_tokens": c.completion_tokens,
            "duration_ms": c.duration_ms, "error": c.error}


def lead_detail_data(session: Session, job_id: str, index: int) -> dict | None:
    job = (session.query(ApiJob).options(undefer(ApiJob.request_payload))
           .filter(ApiJob.id == job_id).first())
    if job is None:
        return None
    results = (job.result or {}).get("results") or []
    if index < 0 or index >= len(results):
        return None
    acct = results[index]
    if not isinstance(acct, dict):
        return None
    payload = job.request_payload or {}
    accounts = payload.get("accounts") or []
    input_acct = (accounts[index]
                  if index < len(accounts) and isinstance(accounts[index], dict)
                  else {})

    # V1.7.1 精确关联：优先按 job_id + account_uid 匹配（V1.7.1 起落库
    # 写入），详情页只展示该账号自身的 3~5 次调用。历史数据回退时间窗近似。
    account_uid = acct.get("account_uid")
    calls = (session.query(LlmCallLog)
             .filter(LlmCallLog.job_id == job_id,
                     LlmCallLog.account_uid == account_uid)
             .order_by(LlmCallLog.created_at).all())
    if not calls:
        # 回退：旧日志无 job_id，按作业时间窗近似（多 worker 并发时不可靠）
        window_end = job.finished_at or datetime.utcnow()
        calls = (session.query(LlmCallLog)
                 .filter(LlmCallLog.created_at >= job.created_at,
                         LlmCallLog.created_at <= window_end)
                 .order_by(LlmCallLog.created_at).all())
    lead_grades = job.lead_grades or []
    internal_grade = (lead_grades[index] if index < len(lead_grades) else None)
    return {"job_id": job.id, "status": job.status,
            "created_at": _iso_utc8(job.created_at),
            "finished_at": _iso_utc8(job.finished_at),
            "progress_done": job.progress_done,
            "progress_total": job.progress_total,
            "acct": acct, "input": input_acct,
            "calls": [_call_dict(c) for c in calls],
            "blacklist_label": blacklist_label(acct),
            "grade": grade_of(acct, internal_grade)}


def _csv_safe(value):
    """防止 Excel/表格软件将以 =、+、-、@ 开头的单元格当公式执行。"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def export_lead_results_csv(session: Session, *, grade: str | None = None,
                            date_from: str | None = None,
                            date_to: str | None = None) -> str:
    rows = _all_rows(session, grade=grade, date_from=date_from,
                     date_to=date_to)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["账号UID", "等级", "价值分", "车主", "购车意向",
                     "意向车型", "车型分类",
                     "画像标签", "画像摘要", "分析文本", "处理时间", "作业ID"])
    for r in rows:
        writer.writerow([
            _csv_safe(r["account_uid"]), r["grade"], r["value_score"],
            r["is_car_owner"], r["has_purchase_intent"],
            _csv_safe("/".join(r["intent_models"])),
            r["intent_model_category"] or "",
            _csv_safe("/".join(r["profile_tags"])),
            _csv_safe(r["profile_summary"]), _csv_safe(r["analysis"]),
            r["processed_at"], r["job_id"]])
    return buf.getvalue()

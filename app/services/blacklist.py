from sqlalchemy.orm import Session

from app.models import BlacklistedUser


def _validate_douyin_id(raw: str) -> bool:
    """判断是否为合法 douyin_id：非空且为纯数字字符串。"""
    stripped = raw.strip()
    return bool(stripped) and stripped.isdigit()


def add_blacklist(session: Session, douyin_ids,
                  nickname: str | None = None,
                  remark: str | None = None) -> dict:
    """批量加入黑名单，幂等。

    仅接受纯数字字符串作为合法 douyin_id；空串/空白串/含非数字字符的
    条目计入 invalid 且不入库。库内已存在者跳过（计入 skipped），本批
    内部重复出现的合法 ID 只首次入库，其余去重跳过。同批共用同一
    nickname / remark，应用到入库的每一条记录。

    返回统计字典：{"added": 新增条数, "skipped": 重复条数, "invalid": 非法条数}。
    """
    # 先归一化：记录每个合法 ID 在本批内出现的次数，非法输入单独计数
    occurrence_count: dict[str, int] = {}
    invalid = 0
    for raw in douyin_ids:
        if _validate_douyin_id(str(raw)):
            normalized = str(raw).strip()
            occurrence_count[normalized] = occurrence_count.get(normalized, 0) + 1
        else:
            invalid += 1

    added = 0
    skipped = 0
    to_insert: list[BlacklistedUser] = []
    # 查询库内已存在的 douyin_id，避免逐条 N+1；空列表跳过查询
    existing: set[str] = set()
    if occurrence_count:
        existing = {row.douyin_id for row in session.query(BlacklistedUser)
                    .filter(BlacklistedUser.douyin_id.in_(
                        list(occurrence_count.keys()))).all()}

    for uid, count in occurrence_count.items():
        if uid in existing:
            # 已在库内：本批出现的每一次都计为跳过，不入库
            skipped += count
        else:
            # 首次出现新增入库，之后出现的计为跳过（同批去重）
            to_insert.append(BlacklistedUser(douyin_id=uid,
                                             nickname=nickname, remark=remark))
            existing.add(uid)
            added += 1
            skipped += count - 1

    if to_insert:
        session.add_all(to_insert)
        session.commit()

    return {"added": added, "skipped": skipped, "invalid": invalid}


def load_blacklist_matches(session: Session, ids) -> set[str]:
    """返回入参 id 中命中黑名单表的 douyin_id 集合；空候选返回空集。"""
    id_list = [str(i).strip() for i in ids]
    if not id_list:
        return set()
    matches = set()
    existing = (session.query(BlacklistedUser.douyin_id)
                .filter(BlacklistedUser.douyin_id.in_(id_list)).all())
    if existing:
        matches = {row[0] for row in existing}
    return matches


def list_blacklist(session: Session) -> list[BlacklistedUser]:
    """返回全部黑名单记录，按 created_at 倒序。"""
    return (session.query(BlacklistedUser)
            .order_by(BlacklistedUser.created_at.desc(),
                      BlacklistedUser.id.desc()).all())


def delete_blacklist(session: Session, record_id: int) -> bool:
    """按记录 id 删除黑名单条目；删除成功返回 True，无此 id 返回 False。"""
    row = session.get(BlacklistedUser, record_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True

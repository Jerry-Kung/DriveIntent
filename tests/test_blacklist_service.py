"""黑名单数据模型与服务层测试。

覆盖：模型字段与 douyin_id 唯一约束；add_blacklist 的新增/重复跳过/
非法归一/同批次去重消歧；load_blacklist_matches 命中/未命中/空候选；
list_blacklist created_at 倒序；delete_blacklist 命中/未命中。
"""

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import BlacklistedUser
from app.services.blacklist import (add_blacklist, delete_blacklist,
                                    list_blacklist, load_blacklist_matches)


def _seed(session, *douyin_ids):
    """直接向库内写入 n 条黑名单记录，返回各记录对象，供前置/校验使用。"""
    rows = []
    for uid in douyin_ids:
        row = BlacklistedUser(douyin_id=uid)
        session.add(row)
        rows.append(row)
    session.commit()
    return rows


# --------------------------------------------------------------------------- #
# 模型字段与唯一约束
# --------------------------------------------------------------------------- #

def test_model_fields_and_defaults(session):
    row = BlacklistedUser(douyin_id="79373130119", nickname="昵称",
                          remark="备注")
    session.add(row)
    session.flush()
    assert row.id is not None
    assert row.douyin_id == "79373130119"
    assert row.nickname == "昵称"
    assert row.remark == "备注"
    assert isinstance(row.created_at, datetime)
    # 未填 nickname / remark 时允许为 NULL
    row2 = BlacklistedUser(douyin_id="123456")
    session.add(row2)
    session.flush()
    assert row2.nickname is None
    assert row2.remark is None


def test_douyin_id_unique_constraint(session):
    """库内存在同名 douyin_id 时，再插一条应触发唯一约束。"""
    _seed(session, "79373130119")
    session.add(BlacklistedUser(douyin_id="79373130119"))
    with pytest.raises(IntegrityError):
        session.flush()


# --------------------------------------------------------------------------- #
# add_blacklist：新增 / 重复跳过 / 非法归一 / 同批次去重
# --------------------------------------------------------------------------- #

def test_add_blacklist_adds_new_ids(session):
    result = add_blacklist(session, ["79373130119", "79373130120"])
    assert result == {"added": 2, "skipped": 0, "invalid": 0}
    # 落库核对
    session.flush()
    assert load_blacklist_matches(session, ["79373130119",
                                            "79373130120"]) == {
        "79373130119", "79373130120"}


def test_add_blacklist_skips_duplicate_in_db(session):
    _seed(session, "79373130119")
    result = add_blacklist(session, ["79373130119", "79373130121"])
    # 已在库中的那条跳过，另一条新增
    assert result == {"added": 1, "skipped": 1, "invalid": 0}
    session.flush()
    assert load_blacklist_matches(session, ["79373130119",
                                            "79373130121"]) == {
        "79373130119", "79373130121"}


def test_add_blacklist_counts_invalid(session):
    result = add_blacklist(session, ["79373130119", "abc", "", "   ",
                                     "12ab", "79373130120"])
    # 纯数字的 79373130119 / 79373130120 新增；abc / "" / "   " / 12ab 非法
    assert result == {"added": 2, "skipped": 0, "invalid": 4}
    session.flush()
    assert load_blacklist_matches(session, ["abc", "", "   ", "12ab"]) == set()


def test_add_blacklist_dedup_within_batch(session):
    """同一批内重复出现的合法 ID：首次 insert，后续去重跳过。"""
    result = add_blacklist(session, ["79373130119", "79373130119",
                                     "79373130120"])
    assert result == {"added": 2, "skipped": 1, "invalid": 0}
    session.flush()
    # 只落库一次
    assert session.query(BlacklistedUser).filter_by(
        douyin_id="79373130119").count() == 1


def test_add_blacklist_same_id_already_in_db_in_batch(session):
    """库内已有 + 本批重复出现：两次都计为跳过。"""
    _seed(session, "79373130119")
    result = add_blacklist(session, ["79373130119", "79373130119"])
    assert result == {"added": 0, "skipped": 2, "invalid": 0}


def test_add_blacklist_shared_nickname_and_remark(session):
    """同批共用同一 nickname / remark，应用到入库的每一条记录。"""
    result = add_blacklist(session, ["79373130119", "79373130120"],
                           nickname="批量昵称", remark="批量备注")
    assert result == {"added": 2, "skipped": 0, "invalid": 0}
    session.flush()
    rows = (session.query(BlacklistedUser)
            .filter(BlacklistedUser.douyin_id.in_(["79373130119",
                                                   "79373130120"]))
            .all())
    assert len(rows) == 2
    for row in rows:
        assert row.nickname == "批量昵称"
        assert row.remark == "批量备注"


def test_add_blacklist_empty_input(session):
    result = add_blacklist(session, [])
    assert result == {"added": 0, "skipped": 0, "invalid": 0}


# --------------------------------------------------------------------------- #
# load_blacklist_matches：命中 / 未命中 / 空候选
# --------------------------------------------------------------------------- #

def test_load_blacklist_matches_hit_and_miss(session):
    _seed(session, "79373130119")
    matches = load_blacklist_matches(session, ["79373130119",
                                               "79373130199", "999999"])
    assert matches == {"79373130119"}


def test_load_blacklist_matches_empty_input(session):
    _seed(session, "79373130119")
    assert load_blacklist_matches(session, []) == set()


# --------------------------------------------------------------------------- #
# list_blacklist：created_at 倒序
# --------------------------------------------------------------------------- #

def test_list_blacklist_newest_first(session):
    rows = _seed(session, "111111", "222222", "333333")
    # 人工将 created_at 改为递增顺序，以便验证倒序
    for i, row in enumerate(rows):
        row.created_at = datetime(2026, 1, 1 + i)
    session.commit()
    listed = list_blacklist(session)
    assert [r.douyin_id for r in listed] == ["333333", "222222", "111111"]


# --------------------------------------------------------------------------- #
# delete_blacklist：命中 / 未命中
# --------------------------------------------------------------------------- #

def test_delete_blacklist_hit(session):
    (row,) = _seed(session, "79373130119")
    assert delete_blacklist(session, row.id) is True
    session.flush()
    assert load_blacklist_matches(session, ["79373130119"]) == set()


def test_delete_blacklist_miss(session):
    _seed(session, "79373130119")
    assert delete_blacklist(session, 999999) is False

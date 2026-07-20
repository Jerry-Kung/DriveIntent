import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Comment, PlatformUser, Video


def _mk(session):
    v = Video(platform="douyin", external_id="v1", title="t", description="d")
    u = PlatformUser(platform="douyin", external_id="u1", nickname="n")
    session.add_all([v, u])
    session.flush()
    c = Comment(platform="douyin", external_id="c1", video_id=v.id,
                user_id=u.id, content="hello")
    session.add(c)
    session.flush()
    return v, u, c


def test_create_core_rows(session):
    v, u, c = _mk(session)
    assert v.id and u.id and c.id


def test_video_unique_constraint(session):
    _mk(session)
    session.add(Video(platform="douyin", external_id="v1"))
    with pytest.raises(IntegrityError):
        session.flush()

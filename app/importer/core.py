import logging

from pydantic import BaseModel
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.importer.tags import extract_tags
from app.models import Comment, PlatformUser, Video
from app.schemas.import_data import ImportBundle

logger = logging.getLogger(__name__)


class ImportStats(BaseModel):
    videos_new: int = 0
    videos_skipped: int = 0
    users_new: int = 0
    users_skipped: int = 0
    comments_new: int = 0
    comments_skipped: int = 0
    empty_comments: int = 0


def _existing_ids(session: Session, model, platform: str) -> dict[str, int]:
    rows = session.query(model.external_id, model.id).filter(
        model.platform == platform).all()
    return {ext: pk for ext, pk in rows}


def import_bundle(session: Session, bundle: ImportBundle) -> ImportStats:
    # 全程批量 executemany 写入：远程 MySQL 下逐行 flush 每行一次网络往返，
    # 2 万行会把导入拖到十分钟以上
    stats = ImportStats(empty_comments=bundle.skipped_empty_comments)
    platform = "douyin"

    video_ids = _existing_ids(session, Video, platform)
    new_videos = []
    for v in bundle.videos:
        if v.external_id in video_ids:
            stats.videos_skipped += 1
            continue
        new_videos.append(dict(
            platform=v.platform, external_id=v.external_id,
            title=v.title, description=v.description, cover_url=v.cover_url,
            tags=extract_tags(f"{v.title} {v.description}"), raw_data=v.raw))
        stats.videos_new += 1
    if new_videos:
        session.execute(insert(Video), new_videos)
        video_ids = _existing_ids(session, Video, platform)

    user_ids = _existing_ids(session, PlatformUser, platform)
    new_users = []
    for u in bundle.users:
        if u.external_id in user_ids:
            stats.users_skipped += 1
            continue
        new_users.append(dict(
            platform=u.platform, external_id=u.external_id,
            nickname=u.nickname, raw_data=u.raw))
        stats.users_new += 1
    if new_users:
        session.execute(insert(PlatformUser), new_users)
        user_ids = _existing_ids(session, PlatformUser, platform)

    seen_comments = set(_existing_ids(session, Comment, platform).keys())
    new_comments = []
    for c in bundle.comments:
        if c.external_id in seen_comments:
            stats.comments_skipped += 1
            continue
        vid = video_ids.get(c.video_external_id)
        uid = user_ids.get(c.user_external_id)
        if vid is None or uid is None:
            stats.comments_skipped += 1
            continue
        new_comments.append(dict(
            platform=c.platform, external_id=c.external_id,
            video_id=vid, user_id=uid, content=c.content,
            comment_time=c.comment_time, raw_data=c.raw))
        seen_comments.add(c.external_id)
        stats.comments_new += 1
    if new_comments:
        session.execute(insert(Comment), new_comments)

    session.commit()
    logger.info("导入完成: %s", stats.model_dump())
    return stats

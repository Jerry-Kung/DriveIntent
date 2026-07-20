from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.importer.tags import extract_tags
from app.models import Comment, PlatformUser, Video
from app.schemas.import_data import ImportBundle


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
    stats = ImportStats(empty_comments=bundle.skipped_empty_comments)
    platform = "douyin"

    video_ids = _existing_ids(session, Video, platform)
    for v in bundle.videos:
        if v.external_id in video_ids:
            stats.videos_skipped += 1
            continue
        row = Video(platform=v.platform, external_id=v.external_id,
                    title=v.title, description=v.description,
                    cover_url=v.cover_url,
                    tags=extract_tags(f"{v.title} {v.description}"),
                    raw_data=v.raw)
        session.add(row)
        session.flush()
        video_ids[v.external_id] = row.id
        stats.videos_new += 1

    user_ids = _existing_ids(session, PlatformUser, platform)
    for u in bundle.users:
        if u.external_id in user_ids:
            stats.users_skipped += 1
            continue
        row = PlatformUser(platform=u.platform, external_id=u.external_id,
                           nickname=u.nickname, raw_data=u.raw)
        session.add(row)
        session.flush()
        user_ids[u.external_id] = row.id
        stats.users_new += 1

    existing_comments = set(
        _existing_ids(session, Comment, platform).keys())
    for c in bundle.comments:
        if c.external_id in existing_comments:
            stats.comments_skipped += 1
            continue
        vid = video_ids.get(c.video_external_id)
        uid = user_ids.get(c.user_external_id)
        if vid is None or uid is None:
            stats.comments_skipped += 1
            continue
        session.add(Comment(platform=c.platform, external_id=c.external_id,
                            video_id=vid, user_id=uid, content=c.content,
                            comment_time=c.comment_time, raw_data=c.raw))
        existing_comments.add(c.external_id)
        stats.comments_new += 1

    session.commit()
    return stats

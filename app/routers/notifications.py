"""알림 목록·미확인 수·읽음 처리·삭제. (알림 생성은 시스템/기기 몫)"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import Notification, Protector
from ..services.access import notification_json

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_own_notification(db: Session, protector: Protector, notification_id: int) -> Notification:
    """내 알림이 아니면 존재 여부가 새지 않도록 똑같이 404."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.protector_id != protector.id:
        raise APIError(404, "알림을 찾을 수 없습니다.")
    return notification


@router.get("")
def list_notifications(
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """내 알림 목록 (최신순, 삭제한 것 제외)."""
    notifications = db.scalars(
        select(Notification)
        .where(
            Notification.protector_id == protector.id,
            Notification.is_deleted.is_(False),
        )
        .order_by(Notification.created_at.desc())
    ).all()
    return envelope([notification_json(n) for n in notifications], "OK", 200)


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """미확인 알림 수 (홈 상단 배지용)."""
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.protector_id == protector.id,
            Notification.is_read.is_(False),
            Notification.is_deleted.is_(False),
        )
    )
    return envelope({"unreadCount": count or 0}, "OK", 200)


@router.patch("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """알림 읽음 처리."""
    notification = _get_own_notification(db, protector, notification_id)
    notification.is_read = True
    db.commit()
    return envelope({"notificationId": notification_id}, "읽음 처리했습니다.", 200)


@router.delete("/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """알림 삭제 (soft delete: 표시만 하고 실제로는 남겨둔다)."""
    notification = _get_own_notification(db, protector, notification_id)
    notification.is_deleted = True
    db.commit()
    return envelope({"notificationId": notification_id}, "알림을 삭제했습니다.", 200)

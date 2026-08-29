"""가족 대화방. 가족이 보낸 글/사진을 인형이 화면에 띄우고 음성으로 읽어준다."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import FamilyChatMessage, Protector
from ..schemas import ChatMessageCreateRequest
from ..services.access import chat_message_json, ensure_own_image, get_owned_user

router = APIRouter(tags=["chat"])


@router.get("/users/{user_id}/chat/messages")
def list_chat_messages(
    user_id: int,
    size: int = Query(30, ge=1, le=100, description="가져올 메시지 수"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """대화 목록 조회 (최신순). 조회하면 안 읽은 메시지를 읽음 처리한다."""
    user = get_owned_user(db, protector, user_id)

    messages = db.scalars(
        select(FamilyChatMessage)
        .where(FamilyChatMessage.user_id == user.id)
        .order_by(FamilyChatMessage.created_at.desc())
        .limit(size)
    ).all()

    # 보호자가 대화방을 열었으므로, 보호자가 보낸 게 아닌 안 읽은 메시지를 읽음 처리
    db.execute(
        update(FamilyChatMessage)
        .where(
            FamilyChatMessage.user_id == user.id,
            FamilyChatMessage.sender_type != "protector",
            FamilyChatMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    db.commit()

    return envelope([chat_message_json(m) for m in messages], "OK", 200)


@router.post("/users/{user_id}/chat/messages", status_code=201)
def send_chat_message(
    user_id: int,
    body: ChatMessageCreateRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """메시지 전송 (텍스트/사진). 사진은 POST /files/images 로 먼저 올린다."""
    user = get_owned_user(db, protector, user_id)

    if not body.content and not body.image_url:
        raise APIError(400, "내용이나 사진 중 하나는 있어야 합니다.")
    ensure_own_image(body.image_url, protector.id)

    message = FamilyChatMessage(
        user_id=user.id,
        sender_type="protector",
        sender_id=protector.id,
        content=body.content,
        image_url=body.image_url,
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return envelope(chat_message_json(message), "메시지를 전송했습니다.", 201)

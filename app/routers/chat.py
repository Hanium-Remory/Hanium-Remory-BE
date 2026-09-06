"""가족 대화방. 가족이 보낸 글/사진을 인형이 화면에 띄우고 음성으로 읽어준다."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import APIError, envelope
from ..models import ChatReadState, FamilyChatMessage, FamilyMember, Protector
from ..schemas import ChatMessageCreateRequest
from ..services.access import chat_message_json, ensure_own_image, get_owned_user
from ..services.notifications import notify_chat_message

router = APIRouter(tags=["chat"])


@router.get("/users/{user_id}/chat/messages")
def list_chat_messages(
    user_id: int,
    size: int = Query(30, ge=1, le=100, description="가져올 메시지 수"),
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """대화 목록 조회 (최신순). 조회하면 안 읽은 메시지를 읽음 처리한다.

    메시지마다 아직 안 읽은 가족이 몇 명인지(unreadCount)와, 인형이 어디까지
    읽어드렸는지(deliveredToDevice)를 함께 준다.
    """
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

    _mark_read_up_to_latest(db, user.id, protector.id)
    db.commit()

    unread_counts = _unread_counts(db, user.id, messages)
    items = []
    for m in messages:
        item = chat_message_json(m)
        item["unreadCount"] = unread_counts[m.id]
        items.append(item)
    return envelope(items, "OK", 200)


def _mark_read_up_to_latest(db: Session, user_id: int, protector_id: int) -> None:
    """대화방을 열었으니 가장 최근 메시지까지 읽은 것으로 둔다.

    화면에 30건만 받아 갔더라도 위로 올려 보면 다 보이므로, 마지막 id 를
    기준으로 삼는다.
    """
    latest = db.scalars(
        select(FamilyChatMessage.id)
        .where(FamilyChatMessage.user_id == user_id)
        .order_by(FamilyChatMessage.id.desc())
        .limit(1)
    ).first()
    if latest is None:
        return

    state = db.scalars(
        select(ChatReadState).where(
            ChatReadState.user_id == user_id,
            ChatReadState.protector_id == protector_id,
        )
    ).first()
    if state is None:
        db.add(
            ChatReadState(
                user_id=user_id,
                protector_id=protector_id,
                last_read_message_id=latest,
            )
        )
    elif latest > state.last_read_message_id:
        state.last_read_message_id = latest


def _unread_counts(db: Session, user_id: int, messages: list) -> dict:
    """메시지마다 아직 안 읽은 가족이 몇 명인지.

    카카오톡처럼 '남은 사람' 을 센다 — 막 보낸 메시지에 가장 큰 수가 뜨고,
    가족이 하나씩 읽을 때마다 줄다가 사라진다. 읽은 사람 수를 세면 보내자마자
    0 이 떠서 아무도 못 읽는 방처럼 보인다.

    보낸 사람은 빼고 센다. 어르신은 앱을 쓰지 않으므로 세는 대상은
    가족(보호자)뿐이고, 인형이 읽어드린 것은 deliveredToDevice 로 따로 준다.
    한 번도 대화방을 연 적이 없는 가족은 읽은 자리가 없으니 안 읽은 쪽이다.
    """
    family = set(
        db.scalars(
            select(FamilyMember.protector_id).where(FamilyMember.user_id == user_id)
        ).all()
    )
    states = dict(
        db.execute(
            select(
                ChatReadState.protector_id, ChatReadState.last_read_message_id
            ).where(ChatReadState.user_id == user_id)
        ).all()
    )

    counts = {}
    for m in messages:
        # sender_id 는 보낸 주체 안에서만 뜻이 있다. 인형이 보낸 메시지의
        # sender_id 를 보호자 id 로 읽으면 엉뚱한 사람이 빠진다.
        audience = family
        if m.sender_type == "protector":
            audience = family - {m.sender_id}
        counts[m.id] = sum(1 for pid in audience if states.get(pid, 0) < m.id)
    return counts


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

    # 보낸 본인 말고 나머지 가족에게 알린다.
    notify_chat_message(
        db,
        user_id=user.id,
        sender_protector_id=protector.id,
        has_image=bool(message.image_url),
    )

    return envelope(chat_message_json(message), "메시지를 전송했습니다.", 201)

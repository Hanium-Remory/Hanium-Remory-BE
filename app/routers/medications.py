"""약 수정·삭제."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_protector
from ..errors import envelope
from ..models import Protector
from ..schemas import MedicationUpdateRequest
from ..services.access import get_owned_medication, medication_json

router = APIRouter(prefix="/medications", tags=["medications"])


@router.put("/{medication_id}")
def update_medication(
    medication_id: int,
    body: MedicationUpdateRequest,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """약 수정. 보내지 않은 필드는 그대로 둔다."""
    medication = get_owned_medication(db, protector, medication_id)
    fields = body.model_dump(exclude_unset=True)

    if "name" in fields and fields["name"] is not None:
        medication.name = fields["name"].strip()
    if "time" in fields and fields["time"] is not None:
        medication.time = fields["time"]
    if "timing" in fields and fields["timing"] is not None:
        medication.timing = fields["timing"]
    if "enabled" in fields and fields["enabled"] is not None:
        medication.enabled = fields["enabled"]

    db.commit()
    return envelope(medication_json(medication), "약 정보를 수정했습니다.", 200)


@router.delete("/{medication_id}")
def delete_medication(
    medication_id: int,
    db: Session = Depends(get_db),
    protector: Protector = Depends(get_current_protector),
):
    """약 삭제."""
    medication = get_owned_medication(db, protector, medication_id)
    db.delete(medication)
    db.commit()
    return envelope({"medicationId": medication_id}, "약을 삭제했습니다.", 200)

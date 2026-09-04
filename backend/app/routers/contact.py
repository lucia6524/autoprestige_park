from fastapi import APIRouter, HTTPException

from app.schemas import ContactMessage
from app.services.email import send_contact_email

router = APIRouter(prefix="/contact", tags=["Contact"])


@router.post("/message")
async def send_message(data: ContactMessage):
    sent = await send_contact_email(
        data.name.strip(),
        str(data.email),
        data.phone.strip(),
        data.subject.strip(),
        data.message.strip(),
    )
    if not sent:
        raise HTTPException(503, "Le service email est temporairement indisponible.")
    return {"ok": True, "message": "Votre message a bien été envoyé."}
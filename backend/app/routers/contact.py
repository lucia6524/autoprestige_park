from fastapi import APIRouter, HTTPException, Request

from app.schemas import ContactMessage
from app.services.email import send_contact_email
from app.services.rate_limit import check_rate_limit, get_client_ip

router = APIRouter(prefix="/contact", tags=["Contact"])


@router.post("/message")
async def send_message(data: ContactMessage, request: Request):
    # Rate limit : 5 messages / 5 min / IP — le endpoint déclenche un email
    # payant (Brevo), il ne doit pas pouvoir être spammé.
    check_rate_limit("contact", get_client_ip(request))

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

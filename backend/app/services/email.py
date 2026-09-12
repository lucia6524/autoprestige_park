"""Email service using Brevo API (HTTPS) — works on Render free tier where SMTP is blocked."""
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_brevo_api_key() -> str:
    """Return the Brevo API key from settings."""
    return getattr(settings, "BREVO_API_KEY", "") or ""


async def _send_brevo_email(to_email: str, subject: str, body: str, reply_to: str = "") -> bool:
    """Send an email via Brevo HTTPS API (async)."""
    api_key = _get_brevo_api_key()
    if not api_key:
        logger.error("BREVO_API_KEY is not configured. Check your Render environment variables.")
        return False
    logger.info("Attempting Brevo email to %s with key ending in ...%s", to_email, api_key[-8:] if len(api_key) > 8 else "short")

    sender_email = settings.SMTP_FROM or "noreply@autoprestige.fr"

    payload_data = {
        "sender": {
            "email": sender_email,
            "name": "Autohaus",
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body,
    }

    if reply_to:
        payload_data["replyTo"] = {"email": reply_to}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BREVO_API_URL,
                json=payload_data,
                headers={"api-key": api_key},
            )
            if resp.is_success:
                logger.info("Brevo email sent to %s — subject: %s", to_email, subject)
                return True
            logger.error("Brevo API returned %s: %s", resp.status_code, resp.text[:500])
            return False
    except (httpx.HTTPError, httpx.TimeoutException) as error:
        logger.error("Brevo email failed: %s", error)
        return False


async def send_otp_email(to_email: str, code: str, first_name: str = "") -> bool:
    """Send OTP verification code via Brevo API."""
    greeting = f"Bonjour {first_name}," if first_name else "Bonjour,"
    body = (
        f"{greeting}\n\n"
        f"Votre code de vérification est : {code}\n"
        f"Il expire dans {settings.OTP_EXPIRE_MINUTES} minutes.\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email."
    )
    return await _send_brevo_email(
        to_email,
        "Votre code de vérification Autohaus",
        body,
    )


async def send_contact_email(name: str, email: str, phone: str, subject: str, body: str) -> bool:
    """Send contact form message to the site admin via Brevo API."""
    content = (
        f"Nom : {name}\n"
        f"Email : {email}\n"
        f"Téléphone : {phone or 'Non renseigné'}\n"
        f"Sujet : {subject}\n\n"
        f"Message :\n{body}"
    )
    recipient = settings.CONTACT_RECIPIENT_EMAIL or "contact@autoprestige.fr"
    return await _send_brevo_email(
        recipient,
        f"Nouveau message du site : {subject}",
        content,
        reply_to=email,
    )


async def send_review_email(name: str, email: str, vehicle: str, rating: int, body: str) -> bool:
    """Notifier l'admin qu'un nouveau témoignage attend une modération."""
    stars = "★" * rating + "☆" * (5 - rating)
    content = (
        f"Nouveau témoignage en attente de modération\n"
        f"\n"
        f"Nom : {name}\n"
        f"Email : {email}\n"
        f"Véhicule : {vehicle or 'Non précisé'}\n"
        f"Note : {stars} ({rating}/5)\n\n"
        f"Avis :\n{body}\n\n"
        f"→ Validez-le dans le dashboard admin, section « Avis clients »."
    )
    recipient = settings.CONTACT_RECIPIENT_EMAIL or "contact@autoprestige.fr"
    return await _send_brevo_email(
        recipient,
        f"Nouvel avis client ({rating}/5) — modération requise",
        content,
        reply_to=email,
    )


async def send_sell_request_email(
    name: str,
    email: str,
    phone: str,
    vehicle: str,
    mileage: int,
    notes: str,
    photo_count: int = 0,
) -> bool:
    """Notifier l'admin d'une nouvelle demande d'estimation (vente/reprise)."""
    content = (
        f"Nouvelle demande d'estimation (page Vendre)\n"
        f"\n"
        f"Nom : {name}\n"
        f"Email : {email}\n"
        f"Téléphone : {phone or 'Non renseigné'}\n"
        f"Véhicule : {vehicle}\n"
        f"Kilométrage : {mileage} km\n"
        f"Photos jointes : {photo_count}\n\n"
        f"Informations complémentaires :\n{notes or 'Aucune'}\n\n"
        f"→ Consultez les photos dans le dashboard admin, section « Demandes de vente »."
    )
    recipient = settings.CONTACT_RECIPIENT_EMAIL or "contact@autoprestige.fr"
    return await _send_brevo_email(
        recipient,
        f"Demande de vente : {vehicle}",
        content,
        reply_to=email,
    )


# Keep backward compatibility
async def send_resend_email(to_email: str, subject: str, body: str) -> bool:
    """Legacy Resend function — now delegates to Brevo."""
    return await _send_brevo_email(to_email, subject, body)

"""Email service using Brevo API (HTTPS) — works on Render free tier where SMTP is blocked."""
import logging
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _get_brevo_api_key() -> str:
    """Return the Brevo API key from settings."""
    return getattr(settings, "BREVO_API_KEY", "") or ""


def _send_brevo_email(to_email: str, subject: str, body: str, reply_to: str = "") -> bool:
    """Send an email via Brevo HTTPS API."""
    api_key = _get_brevo_api_key()
    if not api_key:
        logger.error("BREVO_API_KEY is not configured. Check your Render environment variables.")
        return False
    logger.info("Attempting Brevo email to %s with key ending in ...%s", to_email, api_key[-8:] if len(api_key) > 8 else "short")

    sender_email = settings.SMTP_FROM or "noreply@autoprestige.fr"

    payload_data = {
        "sender": {
            "email": sender_email,
            "name": "AutoPrestige",
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body,
    }

    if reply_to:
        payload_data["replyTo"] = {"email": reply_to}

    payload = json.dumps(payload_data).encode("utf-8")

    request = Request(
        BREVO_API_URL,
        data=payload,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            if 200 <= response.status < 300:
                logger.info("Brevo email sent to %s — subject: %s", to_email, subject)
                return True
            details = response.read().decode("utf-8", errors="replace")
            logger.error("Brevo API returned %s: %s", response.status, details)
            return False
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        logger.error("Brevo email failed (%s): %s", error.code, details)
        return False
    except (URLError, OSError) as error:
        logger.error("Brevo email failed: %s", error)
        return False


def send_otp_email(to_email: str, code: str, first_name: str = "") -> bool:
    """Send OTP verification code via Brevo API."""
    greeting = f"Bonjour {first_name}," if first_name else "Bonjour,"
    body = (
        f"{greeting}\n\n"
        f"Votre code de vérification est : {code}\n"
        f"Il expire dans {settings.OTP_EXPIRE_MINUTES} minutes.\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email."
    )
    return _send_brevo_email(
        to_email,
        "Votre code de vérification AutoPrestige",
        body,
    )


def send_contact_email(name: str, email: str, phone: str, subject: str, body: str) -> bool:
    """Send contact form message to the site admin via Brevo API."""
    content = (
        f"Nom : {name}\n"
        f"Email : {email}\n"
        f"Téléphone : {phone or 'Non renseigné'}\n"
        f"Sujet : {subject}\n\n"
        f"Message :\n{body}"
    )
    recipient = settings.CONTACT_RECIPIENT_EMAIL or "contact@autoprestige.fr"
    return _send_brevo_email(
        recipient,
        f"Nouveau message du site : {subject}",
        content,
        reply_to=email,
    )


# Keep backward compatibility
def send_resend_email(to_email: str, subject: str, body: str) -> bool:
    """Legacy Resend function — now delegates to Brevo."""
    return _send_brevo_email(to_email, subject, body)

"""SMTP email service used for verification codes and contact messages."""
import smtplib
import logging
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def send_otp_email(to_email: str, code: str, first_name: str = "") -> bool:
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        return False

    message = EmailMessage()
    message["Subject"] = "Votre code de vérification AutoPrestige"
    message["From"] = settings.SMTP_FROM
    message["To"] = to_email
    greeting = f"Bonjour {first_name}," if first_name else "Bonjour,"
    message.set_content(
        f"{greeting}\n\nVotre code de vérification est : {code}\n"
        f"Il expire dans {settings.OTP_EXPIRE_MINUTES} minutes.\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet email."
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        logger.error("SMTP OTP email failed: %s", error)
        return False
    return True


def send_contact_email(name: str, email: str, phone: str, subject: str, body: str) -> bool:
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        return False

    message = EmailMessage()
    message["Subject"] = f"Nouveau message du site : {subject}"
    message["From"] = settings.SMTP_FROM
    message["To"] = settings.CONTACT_RECIPIENT_EMAIL
    message["Reply-To"] = email
    message.set_content(
        f"Nom : {name}\n"
        f"Email : {email}\n"
        f"Téléphone : {phone or 'Non renseigné'}\n"
        f"Sujet : {subject}\n\n"
        f"Message :\n{body}"
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        logger.error("SMTP contact email failed: %s", error)
        return False
    return True

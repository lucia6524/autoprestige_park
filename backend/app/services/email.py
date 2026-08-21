"""
Email service — envoi désactivé (option C).
Le code OTP est renvoyé dans la réponse API et affiché à l'écran.
"""
from app.config import settings


def send_otp_email(to_email: str, code: str, first_name: str = "") -> bool:
    """
    N'envoie plus d'email. Log console uniquement.
    Le code est aussi retourné par l'API pour affichage frontend.
    """
    print("\n" + "=" * 50)
    print("  [OTP ÉCRAN] Pas d'envoi email (mode sans SMTP)")
    print(f"  Destinataire → {to_email}")
    print(f"  CODE OTP     → {code}")
    print("=" * 50 + "\n")
    return True

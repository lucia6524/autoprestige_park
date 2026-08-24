import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User, OTPCode
from app.time_utils import utc_now_naive

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None


def generate_otp(length: int | None = None) -> str:
    length = length or getattr(settings, "OTP_LENGTH", 6)
    # secrets (CSPRNG) plutôt que random
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_otp(code: str) -> str:
    """Hash OTP avec pepper (SECRET_KEY) — ne jamais stocker le code en clair."""
    pepper = settings.SECRET_KEY.encode("utf-8")
    return hashlib.sha256(pepper + code.encode("utf-8")).hexdigest()


def verify_otp_hash(plain_code: str, stored_hash: str) -> bool:
    """Comparaison à temps constant."""
    expected = hash_otp(plain_code.strip())
    return hmac.compare_digest(expected, stored_hash)


async def create_otp(db: AsyncSession, email: str) -> str:
    email = email.lower().strip()
    now = utc_now_naive()
    max_per_hour = getattr(settings, "OTP_MAX_PER_HOUR", 5)

    # Rate limit : max N codes / heure / email
    since = now - timedelta(hours=1)
    count_result = await db.execute(
        select(func.count(OTPCode.id)).where(
            OTPCode.email == email,
            OTPCode.created_at >= since,
        )
    )
    count = count_result.scalar() or 0
    if count >= max_per_hour:
        from fastapi import HTTPException
        raise HTTPException(
            429,
            f"Trop de codes demandés. Réessayez dans une heure (max {max_per_hour}/heure).",
        )

    # Invalider les anciens codes non utilisés
    result = await db.execute(
        select(OTPCode).where(OTPCode.email == email, OTPCode.used == False)
    )
    for old in result.scalars().all():
        old.used = True

    code = generate_otp()
    expires = now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)
    otp = OTPCode(
        email=email,
        code=hash_otp(code),  # hash uniquement en base
        expires_at=expires,
        used=False,
        attempts=0,
    )
    db.add(otp)
    await db.commit()
    return code


async def verify_otp(db: AsyncSession, email: str, code: str) -> bool:
    email = email.lower().strip()
    code = (code or "").strip()
    if not code or not code.isdigit():
        return False

    max_attempts = getattr(settings, "OTP_MAX_ATTEMPTS", 5)
    now = utc_now_naive()

    # Dernier code non utilisé pour cet email
    result = await db.execute(
        select(OTPCode)
        .where(OTPCode.email == email, OTPCode.used == False)
        .order_by(OTPCode.created_at.desc())
    )
    otp = result.scalars().first()
    if not otp:
        return False

    exp = otp.expires_at
    if exp < now:
        otp.used = True
        await db.commit()
        return False

    if (otp.attempts or 0) >= max_attempts:
        otp.used = True
        await db.commit()
        return False

    if not verify_otp_hash(code, otp.code):
        otp.attempts = (otp.attempts or 0) + 1
        if otp.attempts >= max_attempts:
            otp.used = True
        await db.commit()
        return False

    # Succès : usage unique
    otp.used = True
    otp.attempts = (otp.attempts or 0) + 1
    await db.commit()
    return True


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()

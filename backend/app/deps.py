from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth import decode_token, get_user_by_id

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentification requise")
    payload = decode_token(credentials.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")
    try:
        user_id = int(payload["sub"])
        token_ver = payload.get("ver")
        token_ver = int(token_ver) if token_ver is not None else None
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Token invalide ou expiré") from None
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Compte non vérifié")
    # Révocation : le token doit porter la version de session courante.
    # Un logout incrémente token_version → tous les tokens antérieurs 401.
    if token_ver is None or token_ver != (user.token_version or 0):
        raise HTTPException(
            status_code=401,
            detail="Session révoquée. Reconnectez-vous.",
        )
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Accès réservé aux administrateurs")
    return user

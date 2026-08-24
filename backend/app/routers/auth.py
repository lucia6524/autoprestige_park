from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.schemas import (
    RegisterStep1, RegisterStep2, RegisterStep3, RegisterVerify,
    LoginRequest, TokenResponse, UserOut
)
from app.services.auth import (
    get_user_by_email, create_otp, verify_otp, create_access_token, hash_password
)
from app.schemas import ProfileUpdate
from app.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])

# Temporary registration store (in-memory for multi-step before user is created)
# In production, use Redis or a pending_registrations table
_pending: dict[str, dict] = {}


@router.post("/register/step1")
async def register_step1(data: RegisterStep1):
    """Étape 1 : Nom + Prénom"""
    session_key = f"{data.first_name.strip().lower()}_{data.last_name.strip().lower()}"
    _pending[session_key] = {
        "first_name": data.first_name.strip(),
        "last_name": data.last_name.strip(),
        "step": 1,
    }
    return {
        "ok": True,
        "step": 1,
        "session_key": session_key,
        "message": "Nom enregistré. Passez à l'étape 2 (email + téléphone).",
    }


@router.post("/register/step2")
async def register_step2(data: RegisterStep2, session_key: str, db: AsyncSession = Depends(get_db)):
    """Étape 2 : Email + Téléphone"""
    if session_key not in _pending:
        raise HTTPException(400, "Session d'inscription invalide. Recommencez à l'étape 1.")
    
    existing = await get_user_by_email(db, data.email)
    if existing and existing.is_verified:
        raise HTTPException(400, "Un compte existe déjà avec cet email.")

    _pending[session_key].update({
        "email": data.email.lower().strip(),
        "phone": data.phone.strip(),
        "step": 2,
    })
    # Also index by email for later steps
    _pending[data.email.lower()] = _pending[session_key]
    
    return {
        "ok": True,
        "step": 2,
        "session_key": session_key,
        "message": "Contact enregistré. Passez à l'étape 3 (salaire mensuel).",
    }


@router.post("/register/step3")
async def register_step3(data: RegisterStep3, session_key: str, db: AsyncSession = Depends(get_db)):
    """Étape 3 : Salaire mensuel → envoi du code OTP"""
    if session_key not in _pending or _pending[session_key].get("step", 0) < 2:
        raise HTTPException(400, "Complétez d'abord les étapes 1 et 2.")

    pending = _pending[session_key]
    pending["monthly_salary"] = data.monthly_salary
    pending["step"] = 3

    email = pending["email"]
    
    # Create or update user (unverified)
    user = await get_user_by_email(db, email)
    if not user:
        user = User(
            first_name=pending["first_name"],
            last_name=pending["last_name"],
            email=email,
            phone=pending["phone"],
            monthly_salary=data.monthly_salary,
            is_verified=False,
            registration_step=3,
        )
        db.add(user)
    else:
        user.first_name = pending["first_name"]
        user.last_name = pending["last_name"]
        user.phone = pending["phone"]
        user.monthly_salary = data.monthly_salary
        user.registration_step = 3
    await db.commit()
    await db.refresh(user)

    # This site uses an internal OTP displayed to the client.
    code = await create_otp(db, email)

    return {
        "ok": True,
        "step": 3,
        "email": email,
        "code": code,
        "message": "Entrez le code affiché à l'écran pour continuer.",
    }


@router.post("/register/verify")
async def register_verify(data: RegisterVerify, db: AsyncSession = Depends(get_db)):
    """Étape 4 : Vérification OTP → puis création du mot de passe (étape 5)"""
    ok = await verify_otp(db, data.email, data.code)
    if not ok:
        raise HTTPException(400, "Code invalide ou expiré.")

    user = await get_user_by_email(db, data.email)
    if not user:
        raise HTTPException(400, "Inscription introuvable. Recommencez.")

    user.registration_step = 4  # OTP OK, password pending
    # Pas encore is_verified tant que le mot de passe n'est pas défini
    await db.commit()

    return {
        "ok": True,
        "step": 4,
        "email": user.email,
        "need_password": True,
        "message": "Code validé. Créez votre mot de passe pour finaliser.",
    }


@router.post("/register/set-password", response_model=TokenResponse)
async def register_set_password(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Étape 5 : Définir le mot de passe → compte activé + token"""
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email:
        raise HTTPException(400, "Email requis.")
    if not password or len(password) < 6:
        raise HTTPException(400, "Le mot de passe doit contenir au moins 6 caractères.")

    user = await get_user_by_email(db, email)
    if not user:
        raise HTTPException(400, "Inscription introuvable. Recommencez.")
    if user.registration_step < 4:
        raise HTTPException(400, "Validez d'abord le code de confirmation.")

    user.hashed_password = hash_password(password)
    user.is_verified = True
    user.registration_step = 5
    await db.commit()
    await db.refresh(user)

    for k in list(_pending.keys()):
        if _pending[k].get("email") == email.lower():
            del _pending[k]

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user={
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "monthly_salary": user.monthly_salary,
            "is_admin": bool(getattr(user, "is_admin", False)),
        },
    )


@router.post("/login/request-code")
async def login_request_code(email: str, db: AsyncSession = Depends(get_db)):
    """Request an internal OTP displayed to the client."""
    user = await get_user_by_email(db, email)
    if not user or not user.is_verified:
        raise HTTPException(404, "Aucun compte vérifié avec cet email.")
    code = await create_otp(db, email)
    return {
        "ok": True,
        "email": email,
        "code": code,
        "message": "Entrez le code affiché à l'écran.",
    }


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Connexion par code OTP ou par mot de passe (admin)"""
    from app.services.auth import verify_password

    user = await get_user_by_email(db, data.email)
    if not user or not user.is_verified:
        raise HTTPException(401, "Compte introuvable ou non vérifié.")

    authenticated = False

    # Login par mot de passe (admin / comptes avec password)
    if data.password:
        if user.hashed_password and verify_password(data.password, user.hashed_password):
            authenticated = True
        else:
            raise HTTPException(401, "Mot de passe incorrect.")
    # Login par OTP
    elif data.code:
        ok = await verify_otp(db, data.email, data.code)
        if not ok:
            raise HTTPException(401, "Code invalide ou expiré.")
        authenticated = True
    else:
        raise HTTPException(400, "Code de vérification ou mot de passe requis.")

    if not authenticated:
        raise HTTPException(401, "Authentification échouée.")

    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user={
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone,
            "monthly_salary": user.monthly_salary,
            "is_admin": bool(getattr(user, "is_admin", False)),
        },
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.first_name = data.first_name.strip()
    user.last_name = data.last_name.strip()
    user.phone = data.phone.strip()
    user.monthly_salary = data.monthly_salary
    await db.commit()
    await db.refresh(user)
    return user

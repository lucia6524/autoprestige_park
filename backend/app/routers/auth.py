import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.schemas import (
    RegisterStep1, RegisterStep2, RegisterStep3, RegisterVerify,
    LoginRequest, TokenResponse, UserOut
)
from app.services.auth import (
    get_user_by_email, create_otp, verify_otp, create_access_token, hash_password,
    verify_password, create_registration_token, decode_registration_token,
)
from app.services.email import send_otp_email
from app.schemas import ProfileUpdate
from app.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Auth"])

# ── Rate limiter (in-memory, per IP) ──────────────────────
_rate_limits: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW = 300  # 5 minutes
RATE_LIMIT_MAX_LOGIN = 10   # max 10 tentatives / 5 min
RATE_LIMIT_MAX_REGISTER = 5  # max 5 inscriptions / 5 min


def _check_rate_limit(ip: str, max_requests: int) -> None:
    """Raise 429 if the IP exceeds the allowed number of requests."""
    now = time.time()
    if ip not in _rate_limits:
        _rate_limits[ip] = []
    # Purge old entries
    _rate_limits[ip] = [t for t in _rate_limits[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[ip]) >= max_requests:
        raise HTTPException(429, "Trop de tentatives. Réessayez dans quelques minutes.")
    _rate_limits[ip].append(now)


def _get_client_ip(request: Request) -> str:
    """IP client réelle — délègue au helper partagé (anti-spoofing XFF)."""
    from app.services.rate_limit import get_client_ip
    return get_client_ip(request)


# Temporary registration store (in-memory for multi-step before user is created)
# In production, use Redis or a pending_registrations table
_pending: dict[str, dict] = {}


@router.post("/register/step1")
async def register_step1(data: RegisterStep1, request: Request):
    """Étape 1 : Nom + Prénom"""
    _check_rate_limit(_get_client_ip(request), RATE_LIMIT_MAX_REGISTER)
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

    # Generate OTP and send it by email — never expose the code in the API response.
    code = await create_otp(db, email)

    email_sent = await send_otp_email(email, code, pending.get("first_name", ""))
    if not email_sent:
        raise HTTPException(503, "Impossible d'envoyer l'email de vérification. Réessayez plus tard.")

    return {
        "ok": True,
        "step": 3,
        "email": email,
        "message": "Un code de vérification a été envoyé à votre adresse email.",
    }


@router.post("/register/verify")
async def register_verify(data: RegisterVerify, db: AsyncSession = Depends(get_db)):
    """Étape 4 : Vérification OTP → token d'inscription + création du mot de passe (étape 5)"""
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
        # Preuve signée que l'OTP a été validé — exigée par set-password (15 min)
        "registration_token": create_registration_token(user.email),
        "message": "Code validé. Créez votre mot de passe pour finaliser.",
    }


@router.post("/register/set-password", response_model=TokenResponse)
async def register_set_password(
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Étape 5 : Définir le mot de passe → compte activé + token.

    ⚠️ Exige un registration_token valide (délivré uniquement après validation
    OTP) lié à l'email fourni — sinon n'importe qui pourrait finaliser le
    compte d'autrui en connaissant son email.
    """
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    reg_token = data.get("registration_token") or ""
    if not email:
        raise HTTPException(400, "Email requis.")
    token_email = decode_registration_token(reg_token)
    if not token_email or token_email != email:
        raise HTTPException(
            403,
            "Session de vérification invalide ou expirée. Validez à nouveau le code reçu par email.",
        )
    # Validate password strength
    import re
    if len(password) < 8:
        raise HTTPException(400, "Le mot de passe doit contenir au moins 8 caractères.")
    if not re.search(r"[A-Z]", password):
        raise HTTPException(400, "Le mot de passe doit contenir au moins une majuscule.")
    if not re.search(r"[a-z]", password):
        raise HTTPException(400, "Le mot de passe doit contenir au moins une minuscule.")
    if not re.search(r"[0-9]", password):
        raise HTTPException(400, "Le mot de passe doit contenir au moins un chiffre.")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\\\|,.<>/?]", password):
        raise HTTPException(400, "Le mot de passe doit contenir au moins un caractère spécial (!@#$%^&*...).")

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


# Message anti-énumération : identique que le compte existe ou non.
_GENERIC_OTP_MESSAGE = (
    "Si un compte existe avec cette adresse email, "
    "un code de vérification vient d'être envoyé."
)


@router.post("/login/request-code")
async def login_request_code(email: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Generate an OTP and send it by email.

    ⚠️ Anti-énumération : la réponse est STRICTEMENT identique (statut + corps)
    que le compte existe ou non. Une limite par email s'applique aux deux cas
    pour que même le 429 ne révèle rien — et pour empêcher le mail-bombing.
    """
    _check_rate_limit(_get_client_ip(request), RATE_LIMIT_MAX_LOGIN)
    email = (email or "").strip().lower()
    # Limite par email (5/h), appliquée AVANT toute vérification d'existence :
    # compte réel ou inexistant, le comportement reste identique.
    from app.services.rate_limit import check_rate_limit
    check_rate_limit("otp_code", f"email:{email}")

    generic = {
        "ok": True,
        "email": email,
        "message": _GENERIC_OTP_MESSAGE,
    }

    user = await get_user_by_email(db, email)
    if not user or not user.is_verified:
        # Compte inexistant ou non vérifié : réponse générique, pas d'email.
        return generic

    code = await create_otp(db, email)
    email_sent = await send_otp_email(email, code, user.first_name)
    if not email_sent:
        # Uniquement quand le service email est réellement indisponible.
        raise HTTPException(503, "Impossible d'envoyer l'email de vérification. Réessayez plus tard.")

    return generic


# Message d'échec unique pour TOUTES les causes d'échec de login (compte
# inexistant, mot de passe faux, code invalide) : aucune différence de statut
# ni de corps ne doit révéler si un email est inscrit.
_GENERIC_LOGIN_ERROR = "Email, mot de passe ou code de vérification incorrect."

# Hash bcrypt factice, calculé une fois, pour égaliser le temps de réponse
# entre « compte inexistant » et « mot de passe incorrect » (sinon le temps
# de bcrypt manquant sur le chemin « inexistant » est un oracle de timing).
_dummy_hash_cache: str = ""


def _timing_equalizer(password: str) -> None:
    """Exécute une vérification bcrypt factice du même coût que la réelle."""
    global _dummy_hash_cache
    if not _dummy_hash_cache:
        _dummy_hash_cache = hash_password("timing-equalizer-dummy-value")
    verify_password(password, _dummy_hash_cache)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Connexion par code OTP ou par mot de passe (admin).

    ⚠️ Anti-énumération : un seul et même message d'erreur 401 quel que soit
    le motif (compte inexistant, mot de passe faux, code invalide), et coût
    bcrypt identique sur tous les chemins mot de passe.
    """
    _check_rate_limit(_get_client_ip(request), RATE_LIMIT_MAX_LOGIN)

    user = await get_user_by_email(db, data.email)

    if not user or not user.is_verified:
        # Égaliser le coût temporel avec le chemin « mauvais mot de passe ».
        if data.password:
            _timing_equalizer(data.password)
        raise HTTPException(401, _GENERIC_LOGIN_ERROR)

    authenticated = False

    # Login par mot de passe (admin / comptes avec password)
    if data.password:
        if user.hashed_password and verify_password(data.password, user.hashed_password):
            authenticated = True
        else:
            raise HTTPException(401, _GENERIC_LOGIN_ERROR)
    # Login par OTP
    elif data.code:
        ok = await verify_otp(db, data.email, data.code)
        if not ok:
            raise HTTPException(401, _GENERIC_LOGIN_ERROR)
        authenticated = True
    else:
        raise HTTPException(400, "Code de vérification ou mot de passe requis.")

    if not authenticated:
        raise HTTPException(401, _GENERIC_LOGIN_ERROR)

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

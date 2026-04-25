"""Souvenir AI - FastAPI app (Vercel + local).

Sur Vercel, ce fichier est l'entry point du runtime Python.
En local, lance via: `uvicorn api.index:app --reload`.

Modes pipeline (auto-detection):
  - LITE     : Pillow only (Vercel serverless, ~10MB)
  - BASIC    : + OpenCV (local ou serveur dedie)
  - ADVANCED : + torch/Real-ESRGAN/CodeFormer (GPU)
"""
from __future__ import annotations

import os
import io
import json
import uuid
import time
import logging
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from ._services.restore_service import RestoreService
from ._services.supabase_client import SupabaseClient
from ._services.quota_service import QuotaService, DAILY_FREE_LIMIT
from ._services.watermark import add_watermark
from ._services.auth_service import AuthService
from ._services.geniuspay_client import GeniusPayClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("souvenir")

MAX_SIZE_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))
MAX_BYTES = MAX_SIZE_MB * 1024 * 1024
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}

app = FastAPI(title="Souvenir AI", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

restore_service = RestoreService()
supabase = SupabaseClient.from_env()
quota_service = QuotaService(supabase)
auth_service = AuthService.from_env()
geniuspay = GeniusPayClient.from_env()

# Premium pricing (FCFA, mensuel manuel par defaut)
PREMIUM_PRICE_XOF = int(os.getenv("PREMIUM_PRICE_XOF", "2999"))
PREMIUM_PLAN = os.getenv("PREMIUM_PLAN", "monthly")  # monthly | lifetime
PREMIUM_DURATION_DAYS = int(os.getenv("PREMIUM_DURATION_DAYS", "30"))
# Rate-limit anti-spam sur /api/payments/create
PAYMENTS_RATE_LIMIT_PER_10MIN = int(os.getenv("PAYMENTS_RATE_LIMIT_PER_10MIN", "5"))


def _device_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Device-Id") or request.headers.get("x-device-id")


def _user_id(request: Request) -> Optional[str]:
    """Extrait le user_id Supabase depuis le header Authorization: Bearer <jwt>."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    return auth_service.user_id_from_token(token)


# Header X-Premium accepte UNIQUEMENT en mode dev (gated par env)
# En prod, le statut premium vient EXCLUSIVEMENT de la table subscriptions.
DEV_ALLOW_PREMIUM_HEADER = os.getenv("DEV_ALLOW_PREMIUM_HEADER", "0") == "1"


def _is_premium(
    request: Request,
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> bool:
    """Determine si l'utilisateur est premium.

    Priorite :
      1. Si user_id (authentifie) : lit subscriptions par user_id.
      2. Si device_id (BGMaster style, anonyme) : lit subscriptions par device_id.
      3. Si DEV_ALLOW_PREMIUM_HEADER=1 : accepte le header X-Premium=1
         (mode dev / tests locaux uniquement).
      4. Sinon : false.
    """
    if supabase.is_configured and (user_id or device_id):
        if supabase.get_premium_status(user_id=user_id, device_id=device_id):
            return True
    if DEV_ALLOW_PREMIUM_HEADER:
        return request.headers.get("X-Premium", "0") == "1"
    return False


# Cap global quotidien anti-abus (toutes restaurations confondues, 24h glissant)
DAILY_GLOBAL_LIMIT = int(os.getenv("DAILY_GLOBAL_LIMIT", "0"))  # 0 = desactive


@app.get("/")
def root():
    return {
        "app": "Souvenir AI",
        "status": "ok",
        "version": "2.0.0",
        "pipeline": restore_service.pipeline_info(),
        "supabase": supabase.is_configured,
    }


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "pipeline": restore_service.pipeline_info(),
        "supabase": supabase.is_configured,
        "daily_free_limit": DAILY_FREE_LIMIT,
    }


@app.get("/api/quota")
def quota(request: Request):
    """Retourne le quota restant pour l'utilisateur (user_id si auth, sinon device)."""
    device_id = _device_id(request)
    user_id = _user_id(request)
    is_premium = _is_premium(request, user_id=user_id, device_id=device_id)
    allowed, info = quota_service.check(
        device_id=device_id, is_premium=is_premium, user_id=user_id,
    )
    return {"allowed": allowed, **info}


@app.post("/api/iap/verify")
async def iap_verify(request: Request):
    """Active premium pour un device (BGMaster style) ou un user.

    Body JSON: {provider, receipt, plan?, expires_at?}
      - provider : 'iap_apple' | 'iap_google' | 'revenuecat' | 'stripe' | 'manual'
      - receipt  : token transaction (App Store / Google Play / Stripe)
      - plan     : 'monthly' | 'yearly' | 'lifetime' (default 'monthly')
      - expires_at: ISO8601 (default null = lifetime)

    Si Authorization: Bearer <jwt>, lie a user_id ; sinon a device_id (X-Device-Id).

    NOTE: La validation reelle du receipt (Apple/Google/Stripe) doit etre
    ajoutee ici avant production. Ce endpoint est actuellement un placeholder
    qui FAIT CONFIANCE au client - PROTEGER avec un secret partage ou une
    vraie validation receipt avant le go-live IAP.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")

    provider = (body.get("provider") or "").strip()
    receipt = (body.get("receipt") or "").strip()
    plan = body.get("plan") or "monthly"
    expires_at = body.get("expires_at")
    if not provider or not receipt:
        raise HTTPException(status_code=400, detail="provider et receipt requis")

    if not supabase.is_configured:
        raise HTTPException(status_code=503, detail="Supabase non configure")

    # TODO PROD: valider le receipt cote serveur
    #   - iap_apple    -> POST https://buy.itunes.apple.com/verifyReceipt
    #   - iap_google   -> Google Play Developer API (purchases.subscriptions.get)
    #   - revenuecat   -> webhook signature header
    #   - stripe       -> webhook signature
    # Pour l'instant: on fait confiance au client (DEV ONLY).

    user_id = _user_id(request)
    device_id = _device_id(request)

    if user_id:
        ok = supabase.set_premium_user(
            user_id=user_id, plan=plan, expires_at=expires_at,
            provider=provider, receipt=receipt,
        )
        scope = "user"
    elif device_id:
        ok = supabase.set_premium_device(
            device_id=device_id, plan=plan, expires_at=expires_at,
            provider=provider, receipt=receipt,
        )
        scope = "device"
    else:
        raise HTTPException(status_code=400,
                            detail="X-Device-Id ou Authorization requis")

    if not ok:
        raise HTTPException(status_code=500, detail="Echec activation premium")
    return {"status": "premium_activated", "scope": scope, "plan": plan,
            "expires_at": expires_at}


@app.post("/api/payments/create")
async def payments_create(request: Request):
    """Initie un paiement Premium via GeniusPay.

    Body JSON optionnel: {plan?: 'monthly'|'lifetime', success_url?, error_url?}
    Sinon utilise les defauts (PREMIUM_PLAN env, PREMIUM_PRICE_XOF env).

    Headers requis: X-Device-Id (mode anonyme) ou Authorization (auth).

    Retourne: {reference, checkout_url, amount, currency, plan, expires_at?}.
    L'app doit ouvrir checkout_url puis ecouter le retour ou
    poll /api/payments/status?reference=... pour confirmer.
    """
    if not geniuspay.is_configured:
        raise HTTPException(status_code=503,
                            detail="Paiement non configure (GeniusPay)")
    if not supabase.is_configured:
        raise HTTPException(status_code=503, detail="Supabase non configure")

    device_id = _device_id(request)
    user_id = _user_id(request)
    if not device_id and not user_id:
        raise HTTPException(status_code=400,
                            detail="X-Device-Id ou Authorization requis")

    # Rate-limit anti-spam : max N paiements pending par device/user en 10 min.
    # Empeche un attaquant de creer 1000 transactions GeniusPay par seconde
    # (qui pourrait soit spammer GeniusPay soit polluer notre table payments).
    try:
        recent_count = supabase.count_recent_payments(
            device_id=device_id, user_id=user_id, minutes=10,
        )
        if recent_count >= PAYMENTS_RATE_LIMIT_PER_10MIN:
            log.warning(
                "rate-limit /payments/create atteint device=%s user=%s count=%d",
                device_id, user_id, recent_count,
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    "Trop de tentatives de paiement. Reessayez dans quelques "
                    "minutes ou finalisez un paiement deja en attente."
                ),
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Si Supabase est down, on log mais on laisse passer (degraded mode)
        log.warning("rate-limit check failed (degraded): %s", exc)

    try:
        body = await request.json()
    except Exception:
        body = {}

    plan = (body.get("plan") or PREMIUM_PLAN).lower()
    if plan not in ("monthly", "lifetime"):
        raise HTTPException(status_code=400, detail="plan invalide")

    success_url = body.get("success_url")
    error_url = body.get("error_url")

    description = (
        "Souvenir AI - Premium a vie" if plan == "lifetime"
        else "Souvenir AI - Premium 30 jours"
    )
    metadata = {
        "plan": plan,
        "device_id": device_id or "",
        "user_id": user_id or "",
        "app": "souvenir",
    }

    try:
        data = geniuspay.create_payment(
            amount=PREMIUM_PRICE_XOF,
            currency="XOF",
            description=description,
            success_url=success_url,
            error_url=error_url,
            metadata=metadata,
        )
    except Exception as exc:
        log.exception("geniuspay create_payment failed")
        raise HTTPException(status_code=502,
                            detail=f"GeniusPay indisponible: {exc}")

    reference = data.get("reference")
    checkout_url = data.get("checkout_url") or data.get("payment_url")
    if not reference or not checkout_url:
        log.error("geniuspay reponse incomplete: %s", data)
        raise HTTPException(status_code=502,
                            detail="Reponse GeniusPay incomplete")

    # Persiste le paiement (status pending)
    supabase.insert_payment(
        reference=reference,
        amount=PREMIUM_PRICE_XOF,
        plan=plan,
        device_id=device_id,
        user_id=user_id,
        currency="XOF",
        checkout_url=checkout_url,
        raw_response=data,
    )

    return {
        "reference": reference,
        "checkout_url": checkout_url,
        "amount": PREMIUM_PRICE_XOF,
        "currency": "XOF",
        "plan": plan,
        "expires_in_days": (PREMIUM_DURATION_DAYS if plan == "monthly" else None),
        "status": data.get("status", "pending"),
    }


@app.get("/api/payments/status")
def payments_status(request: Request, reference: str):
    """Retourne le status d'un paiement (pour polling cote app)."""
    if not supabase.is_configured:
        raise HTTPException(status_code=503, detail="Supabase non configure")
    p = supabase.get_payment_by_reference(reference)
    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    # Verif autorisation : seul le proprietaire (device ou user) peut lire
    device_id = _device_id(request)
    user_id = _user_id(request)
    if user_id and p.get("user_id") and p["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Acces refuse")
    if device_id and p.get("device_id") and p["device_id"] != device_id and not user_id:
        raise HTTPException(status_code=403, detail="Acces refuse")
    return {
        "reference": p.get("reference"),
        "status": p.get("status"),
        "amount": p.get("amount"),
        "currency": p.get("currency"),
        "plan": p.get("plan"),
        "completed_at": p.get("completed_at"),
    }


@app.post("/api/payments/webhook")
async def payments_webhook(request: Request):
    """Webhook GeniusPay : active premium quand payment.success.

    Securite:
      - Verif signature HMAC-SHA256
      - Anti-replay : timestamp tolerance 5 min
      - Idempotency : check status avant de reactiver

    Headers attendus: X-Webhook-Signature, X-Webhook-Timestamp, X-Webhook-Event
    """
    if not geniuspay.webhook_secret:
        # Si pas de secret configure, on refuse tout (mode prod safe par defaut)
        log.error("webhook recu mais GENIUSPAY_WEBHOOK_SECRET non configure")
        raise HTTPException(status_code=503, detail="Webhook non configure")

    raw = await request.body()
    signature = request.headers.get("X-Webhook-Signature")
    timestamp = request.headers.get("X-Webhook-Timestamp")
    event = request.headers.get("X-Webhook-Event") or ""

    if not geniuspay.verify_webhook(signature, timestamp, raw):
        raise HTTPException(status_code=401, detail="Signature invalide")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")

    data = payload.get("data") or {}
    reference = data.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="reference manquante")

    log.info("webhook geniuspay event=%s ref=%s status=%s",
             event, reference, data.get("status"))

    # Idempotency : si deja completed, on ne refait rien
    existing = supabase.get_payment_by_reference(reference) if supabase.is_configured else None
    if existing and existing.get("status") == "completed":
        return {"status": "already_processed"}

    # Cas success
    is_success = (
        event == "payment.success"
        or (data.get("status") in ("completed", "success"))
    )
    if is_success:
        # SECURITE CRITIQUE : verifier que le montant recu == montant attendu.
        # Empeche un attaquant qui connaitrait le whsec de forger un webhook
        # avec amount=1 pour activer premium gratuitement.
        if not existing:
            log.error("webhook success pour reference inconnue: %s", reference)
            raise HTTPException(status_code=404, detail="reference inconnue")

        expected_amount = existing.get("amount")
        try:
            received_amount = int(float(data.get("amount") or 0))
        except (ValueError, TypeError):
            received_amount = 0
        if expected_amount and received_amount != expected_amount:
            log.error(
                "webhook MONTANT INVALIDE ref=%s expected=%s received=%s - REFUSE",
                reference, expected_amount, received_amount,
            )
            supabase.update_payment_status(
                reference=reference, status="suspicious", raw_webhook=payload,
            )
            raise HTTPException(status_code=400, detail="Montant invalide")

        # Recupere le contexte (device_id / user_id / plan) depuis notre row pending
        device_id = existing.get("device_id")
        user_id = existing.get("user_id")
        plan = existing.get("plan") or PREMIUM_PLAN
        # Fallback metadata GeniusPay UNIQUEMENT si la row pending est incomplete
        # (ne pas faire confiance au webhook pour le device/user, c'est notre row
        # initiale qui est la source de verite)
        if not device_id and not user_id:
            meta = data.get("metadata") or {}
            device_id = meta.get("device_id") or None
            user_id = meta.get("user_id") or None

        # Calcul expires_at
        expires_at = None
        if plan == "monthly":
            from datetime import datetime, timedelta, timezone
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=PREMIUM_DURATION_DAYS)
            ).isoformat()

        # Active premium (user_id prioritaire, sinon device_id)
        ok = False
        if user_id:
            ok = supabase.set_premium_user(
                user_id=user_id, plan=plan, expires_at=expires_at,
                provider="geniuspay", receipt=reference,
            )
        elif device_id:
            ok = supabase.set_premium_device(
                device_id=device_id, plan=plan, expires_at=expires_at,
                provider="geniuspay", receipt=reference,
            )
        else:
            log.error("webhook success mais ni user_id ni device_id (ref=%s)",
                      reference)

        supabase.update_payment_status(
            reference=reference,
            status="completed" if ok else "completed_no_target",
            raw_webhook=payload,
            completed=True,
        )
        return {"status": "ok", "premium_activated": ok}

    # Cas echec / autre
    if event == "payment.failed" or data.get("status") == "failed":
        supabase.update_payment_status(
            reference=reference, status="failed", raw_webhook=payload,
        )
        return {"status": "ok", "marked": "failed"}

    # Event inconnu : on accuse reception sans rien faire
    return {"status": "ignored", "event": event}


@app.get("/api/me")
def me(request: Request):
    """Retourne {user_id} si JWT valide, sinon 401."""
    uid = _user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Token invalide ou absent")
    return {"user_id": uid}


@app.get("/api/history")
def history(request: Request, limit: int = 20):
    """Liste les restaurations de l'utilisateur courant (cloud)."""
    uid = _user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Authentification requise")
    if not supabase.is_configured:
        return {"items": []}
    try:
        client = supabase._client  # type: ignore
        res = (
            client.table("restorations")
            .select("job_id, before_url, after_url, processing_ms, created_at, pipeline")
            .eq("user_id", uid)
            .order("created_at", desc=True)
            .limit(min(50, max(1, limit)))
            .execute()
        )
        return {"items": res.data or []}
    except Exception as exc:
        log.warning("history fetch failed: %s", exc)
        raise HTTPException(status_code=500, detail="Erreur historique")


@app.post("/api/restore")
async def restore(
    request: Request,
    file: UploadFile = File(...),
    fidelity: Optional[float] = Form(None),
    upscale: Optional[int] = Form(None),
    provider: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    quality: Optional[str] = Form(None),
    colorize: Optional[str] = Form(None),  # "auto" | "on" | "off"
):
    """Restaure une photo. Retourne JSON {status, restored_image_url, ...}.

    Comportement:
      - Lecture des bytes en memoire (compatible serverless, pas d'ecriture disque)
      - Si Supabase configure: upload before/after vers Storage + log Postgres
      - Sinon: stockage temporaire en /tmp et URL absolue retournee
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Format non supporte. Utilisez {ALLOWED_EXT}")

    src_bytes = await file.read()
    if not src_bytes:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(src_bytes) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Image trop lourde (>{MAX_SIZE_MB}MB)")

    # --- Quota check ---
    device_id = _device_id(request)
    user_id = _user_id(request)  # peut etre None si non authentifie
    is_premium = _is_premium(request, user_id=user_id, device_id=device_id)

    # Cap global anti-abus : si DAILY_GLOBAL_LIMIT > 0, on plafonne le total
    # de restaurations 24h glissantes. Empeche un attaquant de cycler des
    # device_id pour drainer le credit Replicate.
    if DAILY_GLOBAL_LIMIT > 0 and not is_premium and supabase.is_configured:
        try:
            global_count = supabase.get_global_count_24h()
            if global_count >= DAILY_GLOBAL_LIMIT:
                log.warning("DAILY_GLOBAL_LIMIT atteint: %d/%d",
                            global_count, DAILY_GLOBAL_LIMIT)
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": "Service temporairement indisponible (capacite max atteinte). Reessayez dans quelques heures.",
                        "reason": "daily_global_cap",
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("global cap check failed: %s", exc)

    allowed, quota_info = quota_service.check(
        device_id=device_id, is_premium=is_premium, user_id=user_id,
    )
    if not allowed:
        reason = quota_info.get("reason")
        if reason == "premium_monthly_cap":
            msg = (
                "Plafond mensuel premium atteint ({} restaurations / 30 jours). "
                "Reessayez plus tard ou contactez le support."
            ).format(quota_info.get("limit", 100))
        elif reason == "missing_identifier":
            msg = "Identification requise (X-Device-Id ou Authorization)."
        else:
            msg = "Limite quotidienne atteinte"
        raise HTTPException(
            status_code=429,
            detail={
                "message": msg,
                "quota": quota_info,
            },
        )

    job_id = uuid.uuid4().hex[:12]
    log.info("Job %s : %d KB, ext=%s, device=%s, premium=%s",
             job_id, len(src_bytes) // 1024, ext, device_id, is_premium)

    # Provider OpenAI gpt-image-1 reserve aux Premium (cout x10)
    effective_provider = provider
    if effective_provider == "openai" and not is_premium:
        effective_provider = None  # downgrade -> mode auto (replicate)

    # "auto"/None -> None (detection auto), "on" -> True, "off" -> False
    colorize_arg: Optional[bool] = None
    if colorize:
        c = colorize.lower().strip()
        if c in ("on", "true", "1", "yes"):
            colorize_arg = True
        elif c in ("off", "false", "0", "no"):
            colorize_arg = False

    t0 = time.time()
    try:
        restored_bytes = restore_service.restore_bytes(
            src_bytes,
            fidelity=fidelity,
            upscale=upscale,
            provider=effective_provider,
            prompt=prompt,
            quality=quality,
            colorize=colorize_arg,
            is_premium=is_premium,
        )
    except Exception as exc:
        log.exception("Restoration failed")
        raise HTTPException(status_code=500, detail=f"Echec restauration: {exc}")
    elapsed_ms = int((time.time() - t0) * 1000)
    log.info("Job %s : done in %d ms (%d KB)", job_id, elapsed_ms, len(restored_bytes) // 1024)

    # --- Watermark si version gratuite ---
    if not is_premium:
        try:
            restored_bytes = add_watermark(restored_bytes)
        except Exception as exc:
            log.warning("watermark skipped: %s", exc)

    # Enregistrer l'utilisation (memory fallback ; Supabase logge via log_restoration)
    quota_service.record(device_id=device_id, user_id=user_id)

    # --- Stockage ---
    before_url = after_url = None
    if supabase.is_configured:
        try:
            before_url = supabase.upload_image(
                f"uploads/{job_id}{ext}", src_bytes, content_type=f"image/{ext.strip('.')}",
            )
            after_url = supabase.upload_image(
                f"outputs/restored_{job_id}.jpg", restored_bytes, content_type="image/jpeg",
            )
            supabase.log_restoration(
                job_id=job_id,
                before_url=before_url,
                after_url=after_url,
                processing_ms=elapsed_ms,
                size_bytes=len(src_bytes),
                user_id=user_id,
                device_id=device_id,
                is_premium=is_premium,
                pipeline=restore_service.pipeline_info()["mode"],
            )
        except Exception as exc:
            log.warning("Supabase upload failed (fallback inline): %s", exc)

    # Si Supabase non configure ou echec, on retourne le binaire en base64 dans la reponse
    if not after_url:
        # Mode dev / fallback : stocker dans /tmp et servir via une URL absolue
        tmp_dir = Path("/tmp") if Path("/tmp").exists() else Path(os.getenv("TEMP", "."))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_path = tmp_dir / f"restored_{job_id}.jpg"
        out_path.write_bytes(restored_bytes)
        # Pas d'URL publique sans storage -> on renvoie le binaire directement
        # Recompute quota AFTER recording
        _, q_after = quota_service.check(
            device_id=device_id, is_premium=is_premium, user_id=user_id,
        )
        return Response(
            content=restored_bytes,
            media_type="image/jpeg",
            headers={
                "X-Job-Id": job_id,
                "X-Processing-Ms": str(elapsed_ms),
                "X-Pipeline-Mode": restore_service.pipeline_info()["mode"],
                "X-Quota-Used": str(q_after.get("used", 0)),
                "X-Quota-Remaining": str(q_after.get("remaining", -1)),
                "X-Premium": "1" if is_premium else "0",
            },
        )

    _, q_after = quota_service.check(
        device_id=device_id, is_premium=is_premium, user_id=user_id,
    )
    return JSONResponse({
        "status": "success",
        "job_id": job_id,
        "before_image_url": before_url,
        "restored_image_url": after_url,
        "processing_ms": elapsed_ms,
        "pipeline": restore_service.pipeline_info()["mode"],
        "quota": q_after,
        "is_premium": is_premium,
    })


@app.post("/api/restore-binary")
async def restore_binary(request: Request, file: UploadFile = File(...)):
    """Variante qui renvoie toujours le binaire JPEG (sans Supabase).

    Utile pour les clients qui veulent afficher l'image immediatement.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="Format non supporte")
    src_bytes = await file.read()
    if not src_bytes:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(src_bytes) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Trop lourd (>{MAX_SIZE_MB}MB)")

    t0 = time.time()
    restored_bytes = restore_service.restore_bytes(src_bytes)
    elapsed_ms = int((time.time() - t0) * 1000)

    return Response(
        content=restored_bytes,
        media_type="image/jpeg",
        headers={
            "X-Processing-Ms": str(elapsed_ms),
            "X-Pipeline-Mode": restore_service.pipeline_info()["mode"],
        },
    )


# Compat: routes sans prefixe /api (utile en local)
app.add_api_route("/health", health, methods=["GET"])
app.add_api_route("/restore", restore, methods=["POST"])
app.add_api_route("/restore-binary", restore_binary, methods=["POST"])

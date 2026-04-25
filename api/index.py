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


def _device_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Device-Id") or request.headers.get("x-device-id")


def _is_premium(request: Request) -> bool:
    # Hook futur: valider via RevenueCat / Stripe / Supabase Auth claim
    return request.headers.get("X-Premium", "0") == "1"


def _user_id(request: Request) -> Optional[str]:
    """Extrait le user_id Supabase depuis le header Authorization: Bearer <jwt>."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    return auth_service.user_id_from_token(token)


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
    """Retourne le quota restant pour le device courant."""
    device_id = _device_id(request)
    is_premium = _is_premium(request)
    allowed, info = quota_service.check(device_id, is_premium)
    return {"allowed": allowed, **info}


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
    is_premium = _is_premium(request)
    user_id = _user_id(request)  # peut etre None si non authentifie
    allowed, quota_info = quota_service.check(device_id, is_premium)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Limite quotidienne atteinte",
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

    t0 = time.time()
    try:
        restored_bytes = restore_service.restore_bytes(
            src_bytes,
            fidelity=fidelity,
            upscale=upscale,
            provider=effective_provider,
            prompt=prompt,
            quality=quality,
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

    # Enregistrer l'utilisation (memory fallback)
    quota_service.record(device_id)

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
        _, q_after = quota_service.check(device_id, is_premium)
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

    _, q_after = quota_service.check(device_id, is_premium)
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

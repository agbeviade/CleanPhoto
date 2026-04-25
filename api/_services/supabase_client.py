"""Client Supabase: Storage + Postgres logging.

Configure via variables d'environnement:
  - SUPABASE_URL
  - SUPABASE_SERVICE_KEY  (cle service_role - garder secrete cote serveur)
  - SUPABASE_BUCKET       (default: souvenir)

Si non configure, toutes les operations retournent None / no-op.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

log = logging.getLogger("souvenir.supabase")


class SupabaseClient:
    def __init__(self, url: str = "", key: str = "", bucket: str = "souvenir") -> None:
        self.url = url
        self.key = key
        self.bucket = bucket
        self._client = None

        if url and key:
            try:
                from supabase import create_client  # type: ignore
                self._client = create_client(url, key)
                log.info("Supabase client initialise (bucket=%s)", bucket)
            except ImportError:
                log.warning("supabase-py non installe -> mode degrade")
            except Exception as exc:
                log.warning("Echec init Supabase: %s", exc)

    @classmethod
    def from_env(cls) -> "SupabaseClient":
        return cls(
            url=os.getenv("SUPABASE_URL", ""),
            key=os.getenv("SUPABASE_SERVICE_KEY", ""),
            bucket=os.getenv("SUPABASE_BUCKET", "souvenir"),
        )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def upload_image(self, path: str, data: bytes, content_type: str = "image/jpeg") -> Optional[str]:
        """Upload + retourne URL publique. Path est relatif au bucket."""
        if not self._client:
            return None
        try:
            storage = self._client.storage.from_(self.bucket)
            # upsert pour eviter conflit
            storage.upload(
                path=path,
                file=data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            res = storage.get_public_url(path)
            return res
        except Exception as exc:
            log.warning("upload_image failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Postgres
    # ------------------------------------------------------------------
    def log_restoration(
        self,
        job_id: str,
        before_url: Optional[str],
        after_url: Optional[str],
        processing_ms: int,
        size_bytes: int,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        is_premium: bool = False,
        pipeline: Optional[str] = None,
    ) -> None:
        if not self._client:
            return
        try:
            self._client.table("restorations").insert({
                "job_id": job_id,
                "before_url": before_url,
                "after_url": after_url,
                "processing_ms": processing_ms,
                "size_bytes": size_bytes,
                "user_id": user_id,
                "device_id": device_id,
                "is_premium": is_premium,
                "pipeline": pipeline,
            }).execute()
        except Exception as exc:
            log.warning("log_restoration failed: %s", exc)

    def get_user_quota(self, user_id: str) -> int:
        """Compte les restaurations sur les 24 dernieres heures (pour limite quotidienne)."""
        if not self._client:
            return 0
        try:
            from datetime import datetime, timedelta, timezone
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            res = (
                self._client.table("restorations")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .gte("created_at", since)
                .execute()
            )
            return res.count or 0
        except Exception as exc:
            log.warning("get_user_quota failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Premium status (source de verite cote serveur)
    # ------------------------------------------------------------------
    def get_premium_status(
        self,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> bool:
        """Retourne True si l'utilisateur a un abonnement premium actif.

        Priorite : user_id (si authentifie) > device_id (BGMaster style).
        Lit la table `subscriptions` avec le service_role. Verifie aussi
        que `expires_at` n'est pas depasse (ou null = lifetime).
        """
        if not self._client:
            return False
        if not user_id and not device_id:
            return False
        try:
            q = self._client.table("subscriptions").select("is_premium, expires_at")
            if user_id:
                q = q.eq("user_id", user_id)
            else:
                # Cherche un abonnement device anonyme (user_id null)
                q = q.eq("device_id", device_id).is_("user_id", "null")
            res = q.limit(1).execute()
            rows = res.data or []
            if not rows:
                return False
            row = rows[0]
            if not row.get("is_premium"):
                return False
            expires_at = row.get("expires_at")
            if expires_at:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if dt < datetime.now(timezone.utc):
                        return False  # Abonnement expire
                except Exception:
                    pass
            return True
        except Exception as exc:
            log.warning("get_premium_status failed: %s", exc)
            return False

    def set_premium_device(
        self,
        device_id: str,
        plan: str = "monthly",
        expires_at: Optional[str] = None,
        provider: str = "iap_apple",
        receipt: Optional[str] = None,
    ) -> bool:
        """Marque un device comme premium (BGMaster style, sans login)."""
        if not self._client or not device_id:
            return False
        try:
            self._client.rpc("set_premium_device", {
                "p_device_id": device_id,
                "p_plan": plan,
                "p_expires_at": expires_at,
                "p_provider": provider,
                "p_receipt": receipt,
            }).execute()
            return True
        except Exception as exc:
            log.warning("set_premium_device failed: %s", exc)
            return False

    def set_premium_user(
        self,
        user_id: str,
        plan: str = "monthly",
        expires_at: Optional[str] = None,
        provider: str = "manual",
        receipt: Optional[str] = None,
    ) -> bool:
        """Marque un user comme premium (apres webhook RevenueCat/Stripe)."""
        if not self._client or not user_id:
            return False
        try:
            self._client.rpc("set_premium_user", {
                "p_user_id": user_id,
                "p_plan": plan,
                "p_expires_at": expires_at,
                "p_provider": provider,
                "p_receipt": receipt,
            }).execute()
            return True
        except Exception as exc:
            log.warning("set_premium_user failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Paiements GeniusPay
    # ------------------------------------------------------------------
    def insert_payment(
        self,
        reference: str,
        amount: int,
        plan: str,
        device_id: Optional[str] = None,
        user_id: Optional[str] = None,
        currency: str = "XOF",
        provider: str = "geniuspay",
        checkout_url: Optional[str] = None,
        raw_response: Optional[dict] = None,
    ) -> bool:
        """Enregistre un paiement initie (status pending). Idempotent par reference."""
        if not self._client:
            return False
        try:
            self._client.table("payments").upsert({
                "reference": reference,
                "provider": provider,
                "user_id": user_id,
                "device_id": device_id,
                "plan": plan,
                "amount": amount,
                "currency": currency,
                "status": "pending",
                "checkout_url": checkout_url,
                "raw_response": raw_response,
            }, on_conflict="reference").execute()
            return True
        except Exception as exc:
            log.warning("insert_payment failed: %s", exc)
            return False

    def get_payment_by_reference(self, reference: str) -> Optional[dict]:
        """Recupere un paiement par sa reference (pour idempotency webhook)."""
        if not self._client:
            return None
        try:
            res = (
                self._client.table("payments")
                .select("*")
                .eq("reference", reference)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as exc:
            log.warning("get_payment_by_reference failed: %s", exc)
            return None

    def update_payment_status(
        self,
        reference: str,
        status: str,
        raw_webhook: Optional[dict] = None,
        completed: bool = False,
    ) -> bool:
        """Met a jour le status d'un paiement (apres webhook)."""
        if not self._client:
            return False
        try:
            from datetime import datetime, timezone
            update_data: dict = {"status": status, "raw_webhook": raw_webhook}
            if completed:
                update_data["completed_at"] = datetime.now(timezone.utc).isoformat()
            self._client.table("payments").update(update_data).eq(
                "reference", reference
            ).execute()
            return True
        except Exception as exc:
            log.warning("update_payment_status failed: %s", exc)
            return False

    def get_global_count_24h(self) -> int:
        """Compte total des restaurations sur les 24 dernieres heures (cap global anti-abus)."""
        if not self._client:
            return 0
        try:
            from datetime import datetime, timedelta, timezone
            since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            res = (
                self._client.table("restorations")
                .select("id", count="exact")
                .gte("created_at", since)
                .execute()
            )
            return res.count or 0
        except Exception as exc:
            log.warning("get_global_count_24h failed: %s", exc)
            return 0

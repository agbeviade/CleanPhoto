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

"""Quota service: limite quotidienne par device_id (anonyme).

Strategie:
  - Identification : header X-Device-Id (UUID genere cote app, persistant)
  - Limite par defaut: 3 restaurations / 24h glissantes
  - Override: header X-Premium=1 (futur, apres validation IAP / Stripe)
  - Stockage: table Supabase `restorations.device_id`
  - Fallback en memoire si Supabase non configure (dev local)

Architecture future-proof : remplacer le check premium par une
verification de subscription (RevenueCat / Stripe webhook).
"""
from __future__ import annotations

import os
import time
import logging
from collections import defaultdict
from typing import Optional, Tuple

log = logging.getLogger("souvenir.quota")

DAILY_FREE_LIMIT = int(os.getenv("DAILY_FREE_LIMIT", "3"))
QUOTA_WINDOW_SEC = 24 * 3600


class QuotaService:
    def __init__(self, supabase) -> None:
        self.supabase = supabase
        # Fallback in-memory (dev / tests)
        self._memory: dict[str, list[float]] = defaultdict(list)

    def _count_recent(self, device_id: str) -> int:
        """Nombre de restaurations dans les 24h pour ce device."""
        # Supabase
        if self.supabase and self.supabase.is_configured:
            try:
                from datetime import datetime, timedelta, timezone
                since = (datetime.now(timezone.utc) - timedelta(seconds=QUOTA_WINDOW_SEC)).isoformat()
                client = self.supabase._client
                res = (
                    client.table("restorations")
                    .select("id", count="exact")
                    .eq("device_id", device_id)
                    .gte("created_at", since)
                    .execute()
                )
                return res.count or 0
            except Exception as exc:
                log.warning("quota count via supabase failed: %s", exc)

        # Memory fallback
        now = time.time()
        timestamps = [t for t in self._memory[device_id] if now - t < QUOTA_WINDOW_SEC]
        self._memory[device_id] = timestamps
        return len(timestamps)

    def check(self, device_id: Optional[str], is_premium: bool = False) -> Tuple[bool, dict]:
        """Verifie si le device peut effectuer une nouvelle restauration.

        Returns:
            (allowed, info_dict) ou info contient: used, limit, remaining, reset_in_sec
        """
        if is_premium:
            return True, {
                "used": 0, "limit": -1, "remaining": -1,
                "premium": True,
            }
        if not device_id:
            # Pas d'ID = on bloque pour eviter abus (ou autoriser 1 fois en demo?)
            return False, {
                "used": 0, "limit": DAILY_FREE_LIMIT, "remaining": 0,
                "reason": "missing_device_id",
            }

        used = self._count_recent(device_id)
        remaining = max(0, DAILY_FREE_LIMIT - used)
        return remaining > 0, {
            "used": used,
            "limit": DAILY_FREE_LIMIT,
            "remaining": remaining,
            "reset_in_sec": QUOTA_WINDOW_SEC,
            "premium": False,
        }

    def record(self, device_id: Optional[str]) -> None:
        """Enregistre une utilisation en memoire (pour le fallback non-Supabase)."""
        if device_id and not (self.supabase and self.supabase.is_configured):
            self._memory[device_id].append(time.time())

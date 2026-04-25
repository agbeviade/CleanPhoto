"""Quota service: limite quotidienne, user_id prioritaire.

Strategie:
  - PRIORITE 1: user_id Supabase (depuis JWT) -> quota fiable, anti-bypass
  - PRIORITE 2: device_id (UUID app) -> fallback pour utilisateurs anonymes
  - Limite par defaut: 3 restaurations / 24h glissantes (DAILY_FREE_LIMIT env)
  - Premium = quota illimite (verifie cote serveur via Supabase)
  - Stockage: table Supabase `restorations` (user_id + device_id)
  - Fallback en memoire si Supabase non configure (dev local)

Securite:
  - Le quota par user_id est inviolable tant que l'auth Supabase tient.
  - Le quota par device_id reste contournable (l'app peut regenerer un UUID),
    mais c'est le mode anonyme : couple avec DAILY_GLOBAL_LIMIT pour cap.
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
# Plafond mensuel pour utilisateurs PREMIUM (anti-abus heavy users).
# 0 = illimite. Valeur par defaut : 100 photos / 30 jours.
PREMIUM_MONTHLY_LIMIT = int(os.getenv("PREMIUM_MONTHLY_LIMIT", "100"))
PREMIUM_WINDOW_SEC = 30 * 24 * 3600


class QuotaService:
    def __init__(self, supabase) -> None:
        self.supabase = supabase
        # Fallback in-memory (dev / tests)
        self._memory: dict[str, list[float]] = defaultdict(list)

    def _count_recent(
        self,
        user_id: Optional[str] = None,
        device_id: Optional[str] = None,
        window_sec: int = QUOTA_WINDOW_SEC,
    ) -> int:
        """Compte les restaurations sur une fenetre glissante pour user_id ou device_id."""
        # Supabase : query par user_id si dispo, sinon device_id
        if self.supabase and self.supabase.is_configured:
            try:
                from datetime import datetime, timedelta, timezone
                since = (datetime.now(timezone.utc) - timedelta(seconds=window_sec)).isoformat()
                client = self.supabase._client
                q = client.table("restorations").select("id", count="exact")
                if user_id:
                    q = q.eq("user_id", user_id)
                elif device_id:
                    q = q.eq("device_id", device_id)
                else:
                    return 0
                res = q.gte("created_at", since).execute()
                return res.count or 0
            except Exception as exc:
                log.warning("quota count via supabase failed: %s", exc)

        # Memory fallback (cle = user_id en priorite, sinon device_id)
        key = user_id or device_id
        if not key:
            return 0
        now = time.time()
        timestamps = [t for t in self._memory[key] if now - t < window_sec]
        self._memory[key] = timestamps
        return len(timestamps)

    def check(
        self,
        device_id: Optional[str] = None,
        is_premium: bool = False,
        user_id: Optional[str] = None,
    ) -> Tuple[bool, dict]:
        """Verifie si l'utilisateur peut effectuer une nouvelle restauration.

        Priorite : user_id (authentifie) > device_id (anonyme).

        Returns:
            (allowed, info_dict) ou info contient: used, limit, remaining, reset_in_sec
        """
        if is_premium:
            # Plafond mensuel anti-abus pour utilisateurs premium (heavy users).
            # 0 = illimite (override possible via env).
            if PREMIUM_MONTHLY_LIMIT > 0 and (user_id or device_id):
                used_month = self._count_recent(
                    user_id=user_id, device_id=device_id,
                    window_sec=PREMIUM_WINDOW_SEC,
                )
                remaining = max(0, PREMIUM_MONTHLY_LIMIT - used_month)
                if remaining <= 0:
                    log.info(
                        "premium monthly cap reached user=%s device=%s used=%d",
                        user_id, device_id, used_month,
                    )
                    return False, {
                        "used": used_month,
                        "limit": PREMIUM_MONTHLY_LIMIT,
                        "remaining": 0,
                        "reset_in_sec": PREMIUM_WINDOW_SEC,
                        "premium": True,
                        "reason": "premium_monthly_cap",
                    }
                return True, {
                    "used": used_month,
                    "limit": PREMIUM_MONTHLY_LIMIT,
                    "remaining": remaining,
                    "reset_in_sec": PREMIUM_WINDOW_SEC,
                    "premium": True,
                }
            return True, {
                "used": 0, "limit": -1, "remaining": -1,
                "premium": True,
            }
        if not user_id and not device_id:
            # Aucun identifiant = on bloque
            return False, {
                "used": 0, "limit": DAILY_FREE_LIMIT, "remaining": 0,
                "reason": "missing_identifier",
            }

        used = self._count_recent(user_id=user_id, device_id=device_id)
        remaining = max(0, DAILY_FREE_LIMIT - used)
        return remaining > 0, {
            "used": used,
            "limit": DAILY_FREE_LIMIT,
            "remaining": remaining,
            "reset_in_sec": QUOTA_WINDOW_SEC,
            "premium": False,
            "identifier": "user" if user_id else "device",
        }

    def record(
        self,
        device_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Enregistre une utilisation en memoire (fallback si Supabase off).

        Cle = user_id si dispo, sinon device_id.
        """
        if not (self.supabase and self.supabase.is_configured):
            key = user_id or device_id
            if key:
                self._memory[key].append(time.time())

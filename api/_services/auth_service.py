"""Validation des JWTs Supabase.

Strategie:
  - On recoit un Authorization: Bearer <token> envoye par l'app Flutter
  - On valide le token via /auth/v1/user en utilisant SUPABASE_URL + ANON_KEY
    (c'est l'API publique de Supabase, pas besoin de jwt_secret cote serveur)
  - Cache en memoire 60s pour eviter de spammer Supabase

Retourne le user_id (UUID Supabase auth.users) ou None si invalide.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Optional

import requests

log = logging.getLogger("souvenir.auth")

CACHE_TTL_SEC = 60


class AuthService:
    def __init__(self, supabase_url: str, anon_key: str) -> None:
        self.supabase_url = supabase_url.rstrip("/") if supabase_url else ""
        self.anon_key = anon_key
        self._cache: dict[str, tuple[float, Optional[str]]] = {}

    @classmethod
    def from_env(cls) -> "AuthService":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", ""),
            anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.supabase_url and self.anon_key)

    def user_id_from_token(self, token: Optional[str]) -> Optional[str]:
        """Valide un access_token Supabase et retourne le user_id (UUID)."""
        if not token or not self.is_configured:
            return None

        # Cache hit?
        cached = self._cache.get(token)
        now = time.time()
        if cached and now - cached[0] < CACHE_TTL_SEC:
            return cached[1]

        try:
            r = requests.get(
                f"{self.supabase_url}/auth/v1/user",
                headers={
                    "apikey": self.anon_key,
                    "Authorization": f"Bearer {token}",
                },
                timeout=4,
            )
            if r.status_code != 200:
                log.debug("auth: user endpoint %s -> %s", r.status_code, r.text[:200])
                self._cache[token] = (now, None)
                return None
            data = r.json()
            user_id = data.get("id")
            self._cache[token] = (now, user_id)
            return user_id
        except Exception as exc:
            log.warning("auth lookup failed: %s", exc)
            return None

"""Notifier critique : pousse les events securite vers Discord / Slack.

Usage :
    notifier = CriticalNotifier.from_env()
    notifier.alert("Webhook signature invalide", "ref=MTX-xxx", level="error")

Compatible :
  - Discord : webhook officiel (POST JSON {"content": "..."}).
  - Slack   : meme format fonctionne via les Incoming Webhooks (text auto-render).

Anti-spam :
  - Cache en memoire 60s par "key" (titre + message tronque) -> evite de spam
    si le meme evenement se repete 1000x en 1 minute.
"""
from __future__ import annotations

import os
import time
import logging
import threading
from typing import Optional

import requests

log = logging.getLogger("souvenir.notifier")

DEDUPE_WINDOW_SEC = 60


class CriticalNotifier:
    EMOJI = {
        "info": "🔵",
        "warning": "🟡",
        "error": "🔴",
        "critical": "🚨",
    }

    def __init__(self, webhook_url: str = "", app_name: str = "Souvenir AI"):
        self.webhook_url = webhook_url
        self.app_name = app_name
        self._dedupe: dict[str, float] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "CriticalNotifier":
        return cls(
            webhook_url=os.getenv("ADMIN_WEBHOOK_URL", ""),
            app_name=os.getenv("APP_NAME", "Souvenir AI"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def _should_send(self, key: str) -> bool:
        """Dedupe : empeche d'envoyer 2 fois le meme event en < 60s."""
        with self._lock:
            now = time.time()
            # Nettoie les vieilles entrees
            self._dedupe = {
                k: ts for k, ts in self._dedupe.items()
                if now - ts < DEDUPE_WINDOW_SEC
            }
            if key in self._dedupe:
                return False
            self._dedupe[key] = now
            return True

    def alert(
        self,
        title: str,
        message: str = "",
        level: str = "warning",
        context: Optional[dict] = None,
        dedupe: bool = True,
    ) -> bool:
        """Envoie une alerte au webhook configure.

        Args:
            title    : ligne en gras, max ~80 chars
            message  : corps detaille (peut contenir des markdown Discord/Slack)
            level    : 'info' | 'warning' | 'error' | 'critical'
            context  : dict de meta (key=value lignes, max 10 keys affichees)
            dedupe   : si True, suppress les doublons sous 60s

        Returns:
            True si envoye, False si non configure ou dedup hit.
        """
        if not self.is_configured:
            return False

        # Dedupe key (titre + 60 premiers chars du message)
        if dedupe:
            key = f"{title}|{message[:60]}"
            if not self._should_send(key):
                return False

        emoji = self.EMOJI.get(level, "🟡")
        lines = [f"{emoji} **[{self.app_name}] {title}**"]
        if message:
            lines.append(message)
        if context:
            ctx_lines = []
            for k, v in list(context.items())[:10]:
                # Tronque les valeurs longues pour eviter le spam
                v_str = str(v)
                if len(v_str) > 100:
                    v_str = v_str[:100] + "..."
                ctx_lines.append(f"  `{k}` : `{v_str}`")
            if ctx_lines:
                lines.append("\n".join(ctx_lines))

        content = "\n".join(lines)
        # Discord limite a 2000 chars
        if len(content) > 1900:
            content = content[:1900] + "..."

        try:
            r = requests.post(
                self.webhook_url,
                json={"content": content},
                timeout=3,
            )
            if r.status_code >= 400:
                log.warning("notifier %d: %s", r.status_code, r.text[:200])
                return False
            return True
        except Exception as exc:
            log.warning("notifier failed: %s", exc)
            return False

"""Client GeniusPay - integration paiements Mobile Money / cartes Afrique.

Doc API: https://pay.genius.ci/docs/api

Flow:
  1. Backend POST /api/v1/merchant/payments  -> recoit checkout_url
  2. App ouvre checkout_url (WebView ou navigateur externe)
  3. User paie via Wave / Orange Money / MTN / carte
  4. GeniusPay POST notre webhook avec signature HMAC-SHA256
  5. Backend verifie signature, active premium

Securite:
  - X-API-Secret est cote serveur uniquement (jamais expose)
  - Webhook signe avec HMAC-SHA256(timestamp + "." + json_payload, webhook_secret)
  - Tolerance timestamp : 5 minutes (anti replay)
"""
from __future__ import annotations

import os
import hmac
import json
import hashlib
import logging
import time
from typing import Optional

import requests

log = logging.getLogger("souvenir.geniuspay")

DEFAULT_BASE_URL = "https://pay.genius.ci/api/v1/merchant"
WEBHOOK_TIMESTAMP_TOLERANCE_SEC = 300  # 5 minutes


class GeniusPayClient:
    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        webhook_secret: str = "",
        base_url: str = DEFAULT_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.webhook_secret = webhook_secret
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_env(cls) -> "GeniusPayClient":
        return cls(
            api_key=os.getenv("GENIUSPAY_API_KEY", ""),
            api_secret=os.getenv("GENIUSPAY_API_SECRET", ""),
            webhook_secret=os.getenv("GENIUSPAY_WEBHOOK_SECRET", ""),
            base_url=os.getenv("GENIUSPAY_BASE_URL", DEFAULT_BASE_URL),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _headers(self) -> dict:
        return {
            "X-API-Key": self.api_key,
            "X-API-Secret": self.api_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Paiement : initier une transaction
    # ------------------------------------------------------------------
    def create_payment(
        self,
        amount: int,
        description: str,
        currency: str = "XOF",
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None,
        customer_country: Optional[str] = None,
        success_url: Optional[str] = None,
        error_url: Optional[str] = None,
        metadata: Optional[dict] = None,
        timeout: int = 15,
    ) -> dict:
        """Cree une transaction GeniusPay en mode Checkout (page hebergee).

        Pas de payment_method specifie -> GeniusPay genere une checkout_url
        avec tous les moyens de paiement disponibles.

        Returns: dict {reference, checkout_url, status, amount, ...}
        Raises: RuntimeError si l'API repond en erreur.
        """
        if not self.is_configured:
            raise RuntimeError("GeniusPay non configure (cles manquantes)")

        url = f"{self.base_url}/payments"
        payload: dict = {
            "amount": amount,
            "currency": currency,
            "description": description,
        }
        customer: dict = {}
        if customer_name:
            customer["name"] = customer_name
        if customer_email:
            customer["email"] = customer_email
        if customer_phone:
            customer["phone"] = customer_phone
        if customer_country:
            customer["country"] = customer_country
        if customer:
            payload["customer"] = customer
        if success_url:
            payload["success_url"] = success_url
        if error_url:
            payload["error_url"] = error_url
        if metadata:
            payload["metadata"] = metadata

        log.info("geniuspay: POST /payments amount=%d %s", amount, currency)
        r = requests.post(url, headers=self._headers(), json=payload, timeout=timeout)
        if r.status_code >= 400:
            log.error("geniuspay: HTTP %d body=%s", r.status_code, r.text[:500])
            raise RuntimeError(
                f"GeniusPay {r.status_code}: {r.text[:300]}"
            )
        body = r.json()
        if not body.get("success"):
            raise RuntimeError(f"GeniusPay refuse: {body}")
        return body.get("data") or {}

    # ------------------------------------------------------------------
    # Webhook : verification signature
    # ------------------------------------------------------------------
    def verify_webhook(
        self,
        signature: Optional[str],
        timestamp: Optional[str],
        raw_payload: bytes,
        tolerance_sec: int = WEBHOOK_TIMESTAMP_TOLERANCE_SEC,
    ) -> bool:
        """Verifie la signature HMAC-SHA256 d'un webhook GeniusPay.

        Format attendu (d'apres la doc):
          signature = HMAC-SHA256(timestamp + "." + json_payload, webhook_secret)

        Args:
            signature: header X-Webhook-Signature
            timestamp: header X-Webhook-Timestamp (epoch seconds)
            raw_payload: corps brut de la requete (bytes)
            tolerance_sec: fenetre anti-replay

        Returns: True si la signature est valide ET timestamp recent.
        """
        if not self.webhook_secret:
            log.error("webhook secret non configure")
            return False
        if not signature or not timestamp:
            log.warning("webhook: headers manquants (sig=%s ts=%s)",
                        bool(signature), bool(timestamp))
            return False

        # Anti-replay : timestamp doit etre recent
        try:
            ts_int = int(timestamp)
        except (ValueError, TypeError):
            log.warning("webhook: timestamp invalide: %r", timestamp)
            return False
        now = int(time.time())
        if abs(now - ts_int) > tolerance_sec:
            log.warning("webhook: timestamp trop vieux (delta=%ds)", now - ts_int)
            return False

        # Calcul signature attendue
        # IMPORTANT: la doc utilise le payload JSON encode tel quel.
        # On reutilise le raw_payload recu pour eviter les reformattages JSON
        # qui changeraient la signature (espaces, ordre cles, etc.).
        try:
            payload_str = raw_payload.decode("utf-8")
        except UnicodeDecodeError:
            log.warning("webhook: payload non utf-8")
            return False

        signed = f"{timestamp}.{payload_str}"
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            signed.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # comparaison constante
        if not hmac.compare_digest(expected, signature):
            log.warning("webhook: signature invalide")
            return False
        return True

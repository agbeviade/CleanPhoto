"""Verification des receipts Apple StoreKit (in_app_purchase iOS).

Documentation Apple :
  https://developer.apple.com/documentation/appstorereceipts/verifyreceipt

Strategie :
  - POST receipt base64 sur https://buy.itunes.apple.com/verifyReceipt
  - Si status=21007 (receipt sandbox envoye en prod) -> retry sur sandbox URL
  - Validation cote backend = obligatoire (sinon le client peut forger un receipt)

Mapping product_id Apple <-> pack_id de notre catalogue :
  pack_10_ios   -> pack_10_week   (10 photos / 7 jours)
  pack_50_ios   -> pack_50_week   (50 photos / 7 jours)
  pack_100_ios  -> pack_100_week  (100 photos / 7 jours)

Securite :
  - Idempotency par transaction_id (chaque transaction Apple unique)
  - Verification bundle_id (eviter les receipts d'autres apps)
  - Le receipt n'est PAS stocke en clair (juste le transaction_id pour audit)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

log = logging.getLogger("souvenir.apple_iap")

PROD_URL = "https://buy.itunes.apple.com/verifyReceipt"
SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"

# Mapping Apple product_id -> pack interne (mappe sur PACK_CATALOG)
PRODUCT_TO_PACK = {
    "pack_10_ios": "pack_10_week",
    "pack_50_ios": "pack_50_week",
    "pack_100_ios": "pack_100_week",
}

# Codes status Apple importants (https://developer.apple.com/documentation/appstorereceipts/status)
STATUS_OK = 0
STATUS_SANDBOX_RECEIPT_ON_PROD = 21007
STATUS_PROD_RECEIPT_ON_SANDBOX = 21008
STATUS_INVALID_RECEIPT = 21002
STATUS_AUTH_FAILED = 21003


class AppleIapError(Exception):
    """Erreur de validation receipt Apple (a renvoyer en 4xx/5xx au client)."""

    def __init__(self, message: str, status_code: int = 400, apple_status: int = -1):
        super().__init__(message)
        self.status_code = status_code
        self.apple_status = apple_status


class AppleIapVerifier:
    """Verifie un receipt iOS aupres des serveurs Apple."""

    def __init__(
        self,
        shared_secret: Optional[str] = None,
        bundle_id: Optional[str] = None,
        force_sandbox: bool = False,
    ):
        # Shared secret : necessaire pour les subscriptions auto-renouvelables.
        # Pour des consumables (nos packs), c'est OPTIONNEL.
        self.shared_secret = shared_secret or ""
        # Bundle ID attendu : si defini, on rejette les receipts d'autres apps.
        self.bundle_id = bundle_id or ""
        self.force_sandbox = force_sandbox

    @classmethod
    def from_env(cls) -> "AppleIapVerifier":
        return cls(
            shared_secret=os.getenv("APPLE_SHARED_SECRET", ""),
            bundle_id=os.getenv("APPLE_BUNDLE_ID", ""),
            force_sandbox=os.getenv("APPLE_USE_SANDBOX", "0") == "1",
        )

    @property
    def is_configured(self) -> bool:
        # Pas de secret necessaire pour les consumables, donc toujours configure.
        # On peut toutefois desactiver explicitement via APPLE_IAP_ENABLED=0.
        return os.getenv("APPLE_IAP_ENABLED", "1") == "1"

    def verify(self, receipt_data_b64: str, timeout: int = 10) -> dict:
        """Valide un receipt iOS et retourne un dict resume.

        Args:
          receipt_data_b64: base64 du receipt obtenu par
                           SKReceiptRefreshRequest cote iOS.

        Returns:
          dict avec : product_id, transaction_id, purchase_date_ms,
          quantity, original_transaction_id, environment (prod|sandbox).

        Raises:
          AppleIapError: si receipt invalide / mauvais bundle_id / etc.
        """
        if not receipt_data_b64:
            raise AppleIapError("receipt_data manquant", 400)

        body = {"receipt-data": receipt_data_b64}
        if self.shared_secret:
            body["password"] = self.shared_secret

        # 1) Premier appel
        url = SANDBOX_URL if self.force_sandbox else PROD_URL
        env = "sandbox" if self.force_sandbox else "production"
        result = self._post(url, body, timeout)

        # 2) Auto-fallback sandbox si Apple le demande
        status = result.get("status", -1)
        if status == STATUS_SANDBOX_RECEIPT_ON_PROD and not self.force_sandbox:
            log.info("Receipt sandbox envoye en prod -> retry sandbox")
            result = self._post(SANDBOX_URL, body, timeout)
            env = "sandbox"
            status = result.get("status", -1)

        # 3) Status final
        if status != STATUS_OK:
            log.warning("Apple verifyReceipt status=%s", status)
            raise AppleIapError(
                f"Receipt invalide (Apple status={status})",
                status_code=400,
                apple_status=status,
            )

        # 4) Extraction des infos critiques
        receipt = result.get("receipt") or {}
        bundle_id = receipt.get("bundle_id") or ""
        if self.bundle_id and bundle_id != self.bundle_id:
            log.error(
                "Receipt bundle_id mismatch: attendu=%s recu=%s",
                self.bundle_id, bundle_id,
            )
            raise AppleIapError("Bundle ID invalide", 400)

        # in_app : liste des transactions, on prend la plus recente
        in_app_list = receipt.get("in_app") or result.get("latest_receipt_info") or []
        if not in_app_list:
            raise AppleIapError("Aucune transaction trouvee dans le receipt", 400)

        # Tri par purchase_date_ms decroissant pour avoir la plus recente
        try:
            in_app_list_sorted = sorted(
                in_app_list,
                key=lambda x: int(x.get("purchase_date_ms", 0)),
                reverse=True,
            )
        except Exception:
            in_app_list_sorted = in_app_list
        latest = in_app_list_sorted[0]

        product_id = latest.get("product_id") or ""
        transaction_id = latest.get("transaction_id") or ""
        if not product_id or not transaction_id:
            raise AppleIapError("Receipt incomplet (product/transaction)", 400)

        # 5) product_id doit matcher un de nos packs connus
        pack_id = PRODUCT_TO_PACK.get(product_id)
        if not pack_id:
            log.warning("product_id Apple inconnu: %s", product_id)
            raise AppleIapError(f"Produit inconnu: {product_id}", 400)

        return {
            "product_id": product_id,
            "pack_id": pack_id,
            "transaction_id": transaction_id,
            "original_transaction_id": latest.get("original_transaction_id")
                                       or transaction_id,
            "purchase_date_ms": int(latest.get("purchase_date_ms", 0)),
            "quantity": int(latest.get("quantity", 1)),
            "bundle_id": bundle_id,
            "environment": env,
        }

    def _post(self, url: str, body: dict, timeout: int) -> dict:
        try:
            resp = requests.post(url, json=body, timeout=timeout)
        except requests.RequestException as exc:
            log.error("Apple verifyReceipt network error: %s", exc)
            raise AppleIapError("Apple unreachable", status_code=503) from exc

        if resp.status_code != 200:
            log.error("Apple verifyReceipt HTTP %s", resp.status_code)
            raise AppleIapError(
                f"Apple HTTP {resp.status_code}", status_code=502,
            )

        try:
            return resp.json()
        except ValueError as exc:
            log.error("Apple verifyReceipt JSON invalide: %s", exc)
            raise AppleIapError("Reponse Apple invalide", status_code=502) from exc

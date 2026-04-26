"""Configuration pytest globale.

Effets:
  1. Force `DEV_ALLOW_PREMIUM_HEADER=1` AVANT l'import de l'app
     (necessaire pour les tests qui utilisent le header X-Premium en lieu et
     place d'une vraie subscription Supabase).
  2. Force ENV=test pour eviter le hardening qui refuse le header en prod.
  3. Configure un webhook secret deterministe pour les tests de signature.
  4. Expose un client de test FastAPI partage et des fixtures de mock.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 1. Variables d'environnement requises AVANT l'import de api.index
#    (les constantes du module sont evaluees au moment de l'import).
os.environ.setdefault("DEV_ALLOW_PREMIUM_HEADER", "1")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("VERCEL_ENV", "test")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("GENIUSPAY_WEBHOOK_SECRET", "test_whsec_deterministic_123")
# Empeche tout appel reseau accidentel vers Replicate / OpenAI / Supabase
os.environ.pop("REPLICATE_API_TOKEN", None)
os.environ.pop("OPENAI_API_KEY", None)

# 2. Path setup pour que `api.index` soit importable
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """Client FastAPI partage entre tous les tests."""
    from api.index import app
    return TestClient(app)


@pytest.fixture()
def fake_supabase(monkeypatch):
    """Remplace `api.index.supabase` par un faux client en memoire.

    Permet de tester les flux pack-consume / refund / webhook sans Postgres.
    """
    from api import index as api_module

    class FakeSupabase:
        is_configured = True

        def __init__(self) -> None:
            # subscriptions[device_id_or_user_id] = {pack_size, images_used, expires_at}
            self.subscriptions: dict[str, dict] = {}
            self.payments: dict[str, dict] = {}
            self.consume_calls: int = 0
            self.refund_calls: int = 0

        # --- subscriptions -------------------------------------------------
        def _key(self, user_id, device_id):
            return user_id or device_id

        def get_subscription_info(self, user_id=None, device_id=None):
            k = self._key(user_id, device_id)
            sub = self.subscriptions.get(k)
            if not sub:
                return None
            remaining = None
            is_premium = True
            pack_size = sub.get("pack_size")
            used = sub.get("images_used", 0)
            if pack_size is not None:
                remaining = max(0, pack_size - used)
                if remaining <= 0:
                    is_premium = False
            return {
                "is_premium": is_premium,
                "plan": sub.get("plan"),
                "pack_size": pack_size,
                "images_used": used,
                "remaining": remaining,
                "expires_at": sub.get("expires_at"),
            }

        def get_premium_status(self, user_id=None, device_id=None):
            info = self.get_subscription_info(user_id=user_id, device_id=device_id)
            return bool(info and info.get("is_premium"))

        def consume_pack_image(self, user_id=None, device_id=None):
            self.consume_calls += 1
            k = self._key(user_id, device_id)
            sub = self.subscriptions.get(k)
            if not sub:
                return -1
            pack_size = sub.get("pack_size")
            if pack_size is None:
                return 99999
            used = sub.get("images_used", 0)
            if used >= pack_size:
                return 0
            sub["images_used"] = used + 1
            return pack_size - sub["images_used"]

        def refund_pack_image(self, user_id=None, device_id=None):
            self.refund_calls += 1
            k = self._key(user_id, device_id)
            sub = self.subscriptions.get(k)
            if not sub or sub.get("pack_size") is None:
                return -1
            sub["images_used"] = max(0, sub.get("images_used", 0) - 1)
            return sub["pack_size"] - sub["images_used"]

        def set_premium_user(self, user_id, plan="pack_10_week", expires_at=None,
                             provider="geniuspay", receipt=None, pack_size=None):
            self.subscriptions[user_id] = {
                "plan": plan, "expires_at": expires_at,
                "pack_size": pack_size, "images_used": 0,
                "provider": provider, "receipt": receipt,
            }
            return True

        def set_premium_device(self, device_id, plan="pack_10_week", expires_at=None,
                               provider="geniuspay", receipt=None, pack_size=None):
            self.subscriptions[device_id] = {
                "plan": plan, "expires_at": expires_at,
                "pack_size": pack_size, "images_used": 0,
                "provider": provider, "receipt": receipt,
            }
            return True

        # --- payments ------------------------------------------------------
        def insert_payment(self, reference, amount, plan, device_id=None,
                           user_id=None, currency="XOF", provider="geniuspay",
                           checkout_url=None, raw_response=None):
            self.payments[reference] = {
                "reference": reference, "amount": amount, "plan": plan,
                "device_id": device_id, "user_id": user_id,
                "currency": currency, "status": "pending",
                "checkout_url": checkout_url,
            }
            return True

        def get_payment_by_reference(self, reference):
            return self.payments.get(reference)

        def update_payment_status(self, reference, status, raw_webhook=None,
                                  completed=False):
            p = self.payments.get(reference)
            if not p:
                return False
            p["status"] = status
            if completed:
                from datetime import datetime, timezone
                p["completed_at"] = datetime.now(timezone.utc).isoformat()
            return True

        def count_recent_payments(self, *args, **kwargs):
            return 0  # rate-limit OFF dans les tests

        def get_global_count_24h(self):
            return 0

        # --- restorations / storage : no-op pour les tests ----------------
        def upload_image(self, *args, **kwargs):
            return None

        def log_restoration(self, *args, **kwargs):
            return True

    fake = FakeSupabase()
    monkeypatch.setattr(api_module, "supabase", fake)
    # quota_service partage la meme reference -> remplace aussi
    monkeypatch.setattr(api_module.quota_service, "supabase", fake)
    return fake


@pytest.fixture()
def fake_geniuspay(monkeypatch):
    """Remplace le client GeniusPay par un mock qui ne fait pas de HTTP."""
    from api import index as api_module

    class FakeGeniusPay:
        webhook_secret = os.environ["GENIUSPAY_WEBHOOK_SECRET"]
        is_configured = True
        calls: list = []

        def create_payment(self, amount, currency="XOF", description="",
                           success_url=None, error_url=None, metadata=None,
                           **kwargs):
            ref = f"MTX-TEST-{len(self.calls):04d}"
            self.calls.append({"amount": amount, "metadata": metadata})
            return {
                "reference": ref,
                "checkout_url": f"https://pay.test/checkout/{ref}",
                "status": "pending",
            }

        def verify_webhook(self, signature, timestamp, raw_payload,
                           tolerance_sec=300):
            # Delegue a la vraie implementation
            from api._services.geniuspay_client import GeniusPayClient
            real = GeniusPayClient(webhook_secret=self.webhook_secret)
            return real.verify_webhook(signature, timestamp, raw_payload,
                                       tolerance_sec=tolerance_sec)

    fake = FakeGeniusPay()
    monkeypatch.setattr(api_module, "geniuspay", fake)
    return fake


@pytest.fixture()
def fake_image_bytes() -> bytes:
    """Genere un petit JPEG valide en memoire."""
    import io
    import numpy as np
    from PIL import Image
    arr = np.random.randint(0, 256, (64, 64, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=80)
    return buf.getvalue()

"""Tests pour le flux Apple StoreKit / In-App Purchase.

Couvre :
  - Verifier rejette si receipt_data manquant
  - Verifier rejette si product_id inconnu
  - Verifier rejette si bundle_id mismatch
  - Auto-fallback sandbox quand Apple retourne 21007
  - Endpoint /api/payments/apple/verify : succes -> active premium + pack_size
  - Idempotency : meme transaction_id ne reactive pas (already_processed)
  - Refus si receipt_data manquant
  - Refus si X-Device-Id et Authorization absents
  - product_id mismatch entre client et receipt -> 400
"""
from __future__ import annotations

import pytest


# -----------------------------------------------------------------------
# Helpers : faux receipt Apple
# -----------------------------------------------------------------------
def _make_apple_response(
    status: int = 0,
    product_id: str = "pack_10_ios",
    transaction_id: str = "1000000000111111",
    bundle_id: str = "ci.cleanphoto.souvenirai",
    purchase_date_ms: int = 1700000000000,
):
    return {
        "status": status,
        "environment": "Production",
        "receipt": {
            "bundle_id": bundle_id,
            "in_app": [
                {
                    "product_id": product_id,
                    "transaction_id": transaction_id,
                    "original_transaction_id": transaction_id,
                    "purchase_date_ms": str(purchase_date_ms),
                    "quantity": "1",
                }
            ],
        },
    }


@pytest.fixture()
def patch_apple(monkeypatch):
    """Patch requests.post utilise par AppleIapVerifier."""
    state = {"calls": 0, "responses": [], "urls": []}

    def make_post(responses):
        def fake_post(url, json=None, timeout=None):
            state["calls"] += 1
            state["urls"].append(url)
            idx = min(state["calls"] - 1, len(responses) - 1)
            response_body = responses[idx]

            class FakeResp:
                status_code = 200
                def json(self):
                    return response_body
            return FakeResp()
        return fake_post

    def patcher(*responses):
        if not responses:
            responses = [_make_apple_response()]
        state["responses"] = list(responses)
        import api._services.apple_iap as mod
        monkeypatch.setattr(mod.requests, "post", make_post(responses))
        return state

    return patcher


# -----------------------------------------------------------------------
# Tests unitaires AppleIapVerifier
# -----------------------------------------------------------------------
class TestAppleIapVerifier:
    def test_empty_receipt_raises(self):
        from api._services.apple_iap import AppleIapVerifier, AppleIapError
        v = AppleIapVerifier()
        with pytest.raises(AppleIapError) as exc_info:
            v.verify("")
        assert exc_info.value.status_code == 400

    def test_success_returns_pack_mapping(self, patch_apple):
        patch_apple(_make_apple_response(product_id="pack_50_ios"))
        from api._services.apple_iap import AppleIapVerifier
        v = AppleIapVerifier()
        result = v.verify("fake_receipt_b64")
        assert result["product_id"] == "pack_50_ios"
        assert result["pack_id"] == "pack_50_week"
        assert result["transaction_id"] == "1000000000111111"
        assert result["environment"] == "production"

    def test_unknown_product_id_rejected(self, patch_apple):
        patch_apple(_make_apple_response(product_id="random_unknown"))
        from api._services.apple_iap import AppleIapVerifier, AppleIapError
        v = AppleIapVerifier()
        with pytest.raises(AppleIapError) as exc_info:
            v.verify("fake_receipt")
        assert "inconnu" in str(exc_info.value).lower()

    def test_bundle_id_mismatch_rejected(self, patch_apple):
        patch_apple(_make_apple_response(bundle_id="com.evil.app"))
        from api._services.apple_iap import AppleIapVerifier, AppleIapError
        v = AppleIapVerifier(bundle_id="ci.cleanphoto.souvenirai")
        with pytest.raises(AppleIapError) as exc_info:
            v.verify("fake_receipt")
        assert "bundle" in str(exc_info.value).lower()

    def test_invalid_status_rejected(self, patch_apple):
        patch_apple(_make_apple_response(status=21002))
        from api._services.apple_iap import AppleIapVerifier, AppleIapError
        v = AppleIapVerifier()
        with pytest.raises(AppleIapError) as exc_info:
            v.verify("fake_receipt")
        assert exc_info.value.apple_status == 21002

    def test_sandbox_fallback_on_21007(self, patch_apple):
        """Apple renvoie 21007 quand un receipt sandbox est envoye en prod.
        Le verifier doit retry automatiquement sur sandbox URL."""
        state = patch_apple(
            _make_apple_response(status=21007),  # 1er appel : prod -> sandbox
            _make_apple_response(status=0),       # 2eme appel : sandbox -> ok
        )
        from api._services.apple_iap import AppleIapVerifier
        v = AppleIapVerifier()
        result = v.verify("sandbox_receipt")
        assert result["environment"] == "sandbox"
        assert state["calls"] == 2
        assert "sandbox" in state["urls"][1]

    def test_force_sandbox_uses_sandbox_url(self, patch_apple):
        state = patch_apple(_make_apple_response())
        from api._services.apple_iap import AppleIapVerifier
        v = AppleIapVerifier(force_sandbox=True)
        v.verify("fake_receipt")
        assert "sandbox" in state["urls"][0]

    def test_empty_in_app_rejected(self, patch_apple):
        bad = _make_apple_response()
        bad["receipt"]["in_app"] = []
        patch_apple(bad)
        from api._services.apple_iap import AppleIapVerifier, AppleIapError
        v = AppleIapVerifier()
        with pytest.raises(AppleIapError):
            v.verify("fake_receipt")


# -----------------------------------------------------------------------
# Tests integration /api/payments/apple/verify
# -----------------------------------------------------------------------
class TestAppleVerifyEndpoint:
    def test_missing_receipt_400(self, client, fake_supabase):
        r = client.post(
            "/api/payments/apple/verify",
            json={},
            headers={"X-Device-Id": "test-device-1"},
        )
        assert r.status_code == 400
        assert "receipt" in r.json()["detail"].lower()

    def test_missing_device_and_auth_400(self, client, fake_supabase):
        r = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "abc"},
        )
        assert r.status_code == 400

    def test_success_activates_premium(self, client, fake_supabase, patch_apple):
        patch_apple(_make_apple_response(
            product_id="pack_10_ios",
            transaction_id="TX-SUCCESS-001",
        ))
        r = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake_b64", "product_id": "pack_10_ios"},
            headers={"X-Device-Id": "device-success-1"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["plan"] == "pack_10_week"
        assert body["pack_size"] == 10
        assert body["premium_activated"] is True
        assert body["reference"] == "apple_TX-SUCCESS-001"

        # Verifie que le device est passe premium dans le fake supabase
        sub = fake_supabase.subscriptions.get("device-success-1")
        assert sub is not None
        assert sub["pack_size"] == 10
        assert sub["plan"] == "pack_10_week"
        assert sub["provider"] == "apple"

    def test_idempotency_same_transaction(self, client, fake_supabase, patch_apple):
        """Meme receipt rejoue ne reactive pas (already_processed)."""
        patch_apple(_make_apple_response(transaction_id="TX-IDEM-002"))
        # 1er appel : active
        r1 = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake"},
            headers={"X-Device-Id": "device-idem"},
        )
        assert r1.json()["status"] == "ok"
        # On force le pack_size a 0 pour detecter une eventuelle reactivation
        fake_supabase.subscriptions["device-idem"]["pack_size"] = 0
        # 2eme appel avec MEME receipt
        patch_apple(_make_apple_response(transaction_id="TX-IDEM-002"))
        r2 = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake"},
            headers={"X-Device-Id": "device-idem"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_processed"
        # Le pack_size n'a PAS ete reset (preuve qu'on n'a pas reactive)
        assert fake_supabase.subscriptions["device-idem"]["pack_size"] == 0

    def test_product_id_mismatch_rejected(self, client, fake_supabase, patch_apple):
        # Receipt dit pack_10, client annonce pack_50 -> tentative de fraude
        patch_apple(_make_apple_response(product_id="pack_10_ios"))
        r = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake", "product_id": "pack_50_ios"},
            headers={"X-Device-Id": "device-mismatch"},
        )
        assert r.status_code == 400
        assert "mismatch" in r.json()["detail"].lower() or \
               "product" in r.json()["detail"].lower()

    def test_invalid_apple_status_returns_4xx(
        self, client, fake_supabase, patch_apple
    ):
        patch_apple(_make_apple_response(status=21002))
        r = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake"},
            headers={"X-Device-Id": "device-invalid"},
        )
        assert r.status_code == 400

    def test_pack_50_activates_50_images(self, client, fake_supabase, patch_apple):
        patch_apple(_make_apple_response(
            product_id="pack_50_ios",
            transaction_id="TX-PACK50-003",
        ))
        r = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake"},
            headers={"X-Device-Id": "device-50"},
        )
        assert r.status_code == 200
        assert r.json()["pack_size"] == 50
        assert r.json()["plan"] == "pack_50_week"

    def test_pack_100_activates_100_images(self, client, fake_supabase, patch_apple):
        patch_apple(_make_apple_response(
            product_id="pack_100_ios",
            transaction_id="TX-PACK100-004",
        ))
        r = client.post(
            "/api/payments/apple/verify",
            json={"receipt_data": "fake"},
            headers={"X-Device-Id": "device-100"},
        )
        assert r.status_code == 200
        assert r.json()["pack_size"] == 100

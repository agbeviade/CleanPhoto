"""Tests securite : endpoint /api/payments/webhook.

Couvre :
  - Signature HMAC-SHA256 valide / invalide
  - Anti-replay timestamp (>5 min refuse)
  - Tampering du montant (refuse + status=suspicious)
  - Idempotency (deuxieme webhook ignore)
  - Reference inconnue (404, empeche la forge)
  - Headers manquants (signature/timestamp absents)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import pytest


WHSEC = os.environ["GENIUSPAY_WEBHOOK_SECRET"]


def _sign(payload: dict, ts: int | None = None) -> tuple[str, str, bytes]:
    """Calcule la signature HMAC pour un payload donne. Retourne (sig, ts, raw)."""
    if ts is None:
        ts = int(time.time())
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    msg = f"{ts}.{raw.decode('utf-8')}"
    sig = hmac.new(WHSEC.encode("utf-8"), msg.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return sig, str(ts), raw


def _payload(reference: str = "MTX-TEST-0000",
             amount: int = 2999,
             status: str = "completed") -> dict:
    return {
        "data": {
            "reference": reference,
            "amount": amount,
            "status": status,
            "metadata": {"plan": "pack_50_week", "device_id": "dev-test"},
        }
    }


def _seed_payment(fake_supabase, reference: str = "MTX-TEST-0000",
                  amount: int = 2999, plan: str = "pack_50_week"):
    """Insere un row payment 'pending' pour les tests d'idempotency / amount."""
    fake_supabase.payments[reference] = {
        "reference": reference, "amount": amount, "plan": plan,
        "device_id": "dev-test", "user_id": None,
        "status": "pending",
    }


class TestWebhookSignature:
    def test_valid_signature_activates_premium(
        self, client, fake_supabase, fake_geniuspay
    ):
        _seed_payment(fake_supabase)
        payload = _payload()
        sig, ts, raw = _sign(payload)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": sig,
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Event": "payment.success",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["premium_activated"] is True
        # Subscription creee avec le bon pack_size
        sub = fake_supabase.subscriptions["dev-test"]
        assert sub["pack_size"] == 50
        assert sub["plan"] == "pack_50_week"

    def test_invalid_signature_refused(
        self, client, fake_supabase, fake_geniuspay
    ):
        _seed_payment(fake_supabase)
        payload = _payload()
        _, ts, raw = _sign(payload)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": "deadbeef" * 8,  # mauvaise sig
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Event": "payment.success",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401
        # Aucune subscription creee
        assert "dev-test" not in fake_supabase.subscriptions

    def test_missing_signature_refused(self, client, fake_geniuspay):
        r = client.post(
            "/api/payments/webhook",
            json=_payload(),
            headers={"X-Webhook-Timestamp": str(int(time.time()))},
        )
        assert r.status_code == 401

    def test_missing_timestamp_refused(self, client, fake_geniuspay):
        payload = _payload()
        sig, _, raw = _sign(payload)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": sig,
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401


class TestAntiReplay:
    def test_old_timestamp_refused(
        self, client, fake_supabase, fake_geniuspay
    ):
        """Timestamp > 5 minutes dans le passe -> 401."""
        _seed_payment(fake_supabase)
        old_ts = int(time.time()) - 600  # 10 minutes
        payload = _payload()
        sig, ts, raw = _sign(payload, ts=old_ts)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": sig,
                "X-Webhook-Timestamp": ts,
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401

    def test_future_timestamp_refused(
        self, client, fake_supabase, fake_geniuspay
    ):
        """Timestamp > 5 minutes dans le futur -> 401."""
        _seed_payment(fake_supabase)
        future_ts = int(time.time()) + 600
        payload = _payload()
        sig, ts, raw = _sign(payload, ts=future_ts)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": sig,
                "X-Webhook-Timestamp": ts,
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401


class TestAmountTampering:
    def test_amount_mismatch_refused(
        self, client, fake_supabase, fake_geniuspay
    ):
        """Si webhook envoie amount=1 alors qu'on attendait 2999, refus + status suspicious."""
        _seed_payment(fake_supabase, amount=2999)
        # Webhook ment sur le montant
        payload = _payload(amount=1)
        sig, ts, raw = _sign(payload)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": sig,
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Event": "payment.success",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 400
        # Le payment est marque suspicious
        p = fake_supabase.payments["MTX-TEST-0000"]
        assert p["status"] == "suspicious"
        # Aucune subscription activee
        assert "dev-test" not in fake_supabase.subscriptions


class TestIdempotency:
    def test_double_webhook_ignored(
        self, client, fake_supabase, fake_geniuspay
    ):
        """Un 2eme webhook 'completed' pour la meme reference -> already_processed."""
        _seed_payment(fake_supabase)
        payload = _payload()
        sig, ts, raw = _sign(payload)
        headers = {
            "X-Webhook-Signature": sig,
            "X-Webhook-Timestamp": ts,
            "X-Webhook-Event": "payment.success",
            "Content-Type": "application/json",
        }
        # 1er appel : OK
        r1 = client.post("/api/payments/webhook", content=raw, headers=headers)
        assert r1.status_code == 200

        # On regen une signature avec un timestamp recent (sinon anti-replay)
        sig2, ts2, raw2 = _sign(payload)
        headers2 = {**headers, "X-Webhook-Signature": sig2,
                    "X-Webhook-Timestamp": ts2}
        # 2eme appel : already_processed (pas de re-activation)
        r2 = client.post("/api/payments/webhook", content=raw2, headers=headers2)
        assert r2.status_code == 200
        assert r2.json()["status"] == "already_processed"


class TestUnknownReference:
    def test_unknown_reference_refused(self, client, fake_supabase, fake_geniuspay):
        """Webhook avec reference inconnue -> 404 (empeche la forge)."""
        # Pas de _seed_payment ici
        payload = _payload(reference="MTX-FORGED-9999")
        sig, ts, raw = _sign(payload)
        r = client.post(
            "/api/payments/webhook",
            content=raw,
            headers={
                "X-Webhook-Signature": sig,
                "X-Webhook-Timestamp": ts,
                "X-Webhook-Event": "payment.success",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 404

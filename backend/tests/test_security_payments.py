"""Tests securite : endpoint /api/payments/create + /api/plans.

Couvre :
  - Validation du plan contre le catalogue
  - Montant cote serveur = montant catalogue (pas confiance au client)
  - Header device_id ou user_id requis
  - /api/plans expose le catalogue
"""
from __future__ import annotations

import pytest


class TestPlansEndpoint:
    def test_plans_returns_catalog(self, client):
        r = client.get("/api/plans")
        assert r.status_code == 200
        body = r.json()
        assert body["currency"] == "XOF"
        plans = body["plans"]
        assert "pack_10_week" in plans
        assert "pack_50_week" in plans
        assert "pack_100_week" in plans
        # Validation des champs cles
        for pid, p in plans.items():
            assert "images" in p and isinstance(p["images"], int)
            assert "price" in p and isinstance(p["price"], int)
            assert "days" in p and isinstance(p["days"], int)
            assert p["images"] > 0
            assert p["price"] > 0
            assert p["days"] > 0

    def test_default_pricing_matches_spec(self, client):
        """Les prix doivent matcher la specification utilisateur."""
        r = client.get("/api/plans")
        plans = r.json()["plans"]
        assert plans["pack_10_week"]["price"] == 1499
        assert plans["pack_10_week"]["images"] == 10
        assert plans["pack_50_week"]["price"] == 2999
        assert plans["pack_50_week"]["images"] == 50
        assert plans["pack_100_week"]["price"] == 4999
        assert plans["pack_100_week"]["images"] == 100


class TestPaymentCreateValidation:
    def test_invalid_plan_rejected(
        self, client, fake_supabase, fake_geniuspay
    ):
        r = client.post(
            "/api/payments/create",
            json={"plan": "pack_999_year"},  # n'existe pas
            headers={"X-Device-Id": "dev-pay-001"},
        )
        assert r.status_code == 400
        assert "plan invalide" in r.json()["detail"].lower()

    def test_missing_plan_rejected(
        self, client, fake_supabase, fake_geniuspay
    ):
        r = client.post(
            "/api/payments/create",
            json={},
            headers={"X-Device-Id": "dev-pay-001"},
        )
        assert r.status_code == 400

    def test_no_identifier_rejected(
        self, client, fake_supabase, fake_geniuspay
    ):
        """Sans X-Device-Id ni Authorization, refus."""
        r = client.post(
            "/api/payments/create",
            json={"plan": "pack_10_week"},
        )
        assert r.status_code == 400

    def test_valid_plan_creates_payment_with_catalog_amount(
        self, client, fake_supabase, fake_geniuspay
    ):
        """Le montant retourne DOIT etre celui du catalogue, pas un input client."""
        r = client.post(
            "/api/payments/create",
            json={"plan": "pack_50_week", "amount": 1},  # tentative tampering
            headers={"X-Device-Id": "dev-pay-001"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Le montant DOIT etre 2999 (catalogue), PAS 1
        assert body["amount"] == 2999
        assert body["plan"] == "pack_50_week"
        assert body["pack_size"] == 50
        assert body["expires_in_days"] == 7
        assert body["reference"].startswith("MTX-TEST-")
        assert body["checkout_url"].startswith("https://pay.test/")

    def test_payment_persisted_with_correct_amount(
        self, client, fake_supabase, fake_geniuspay
    ):
        r = client.post(
            "/api/payments/create",
            json={"plan": "pack_100_week"},
            headers={"X-Device-Id": "dev-pay-002"},
        )
        assert r.status_code == 200
        ref = r.json()["reference"]
        stored = fake_supabase.payments[ref]
        assert stored["amount"] == 4999
        assert stored["plan"] == "pack_100_week"
        assert stored["status"] == "pending"
        assert stored["device_id"] == "dev-pay-002"

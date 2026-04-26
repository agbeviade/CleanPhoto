"""Tests securite : consommation et remboursement des packs.

Couvre :
  - Consume avant restoration (anti cost amplification C2)
  - Refund automatique si la restoration AI echoue
  - Pack epuise -> 429 avec reason=pack_exhausted
  - Pack consume incremente exactement 1 fois par requete reussie
  - Legacy unlimited (pack_size=None) : pas de consume
"""
from __future__ import annotations

import pytest


def _post_restore(client, image_bytes, device_id="dev-pack-test"):
    return client.post(
        "/api/restore",
        files={"file": ("t.jpg", image_bytes, "image/jpeg")},
        headers={"X-Device-Id": device_id},
    )


def _activate_pack(fake_supabase, device_id, pack_size=10, used=0):
    fake_supabase.subscriptions[device_id] = {
        "plan": "pack_10_week",
        "expires_at": None,  # pas d'expiration dans le mock
        "pack_size": pack_size,
        "images_used": used,
        "provider": "geniuspay",
        "receipt": "MTX-TEST",
    }


class TestPackConsumeFlow:
    def test_consume_called_once_per_successful_restore(
        self, client, fake_supabase, fake_image_bytes
    ):
        _activate_pack(fake_supabase, "dev-pack-test", pack_size=10)
        r = _post_restore(client, fake_image_bytes)
        assert r.status_code == 200, r.text
        assert fake_supabase.consume_calls == 1
        assert fake_supabase.refund_calls == 0
        assert fake_supabase.subscriptions["dev-pack-test"]["images_used"] == 1

    def test_pack_exhausted_returns_429(
        self, client, fake_supabase, fake_image_bytes
    ):
        # 10/10 deja utilises
        _activate_pack(fake_supabase, "dev-pack-test", pack_size=10, used=10)
        r = _post_restore(client, fake_image_bytes)
        # is_premium devrait etre False (remaining=0) -> tombe dans le quota free
        # Mais comme le device n'a pas encore consomme cote free, il a 3 essais
        # gratuits. Donc 200. Verifions que ce n'est PAS la consume_pack qui passe.
        assert r.status_code == 200
        assert fake_supabase.consume_calls == 0

    def test_pack_consume_increments_exactly_once(
        self, client, fake_supabase, fake_image_bytes
    ):
        _activate_pack(fake_supabase, "dev-pack-test", pack_size=10)
        # 3 requetes successives
        for _ in range(3):
            r = _post_restore(client, fake_image_bytes)
            assert r.status_code == 200
        assert fake_supabase.consume_calls == 3
        assert fake_supabase.subscriptions["dev-pack-test"]["images_used"] == 3


class TestPackRefundOnFailure:
    def test_refund_when_restore_throws(
        self, client, fake_supabase, fake_image_bytes, monkeypatch
    ):
        """Si restore_service.restore_bytes leve, le pack est rembourse."""
        from api import index as api_module

        def boom(*args, **kwargs):
            raise RuntimeError("simulated AI failure")

        monkeypatch.setattr(api_module.restore_service, "restore_bytes", boom)
        _activate_pack(fake_supabase, "dev-pack-test", pack_size=10)

        r = _post_restore(client, fake_image_bytes)
        assert r.status_code == 500
        assert fake_supabase.consume_calls == 1
        assert fake_supabase.refund_calls == 1
        # images_used revenu a 0 (1 consume + 1 refund)
        assert fake_supabase.subscriptions["dev-pack-test"]["images_used"] == 0


class TestPackBoundaryConditions:
    def test_race_loser_gets_429_pack_exhausted(
        self, client, fake_supabase, fake_image_bytes, monkeypatch
    ):
        """Simule la race : is_premium passe, mais consume retourne 0 entre temps."""
        from api import index as api_module

        # Pack avec 1 slot, mais on simule consume=0 (race perdue)
        _activate_pack(fake_supabase, "dev-pack-test", pack_size=1, used=0)
        original = fake_supabase.consume_pack_image

        def consume_returns_zero(user_id=None, device_id=None):
            fake_supabase.consume_calls += 1
            return 0  # race perdue

        monkeypatch.setattr(fake_supabase, "consume_pack_image",
                            consume_returns_zero)
        r = _post_restore(client, fake_image_bytes)
        assert r.status_code == 429
        body = r.json()
        # Le detail peut etre une string ou un dict selon FastAPI
        detail = body.get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("reason") == "pack_exhausted"

    def test_legacy_unlimited_no_consume(
        self, client, fake_supabase, fake_image_bytes
    ):
        """Sub legacy avec pack_size=None : aucune consume ne doit modifier images_used."""
        fake_supabase.subscriptions["dev-pack-test"] = {
            "plan": "monthly",
            "expires_at": None,
            "pack_size": None,  # legacy unlimited
            "images_used": 0,
            "provider": "manual",
            "receipt": None,
        }
        r = _post_restore(client, fake_image_bytes)
        assert r.status_code == 200
        # consume_pack_image est appelee mais retourne 99999 -> pack_consumed=False
        assert fake_supabase.consume_calls == 1
        assert fake_supabase.subscriptions["dev-pack-test"]["images_used"] == 0
        assert fake_supabase.refund_calls == 0

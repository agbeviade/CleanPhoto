"""Tests : endpoint /api/admin/stats (auth + structure).

Couvre :
  - Auth via X-Admin-Token (constant-time)
  - Refus si token absent / faux
  - Refus si ADMIN_TOKEN cote serveur < 16 chars (= non configure)
  - Structure du JSON retourne
"""
from __future__ import annotations

import os
import pytest


ADMIN_TOKEN = "test_admin_token_at_least_32_chars_long_xxxx"


@pytest.fixture(autouse=True)
def _set_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)


class TestAdminAuth:
    def test_no_token_returns_401(self, client, fake_supabase):
        r = client.get("/api/admin/stats")
        assert r.status_code == 401

    def test_wrong_token_returns_401(self, client, fake_supabase):
        r = client.get(
            "/api/admin/stats",
            headers={"X-Admin-Token": "wrong_token_value"},
        )
        assert r.status_code == 401

    def test_valid_token_returns_stats(self, client, fake_supabase):
        # Le mock fake_supabase n'a pas la methode admin_stats. Patch-la.
        fake_supabase.admin_stats = lambda: {
            "today": {"revenue_xof": 0, "restorations": 0},
            "subscriptions": {"active": 0, "by_plan": {}},
            "all_time": {"total_revenue_xof": 0},
        }
        r = client.get(
            "/api/admin/stats",
            headers={"X-Admin-Token": ADMIN_TOKEN},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "today" in body
        assert "subscriptions" in body
        assert "runtime" in body
        assert body["runtime"]["catalog"]["pack_50_week"]["price"] == 2999

    def test_short_admin_token_refuses_all(self, client, fake_supabase, monkeypatch):
        """Si ADMIN_TOKEN < 16 chars, /api/admin/* est INACCESSIBLE meme avec match."""
        monkeypatch.setenv("ADMIN_TOKEN", "tooshort")
        r = client.get(
            "/api/admin/stats",
            headers={"X-Admin-Token": "tooshort"},
        )
        assert r.status_code == 401


class TestNotifierDedupe:
    def test_dedupe_window(self, monkeypatch):
        """Le notifier ne doit pas spammer 2 fois le meme event en < 60s."""
        from api._services.notifier import CriticalNotifier
        sent = []

        # Mock requests.post pour capturer les envois
        def fake_post(url, json=None, timeout=None):
            sent.append(json)
            class FakeResp:
                status_code = 204
            return FakeResp()

        import api._services.notifier as notifier_mod
        monkeypatch.setattr(notifier_mod.requests, "post", fake_post)

        n = CriticalNotifier(webhook_url="https://discord.test/webhook")
        ok1 = n.alert("Same event", "msg", level="warning")
        ok2 = n.alert("Same event", "msg", level="warning")
        assert ok1 is True
        assert ok2 is False  # dedup hit
        assert len(sent) == 1

    def test_dedupe_disabled_explicitly(self, monkeypatch):
        from api._services.notifier import CriticalNotifier
        sent = []

        def fake_post(url, json=None, timeout=None):
            sent.append(json)
            class FakeResp:
                status_code = 204
            return FakeResp()

        import api._services.notifier as notifier_mod
        monkeypatch.setattr(notifier_mod.requests, "post", fake_post)

        n = CriticalNotifier(webhook_url="https://discord.test/webhook")
        n.alert("Fraude", "x", level="critical", dedupe=False)
        n.alert("Fraude", "x", level="critical", dedupe=False)
        assert len(sent) == 2  # pas de dedupe

    def test_no_url_means_no_send(self):
        from api._services.notifier import CriticalNotifier
        n = CriticalNotifier(webhook_url="")
        ok = n.alert("Test", "should not send")
        assert ok is False
        assert n.is_configured is False

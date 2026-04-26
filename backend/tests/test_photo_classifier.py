"""Tests pour PhotoClassifier + integration prompt adapte.

Couvre :
  - Mock OpenAI Vision response -> mapping correct vers categorie
  - Cache MD5 (2eme appel ne refait PAS de HTTP)
  - Fallback "unknown" silencieux sur erreur HTTP / JSON / network
  - Categorie inconnue retournee par l'API -> fallback "unknown"
  - classify_and_select_prompt : user_prompt -> bypass classifier
  - classify_and_select_prompt : classifier off -> prompt=None (default provider)
  - Headers X-Detected-Category / detected_category dans /api/restore
"""
from __future__ import annotations

import json
import pytest


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------
def _mock_openai_response(category: str, confidence: float = 0.95,
                          is_grayscale: bool = False,
                          has_visible_damage: bool = False):
    """Construit une fake reponse OpenAI chat completion."""
    content = json.dumps({
        "category": category,
        "confidence": confidence,
        "is_grayscale": is_grayscale,
        "has_visible_damage": has_visible_damage,
    })
    return {
        "choices": [{"message": {"content": content}}],
    }


@pytest.fixture()
def patch_openai(monkeypatch):
    """Patch requests.post utilise par PhotoClassifier."""
    calls = {"count": 0, "last_payload": None}

    def make_post(response_body):
        def fake_post(url, headers=None, json=None, timeout=None):
            calls["count"] += 1
            calls["last_payload"] = json

            class FakeResp:
                status_code = 200
                def json(self):
                    return response_body
            return FakeResp()
        return fake_post

    def patcher(category="face_portrait", **kwargs):
        body = _mock_openai_response(category, **kwargs)
        import api._services.photo_classifier as mod
        monkeypatch.setattr(mod.requests, "post", make_post(body))
        return calls

    return patcher


# -----------------------------------------------------------------------
# Tests unitaires PhotoClassifier
# -----------------------------------------------------------------------
class TestPhotoClassifier:
    def test_not_configured_returns_unknown(self, fake_image_bytes):
        from api._services.photo_classifier import PhotoClassifier
        c = PhotoClassifier(api_key="", enabled=True)
        result = c.classify(fake_image_bytes)
        assert result["category"] == "unknown"
        assert result["skipped"] == "not_configured"

    def test_disabled_returns_unknown(self, fake_image_bytes):
        from api._services.photo_classifier import PhotoClassifier
        c = PhotoClassifier(api_key="sk-test", enabled=False)
        result = c.classify(fake_image_bytes)
        assert result["category"] == "unknown"
        assert result["skipped"] == "not_configured"

    def test_face_portrait_classification(self, fake_image_bytes, patch_openai):
        patch_openai(category="face_portrait", confidence=0.92)
        from api._services.photo_classifier import PhotoClassifier
        c = PhotoClassifier(api_key="sk-test")
        result = c.classify(fake_image_bytes)
        assert result["category"] == "face_portrait"
        assert result["confidence"] == 0.92
        assert result["cached"] is False

    def test_cache_hits_second_call(self, fake_image_bytes, patch_openai):
        calls = patch_openai(category="landscape")
        from api._services.photo_classifier import PhotoClassifier
        c = PhotoClassifier(api_key="sk-test")
        r1 = c.classify(fake_image_bytes)
        r2 = c.classify(fake_image_bytes)
        assert r1["category"] == "landscape"
        assert r2["category"] == "landscape"
        assert r2["cached"] is True
        assert calls["count"] == 1  # 1 seul appel HTTP

    def test_invalid_category_falls_back_to_unknown(
        self, fake_image_bytes, patch_openai
    ):
        patch_openai(category="random_invalid_xyz")
        from api._services.photo_classifier import PhotoClassifier
        c = PhotoClassifier(api_key="sk-test")
        result = c.classify(fake_image_bytes)
        assert result["category"] == "unknown"

    def test_http_error_falls_back_to_unknown(
        self, fake_image_bytes, monkeypatch
    ):
        import api._services.photo_classifier as mod

        def fake_post_500(url, **kwargs):
            class FakeResp:
                status_code = 500
                text = "Server error"
                def json(self):
                    return {}
            return FakeResp()

        monkeypatch.setattr(mod.requests, "post", fake_post_500)
        c = mod.PhotoClassifier(api_key="sk-test")
        result = c.classify(fake_image_bytes)
        assert result["category"] == "unknown"
        assert "http_500" in result.get("error", "")

    def test_network_exception_falls_back_to_unknown(
        self, fake_image_bytes, monkeypatch
    ):
        import api._services.photo_classifier as mod

        def fake_post_raises(url, **kwargs):
            raise Exception("connection timeout")

        monkeypatch.setattr(mod.requests, "post", fake_post_raises)
        c = mod.PhotoClassifier(api_key="sk-test")
        result = c.classify(fake_image_bytes)
        assert result["category"] == "unknown"
        assert "connection timeout" in result.get("error", "")

    def test_uses_low_detail_and_resized_image(
        self, fake_image_bytes, patch_openai
    ):
        calls = patch_openai(category="document")
        from api._services.photo_classifier import PhotoClassifier
        c = PhotoClassifier(api_key="sk-test")
        c.classify(fake_image_bytes)
        # Le payload envoye doit contenir detail=low (cost optim)
        payload = calls["last_payload"]
        msg_content = payload["messages"][0]["content"]
        image_part = next(p for p in msg_content if p["type"] == "image_url")
        assert image_part["image_url"]["detail"] == "low"
        # Et response_format JSON
        assert payload["response_format"]["type"] == "json_object"


# -----------------------------------------------------------------------
# Tests integration RestoreService.classify_and_select_prompt
# -----------------------------------------------------------------------
class TestClassifyAndSelectPrompt:
    def test_user_prompt_bypasses_classifier(self, fake_image_bytes):
        from api._services.restore_service import RestoreService
        rs = RestoreService()
        result = rs.classify_and_select_prompt(
            fake_image_bytes, user_prompt="My custom prompt"
        )
        assert result["prompt"] == "My custom prompt"
        assert result["category"] == "user_override"

    def test_classifier_disabled_returns_none_prompt(
        self, fake_image_bytes, monkeypatch
    ):
        from api._services.restore_service import RestoreService
        rs = RestoreService()
        # Force classifier off
        rs._classifier.api_key = ""
        result = rs.classify_and_select_prompt(fake_image_bytes)
        assert result["prompt"] is None  # provider utilise son DEFAULT_PROMPT
        assert result["category"] == "unknown"
        assert result["label"] == "Photo generique"

    def test_face_portrait_maps_to_specialized_prompt(
        self, fake_image_bytes, patch_openai
    ):
        patch_openai(category="face_portrait")
        from api._services.restore_service import RestoreService
        rs = RestoreService()
        rs._classifier.api_key = "sk-test"  # force enabled
        rs._classifier.enabled = True
        result = rs.classify_and_select_prompt(fake_image_bytes)
        assert result["category"] == "face_portrait"
        assert result["label"] == "Portrait individuel"
        assert result["prompt"] is not None
        # Le prompt portrait doit contenir "identity" (preservation cle)
        assert "identity" in result["prompt"].lower()

    def test_face_group_emphasizes_each_person(
        self, fake_image_bytes, patch_openai
    ):
        patch_openai(category="face_group")
        from api._services.restore_service import RestoreService
        rs = RestoreService()
        rs._classifier.api_key = "sk-test"
        rs._classifier.enabled = True
        result = rs.classify_and_select_prompt(fake_image_bytes)
        assert result["category"] == "face_group"
        # Le prompt groupe doit insister sur "each" et "do not merge"
        assert "each" in result["prompt"].lower()
        assert "merge" in result["prompt"].lower()

    def test_document_preserves_text(self, fake_image_bytes, patch_openai):
        patch_openai(category="document")
        from api._services.restore_service import RestoreService
        rs = RestoreService()
        rs._classifier.api_key = "sk-test"
        rs._classifier.enabled = True
        result = rs.classify_and_select_prompt(fake_image_bytes)
        assert result["category"] == "document"
        # Le prompt doc doit interdire d'inventer du texte
        assert "do not invent" in result["prompt"].lower() or \
               "preserve text" in result["prompt"].lower()


# -----------------------------------------------------------------------
# Tests integration /api/restore : headers + JSON exposes
# -----------------------------------------------------------------------
class TestRestoreEndpointExposesCategory:
    def test_response_contains_detected_category_header(
        self, client, fake_image_bytes
    ):
        """Sans OpenAI configure, la categorie est 'unknown' mais le header
        est present (verification que le mecanisme fonctionne)."""
        r = client.post(
            "/api/restore",
            files={"file": ("t.jpg", fake_image_bytes, "image/jpeg")},
            headers={"X-Device-Id": "test-cat-header"},
        )
        assert r.status_code == 200
        # Mode binary fallback (pas de Supabase) -> headers
        assert "x-detected-category" in {k.lower() for k in r.headers.keys()}
        assert r.headers["x-detected-category"] in {
            "unknown", "face_portrait", "face_group",
            "landscape", "document", "object",
        }

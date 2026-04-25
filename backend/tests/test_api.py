"""Tests d'integration de l'API.

Run: pytest -q
"""
import io
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from api.index import app  # noqa: E402

client = TestClient(app)


def _fake_jpeg_bytes(w: int = 320, h: int = 240) -> bytes:
    arr = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "pipeline" in body
    assert body["pipeline"]["mode"] in {"lite", "basic", "advanced"}


def test_restore_no_supabase_returns_binary():
    """Sans Supabase configure, /api/restore renvoie le binaire JPEG."""
    data = _fake_jpeg_bytes()
    r = client.post(
        "/api/restore",
        files={"file": ("test.jpg", data, "image/jpeg")},
        headers={"X-Device-Id": "test-no-supabase"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/jpeg")
    assert "x-processing-ms" in r.headers
    assert "x-pipeline-mode" in r.headers
    assert len(r.content) > 100


def test_restore_binary_endpoint():
    data = _fake_jpeg_bytes()
    r = client.post(
        "/api/restore-binary",
        files={"file": ("test.jpg", data, "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")


def test_invalid_format():
    r = client.post(
        "/api/restore",
        files={"file": ("test.gif", b"GIF89a", "image/gif")},
        headers={"X-Device-Id": "test-invalid"},
    )
    assert r.status_code == 400


def test_empty_file():
    r = client.post(
        "/api/restore",
        files={"file": ("test.jpg", b"", "image/jpeg")},
        headers={"X-Device-Id": "test-empty"},
    )
    assert r.status_code == 400


def test_restore_without_device_id_blocked():
    """Sans X-Device-Id, le quota retourne 429 (anti-abus)."""
    data = _fake_jpeg_bytes()
    r = client.post(
        "/api/restore",
        files={"file": ("t.jpg", data, "image/jpeg")},
    )
    assert r.status_code == 429


def test_legacy_routes_compat():
    """Les routes sans /api doivent fonctionner (mode local)."""
    r = client.get("/health")
    assert r.status_code == 200


def test_replicate_provider_not_configured():
    """Sans token, le provider doit etre detecte comme non configure."""
    import os
    from api._services.replicate_provider import ReplicateProvider
    old = os.environ.pop("REPLICATE_API_TOKEN", None)
    try:
        p = ReplicateProvider.from_env()
        assert not p.is_configured
    finally:
        if old:
            os.environ["REPLICATE_API_TOKEN"] = old


def test_quota_endpoint():
    """L'endpoint /api/quota retourne les infos quota."""
    r = client.get("/api/quota", headers={"X-Device-Id": "test-device-001"})
    assert r.status_code == 200
    body = r.json()
    assert "allowed" in body
    assert "remaining" in body
    assert body["limit"] == 3


def test_quota_enforcement():
    """Apres N appels reussis (N=DAILY_FREE_LIMIT), le suivant doit etre 429."""
    import os
    os.environ.pop("REPLICATE_API_TOKEN", None)  # forcer LITE local
    headers = {"X-Device-Id": "test-quota-enforce"}
    data = _fake_jpeg_bytes()
    # 3 appels OK
    for i in range(3):
        r = client.post(
            "/api/restore",
            files={"file": ("t.jpg", data, "image/jpeg")},
            headers=headers,
        )
        assert r.status_code == 200, f"call {i}: {r.status_code} {r.text[:200]}"
    # 4eme bloque
    r = client.post(
        "/api/restore",
        files={"file": ("t.jpg", data, "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 429


def test_premium_bypasses_quota():
    """Un device premium n'est jamais bloque par le quota."""
    headers = {"X-Device-Id": "test-premium", "X-Premium": "1"}
    data = _fake_jpeg_bytes()
    for _ in range(5):
        r = client.post(
            "/api/restore",
            files={"file": ("t.jpg", data, "image/jpeg")},
            headers=headers,
        )
        assert r.status_code == 200


def test_watermark_added_for_free():
    """Une reponse free doit contenir un X-Premium=0."""
    headers = {"X-Device-Id": "test-wm-free"}
    data = _fake_jpeg_bytes()
    r = client.post(
        "/api/restore",
        files={"file": ("t.jpg", data, "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.headers.get("x-premium") == "0"


def test_me_requires_auth():
    """Sans Authorization header, /api/me renvoie 401."""
    r = client.get("/api/me")
    assert r.status_code == 401


def test_history_requires_auth():
    """Sans Authorization header, /api/history renvoie 401."""
    r = client.get("/api/history")
    assert r.status_code == 401


def test_restore_with_settings():
    """fidelity et upscale sont accept\u00e9s en form fields."""
    data = _fake_jpeg_bytes()
    r = client.post(
        "/api/restore",
        files={"file": ("t.jpg", data, "image/jpeg")},
        data={"fidelity": "0.5", "upscale": "2"},
        headers={"X-Device-Id": "test-settings"},
    )
    assert r.status_code == 200


def test_replicate_provider_configured():
    """Avec token, le provider doit etre detecte comme configure."""
    import os
    from api._services.replicate_provider import ReplicateProvider
    os.environ["REPLICATE_API_TOKEN"] = "r8_test_fake"
    try:
        p = ReplicateProvider.from_env()
        assert p.is_configured
        assert p.fidelity == 0.7
    finally:
        del os.environ["REPLICATE_API_TOKEN"]

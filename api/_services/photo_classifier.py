"""Classification automatique du type de photo via OpenAI gpt-4o-mini Vision.

Strategie cout :
  - Resize 512x512 + JPEG q70 -> ~50KB envoyes
  - detail=low -> tokens vision reduits (~85 tokens fixes)
  - Cache MD5 du fichier -> 0 appel pour les retries / re-essais
  - Fallback "unknown" silencieux en cas d'erreur (jamais bloquant)

Cout estime : ~$0.0001 / classification avec gpt-4o-mini en low detail.
Pour 1000 restaurations/mois : ~$0.10/mois.

Categories :
  face_portrait : 1 visage dominant (50%+ du cadre)
  face_group    : 2+ personnes / visages
  landscape     : scene exterieure, nature, ville, sans personne dominante
  document      : papier, ID, certificat, lettre, texte
  object        : animal, fleur, food, objet (sans personne)
  unknown       : ambigu ou erreur (-> prompt par defaut)
"""
from __future__ import annotations

import os
import io
import json
import base64
import hashlib
import logging
import threading
from typing import Optional

import requests

log = logging.getLogger("souvenir.classifier")

VALID_CATEGORIES = {
    "face_portrait", "face_group", "landscape",
    "document", "object", "unknown",
}

CLASSIFY_SYSTEM_PROMPT = (
    "You are a photo categorization expert. Classify images into ONE category. "
    "Respond ONLY with a JSON object, no markdown, no explanation.\n\n"
    "Categories:\n"
    "- 'face_portrait': single dominant person/face (50%+ of frame)\n"
    "- 'face_group': multiple people/faces (2+ visible)\n"
    "- 'landscape': outdoor scene, nature, city, no dominant person\n"
    "- 'document': document, ID card, paper, certificate, text-heavy\n"
    "- 'object': animal, flower, food, object (no person)\n"
    "- 'unknown': ambiguous or low quality\n\n"
    'Respond ONLY with: {"category":"...", "confidence":0.0-1.0, '
    '"is_grayscale":true/false, "has_visible_damage":true/false}'
)

CACHE_MAX_ENTRIES = 500


class PhotoClassifier:
    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4o-mini",
        enabled: bool = True,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.enabled = enabled
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "PhotoClassifier":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("CLASSIFIER_MODEL", "gpt-4o-mini"),
            enabled=os.getenv("CLASSIFIER_ENABLED", "1") == "1",
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and self.enabled

    def _resize_for_vision(self, src_bytes: bytes) -> str:
        """Resize 512x512 + JPEG q70 + base64. Reduit le cout vision drastiquement."""
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(src_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((512, 512))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def classify(self, src_bytes: bytes, timeout: int = 8) -> dict:
        """Classifie l'image. Toujours non-bloquant.

        Returns:
            {
              "category": "face_portrait" | ... | "unknown",
              "confidence": 0.0-1.0,
              "is_grayscale": bool,
              "has_visible_damage": bool,
              "cached": bool,
              "skipped": str | None,
              "error": str | None,
            }
        """
        result_default = {
            "category": "unknown",
            "confidence": 0.0,
            "is_grayscale": False,
            "has_visible_damage": False,
            "cached": False,
        }
        if not self.is_configured:
            return {**result_default, "skipped": "not_configured"}

        # Cache par hash content
        key = hashlib.md5(src_bytes).hexdigest()
        with self._lock:
            cached = self._cache.get(key)
            if cached:
                return {**cached, "cached": True}

        try:
            small_b64 = self._resize_for_vision(src_bytes)
        except Exception as exc:
            log.warning("classifier resize failed: %s", exc)
            return {**result_default, "error": f"resize: {exc}"}

        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": CLASSIFY_SYSTEM_PROMPT},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/jpeg;base64,{small_b64}",
                                "detail": "low",
                            }},
                        ],
                    }],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 100,
                    "temperature": 0,
                },
                timeout=timeout,
            )
            if r.status_code >= 400:
                log.warning("classifier HTTP %d: %s", r.status_code, r.text[:200])
                return {**result_default, "error": f"http_{r.status_code}"}

            body = r.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            cat = str(parsed.get("category", "unknown")).lower()
            if cat not in VALID_CATEGORIES:
                cat = "unknown"
            try:
                conf = float(parsed.get("confidence", 0.5))
            except (ValueError, TypeError):
                conf = 0.5
            result = {
                "category": cat,
                "confidence": max(0.0, min(1.0, conf)),
                "is_grayscale": bool(parsed.get("is_grayscale", False)),
                "has_visible_damage": bool(parsed.get("has_visible_damage", False)),
                "cached": False,
            }
            # Cap le cache
            with self._lock:
                if len(self._cache) >= CACHE_MAX_ENTRIES:
                    # Drop arbitrarily (FIFO via dict order Python 3.7+)
                    first_key = next(iter(self._cache))
                    self._cache.pop(first_key, None)
                self._cache[key] = result
            log.info(
                "classify: %s (conf=%.2f, gray=%s, damaged=%s)",
                cat, result["confidence"],
                result["is_grayscale"], result["has_visible_damage"],
            )
            return result
        except Exception as exc:
            log.warning("classify failed: %s", exc)
            return {**result_default, "error": str(exc)[:100]}

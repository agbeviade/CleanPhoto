"""Provider OpenAI gpt-image-1 pour restauration via prompt.

Endpoint: POST https://api.openai.com/v1/images/edits
Modele: gpt-image-1 (sortie 2025, supporte image en entree + prompt)

Variables d'env:
  - OPENAI_API_KEY        (sk-... requise)
  - OPENAI_IMAGE_MODEL    (default: gpt-image-1)
  - OPENAI_IMAGE_QUALITY  (low | medium | high, default: medium)
  - OPENAI_IMAGE_SIZE     (1024x1024 | 1024x1536 | 1536x1024 | auto, default: auto)
  - OPENAI_RESTORE_PROMPT (prompt par defaut pour restauration)

Cout indicatif (per image):
  - low quality:    ~$0.011 - $0.017
  - medium quality: ~$0.042 - $0.063
  - high quality:   ~$0.167 - $0.252
"""
from __future__ import annotations

import io
import os
import base64
import logging
from typing import Optional

import requests

log = logging.getLogger("souvenir.openai")

DEFAULT_MODEL = "gpt-image-1"
DEFAULT_PROMPT = (
    "Restore this photograph with high fidelity: enhance facial details, "
    "remove scratches and noise, sharpen blurred areas, balance colors, "
    "improve lighting. Keep the exact same person, pose, and composition. "
    "Studio-quality 4K result, photorealistic."
)


class OpenAIProvider:
    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        quality: str = "medium",
        size: str = "auto",
        prompt: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.quality = quality
        self.size = size
        self.prompt = prompt or DEFAULT_PROMPT

    @classmethod
    def from_env(cls) -> "OpenAIProvider":
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_IMAGE_MODEL", DEFAULT_MODEL),
            quality=os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
            size=os.getenv("OPENAI_IMAGE_SIZE", "auto"),
            prompt=os.getenv("OPENAI_RESTORE_PROMPT") or None,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def restore_bytes(
        self,
        src_bytes: bytes,
        timeout: int = 60,
        prompt: Optional[str] = None,
        quality: Optional[str] = None,
    ) -> bytes:
        """Envoie l'image a OpenAI /v1/images/edits avec un prompt de restauration."""
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY absent")

        used_prompt = (prompt or self.prompt).strip()
        used_quality = quality or self.quality

        headers = {"Authorization": f"Bearer {self.api_key}"}
        # multipart/form-data : 'image' = fichier source, 'prompt' = consigne
        files = {
            "image": ("photo.png", src_bytes, "image/png"),
        }
        data = {
            "model": self.model,
            "prompt": used_prompt,
            "n": "1",
            "size": self.size,
            "quality": used_quality,
        }

        log.info(
            "OpenAI: POST /v1/images/edits (model=%s, quality=%s, size=%s)",
            self.model, used_quality, self.size,
        )
        r = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers=headers,
            files=files,
            data=data,
            timeout=timeout,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI API error {r.status_code}: {r.text[:300]}")

        body = r.json()
        items = body.get("data", [])
        if not items:
            raise RuntimeError("OpenAI: reponse vide")

        first = items[0]
        # gpt-image-1 retourne du base64 par defaut
        b64 = first.get("b64_json")
        if b64:
            return base64.b64decode(b64)

        # Fallback: certains modeles retournent une URL
        url = first.get("url")
        if url:
            log.info("OpenAI: download via URL")
            img = requests.get(url, timeout=30)
            img.raise_for_status()
            return img.content

        raise RuntimeError("OpenAI: aucun b64_json ni url dans la reponse")

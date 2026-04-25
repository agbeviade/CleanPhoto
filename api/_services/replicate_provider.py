"""Provider Replicate pour la restauration GPU serverless.

Modele: sczhou/codeformer - combine restauration visages (CodeFormer)
+ upscale background (Real-ESRGAN) en un seul appel.

Configure via variables d'env:
  - REPLICATE_API_TOKEN  (cle r_xxx, https://replicate.com/account/api-tokens)
  - REPLICATE_MODEL      (default: sczhou/codeformer)
  - REPLICATE_FIDELITY   (default: 0.7, 0.0=plus restaure, 1.0=plus fidele)
  - REPLICATE_UPSCALE    (default: 2)

Cout indicatif: ~$0.005-$0.01 par image, ~5-10s sur GPU T4.
"""
from __future__ import annotations

import os
import io
import base64
import logging
from typing import Optional

import requests

log = logging.getLogger("souvenir.replicate")

DEFAULT_MODEL = "sczhou/codeformer"
DEFAULT_VERSION = (
    # Pinne explicitement la version pour stabilite. Mettre a jour ponctuellement.
    "7de2ea26c616d5bf2245ad0d5e24f0ff9a6204578a5c876db53142edd9d2cd56"
)


class ReplicateProvider:
    def __init__(self, token: str = "", model: str = DEFAULT_MODEL,
                 version: str = DEFAULT_VERSION) -> None:
        self.token = token
        self.model = model
        self.version = version
        self.fidelity = float(os.getenv("REPLICATE_FIDELITY", "0.7"))
        self.upscale = int(os.getenv("REPLICATE_UPSCALE", "2"))

    @classmethod
    def from_env(cls) -> "ReplicateProvider":
        return cls(
            token=os.getenv("REPLICATE_API_TOKEN", ""),
            model=os.getenv("REPLICATE_MODEL", DEFAULT_MODEL),
            version=os.getenv("REPLICATE_VERSION", DEFAULT_VERSION),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def restore_bytes(self, src_bytes: bytes, timeout: int = 60) -> bytes:
        """Envoie l'image a Replicate, attend le resultat, telecharge le binaire."""
        if not self.token:
            raise RuntimeError("REPLICATE_API_TOKEN absent")

        # Image en data URI (Replicate accepte URLs et data URIs)
        b64 = base64.b64encode(src_bytes).decode("ascii")
        data_uri = f"data:image/jpeg;base64,{b64}"

        headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
            "Prefer": "wait",  # bloquant cote Replicate jusqu'a 60s
        }
        payload = {
            "version": self.version,
            "input": {
                "image": data_uri,
                "codeformer_fidelity": self.fidelity,
                "background_enhance": True,
                "face_upsample": True,
                "upscale": self.upscale,
            },
        }

        log.info("Replicate: POST predict (fidelity=%s, upscale=%s)",
                 self.fidelity, self.upscale)
        r = requests.post(
            "https://api.replicate.com/v1/predictions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Replicate API error {r.status_code}: {r.text[:300]}")

        data = r.json()
        status = data.get("status")
        output = data.get("output")

        # Si pas terminé en mode "wait", poll
        prediction_url = data.get("urls", {}).get("get")
        import time
        deadline = time.time() + timeout
        while status not in {"succeeded", "failed", "canceled"} and time.time() < deadline:
            time.sleep(1.5)
            pr = requests.get(prediction_url, headers=headers, timeout=10)
            data = pr.json()
            status = data.get("status")
            output = data.get("output")

        if status != "succeeded":
            raise RuntimeError(f"Replicate prediction {status}: {data.get('error')}")

        # output peut etre une string URL ou une list[str]
        url = output[0] if isinstance(output, list) else output
        if not url:
            raise RuntimeError("Replicate: output vide")

        log.info("Replicate: download result")
        img = requests.get(url, timeout=30)
        img.raise_for_status()
        return img.content

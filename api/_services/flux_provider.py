"""Provider Flux Kontext (Black Forest Labs) sur Replicate.

Flux Kontext est un modele de diffusion generative specialise dans
l'edition d'image guidee par texte. Il prend une image + un prompt
et regenere l'image en suivant l'instruction tout en preservant
la composition.

Pour la restauration de vieilles photos, c'est l'approche utilisee
par BGMaster et consorts : prompt hardcode cote serveur, l'utilisateur
ne voit rien. En un seul appel le modele fait :
  - in-painting des dechirures / rayures / poussieres
  - re-colorisation realiste (ecrase la coloration peinte d'epoque)
  - reconstruction du fond
  - reconstruction des visages (identite preservee)

Variantes disponibles sur Replicate :
  - black-forest-labs/flux-kontext-dev  (~0.025 $/image, plus rapide)
  - black-forest-labs/flux-kontext-pro  (~0.04  $/image, qualite max)

Variables d'env :
  - REPLICATE_API_TOKEN          (requis, deja configure pour CodeFormer)
  - FLUX_MODEL                   (override, default: flux-kontext-pro)
  - FLUX_RESTORE_PROMPT          (override du prompt par defaut)
  - FLUX_SAFETY_TOLERANCE        (1-6, default 2)
  - FLUX_OUTPUT_FORMAT           (jpg|png, default jpg)
"""
from __future__ import annotations

import os
import io
import time
import base64
import logging
from typing import Optional, Tuple

import requests

log = logging.getLogger("souvenir.flux")

API_BASE = "https://api.replicate.com/v1"

DEFAULT_MODEL = "black-forest-labs/flux-kontext-pro"
# Pro pour tous (Dev n'est pas expose en API serverless sur Replicate).
# Override possible via env FLUX_FREE_MODEL / FLUX_PREMIUM_MODEL.
FREE_MODEL = os.getenv(
    "FLUX_FREE_MODEL", "black-forest-labs/flux-kontext-pro"
)
PREMIUM_MODEL = os.getenv(
    "FLUX_PREMIUM_MODEL", "black-forest-labs/flux-kontext-pro"
)

# Prompt hardcode applique automatiquement a chaque restauration.
# Inspire des resultats BGMaster + cahier des charges utilisateur.
DEFAULT_PROMPT = (
    "Restore this damaged old photograph to its original condition. "
    "Remove all scratches, tears, folds, dust spots, stains, and creases "
    "completely. Remove any artificial hand-painted coloring from the "
    "original (such as greenish or yellowish tints applied by hand). "
    "Recreate natural realistic colors appropriate to the historical era: "
    "warm lifelike skin tones, fabrics in their original natural shades, "
    "neutral studio backgrounds. Reconstruct faces in high definition "
    "while strictly preserving the original identity, age, gender, "
    "ethnicity, and facial expression of every person. Keep the exact "
    "composition, poses, framing, and clothing as in the source image. "
    "Sharp, photorealistic, high resolution, no artistic stylization."
)


class FluxKontextProvider:
    def __init__(self, token: str = "",
                 model: str = DEFAULT_MODEL,
                 prompt: str = DEFAULT_PROMPT) -> None:
        self.token = token
        self.model = model
        self.prompt = prompt
        self.safety = int(os.getenv("FLUX_SAFETY_TOLERANCE", "2"))
        self.output_format = os.getenv("FLUX_OUTPUT_FORMAT", "jpg")

    @classmethod
    def from_env(cls) -> "FluxKontextProvider":
        return cls(
            token=os.getenv("REPLICATE_API_TOKEN", ""),
            model=os.getenv("FLUX_MODEL", DEFAULT_MODEL),
            prompt=os.getenv("FLUX_RESTORE_PROMPT", DEFAULT_PROMPT),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    @staticmethod
    def _to_data_uri(img_bytes: bytes) -> str:
        if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif img_bytes[:4] == b"RIFF":
            mime = "image/webp"
        else:
            mime = "image/jpeg"
        b64 = base64.b64encode(img_bytes).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def restore_bytes(
        self,
        src_bytes: bytes,
        prompt: Optional[str] = None,
        timeout: int = 120,
        model: Optional[str] = None,
    ) -> bytes:
        """Envoie l'image a Flux Kontext avec le prompt de restauration.

        Args:
          model: override du modele (ex: FREE_MODEL pour les gratuits,
                 PREMIUM_MODEL pour les payants).
        Retourne les bytes de l'image restauree.
        """
        if not self.token:
            raise RuntimeError("REPLICATE_API_TOKEN absent")

        chosen_model = model or self.model
        url = f"{API_BASE}/models/{chosen_model}/predictions"
        headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        payload = {
            "input": {
                "prompt": prompt or self.prompt,
                "input_image": self._to_data_uri(src_bytes),
                "output_format": self.output_format,
                "safety_tolerance": self.safety,
                "aspect_ratio": "match_input_image",
            }
        }
        log.info("flux: POST %s (prompt=%dch)", chosen_model,
                 len(payload["input"]["prompt"]))
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"Flux API error {r.status_code}: {r.text[:300]}")

        data = r.json()
        status = data.get("status")
        output = data.get("output")
        prediction_url = (data.get("urls") or {}).get("get")

        deadline = time.time() + timeout
        while (status not in {"succeeded", "failed", "canceled"}
               and time.time() < deadline and prediction_url):
            time.sleep(2.0)
            pr = requests.get(prediction_url, headers=headers, timeout=10)
            data = pr.json()
            status = data.get("status")
            output = data.get("output")

        if status != "succeeded":
            raise RuntimeError(f"Flux ({chosen_model}) {status}: {data.get('error')}")

        out_url = output[0] if isinstance(output, list) else output
        if not out_url or not isinstance(out_url, str):
            raise RuntimeError("Flux: output vide")
        log.info("flux: download result")
        img = requests.get(out_url, timeout=60)
        img.raise_for_status()
        return img.content

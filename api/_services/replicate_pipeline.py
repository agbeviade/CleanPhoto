"""Pipeline Replicate multi-modeles pour restauration complete.

Implemente la spec "RESTAURATION COMPLETE" :
  1. Reparation rayures/taches/plis  -> microsoft/bringing-old-photos-back-to-life
  2. Colorisation (si N&B/sepia)     -> piddnad/ddcolor
  3. Restauration visages + HD x2/4  -> sczhou/codeformer

Detection N&B automatique via saturation moyenne (Pillow + numpy).
Chaque etape est tolerante : un modele KO -> on saute et on continue.
La sortie d'un modele est passee a la suivante via son URL Replicate
(plus rapide que de re-base64-encoder a chaque etape).

Variables d'env optionnelles :
  - REPLICATE_API_TOKEN          (requis)
  - PIPELINE_REPAIR=1            (active etape 1)
  - PIPELINE_COLORIZE=1          (active detection N&B + etape 2)
  - BW_SATURATION_THRESHOLD=18   (seuil detection N&B)
  - REPLICATE_FIDELITY=0.7       (CodeFormer fidelity)
  - REPLICATE_UPSCALE=2          (CodeFormer upscale, 1-4)
  - REPLICATE_BOPBTL / REPLICATE_DDCOLOR / REPLICATE_CODEFORMER
    (override des identifiants owner/name si besoin)
"""
from __future__ import annotations

import os
import io
import time
import base64
import logging
from typing import Optional, Tuple

import requests
import numpy as np
from PIL import Image

log = logging.getLogger("souvenir.pipeline")

API_BASE = "https://api.replicate.com/v1"

MODEL_BOPBTL = os.getenv(
    "REPLICATE_BOPBTL", "microsoft/bringing-old-photos-back-to-life"
)
MODEL_DDCOLOR = os.getenv("REPLICATE_DDCOLOR", "piddnad/ddcolor")
MODEL_CODEFORMER = os.getenv("REPLICATE_CODEFORMER", "sczhou/codeformer")

BW_SATURATION_THRESHOLD = float(os.getenv("BW_SATURATION_THRESHOLD", "18"))


class ReplicatePipeline:
    """Orchestre 1 a 3 modeles Replicate pour la restauration complete."""

    def __init__(self, token: str = "") -> None:
        self.token = token
        self.fidelity = float(os.getenv("REPLICATE_FIDELITY", "0.7"))
        self.upscale = int(os.getenv("REPLICATE_UPSCALE", "2"))
        self.repair_enabled = os.getenv("PIPELINE_REPAIR", "1") == "1"
        self.colorize_enabled = os.getenv("PIPELINE_COLORIZE", "1") == "1"

    @classmethod
    def from_env(cls) -> "ReplicatePipeline":
        return cls(token=os.getenv("REPLICATE_API_TOKEN", ""))

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    # ------------------------------------------------------------------
    # Detection N&B / sepia
    # ------------------------------------------------------------------
    @staticmethod
    def is_grayscale(img_bytes: bytes,
                     threshold: float = BW_SATURATION_THRESHOLD) -> bool:
        """True si la saturation moyenne (R,G,B max-min) < threshold."""
        try:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img.thumbnail((256, 256))  # speed
            arr = np.asarray(img, dtype=np.float32)
            mx = arr.max(axis=-1)
            mn = arr.min(axis=-1)
            sat = float((mx - mn).mean())
            log.info("BW detect: avg-saturation=%.1f (threshold=%.1f)",
                     sat, threshold)
            return sat < threshold
        except Exception as exc:
            log.warning("BW detect failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Helpers HTTP
    # ------------------------------------------------------------------
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

    def _run_model(
        self,
        model_id: str,
        inputs: dict,
        timeout: int = 90,
    ) -> Tuple[bytes, str]:
        """Lance un modele Replicate (latest version) et retourne (bytes, url)."""
        if not self.token:
            raise RuntimeError("REPLICATE_API_TOKEN absent")

        url = f"{API_BASE}/models/{model_id}/predictions"
        headers = {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        log.info("pipeline: POST %s", model_id)
        r = requests.post(url, headers=headers,
                          json={"input": inputs}, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"{model_id} error {r.status_code}: {r.text[:300]}")
        data = r.json()
        status = data.get("status")
        output = data.get("output")
        prediction_url = (data.get("urls") or {}).get("get")

        deadline = time.time() + timeout
        while (status not in {"succeeded", "failed", "canceled"}
               and time.time() < deadline and prediction_url):
            time.sleep(1.5)
            pr = requests.get(prediction_url, headers=headers, timeout=10)
            data = pr.json()
            status = data.get("status")
            output = data.get("output")

        if status != "succeeded":
            raise RuntimeError(f"{model_id} {status}: {data.get('error')}")

        out_url = output[0] if isinstance(output, list) else output
        if not out_url or not isinstance(out_url, str):
            raise RuntimeError(f"{model_id}: output vide ou non-url")
        img = requests.get(out_url, timeout=60)
        img.raise_for_status()
        return img.content, out_url

    # ------------------------------------------------------------------
    # Pipeline public
    # ------------------------------------------------------------------
    def restore_bytes(
        self,
        src_bytes: bytes,
        fidelity: Optional[float] = None,
        upscale: Optional[int] = None,
        colorize: Optional[bool] = None,
    ) -> bytes:
        """Lance le pipeline complet et retourne les bytes JPEG finaux.

        Args:
          fidelity (0.0-1.0)  : CodeFormer (override env)
          upscale  (1-4)      : CodeFormer (override env)
          colorize (bool|None): force ou desactive l'etape couleur. None => auto.
        """
        f = self.fidelity if fidelity is None else max(0.0, min(1.0, float(fidelity)))
        u = self.upscale if upscale is None else max(1, min(4, int(upscale)))

        current_bytes = src_bytes
        current_arg: str = self._to_data_uri(src_bytes)
        steps_done: list[str] = []

        # Etape 1 : Reparation rayures / taches / plis
        if self.repair_enabled:
            try:
                log.info("[1/3] repair (BOPBTL)")
                current_bytes, current_arg = self._run_model(
                    MODEL_BOPBTL,
                    {"image": current_arg, "with_scratch": True, "HR": False},
                )
                steps_done.append("repair")
            except Exception as exc:
                log.warning("[1/3] repair skipped: %s", exc)

        # Etape 2 : Colorisation conditionnelle
        do_color = colorize
        if do_color is None:
            do_color = self.colorize_enabled and self.is_grayscale(current_bytes)
        if do_color:
            try:
                log.info("[2/3] colorize (DDColor)")
                current_bytes, current_arg = self._run_model(
                    MODEL_DDCOLOR,
                    {"image": current_arg, "model_size": "large"},
                )
                steps_done.append("colorize")
            except Exception as exc:
                log.warning("[2/3] colorize skipped: %s", exc)
        else:
            log.info("[2/3] colorize: bypass (deja en couleur)")

        # Etape 3 : Restauration visages + upscale HD
        try:
            log.info("[3/3] face-restore + upscale (CodeFormer)")
            current_bytes, current_arg = self._run_model(
                MODEL_CODEFORMER,
                {
                    "image": current_arg,
                    "codeformer_fidelity": f,
                    "background_enhance": True,
                    "face_upsample": True,
                    "upscale": u,
                },
            )
            steps_done.append("codeformer")
        except Exception as exc:
            log.warning("[3/3] codeformer failed: %s", exc)
            if not steps_done:
                # Aucune etape n'a reussi : on remonte l'erreur
                raise

        log.info("pipeline ok, steps=%s", steps_done)
        return current_bytes

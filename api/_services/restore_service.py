"""Service de restauration multi-mode (LITE / BASIC / ADVANCED).

Auto-detection au demarrage en fonction des dependances disponibles:
  - LITE     : Pillow + numpy uniquement (~10MB) -> compatible Vercel serverless
  - BASIC    : + opencv-python-headless (~50MB)  -> serveur dedie
  - ADVANCED : + torch / Real-ESRGAN / GFPGAN    -> GPU recommande

Force un mode via la variable d'env: PIPELINE_MODE=lite|basic|advanced
"""
from __future__ import annotations

import io
import os
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .replicate_provider import ReplicateProvider

log = logging.getLogger("souvenir.restore")

# Optional imports
try:
    import cv2  # type: ignore
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

MODELS_DIR = Path(__file__).parent.parent.parent / "backend" / "models"
CODEFORMER_PATH = MODELS_DIR / "codeformer.pth"
REALESRGAN_PATH = MODELS_DIR / "RealESRGAN_x4plus.pth"


class RestoreService:
    def __init__(self) -> None:
        forced = os.getenv("PIPELINE_MODE", "").lower()
        self._codeformer = None
        self._upsampler = None
        self._replicate = ReplicateProvider.from_env()

        # Auto-detect (priorite: replicate > advanced > basic > lite)
        if forced == "lite":
            self.mode = "lite"
        elif forced == "basic" and HAS_CV2:
            self.mode = "basic"
        elif forced == "replicate" and self._replicate.is_configured:
            self.mode = "replicate"
        elif forced == "advanced":
            self.mode = "advanced" if self._can_load_advanced() else "basic" if HAS_CV2 else "lite"
        else:
            # Auto: privilegier replicate si token configure (effet wow + sans GPU local)
            if self._replicate.is_configured:
                self.mode = "replicate"
            elif self._can_load_advanced():
                self.mode = "advanced"
            elif HAS_CV2:
                self.mode = "basic"
            else:
                self.mode = "lite"
        log.info("Pipeline mode: %s (cv2=%s, replicate=%s)",
                 self.mode, HAS_CV2, self._replicate.is_configured)

    def _can_load_advanced(self) -> bool:
        if not (CODEFORMER_PATH.exists() and REALESRGAN_PATH.exists()):
            return False
        try:
            import torch  # noqa
            import realesrgan  # noqa
            import basicsr  # noqa
            return True
        except ImportError:
            return False

    def pipeline_info(self) -> dict:
        return {
            "mode": self.mode,
            "cv2_available": HAS_CV2,
            "replicate_configured": self._replicate.is_configured,
            "codeformer_weights": CODEFORMER_PATH.exists(),
            "realesrgan_weights": REALESRGAN_PATH.exists(),
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def restore_bytes(self, src_bytes: bytes) -> bytes:
        """Restaure depuis bytes -> bytes (JPEG). Compatible serverless.

        Cascade de fallback en cas d'echec:
          replicate -> advanced (local GPU) -> basic (cv2) -> lite (Pillow)
        """
        if self.mode == "replicate":
            try:
                return self._replicate.restore_bytes(src_bytes)
            except Exception as exc:
                log.exception("Replicate failed -> fallback: %s", exc)
        if self.mode == "advanced":
            try:
                return self._restore_advanced_bytes(src_bytes)
            except Exception as exc:
                log.exception("Advanced failed -> fallback: %s", exc)
        if self.mode in ("basic", "advanced", "replicate") and HAS_CV2:
            try:
                return self._restore_basic_bytes(src_bytes)
            except Exception as exc:
                log.exception("Basic failed -> fallback lite: %s", exc)
        return self._restore_lite_bytes(src_bytes)

    # File-based API (compat backend/main.py)
    def restore(self, src_path: str, dst_path: str) -> str:
        src_bytes = Path(src_path).read_bytes()
        out = self.restore_bytes(src_bytes)
        Path(dst_path).write_bytes(out)
        return dst_path

    # ------------------------------------------------------------------
    # LITE (Pillow only - serverless friendly)
    # ------------------------------------------------------------------
    def _restore_lite_bytes(self, src_bytes: bytes) -> bytes:
        img = Image.open(io.BytesIO(src_bytes)).convert("RGB")
        img = ImageOps.exif_transpose(img)
        w, h = img.size

        # 1. Upscale x1.5/x2 si petit (Lanczos)
        max_dim = max(w, h)
        if max_dim < 1000:
            scale = 2
        elif max_dim < 1500:
            scale = 1.5
        else:
            scale = 1
        if scale > 1:
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        # 2. Auto-contrast + equalization legere
        img = ImageOps.autocontrast(img, cutoff=1)

        # 3. Denoise (median filter doux)
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # 4. Sharpening
        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=140, threshold=2))

        # 5. Boost emotionnel
        img = ImageEnhance.Color(img).enhance(1.18)
        img = ImageEnhance.Contrast(img).enhance(1.08)
        img = ImageEnhance.Brightness(img).enhance(1.04)

        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95, optimize=True)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # BASIC (cv2)
    # ------------------------------------------------------------------
    def _restore_basic_bytes(self, src_bytes: bytes) -> bytes:
        arr = np.frombuffer(src_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return self._restore_lite_bytes(src_bytes)

        h, w = img.shape[:2]
        denoised = cv2.fastNlMeansDenoisingColored(img, None, 7, 7, 7, 21)

        # CLAHE
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        contrast = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

        # Face enhance
        contrast = self._enhance_faces_cv(contrast)

        # Upscale
        max_dim = max(h, w)
        if max_dim < 1500:
            s = 2 if max_dim < 1000 else 1.5
            up = cv2.resize(contrast, (int(w * s), int(h * s)), interpolation=cv2.INTER_LANCZOS4)
        else:
            up = contrast

        gauss = cv2.GaussianBlur(up, (0, 0), 1.5)
        sharp = cv2.addWeighted(up, 1.5, gauss, -0.5, 0)

        pil = Image.fromarray(cv2.cvtColor(sharp, cv2.COLOR_BGR2RGB))
        pil = ImageEnhance.Color(pil).enhance(1.15)
        pil = ImageEnhance.Contrast(pil).enhance(1.05)

        buf = io.BytesIO()
        pil.save(buf, "JPEG", quality=95, optimize=True)
        return buf.getvalue()

    def _enhance_faces_cv(self, img):
        try:
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.2, 5, minSize=(40, 40))
            out = img.copy()
            for (x, y, w, h) in faces:
                pad = int(0.1 * max(w, h))
                x0, y0 = max(0, x - pad), max(0, y - pad)
                x1, y1 = min(img.shape[1], x + w + pad), min(img.shape[0], y + h + pad)
                roi = out[y0:y1, x0:x1]
                smooth = cv2.bilateralFilter(roi, 7, 40, 40)
                gauss = cv2.GaussianBlur(smooth, (0, 0), 1.0)
                out[y0:y1, x0:x1] = cv2.addWeighted(smooth, 1.4, gauss, -0.4, 0)
            return out
        except Exception as exc:
            log.warning("face enhance skipped: %s", exc)
            return img

    # ------------------------------------------------------------------
    # ADVANCED (Real-ESRGAN + CodeFormer/GFPGAN)
    # ------------------------------------------------------------------
    def _restore_advanced_bytes(self, src_bytes: bytes) -> bytes:
        import torch
        from basicsr.archs.rrdbnet_arch import RRDBNet
        from realesrgan import RealESRGANer
        from gfpgan import GFPGANer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._upsampler is None:
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23,
                            num_grow_ch=32, scale=4)
            self._upsampler = RealESRGANer(
                scale=4, model_path=str(REALESRGAN_PATH), model=model,
                tile=400, tile_pad=10, pre_pad=0, half=(device == "cuda"),
            )
        if self._codeformer is None:
            self._codeformer = GFPGANer(
                model_path=str(CODEFORMER_PATH), upscale=2, arch="clean",
                channel_multiplier=2, bg_upsampler=self._upsampler,
            )
        arr = np.frombuffer(src_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        _, _, restored = self._codeformer.enhance(
            img, has_aligned=False, only_center_face=False, paste_back=True, weight=0.7,
        )
        pil = Image.fromarray(cv2.cvtColor(restored, cv2.COLOR_BGR2RGB))
        pil = ImageEnhance.Color(pil).enhance(1.10)
        buf = io.BytesIO()
        pil.save(buf, "JPEG", quality=95, optimize=True)
        return buf.getvalue()

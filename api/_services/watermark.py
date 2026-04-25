"""Watermark discret pour la version gratuite.

Position: coin inferieur droit, 4% de la largeur, opacite 60%.
Texte: "Souvenir AI"
"""
from __future__ import annotations

import io
from PIL import Image, ImageDraw, ImageFont


def add_watermark(jpeg_bytes: bytes, text: str = "Souvenir AI") -> bytes:
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    w, h = img.size

    # Calque transparent
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Taille de police proportionnelle (~3.5% de la largeur)
    font_size = max(14, int(w * 0.035))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Mesure du texte
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        tw, th = draw.textsize(text, font=font)  # Pillow < 9.2

    # Position : bas-droite avec marge
    margin = max(8, int(w * 0.015))
    x = w - tw - margin
    y = h - th - margin - int(font_size * 0.2)

    # Ombre legere puis texte
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 130))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 200))

    out = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=95, optimize=True)
    return buf.getvalue()

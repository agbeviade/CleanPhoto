"""Prompts Flux specialises par categorie de photo.

Chaque prompt est ecrit en anglais (Flux performe mieux en anglais) et :
  - garde le coeur du DEFAULT_PROMPT (restoration logic)
  - ajoute des contraintes specifiques a la categorie
  - emphasise la preservation d'identite quand applicable

Mapping :
  face_portrait -> portrait individuel : focus visage, identity preservation
  face_group    -> groupe : preserve EACH face, no merging
  landscape     -> paysage : sky/foliage, no over-sharpening
  document      -> document : text legibility 100%, no decoration
  object        -> objet/animal : general restoration
  unknown       -> None (utilise DEFAULT_PROMPT du provider)
"""
from __future__ import annotations

from typing import Optional


CATEGORY_PROMPTS: dict[str, str] = {
    "face_portrait": (
        "Restore this portrait photograph to studio quality. Focus on the face: "
        "enhance eye clarity (iris details, eyelashes), restore natural skin "
        "texture (pores, micro-contrast - avoid plastic AI look), sharpen lips "
        "and teeth definition. CRITICAL CONSTRAINT: preserve the person's "
        "EXACT identity, unique facial features, expression, age, gender, and "
        "ethnicity at 100% fidelity. Do NOT alter facial bone structure, "
        "mouth shape, eye color, or hairline. Repair scratches, dust, creases, "
        "and physical damage. If the image is grayscale or sepia, apply "
        "realistic skin-tone colorization (avoid uniform tan, respect natural "
        "skin variation). Final output: 4K, photorealistic, natural lighting."
    ),
    "face_group": (
        "Restore this group photograph. ABSOLUTE CRITICAL CONSTRAINT: preserve "
        "EACH person's individual identity, unique features, age, gender, and "
        "expression at 100% fidelity. Do NOT merge faces, do NOT homogenize "
        "appearance, do NOT make people look alike. Enhance every face with "
        "equal precision: eye clarity, skin texture, facial detail. Repair "
        "scratches, tears, and damage across the entire image. Maintain the "
        "exact group composition, spatial relationships, body posture, and "
        "any visible clothing/objects. If grayscale, apply period-appropriate "
        "colorization (era-correct clothing colors, natural skin tones). "
        "Final 4K, photorealistic, faithful to the original moment."
    ),
    "landscape": (
        "Restore this landscape or scene photograph. Enhance atmospheric depth "
        "and sky details (clouds, gradients), recover foliage texture (leaves, "
        "grass, trees), restore architectural details if present (buildings, "
        "monuments). Repair scratches, dust spots, and color fading. AVOID "
        "over-sharpening which creates an unnatural HDR look - keep it organic. "
        "If grayscale, apply realistic colorization based on object recognition "
        "(sky blue, foliage green, accurate building/stone tones, water blue). "
        "Preserve the original lighting mood, time-of-day, and weather "
        "atmosphere. Final 4K, photorealistic, natural color palette."
    ),
    "document": (
        "Restore this document, paper, or photograph of text. ABSOLUTE "
        "CRITICAL CONSTRAINT: preserve text legibility 100% - DO NOT invent, "
        "alter, or hallucinate any letters, numbers, words, or characters. "
        "If text is unclear, leave it unclear rather than guessing. Remove "
        "paper yellowing, brown stains, water marks, and creases. Enhance "
        "ink contrast against the paper background. Preserve original layout, "
        "stamps, signatures, and graphical elements exactly as positioned. "
        "Do NOT add decorations or embellishments. Final output: clean, "
        "high-resolution scan appearance, faithful to the original document."
    ),
    "object": (
        "Restore this photograph of an object, animal, or scene without people. "
        "Enhance subject details (fur texture, surface materials, fine details), "
        "repair scratches and physical damage, balance colors and lighting. "
        "If grayscale or faded, apply realistic colorization respecting the "
        "natural appearance of the subject. Avoid over-saturation or fantasy "
        "colors. Preserve the original composition, depth of field, and "
        "atmosphere. Final 4K, photorealistic, natural."
    ),
}


# Labels affiches cote mobile (UI-friendly).
CATEGORY_LABELS: dict[str, str] = {
    "face_portrait": "Portrait individuel",
    "face_group": "Photo de groupe",
    "landscape": "Paysage / scene",
    "document": "Document",
    "object": "Objet / animal",
    "unknown": "Photo generique",
}


def get_prompt_for_category(category: str) -> Optional[str]:
    """Retourne le prompt specialise, ou None si la categorie n'a pas de prompt
    (=> utiliser le DEFAULT_PROMPT du provider)."""
    return CATEGORY_PROMPTS.get(category)


def get_label(category: str) -> str:
    """Label UI a afficher dans l'app mobile."""
    return CATEGORY_LABELS.get(category, CATEGORY_LABELS["unknown"])

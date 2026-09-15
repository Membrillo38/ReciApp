"""Authorized culinary densities for volume↔mass conversion.

Server stores extracted quantity/unit as-is. density_g_per_ml is filled only from
this table (or left null). Never invent values.
"""

from __future__ import annotations

import re
import unicodedata

# Culinary bulk densities (g/ml) for common pantry items with preparation state.
# Prefer specific keys (packed / sifted / salt type) over bare names.
_DENSITY_G_PER_ML: dict[str, float] = {
    # Flours
    "all-purpose flour": 0.53,
    "all purpose flour": 0.53,
    "plain flour": 0.53,
    "flour": 0.53,
    "sifted all-purpose flour": 0.45,
    "sifted flour": 0.45,
    "bread flour": 0.54,
    "cake flour": 0.48,
    "whole wheat flour": 0.51,
    "harina": 0.53,
    "harina de trigo": 0.53,
    "harina tamizada": 0.45,
    "farine": 0.53,
    "farine tamisee": 0.45,
    # Sugars
    "granulated sugar": 0.85,
    "white sugar": 0.85,
    "sugar": 0.85,
    "caster sugar": 0.80,
    "powdered sugar": 0.48,
    "confectioners sugar": 0.48,
    "icing sugar": 0.48,
    "brown sugar": 0.72,
    "light brown sugar": 0.72,
    "dark brown sugar": 0.78,
    "packed brown sugar": 0.85,
    "packed light brown sugar": 0.85,
    "azucar": 0.85,
    "azucar moreno": 0.72,
    "azucar moreno compacto": 0.85,
    # Salts — type matters
    "table salt": 1.2,
    "fine salt": 1.2,
    "salt": 1.2,
    "kosher salt": 0.80,
    "sea salt": 1.0,
    "flaky salt": 0.48,
    "sal": 1.2,
    "sal fina": 1.2,
    "sal kosher": 0.80,
    "sal marina": 1.0,
    # Fats / dairy
    "butter": 0.96,
    "melted butter": 0.91,
    "oil": 0.92,
    "olive oil": 0.91,
    "vegetable oil": 0.92,
    "mantequilla": 0.96,
    "mantequilla derretida": 0.91,
    "aceite": 0.92,
    "aceite de oliva": 0.91,
    "milk": 1.03,
    "whole milk": 1.03,
    "leche": 1.03,
    "water": 1.0,
    "agua": 1.0,
    "honey": 1.42,
    "miel": 1.42,
    "cocoa powder": 0.50,
    "unsweetened cocoa powder": 0.50,
    "cacao en polvo": 0.50,
    "rice": 0.85,
    "uncooked rice": 0.85,
    "arroz": 0.85,
}

_COUNTABLE_UNITS = frozenset({
    "piece", "pieces", "pc", "pcs",
    "unit", "units", "unidad", "unidades",
    "egg", "eggs", "huevo", "huevos",
    "clove", "cloves", "diente", "dientes",
    "slice", "slices", "rebanada", "rebanadas",
    "leaf", "leaves", "hoja", "hojas",
    "sprig", "sprigs",
    "stalk", "stalks",
    "bunch", "bunches",
    "can", "cans",
    "package", "packages", "pack", "packs",
    "large", "medium", "small",
    "whole", "halves", "half",
})

_TO_TASTE_RE = re.compile(
    r"(?i)^(to\s+taste|al\s+gusto|q\.?\s*b\.?|nach\s+geschmack|a\s+piacere|"
    r"au\s+go[uû]t|a\s+gosto|smak\s+etter)$"
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_SPACE_RE = re.compile(r"\s+")


def normalize_ingredient_key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _NON_ALNUM_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def parse_density_g_per_ml(raw: object) -> float | None:
    """Accept positive number only; 0 / negative / junk → None."""
    if raw is None or raw is False:
        return None
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value != value:  # NaN
        return None
    return value


def resolve_density_g_per_ml(
    name: str,
    *,
    quantity: str | None = None,
    unit: str | None = None,
) -> float | None:
    """Return authorized culinary density or None. Never guess."""
    if not (name or "").strip():
        return None
    qty = (quantity or "").strip()
    if qty and _TO_TASTE_RE.match(qty):
        return None
    unit_key = normalize_ingredient_key(unit or "")
    if unit_key in _COUNTABLE_UNITS:
        return None

    key = normalize_ingredient_key(name)
    if not key:
        return None
    if key in _DENSITY_G_PER_ML:
        return _DENSITY_G_PER_ML[key]

    # Longest phrase match inside the ingredient name (qualifiers first).
    padded = f" {key} "
    best: tuple[int, float] | None = None
    for phrase, density in _DENSITY_G_PER_ML.items():
        if f" {phrase} " in padded:
            length = len(phrase)
            if best is None or length > best[0]:
                best = (length, density)
    return best[1] if best else None

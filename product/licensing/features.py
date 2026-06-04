"""Feature-Flags und Paket-Definitionen für Hermes Sales Operator.

Drei Pakete:
  STARTER    — Suche + Berichte
  PRO        — + Target Fill, Mail-Vorschau, Freigabe
  ENTERPRISE — + Live Closer

Wenn kein Lizenz-Key gesetzt ist (Entwicklungsmodus), sind alle Features aktiv.
"""
from __future__ import annotations

from enum import Enum


class Feature(str, Enum):
    SUCHEN         = "suchen"          # Lead-Suche (immer aktiv)
    TARGET_FILL    = "target_fill"     # automatisches Auffüllen
    MAIL_VORSCHAU  = "mail_vorschau"   # Mail-Vorschau Tab
    FREIGABE       = "freigabe"        # Freigabe-Button (Senden)
    CLOSER         = "closer"          # Live Sales Coach


# Features pro Paket — jedes Paket enthält alle Features der darunter liegenden Pakete.
PAKETE: dict[str, list[Feature]] = {
    "starter": [
        Feature.SUCHEN,
    ],
    "pro": [
        Feature.SUCHEN,
        Feature.TARGET_FILL,
        Feature.MAIL_VORSCHAU,
        Feature.FREIGABE,
    ],
    "enterprise": [
        Feature.SUCHEN,
        Feature.TARGET_FILL,
        Feature.MAIL_VORSCHAU,
        Feature.FREIGABE,
        Feature.CLOSER,
    ],
}

# Im Entwicklungsmodus (kein Lizenz-Key) sind alle Features aktiv.
ALLE_FEATURES: list[Feature] = list(Feature)


def features_fuer_plan(plan: str) -> list[Feature]:
    """Gibt Feature-Liste für einen Plan zurück. Unbekannter Plan → STARTER."""
    return PAKETE.get(plan.lower(), PAKETE["starter"])

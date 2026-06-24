"""Angebot → Signal-Set: koppelt jedes Akquise-Angebot an seine Kaufsignale.

Warum diese Schicht existiert
------------------------------
Es gibt zwei sehr verschiedene Verkaufsfälle mit JE EIGENER Signal-Logik:
  • Vertrieb (B2B-System / Akquise / Website): „die Firma braucht mehr Kunden/
    Termine" → die 6 Vertriebs-Signale (sales_hiring … new_location).
  • Versicherung (Angebot „Versicherungsleads"): „eine Veränderung reißt eine
    Deckungslücke auf" → die 6 vs_*-Signale (vs_hiring … vs_cyber).

Damit sich nichts vermischt, richtet sich die Signal-Auswahl nach dem aktiven
Angebot. Diese Schicht ist die EINE Wahrheit dafür: UI-Häkchen, Backend-
Validierung und das ICP-Gate ziehen alle hierher. Rein deterministisch, kein
Netz — voll testbar. Nichts Bestehendes wird verändert (additiv).
"""
from __future__ import annotations

from product.bridge.signal_discovery import (
    SIGNAL_LABELS,
    _VERSICHERUNGS_SIGNAL_TYPES as VERSICHERUNGS_SIGNALE,
    _VERTRIEBS_SIGNAL_TYPES as VERTRIEBS_SIGNALE,
)

# Gruppen-Schlüssel.
GRUPPE_VERTRIEB = "vertrieb"
GRUPPE_VERSICHERUNG = "versicherung"

_GRUPPE_SIGNALE: dict[str, tuple[str, ...]] = {
    GRUPPE_VERTRIEB: VERTRIEBS_SIGNALE,
    GRUPPE_VERSICHERUNG: VERSICHERUNGS_SIGNALE,
}

# Je Gruppe: Default-angehakte Signale + das „heißeste" (Badge im UI).
# Die Vertriebs-Gruppe spiegelt das bisherige UI-Verhalten 1:1.
_GRUPPE_DEFAULT: dict[str, tuple[str, ...]] = {
    GRUPPE_VERTRIEB: ("sales_hiring", "appointment_setter", "growth_expansion"),
    GRUPPE_VERSICHERUNG: ("vs_hiring", "vs_benefits", "vs_fuhrpark"),
}
_GRUPPE_HOT: dict[str, str] = {
    GRUPPE_VERTRIEB: "sales_hiring",
    GRUPPE_VERSICHERUNG: "vs_hiring",
}


def gruppe_fuer_angebot(angebot_id: str) -> str:
    """Welche Signal-Gruppe gehört zum Angebot? Default = Vertrieb.

    Robust gegen Benennung: jede Angebot-ID, die „versicherung" enthält
    (z. B. „versicherungsleads", „versicherungs_leads"), ist Versicherung.
    So funktioniert es egal, ob das Angebot per Seed oder über die UI angelegt
    wurde (der Slug enthält in beiden Fällen „versicherung").
    """
    pid = (angebot_id or "").strip().lower()
    if "versicherung" in pid:
        return GRUPPE_VERSICHERUNG
    return GRUPPE_VERTRIEB


def signaltypen_fuer_angebot(angebot_id: str) -> tuple[str, ...]:
    """Die erlaubten Signaltypen des Angebots (für UI + Validierung)."""
    return _GRUPPE_SIGNALE[gruppe_fuer_angebot(angebot_id)]


def ist_versicherungs_angebot(angebot_id: str) -> bool:
    """True, wenn das Angebot das Versicherungs-Signal-Set nutzt."""
    return gruppe_fuer_angebot(angebot_id) == GRUPPE_VERSICHERUNG


def ist_versicherungs_signalset(signale) -> bool:
    """True, wenn (mind.) ein gewähltes Signal ein Versicherungs-Signal ist.

    Treibt den breiten-ICP-Modus im Premium-Gate: Versicherungs-Signale zielen
    bewusst auf „gewerblicher Mittelstand mit Trigger", nicht auf eine enge
    Branche — darum darf das Gate hier nicht alles wegen ICP-Branche rejecten.
    Entkoppelt vom Angebot-Namen (hängt an der echten Signal-Semantik).
    """
    vs = set(VERSICHERUNGS_SIGNALE)
    return any((str(s) or "").strip().lower() in vs for s in (signale or []))


def signal_meta_fuer_angebot(angebot_id: str) -> list[dict]:
    """UI-Metadaten der Häkchen-Liste des Angebots: key, label, default, hot.

    Reihenfolge = Gewichtung der Gruppe. ``default`` = vorab angehakt,
    ``hot`` = heißeste Spur (Badge). Die UI rendert die Checkboxen daraus —
    so wechselt die Liste mit dem gewählten Angebot, ohne dass sich die zwei
    Signal-Welten vermischen.
    """
    gruppe = gruppe_fuer_angebot(angebot_id)
    typen = _GRUPPE_SIGNALE[gruppe]
    default = set(_GRUPPE_DEFAULT.get(gruppe, ()))
    hot = _GRUPPE_HOT.get(gruppe, "")
    return [
        {
            "key": t,
            "label": SIGNAL_LABELS.get(t, t),
            "default": t in default,
            "hot": t == hot,
        }
        for t in typen
    ]

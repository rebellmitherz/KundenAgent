"""Lizenzprüfung für Rebellsystem Sales Operator — NUR Verifikation.

Format: BASE32(payload).HMAC12
payload: "kunde|plan|ablauf_timestamp"
  ablauf_timestamp: 0 = unbegrenzt, sonst Unix-Timestamp

PFLICHT VOR AUSLIEFERUNG:
  Umgebungsvariable REBELLSYSTEM_LICENSE_SECRET setzen (min. 32 Zeichen).
  Wer das SECRET nicht kennt, kann keine gültigen Schlüssel erzeugen.
  Ohne gesetzte Variable startet die Produktion NICHT (hartes Tor).

Generierung von Schlüsseln: NUR über keygen.py (NICHT im Kundenpaket).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass, field

from product.licensing.features import Feature, features_fuer_plan, ALLE_FEATURES

_SECRET_ENV = "REBELLSYSTEM_LICENSE_SECRET"
# Nur für Tests/Entwicklung — in Produktion MUSS die Env-Var gesetzt sein.
_SECRET_FALLBACK = b"REBELLSYSTEM-CHANGE-BEFORE-SHIPPING-2026"


def _secret(produktionsmodus: bool = False) -> bytes:
    """Liest das Lizenz-Secret aus der Umgebungsvariable.

    Im Produktionsmodus (produktionsmodus=True) wird ein harter Fehler
    geworfen, wenn die Variable nicht gesetzt ist — so kann kein Kunde
    mit dem Entwicklungs-Secret ausgeliefert werden.
    """
    env = os.environ.get(_SECRET_ENV, "")
    if env:
        return env.encode("utf-8")
    if produktionsmodus:
        raise RuntimeError(
            f"SICHERHEITSFEHLER: Umgebungsvariable '{_SECRET_ENV}' ist nicht gesetzt. "
            "Bitte vor Auslieferung setzen (min. 32 Zeichen)."
        )
    return _SECRET_FALLBACK


def _sign(payload: str) -> str:
    mac = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return mac[:12]


def secret_gesetzt() -> bool:
    """True wenn das Produktions-Secret korrekt gesetzt ist (für Check-Install)."""
    return bool(os.environ.get(_SECRET_ENV, ""))


# ── Datenklasse ──────────────────────────────────────────────────────────────

@dataclass
class LizenzDaten:
    kunde: str
    plan: str
    features: list[Feature] = field(default_factory=list)
    ablauf: int = 0          # Unix-Timestamp, 0 = unbegrenzt

    def hat_feature(self, f: Feature) -> bool:
        return f in self.features

    def ist_abgelaufen(self) -> bool:
        return bool(self.ablauf) and time.time() > self.ablauf

    def tage_verbleibend(self) -> int | None:
        """Verbleibende Tage oder None wenn unbegrenzt."""
        if not self.ablauf:
            return None
        rest = int((self.ablauf - time.time()) / 86400)
        return max(0, rest)

    def zusammenfassung(self) -> str:
        ablauf_str = "unbegrenzt"
        if self.ablauf:
            tage = self.tage_verbleibend()
            ablauf_str = f"{tage} Tage verbleibend"
        feature_namen = [f.value for f in self.features]
        return (
            f"Lizenz: {self.kunde} | Paket: {self.plan.upper()} | "
            f"Features: {', '.join(feature_namen)} | Gültigkeit: {ablauf_str}"
        )


# ── Fehler ───────────────────────────────────────────────────────────────────

class LizenzFehler(Exception):
    pass


# ── Verifikation ─────────────────────────────────────────────────────────────

def lizenz_pruefen(key: str) -> LizenzDaten:
    """Prüft einen Lizenzschlüssel. Gibt LizenzDaten zurück oder wirft LizenzFehler."""
    try:
        enc, sig = key.strip().split(".", 1)
        pad = "=" * (-len(enc) % 8)
        payload = base64.b32decode(enc + pad).decode("utf-8")
    except Exception:
        raise LizenzFehler("Schlüssel nicht lesbar — bitte prüfen.")

    if not hmac.compare_digest(sig, _sign(payload)):
        raise LizenzFehler("Ungültige Signatur — Schlüssel wurde verändert oder ist gefälscht.")

    try:
        teile = payload.split("|", 2)
        if len(teile) != 3:
            raise ValueError
        kunde, plan, ablauf_s = teile
        ablauf = int(ablauf_s)
    except Exception:
        raise LizenzFehler("Schlüsselformat ungültig.")

    if ablauf and time.time() > ablauf:
        raise LizenzFehler("Lizenz ist abgelaufen. Bitte erneuern.")

    return LizenzDaten(
        kunde=kunde,
        plan=plan,
        features=features_fuer_plan(plan),
        ablauf=ablauf,
    )


def lizenz_laden(key: str) -> LizenzDaten | None:
    """Wie lizenz_pruefen, aber gibt None zurück statt zu werfen (für optionalen Modus)."""
    if not key:
        return None
    try:
        return lizenz_pruefen(key)
    except LizenzFehler:
        return None


def feature_erlaubt(lizenz: LizenzDaten | None, feature: Feature) -> bool:
    """True wenn Feature erlaubt ist.

    Kein Lizenz-Objekt (Entwicklungsmodus) = alle Features erlaubt.
    """
    if lizenz is None:
        return True
    return lizenz.hat_feature(feature)

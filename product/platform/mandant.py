"""Mandanten-Modell + Register — das Fundament der Multi-Mandanten-Plattform (F3).

Ein **Mandant** ist ein zahlender Kunde mit einem eigenen, isolierten Akquise-
Agenten. Das Register verwaltet beliebig viele Mandanten und garantiert die
Isolation technisch (nicht per Konvention):

  - Jeder Mandant bekommt ein eigenes Daten-Verzeichnis (abgeleitet aus der
    Mandanten-ID — strukturell kollisionsfrei).
  - Keine zwei aktiven Mandanten dürfen dieselbe Engine-Instanz (engine_dir)
    teilen — sonst vermischten sich Pipelines/Postfächer.
  - Die Mandanten-ID ist ein eindeutiger, dateisystem-sicherer Slug.

Reine Daten-/Dateisystem-Logik: KEINE Engine-Aufrufe, kein Versand, kein
Netzwerk — voll testbar ohne Schlüssel. Die Verdrahtung zu Runner/Bridge je
Mandant kommt in F4 (Plattform-Orchestrierung).

Branchenunabhängig: standard_zielgruppe/standard_region/branche sind reine
Vorbelegungen bzw. Labels — KEINE branchenspezifische Kernlogik.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


def slugify(name: str) -> str:
    """Dateisystem-sicherer, eindeutiger Bezeichner aus einem Namen/Id."""
    s = re.sub(r"[^a-z0-9._-]+", "_", (name or "").lower()).strip("_")
    return s


class MandantenFehler(Exception):
    pass


# ─── Mandant (Datensatz) ─────────────────────────────────────────────────────


@dataclass
class Mandant:
    """Ein Kunde der Plattform mit eigener Akquise-Konfiguration.

    Felder mit Secrets (license_key, anthropic_api_key, bot_token) werden über
    das Register in einer gitignorierten Datei gespeichert — nie eingecheckt.
    """
    mandant_id: str
    name: str = ""
    engine_dir: str = ""              # eigene b2bbot-Instanz (isoliert)
    owner_chat_id: str = ""           # Telegram-Routing (welcher Chat = dieser Kunde)
    bot_token: str = ""               # optional eigener Bot; leer = Plattform-Bot
    license_key: str = ""
    anthropic_api_key: str = ""
    standard_zielgruppe: str = ""     # Vorbelegung, branchenunabhängig
    standard_region: str = ""
    branche: str = ""                 # reines Label / Template-Hinweis
    aktiv: bool = True

    def __post_init__(self) -> None:
        roh = self.mandant_id
        self.mandant_id = slugify(self.mandant_id)
        if not self.mandant_id:
            raise MandantenFehler(
                f"Mandant-ID ergibt keinen gültigen Slug: {roh!r}"
            )
        if not self.name:
            self.name = roh or self.mandant_id

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Mandant":
        erlaubt = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in erlaubt})


# ─── Register ────────────────────────────────────────────────────────────────


class MandantenRegister:
    """Verwaltet alle Mandanten in einer JSON-Datei unter basis_dir.

    Layout:
      <basis_dir>/mandanten.json            ← Stammdaten aller Mandanten
      <basis_dir>/mandanten/<id>/           ← isoliertes data_dir je Mandant
    """

    def __init__(self, basis_dir: str | Path):
        self._basis = Path(basis_dir)
        self._datei = self._basis / "mandanten.json"
        self._basis.mkdir(parents=True, exist_ok=True)
        self._mandanten: dict[str, Mandant] = {}
        self._laden()

    # --- Pfade (Isolation strukturell garantiert) ---

    def data_dir_fuer(self, mandant_id: str) -> Path:
        """Isoliertes Daten-Verzeichnis eines Mandanten (aus der ID abgeleitet)."""
        mid = slugify(mandant_id)
        return self._basis / "mandanten" / mid

    # --- Lesen ---

    def alle(self, nur_aktive: bool = False) -> list[Mandant]:
        werte = sorted(self._mandanten.values(), key=lambda m: m.mandant_id)
        return [m for m in werte if (m.aktiv or not nur_aktive)]

    def holen(self, mandant_id: str) -> Optional[Mandant]:
        return self._mandanten.get(slugify(mandant_id))

    def per_owner(self, owner_chat_id: str) -> Optional[Mandant]:
        """Mandant anhand der Telegram-owner_chat_id (für Routing in F4)."""
        oid = (owner_chat_id or "").strip()
        if not oid:
            return None
        for m in self._mandanten.values():
            if m.owner_chat_id == oid:
                return m
        return None

    # --- Schreiben ---

    def anlegen(self, mandant: Mandant) -> Mandant:
        """Legt einen neuen Mandanten an. Erzwingt Eindeutigkeit + Isolation."""
        if mandant.mandant_id in self._mandanten:
            raise MandantenFehler(f"Mandant '{mandant.mandant_id}' existiert bereits.")
        self._engine_dir_pruefen(mandant)
        self._mandanten[mandant.mandant_id] = mandant
        self.data_dir_fuer(mandant.mandant_id).mkdir(parents=True, exist_ok=True)
        self._speichern()
        return mandant

    def aktualisieren(self, mandant: Mandant) -> Mandant:
        """Aktualisiert einen bestehenden Mandanten (ID muss existieren)."""
        if mandant.mandant_id not in self._mandanten:
            raise MandantenFehler(f"Unbekannter Mandant '{mandant.mandant_id}'.")
        self._engine_dir_pruefen(mandant)
        self._mandanten[mandant.mandant_id] = mandant
        self._speichern()
        return mandant

    def entfernen(self, mandant_id: str) -> bool:
        """Entfernt einen Mandanten aus dem Register (Daten-Verzeichnis bleibt
        bestehen — bewusst, kein automatisches Löschen von Kundendaten)."""
        mid = slugify(mandant_id)
        if mid in self._mandanten:
            del self._mandanten[mid]
            self._speichern()
            return True
        return False

    # --- Isolation ---

    def _engine_dir_pruefen(self, mandant: Mandant) -> None:
        """Kein anderer AKTIVER Mandant darf dieselbe Engine-Instanz nutzen."""
        ed = (mandant.engine_dir or "").strip()
        if not ed:
            return  # leer erlaubt (noch nicht eingerichtet)
        ziel = self._normpfad(ed)
        for m in self._mandanten.values():
            if m.mandant_id == mandant.mandant_id:
                continue
            if m.aktiv and m.engine_dir and self._normpfad(m.engine_dir) == ziel:
                raise MandantenFehler(
                    f"engine_dir '{ed}' wird bereits von Mandant "
                    f"'{m.mandant_id}' genutzt — Engine-Instanzen müssen je "
                    "Mandant getrennt sein (Postfach/Pipeline-Isolation)."
                )

    @staticmethod
    def _normpfad(p: str) -> str:
        try:
            return str(Path(p).expanduser().resolve()).lower()
        except Exception:
            return (p or "").strip().lower()

    # --- Persistenz ---

    def _laden(self) -> None:
        if not self._datei.exists():
            return
        try:
            data = json.loads(self._datei.read_text(encoding="utf-8"))
        except Exception:
            return
        for d in data.get("mandanten", []):
            try:
                m = Mandant.from_dict(d)
                self._mandanten[m.mandant_id] = m
            except Exception:
                continue

    def _speichern(self) -> None:
        nutz = {"mandanten": [m.to_dict() for m in self.alle()]}
        tmp = self._datei.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(nutz, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._datei)

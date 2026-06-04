"""Ergebnis-Reporter — liest Engine-Output und erzeugt kundenfähige Berichte.

Liest aus `output/latest/` der Engine (read-only, kein mine.py-Aufruf).
Erzeugt zwei Formate:
  - text()       → Telegram-Nachricht (reiner Text)
  - strukturiert() → dict für Mini-UI (Schritt 6)

Verwendet in:
  - dialog.py   (Telegram-Abschlussbericht)
  - ui/         (Mini-UI Ansicht 1 + 4, Schritt 6)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from product.operator.expansion_maps import region_erweiterungen, verwandte_branchen
from product.operator.order_schema import Auftrag


@dataclass
class RunDaten:
    """Aufbereitete Rohdaten aus dem Engine-Output."""
    angefordert: int = 0
    gefunden: int = 0
    hot: int = 0            # Score ≥ 60 (Premium)
    mit_email: int = 0
    mit_telefon: int = 0
    mit_ansprechpartner: int = 0
    avg_score: float = 0.0
    dauer_sek: int = 0
    fehler: list[str] = field(default_factory=list)
    pipeline_sendbar: int = 0   # wirklich sendbar (aus outreach_pipeline)


@dataclass
class BerichtErgebnis:
    """Was der Reporter zurückgibt."""
    run: RunDaten
    auftrag: Optional[Auftrag]
    ziel_erreicht: bool
    fehlend: int
    zielgruppe_erschoepft: bool
    vorschlaege: list[str] = field(default_factory=list)
    top_leads: list[dict] = field(default_factory=list)   # für Mini-UI


class Reporter:
    def __init__(self, engine_dir: str | Path):
        self._engine = Path(engine_dir)
        self._latest = self._engine / "output" / "latest"

    # ----------------------------------------------------------------- public

    def bericht(self, auftrag: Optional[Auftrag] = None) -> BerichtErgebnis:
        """Liest den aktuellen Run und erstellt einen BerichtErgebnis."""
        run = self._lade_run_daten()
        pipeline = self._lade_pipeline_sendbar()
        run.pipeline_sendbar = pipeline

        ziel = auftrag.lead_anzahl if auftrag else run.angefordert
        sauber = run.mit_telefon   # Qualitätskriterium: Telefon Pflicht
        fehlend = max(0, ziel - sauber)
        ziel_erreicht = fehlend == 0

        # Erschöpfungs-Erkennung: gefunden ≈ sauber → Region ist leer
        erschoepft = (
            run.gefunden > 0
            and run.gefunden <= sauber + 3
            and not ziel_erreicht
        )

        vorschlaege = self._vorschlaege(auftrag, fehlend, erschoepft)
        top_leads = self._top_leads(limit=10)

        return BerichtErgebnis(
            run=run,
            auftrag=auftrag,
            ziel_erreicht=ziel_erreicht,
            fehlend=fehlend,
            zielgruppe_erschoepft=erschoepft,
            vorschlaege=vorschlaege,
            top_leads=top_leads,
        )

    def text(self, auftrag: Optional[Auftrag] = None) -> str:
        """Kundenfähige Telegram-Nachricht."""
        b = self.bericht(auftrag)
        return self._als_text(b)

    def strukturiert(self, auftrag: Optional[Auftrag] = None) -> dict:
        """Strukturierte Daten für Mini-UI."""
        b = self.bericht(auftrag)
        return {
            "ziel": b.run.angefordert,
            "gefunden": b.run.gefunden,
            "sauber_telefon": b.run.mit_telefon,
            "hot": b.run.hot,
            "mit_ansprechpartner": b.run.mit_ansprechpartner,
            "avg_score": b.run.avg_score,
            "pipeline_sendbar": b.run.pipeline_sendbar,
            "ziel_erreicht": b.ziel_erreicht,
            "fehlend": b.fehlend,
            "zielgruppe_erschoepft": b.zielgruppe_erschoepft,
            "vorschlaege": b.vorschlaege,
            "top_leads": b.top_leads,
            "auftrag": {
                "zielgruppe": auftrag.zielgruppe if auftrag else "",
                "region": auftrag.region if auftrag else "",
                "angebot": auftrag.angebot if auftrag else "",
                "lead_anzahl": auftrag.lead_anzahl if auftrag else 0,
            } if auftrag else {},
        }

    # --------------------------------------------------------------- internal

    def _lade_run_daten(self) -> RunDaten:
        pfad = self._latest / "run_report.json"
        if not pfad.exists():
            return RunDaten()
        try:
            r = json.loads(pfad.read_text(encoding="utf-8"))
            return RunDaten(
                angefordert=r.get("count_requested", 0),
                gefunden=r.get("count_found", 0),
                hot=r.get("count_hot", 0),
                mit_email=r.get("count_with_email", 0),
                mit_telefon=r.get("count_with_phone", 0),
                mit_ansprechpartner=r.get("count_with_director", 0),
                avg_score=round(float(r.get("avg_score", 0)), 1),
                dauer_sek=int(r.get("duration_seconds", 0)),
                fehler=r.get("errors", []) if isinstance(r.get("errors"), list) else [],
            )
        except Exception:
            return RunDaten()

    def _lade_pipeline_sendbar(self) -> int:
        pfad = self._engine / "output" / "outreach_pipeline.json"
        if not pfad.exists():
            return 0
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            return sum(
                1 for e in entries
                if (e.get("ready_to_send") or "").strip().lower() == "yes"
                and not e.get("do_not_resend")
            )
        except Exception:
            return 0

    def _top_leads(self, limit: int = 10) -> list[dict]:
        """Top-Leads aus hot_leads.json — aufbereitet, keine Rohdaten."""
        pfad = self._latest / "hot_leads.json"
        if not pfad.exists():
            return []
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            result = []
            for e in data[:limit]:
                result.append({
                    "firma": e.get("company_name", ""),
                    "ort": e.get("city", ""),
                    "telefon": e.get("phone") or e.get("contact_phone") or "",
                    "ansprechpartner": e.get("contact_name", ""),
                    "website": e.get("website", ""),
                    "score": e.get("score", 0),
                    "branche": e.get("industry", ""),
                })
            return result
        except Exception:
            return []

    @staticmethod
    def _vorschlaege(
        auftrag: Optional[Auftrag], fehlend: int, erschoepft: bool
    ) -> list[str]:
        """Konkrete Handlungsvorschläge bei Target-Fill-Lücken."""
        if fehlend == 0:
            return []

        vorschlaege = []

        if erschoepft:
            vorschlaege.append(
                "Die Zielgruppe in dieser Region scheint ausgeschöpft. "
                "Angrenzende Gebiete einbeziehen?"
            )

        if auftrag:
            gebiete = region_erweiterungen(auftrag.region)
            if gebiete:
                vorschlaege.append(f"Regionale Erweiterung: {', '.join(gebiete[:3])}")

            verwandte = verwandte_branchen(auftrag.zielgruppe)
            if verwandte:
                vorschlaege.append(f"Verwandte Branchen: {', '.join(verwandte[:3])}")

        if fehlend > 50:
            vorschlaege.append(
                f"Ziel um {fehlend} Leads verfehlt — Qualitätskriterien leicht lockern? "
                "(z. B. Telefon nicht Pflicht)"
            )

        return vorschlaege[:3]   # max 3 Vorschläge

    @staticmethod
    def _als_text(b: BerichtErgebnis) -> str:
        r = b.run
        a = b.auftrag
        zeilen = []

        if b.ziel_erreicht:
            zeilen.append("✅ Auftrag abgeschlossen — Ziel vollständig erreicht!\n")
        else:
            zeilen.append("✅ Suche abgeschlossen.\n")

        if a:
            zeilen.append(f"🎯 {a.zielgruppe}  ·  {a.region}  ·  Ziel: {a.lead_anzahl} Leads")

        zeilen.append(f"📊 Ergebnis:")
        zeilen.append(f"   Gefunden:           {r.gefunden}")
        zeilen.append(f"   Mit Telefon:        {r.mit_telefon}  ✅")
        zeilen.append(f"   Mit Ansprechpartner:{r.mit_ansprechpartner}")
        zeilen.append(f"   Sendbar (Pipeline): {r.pipeline_sendbar}")
        if r.avg_score:
            zeilen.append(f"   Ø Score:            {r.avg_score}/100")

        if b.fehlend > 0:
            zeilen.append(f"\n⚠️  {b.fehlend} Leads fehlen zum Ziel.")

        if b.vorschlaege:
            zeilen.append("\n💡 Vorschläge:")
            for v in b.vorschlaege:
                zeilen.append(f"   • {v}")

        if b.ziel_erreicht and r.pipeline_sendbar > 0:
            zeilen.append(
                f"\n👉 {r.pipeline_sendbar} Leads bereit. "
                "Sag mir, wenn du die Mail-Vorschau sehen willst."
            )
        elif not b.ziel_erreicht:
            zeilen.append(
                "\n👉 Sag mir, welchen Vorschlag ich umsetzen soll — "
                "oder ob wir mit den gefundenen Leads starten."
            )

        return "\n".join(zeilen)

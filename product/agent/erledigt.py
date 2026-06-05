"""Erledigt-Speicher — markiert abgeschlossene Termine (Phase: Termin abschließen).

Rein agent-seitig: schreibt NUR in <data_dir>/agent/erledigte_termine.json.
Berührt die Engine nicht (keine Pipeline-Änderung, kein Versand). Ein erledigter
Termin verschwindet aus den Push-Meldungen und der Detail-Ansicht.

Identifikation über entry_key (stabil aus der Engine-Pipeline). Zusätzlich wird
der Firmenname gespeichert, damit der Mensch im Log lesbare Einträge sieht.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class ErledigtSpeicher:
    """Persistente Menge erledigter Termine (entry_key → Metadaten)."""

    def __init__(self, data_dir: str | Path):
        self._pfad = Path(data_dir) / "agent" / "erledigte_termine.json"

    def _laden(self) -> dict:
        if not self._pfad.exists():
            return {}
        try:
            d = json.loads(self._pfad.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _speichern(self, daten: dict) -> None:
        self._pfad.parent.mkdir(parents=True, exist_ok=True)
        self._pfad.write_text(
            json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def ist_erledigt(self, entry_key: str) -> bool:
        if not entry_key:
            return False
        return entry_key in self._laden()

    def erledigte_keys(self) -> set[str]:
        return set(self._laden().keys())

    def abschliessen(self, entry_key: str, firma: str = "") -> bool:
        """Markiert einen Termin als erledigt. True wenn neu, False wenn schon da."""
        if not entry_key:
            return False
        daten = self._laden()
        if entry_key in daten:
            return False
        daten[entry_key] = {
            "firma": firma,
            "abgeschlossen_am": datetime.now().isoformat(timespec="seconds"),
        }
        self._speichern(daten)
        return True

    def wieder_oeffnen(self, entry_key: str) -> bool:
        """Hebt 'erledigt' wieder auf (falls aus Versehen geschlossen)."""
        daten = self._laden()
        if entry_key in daten:
            del daten[entry_key]
            self._speichern(daten)
            return True
        return False

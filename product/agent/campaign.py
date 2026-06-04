"""Kampagnen-Speicher — persistente Trichter-Snapshots über die Zeit (Phase C).

Hält je Kampagne eine Reihe von Snapshots (Zeitstempel + Stufen-Zählung). So
überlebt das Kampagnen-Bild Neustarts und ein Trend wird sichtbar
(„gestern 0 Termine, heute 1"). Die Lead-Wahrheit selbst bleibt die Engine-
Pipeline — hier liegt nur die abgeleitete Verlaufs-Sicht.

JSON in <data_dir>/agent/kampagnen/<name>.json. Atomar geschrieben.
Maschinenraum: nur Zahlen, keine Lead-PII.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _jetzt() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9._-]+", "_", (name or "gesamt").lower()).strip("_")
    return s or "gesamt"


class KampagnenSpeicher:
    """Snapshots je Kampagne, neueste am Ende. Verlauf gekappt auf max_verlauf."""

    def __init__(self, data_dir: str | Path, max_verlauf: int = 500):
        self._dir = Path(data_dir) / "agent" / "kampagnen"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max = max_verlauf

    def _pfad(self, name: str) -> Path:
        return self._dir / f"{_slug(name)}.json"

    def _laden(self, name: str) -> dict:
        pfad = self._pfad(name)
        if pfad.exists():
            try:
                return json.loads(pfad.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"name": name, "erstellt_am": _jetzt(), "snapshots": []}

    def snapshot_speichern(self, name: str, funnel: dict) -> dict:
        """Hängt einen Trichter-Snapshot an und gibt den gespeicherten Eintrag zurück."""
        rec = self._laden(name)
        eintrag = {
            "zeitstempel": _jetzt(),
            "gesamt": funnel.get("gesamt", 0),
            "stufen": dict(funnel.get("stufen", {})),
        }
        rec["snapshots"].append(eintrag)
        if len(rec["snapshots"]) > self._max:
            rec["snapshots"] = rec["snapshots"][-self._max:]
        rec["aktualisiert_am"] = _jetzt()
        self._schreiben(name, rec)
        return eintrag

    def verlauf(self, name: str) -> list[dict]:
        return self._laden(name).get("snapshots", [])

    def letzter(self, name: str) -> Optional[dict]:
        snaps = self.verlauf(name)
        return snaps[-1] if snaps else None

    def alle_kampagnen(self) -> list[str]:
        namen = []
        for pfad in self._dir.glob("*.json"):
            try:
                namen.append(json.loads(pfad.read_text(encoding="utf-8")).get("name", pfad.stem))
            except Exception:
                continue
        return namen

    def _schreiben(self, name: str, rec: dict) -> None:
        pfad = self._pfad(name)
        tmp = pfad.with_name(pfad.name + ".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, pfad)

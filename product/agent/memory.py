"""Lauf-Speicher — schlankes, persistentes Gedächtnis des Agenten (Phase A.3).

Hält pro Auftrag fest: das Ziel, die getanen Schritte und die Funnel-Zahlen.
Persistent als JSON in `<data_dir>/agent/<auftrags_id>.json` — übersteht
Neustarts. (Der volle Funnel-State je Lead kommt erst in Phase C.)

Implementiert den Speicher-Vertrag aus brain.py (aufzeichnen / abschluss),
strukturell — Brain nimmt jeden Speicher mit dieser Schnittstelle.

Sichtbarkeit: Diese Dateien sind Maschinenraum (Admin), nie Kundenansicht.
Sie enthalten Zahlen + kundenfähige Zusammenfassungen, KEINE Lead-Rohdaten.

Packaging-Regel: data_dir wird übergeben, nie hardcodiert.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from product.agent.brain import Aktionstyp, Lage, Laufergebnis, Schritt
from product.operator.order_schema import Auftrag


def _jetzt() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# Abschluss-Typ → kundenfähiger Lauf-Status
_STATUS_NACH_TYP = {
    Aktionstyp.MENSCH_FRAGEN: "wartet_auf_mensch",
    Aktionstyp.FERTIG: "abgeschlossen",
    Aktionstyp.AUFGEBEN: "aufgegeben",
}


class LaufSpeicher:
    """Persistenter Lauf-Speicher. Eine JSON-Datei pro Auftrag (auftrags_id).

    Jeder aufzeichnen()/abschluss()-Aufruf schreibt den vollständigen Datensatz
    atomar (Temp-Datei + os.replace) — ein Absturz mitten im Lauf hinterlässt
    nie eine halb geschriebene Datei.
    """

    def __init__(self, data_dir: str | Path):
        self._dir = Path(data_dir) / "agent"
        self._dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------- Speicher-Vertrag

    def aufzeichnen(self, auftrag: Auftrag, schritt: Schritt, lage: Lage) -> None:
        """Hängt einen ausgeführten Schritt an und aktualisiert die Funnel-Zahlen."""
        record = self._laden_oder_neu(auftrag)
        record["schritte"].append(self._schritt_dict(schritt))
        record["funnel"] = self._funnel_dict(lage)
        record["aktualisiert_am"] = _jetzt()
        self._schreiben(auftrag.auftrags_id, record)

    def abschluss(self, auftrag: Auftrag, ergebnis: Laufergebnis) -> None:
        """Schreibt das Abschluss-Ergebnis: finaler Funnel, Status, Begründung."""
        record = self._laden_oder_neu(auftrag)
        record["funnel"] = self._funnel_dict(ergebnis.lage)
        record["abschluss"] = {
            "typ": ergebnis.abschluss.typ.value,
            "begruendung": ergebnis.abschluss.begruendung,
            "zeitstempel": _jetzt(),
        }
        record["status"] = _STATUS_NACH_TYP.get(ergebnis.abschluss.typ, "laeuft")
        record["aktualisiert_am"] = _jetzt()
        self._schreiben(auftrag.auftrags_id, record)

    def freigabe_aufzeichnen(
        self, auftrags_id: str, gesendet: int, meldung: str, ok: bool
    ) -> bool:
        """Hält eine menschlich bestätigte Freigabe (Versand) am Lauf fest.

        Nur möglich für einen bereits existierenden Lauf. Bei Erfolg wandert der
        Status auf 'gesendet'. Gibt False zurück, wenn der Lauf unbekannt ist.
        """
        pfad = self._pfad(auftrags_id)
        if not pfad.exists():
            return False
        try:
            record = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return False
        record.setdefault("freigaben", []).append({
            "zeitstempel": _jetzt(),
            "gesendet": gesendet,
            "ok": bool(ok),
            "meldung": meldung,
        })
        if ok:
            record["status"] = "gesendet"
        record["aktualisiert_am"] = _jetzt()
        self._schreiben(auftrags_id, record)
        return True

    def nachfass_aufzeichnen(
        self, auftrags_id: str, nachgefasst: int, meldung: str, ok: bool
    ) -> bool:
        """Hält eine menschlich bestätigte Nachfass-Runde am Lauf fest.

        Nur für einen bereits existierenden Lauf. Status wandert bei Erfolg auf
        'nachgefasst'. False, wenn der Lauf unbekannt ist.
        """
        pfad = self._pfad(auftrags_id)
        if not pfad.exists():
            return False
        try:
            record = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return False
        record.setdefault("nachfass", []).append({
            "zeitstempel": _jetzt(),
            "nachgefasst": nachgefasst,
            "ok": bool(ok),
            "meldung": meldung,
        })
        if ok:
            record["status"] = "nachgefasst"
        record["aktualisiert_am"] = _jetzt()
        self._schreiben(auftrags_id, record)
        return True

    # ----------------------------------------------------------------- Lesen (für UI/Telegram, A.5)

    def lauf_anlegen(self, auftrag: Auftrag) -> None:
        """Legt sofort einen 'laeuft'-Datensatz an (falls noch nicht vorhanden).

        Damit erscheint ein gerade gestarteter Lauf unmittelbar in der Übersicht,
        noch bevor der erste Agent-Schritt geschrieben wird (für die UI-Anzeige)."""
        pfad = self._pfad(auftrag.auftrags_id)
        if pfad.exists():
            return
        self._schreiben(auftrag.auftrags_id, self._neuer_record(auftrag))

    def lesen(self, auftrags_id: str) -> Optional[dict]:
        """Liest den vollständigen Datensatz eines Auftrags. None wenn unbekannt."""
        pfad = self._pfad(auftrags_id)
        if not pfad.exists():
            return None
        try:
            return json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return None

    def funnel(self, auftrags_id: str) -> dict:
        """Nur die aktuellen Funnel-Zahlen. Leeres dict wenn unbekannt."""
        record = self.lesen(auftrags_id)
        return record.get("funnel", {}) if record else {}

    def alle_laeufe(self) -> list[dict]:
        """Kompakte Übersicht aller Läufe — neueste zuerst. Für Dashboard/Status."""
        uebersicht: list[dict] = []
        for pfad in self._dir.glob("*.json"):
            try:
                r = json.loads(pfad.read_text(encoding="utf-8"))
            except Exception:
                continue
            uebersicht.append({
                "auftrags_id": r.get("auftrags_id", pfad.stem),
                "auftrag": r.get("auftrag", {}),
                "status": r.get("status", "unbekannt"),
                "funnel": r.get("funnel", {}),
                "schritte_anzahl": len(r.get("schritte", [])),
                "aktualisiert_am": r.get("aktualisiert_am", ""),
            })
        uebersicht.sort(key=lambda x: x.get("aktualisiert_am", ""), reverse=True)
        return uebersicht

    # ----------------------------------------------------------------- intern

    def _pfad(self, auftrags_id: str) -> Path:
        return self._dir / f"{auftrags_id}.json"

    def _laden_oder_neu(self, auftrag: Auftrag) -> dict:
        pfad = self._pfad(auftrag.auftrags_id)
        if pfad.exists():
            try:
                return json.loads(pfad.read_text(encoding="utf-8"))
            except Exception:
                # Korrupte Datei → sauber neu beginnen, nicht abstürzen.
                pass
        return self._neuer_record(auftrag)

    @staticmethod
    def _neuer_record(auftrag: Auftrag) -> dict:
        jetzt = _jetzt()
        return {
            "auftrags_id": auftrag.auftrags_id,
            "auftrag": {
                "zielgruppe": auftrag.zielgruppe,
                "region": auftrag.region,
                "lead_anzahl": auftrag.lead_anzahl,
                "angebot": auftrag.angebot,
            },
            "erstellt_am": jetzt,
            "aktualisiert_am": jetzt,
            "status": "laeuft",
            "funnel": {},
            "schritte": [],
            "abschluss": None,
        }

    @staticmethod
    def _schritt_dict(schritt: Schritt) -> dict:
        erg = schritt.ergebnis
        eintrag = {
            "nummer": schritt.nummer,
            "werkzeug": schritt.werkzeug,
            "typ": schritt.entscheidung.typ.value,
            "begruendung": schritt.entscheidung.begruendung,
            "erfolg": bool(erg.erfolg) if erg is not None else None,
            "zusammenfassung": erg.zusammenfassung if erg is not None else "",
            "zeitstempel": _jetzt(),
        }
        # Fehler nur falls vorhanden (Admin-Maschinenraum, kein Kundenleak).
        if erg is not None and erg.fehler:
            eintrag["fehler"] = erg.fehler
        return eintrag

    @staticmethod
    def _funnel_dict(lage: Lage) -> dict:
        return {
            "ziel": lage.ziel,
            "sendbar": lage.sendbar,
            "fehlend": lage.fehlend,
            "ziel_erreicht": lage.ziel_erreicht,
            "erschoepft": lage.erschoepft,
            "gesucht_schon": lage.gesucht_schon,
        }

    def _schreiben(self, auftrags_id: str, record: dict) -> None:
        pfad = self._pfad(auftrags_id)
        tmp = pfad.with_name(pfad.name + ".tmp")
        tmp.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, pfad)   # atomar (auch auf Windows)

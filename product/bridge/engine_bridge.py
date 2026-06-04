"""Bridge — einzige Verbindung zwischen Produktschicht und B2B-Engine.

V1: genau drei Aktionen (suchen, status_lesen, leads_lesen).
KEIN Send-, Approve- oder Reply-Pfad — diese existieren hier nicht.

Packaging-Regel: engine_dir konfigurierbar, nie hardcodiert.
Muster: analog telegram_seller/engine.py (Subprozess auf mine.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from product.operator.order_schema import Auftrag, AuftragsStatus, ErlaubteAktion


class EngineError(Exception):
    pass


@dataclass
class EngineBrueckenErgebnis:
    ok: bool
    leads_gefunden: int = 0
    leads_sauber: int = 0
    meldung: str = ""
    rohdaten: dict = field(default_factory=dict)


class EngineBridge:
    """Übersetzte bestätigte Aufträge in mine.py-Aufrufe.

    Darf nur von bestätigten Aufträgen aufgerufen werden.
    Erzwingt Sicherheitsgrenzen technisch — kein Verlass auf Prompt.
    """

    def __init__(self, engine_dir: str | Path):
        self.engine_dir = Path(engine_dir)
        mine = self.engine_dir / "mine.py"
        if not mine.exists():
            raise EngineError(
                f"mine.py nicht gefunden: {self.engine_dir}\n"
                "engine_dir in der Konfiguration prüfen."
            )

    # --- Interne Hilfsmethoden ---

    def _run(self, args: list[str], timeout: int = 3600) -> tuple[int, str]:
        cmd = [sys.executable, "mine.py"] + args
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.engine_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, "Zeitüberschreitung — Suche läuft zu lange."
        except FileNotFoundError:
            return -1, "Python oder mine.py nicht gefunden."

    def _output_dir(self) -> Path:
        return self.engine_dir / "output"

    def _pipeline_pfad(self) -> Path:
        return self._output_dir() / "outreach_pipeline.json"

    def _sent_pfad(self) -> Path:
        return self._output_dir() / "sent_log.json"

    # --- Sicherheits-Gate ---

    def _pruefen(self, auftrag: Auftrag, benoetigte_aktion: ErlaubteAktion) -> None:
        if auftrag.status != AuftragsStatus.BESTAETIGT:
            raise EngineError(
                f"Auftrag muss BESTAETIGT sein, ist: {auftrag.status.value}"
            )
        if auftrag.erlaubte_aktion != benoetigte_aktion:
            raise EngineError(
                f"Auftrag erlaubt nur '{auftrag.erlaubte_aktion.value}', "
                f"nicht '{benoetigte_aktion.value}'"
            )

    # --- V1: drei erlaubte Aktionen ---

    def suchen(self, auftrag: Auftrag) -> EngineBrueckenErgebnis:
        """Startet die Lead-Suche. Kein Versand, kein Approve."""
        self._pruefen(auftrag, ErlaubteAktion.SUCHEN_AUFBEREITEN)
        auftrag.starten()

        rc, ausgabe = self._run(
            [
                "-i", auftrag.zielgruppe,
                "-c", auftrag.region,
                "-n", str(auftrag.lead_anzahl),
                "--mode", "local",
            ],
            timeout=3600,
        )

        if rc != 0:
            auftrag.fehler_setzen(ausgabe[-500:])
            return EngineBrueckenErgebnis(ok=False, meldung=ausgabe[-500:])

        status = self.status_lesen()
        return EngineBrueckenErgebnis(
            ok=True,
            leads_gefunden=status.get("pipeline_total", 0),
            leads_sauber=status.get("sendable", 0),
            meldung="Suche abgeschlossen.",
            rohdaten=status,
        )

    def status_lesen(self) -> dict:
        """Liest Statusdaten direkt aus Engine-Output-Dateien (kein mine.py-Aufruf)."""
        pipeline = self._pipeline_pfad()
        sent = self._sent_pfad()
        result = {
            "pipeline_total": 0,
            "sendable": 0,
            "approved": 0,
            "sent_total": 0,
            "already_contacted": 0,
        }
        try:
            if pipeline.exists():
                data = json.loads(pipeline.read_text(encoding="utf-8"))
                entries = data.get("entries", [])
                result["pipeline_total"] = len(entries)
                result["approved"] = sum(
                    1 for e in entries if e.get("approved_for_send")
                )
                result["sendable"] = sum(
                    1 for e in entries
                    if (e.get("ready_to_send") or "").strip().lower() == "yes"
                    and not e.get("do_not_resend")
                )
        except Exception:
            pass
        try:
            if sent.exists():
                data = json.loads(sent.read_text(encoding="utf-8"))
                events = data.get("events", []) if isinstance(data, dict) else []
                result["sent_total"] = sum(1 for e in events if e.get("ok"))
        except Exception:
            pass
        return result

    def leads_lesen(self, limit: int = 50) -> list[dict]:
        """Liest aufbereitete Leadliste für UI/Bericht. Keine Rohdaten."""
        pipeline = self._pipeline_pfad()
        if not pipeline.exists():
            return []
        try:
            data = json.loads(pipeline.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            out = []
            for e in entries:
                if e.get("do_not_resend"):
                    continue
                out.append({
                    "firma": e.get("company_name", ""),
                    "email": e.get("email", ""),
                    "telefon": e.get("phone") or e.get("contact_phone") or "",
                    "ansprechpartner": e.get("contact_name", ""),
                    "website": e.get("website", ""),
                    "score": e.get("score", 0),
                    "ort": e.get("city", ""),
                })
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    # ----------------------------------------------------------------- V2

    def vorschau_lesen(self, limit: int = 30) -> list[dict]:
        """V2: Liest Mail-Vorschau (noch nicht gesendete, sendbare Eintraege).

        Gibt subject + body zurueck — keine Secrets, keine Admin-Felder.
        Kein mine.py-Aufruf, nur Datei-Lesen.
        """
        pipeline = self._pipeline_pfad()
        if not pipeline.exists():
            return []
        try:
            data = json.loads(pipeline.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            out = []
            for e in entries:
                # Nur sendbare, noch nicht gesendete Eintraege
                if e.get("do_not_resend"):
                    continue
                if e.get("sent_message_id"):
                    continue
                if (e.get("ready_to_send") or "").strip().lower() != "yes":
                    continue
                body = e.get("first_email_body", "").strip()
                if not body:
                    continue
                out.append({
                    "firma":           e.get("company_name", ""),
                    "email":           e.get("email", ""),
                    "ansprechpartner": e.get("contact_name", ""),
                    "betreff":         e.get("first_email_subject", ""),
                    "inhalt":          body,
                    "approved":        bool(e.get("approved_for_send")),
                    "entry_key":       e.get("entry_key", ""),
                })
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    def freigabe_ausfuehren(self, limit: int = 20) -> EngineBrueckenErgebnis:
        """V2: Approve + Send — NUR nach explizitem menschlichem Freigabe-Klick aufrufbar.

        Sicherheit: Diese Methode wird vom UI-Server erst aufgerufen,
        wenn der Nutzer im Modal explizit bestaetigt hat.
        Kein CRM-Push, kein Auto-Reply, nur der kontrollierte Versand.
        """
        # Schritt 1: Approve
        rc1, out1 = self._run(
            ["--outreach", "approve", "--outreach-limit", str(limit)],
            timeout=120,
        )
        if rc1 != 0:
            return EngineBrueckenErgebnis(ok=False, meldung=f"Approve fehlgeschlagen:\n{out1[-400:]}")

        # Schritt 2: Send
        rc2, out2 = self._run(
            ["--outreach", "send", "--outreach-limit", str(limit)],
            timeout=300,
        )
        if rc2 != 0:
            return EngineBrueckenErgebnis(ok=False, meldung=f"Send fehlgeschlagen:\n{out2[-400:]}")

        # Status nach dem Senden lesen
        status = self.status_lesen()
        return EngineBrueckenErgebnis(
            ok=True,
            leads_sauber=status.get("sent_total", 0),
            meldung=f"Freigabe ausgefuehrt. Gesendet bisher: {status.get('sent_total', 0)}",
            rohdaten=status,
        )

    # NICHT VORHANDEN — kein CRM-Push, kein Auto-Reply:
    # def crm_push(self): ...
    # def auto_reply(self): ...

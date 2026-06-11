"""Closer-Adapter — startet/stoppt ClouseAgent als eigenständigen Subprozess.

Sicherheitsregeln:
  - ClouseAgent/ wird NICHT verändert, NICHT kopiert.
  - Adapter ist NIEMALS im B2B-Telegram-Fluss erreichbar.
  - Nur über Mini-UI (Admin-Token) startbar.
  - OPENAI_API_KEY und andere Secrets werden NIEMALS geloggt.
  - Subprozess-Output wird gepuffert (max 200 Zeilen), nie persistiert.

Verwendung:
  adapter = CloserAdapter(Path("../../ClouseAgent"))
  adapter.starten()
  adapter.status()
  adapter.stoppen()
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Deque


_MAX_LOG_ZEILEN = 200
_MAX_EVENTS = 200
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_GEHEIME_ENV_VARS = frozenset({
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "BOT_TOKEN",
    "SMTP_PASS", "IMAP_PASS",
})


class CloserFehler(Exception):
    pass


class CloserAdapter:
    """Verwaltet ClouseAgent als Subprozess.

    Instanz lebt so lange wie der Mini-UI-Server läuft.
    Thread-sicher: Lock schützt _prozess und _log.
    """

    def __init__(self, closer_dir: Path) -> None:
        self.closer_dir = Path(closer_dir)
        self._prozess: subprocess.Popen | None = None
        self._log: Deque[str] = deque(maxlen=_MAX_LOG_ZEILEN)
        self._events: Deque[dict] = deque(maxlen=_MAX_EVENTS)
        self._lock = threading.Lock()
        self._log_thread: threading.Thread | None = None

    # ── Öffentliche API ──────────────────────────────────────────────────────

    def starten(self) -> dict:
        """Startet ClouseAgent. Gibt {"ok": bool, "meldung": str} zurück."""
        with self._lock:
            if self._laeuft_unsicher():
                return {"ok": False, "meldung": "Closer läuft bereits."}

            entry = self.closer_dir / "app.py"
            if not entry.exists():
                return {
                    "ok": False,
                    "meldung": f"app.py nicht gefunden: {entry}",
                }

            env = self._umgebung()
            try:
                self._prozess = subprocess.Popen(
                    [sys.executable, "-u", str(entry)],
                    cwd=str(self.closer_dir),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as e:
                return {"ok": False, "meldung": f"Start fehlgeschlagen: {e}"}

            self._log.clear()
            self._events.clear()
            self._log_thread = threading.Thread(
                target=self._log_lesen_loop,
                daemon=True,
                name="closer-log",
            )
            self._log_thread.start()

        return {"ok": True, "meldung": "Closer gestartet.", "pid": self._prozess.pid}

    def stoppen(self) -> dict:
        """Beendet den Subprozess (SIGTERM → SIGKILL nach 5s)."""
        with self._lock:
            if not self._laeuft_unsicher():
                return {"ok": False, "meldung": "Closer läuft nicht."}
            try:
                self._prozess.terminate()
                try:
                    self._prozess.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._prozess.kill()
                    self._prozess.wait(timeout=2)
            except OSError:
                pass
            self._prozess = None

        return {"ok": True, "meldung": "Closer gestoppt."}

    def status(self) -> dict:
        """Gibt aktuellen Status zurück. Kein Secret im Output."""
        with self._lock:
            laeuft = self._laeuft_unsicher()
            pid = self._prozess.pid if laeuft else None
            closer_verfuegbar = (self.closer_dir / "app.py").exists()

        return {
            "laeuft": laeuft,
            "pid": pid,
            "closer_dir": str(self.closer_dir),
            "closer_verfuegbar": closer_verfuegbar,
            "log_zeilen": len(self._log),
        }

    def log_lesen(self, limit: int = 30) -> list[str]:
        """Letzte N Log-Zeilen — gefiltert (keine Secrets)."""
        with self._lock:
            zeilen = list(self._log)
        return zeilen[-limit:] if limit < len(zeilen) else zeilen

    def events_lesen(self, limit: int = 80) -> list[dict]:
        """Letzte N strukturierte Events (transkript / coaching / log)."""
        with self._lock:
            evs = list(self._events)
        return evs[-limit:] if limit < len(evs) else evs

    def skript(self) -> dict:
        """Liest das Gesprächsskript aus playbook.json (für das Dashboard-Panel).

        Gibt nur anzeige-relevante, nicht-geheime Felder zurück.
        """
        pfad = self.closer_dir / "playbook.json"
        try:
            with open(pfad, encoding="utf-8") as f:
                pb = json.load(f)
        except (OSError, ValueError):
            return {"verfuegbar": False}

        produkt = pb.get("produkt", {})
        skript = pb.get("gespraechsskript", {})
        einwaende = [e.get("label", "") for e in pb.get("einwaende", []) if e.get("label")]
        return {
            "verfuegbar": True,
            "produkt_name": produkt.get("name", ""),
            "zielgruppe": produkt.get("zielgruppe", ""),
            "eroeffnung": skript.get("eroeffnung", ""),
            "sympathie": (skript.get("sympathie_saetze") or [None])[0] or "",
            "nutzensatz": skript.get("nutzensatz_universal", ""),
            "abschlussfrage": skript.get("abschlussfrage", ""),
            "termin_frage": skript.get("termin_frage", ""),
            "einwand_labels": einwaende,
        }

    # ── Interne Helfer ───────────────────────────────────────────────────────

    def _laeuft_unsicher(self) -> bool:
        """Prüft ob Prozess noch läuft (OHNE Lock — nur innen aufrufen)."""
        if self._prozess is None:
            return False
        return self._prozess.poll() is None

    def _umgebung(self) -> dict[str, str]:
        """Baut Prozess-Umgebung. Erbt alle Variablen — keine werden geloggt."""
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        # Dashboard-Modus: ClouseAgent gibt strukturierte JSONL-Events aus
        env["CLOSER_OUTPUT"] = "json"
        return env

    def _log_lesen_loop(self) -> None:
        """Liest stdout des Subprozesses, befüllt Roh-Log UND Event-Puffer."""
        try:
            for zeile in self._prozess.stdout:
                bereinigt = zeile.rstrip("\n")
                if _enthaelt_secret(bereinigt):
                    continue
                with self._lock:
                    self._log.append(bereinigt)
                    self._events.append(self._zu_event(bereinigt))
        except Exception:
            pass

    @staticmethod
    def _zu_event(zeile: str) -> dict:
        """Parst eine stdout-Zeile zu einem strukturierten Event.

        JSON-Zeilen mit "typ" werden direkt übernommen. Alles andere
        (Boot-/Status-Ausgaben) wird als Log-Event verpackt (ANSI entfernt).
        """
        s = zeile.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and "typ" in obj:
                    return obj
            except (ValueError, TypeError):
                pass
        return {"typ": "log", "text": _ANSI.sub("", zeile)}


def _enthaelt_secret(zeile: str) -> bool:
    """True wenn die Zeile einen bekannten Secret-Schlüssel enthält."""
    zeile_upper = zeile.upper()
    return any(key in zeile_upper for key in _GEHEIME_ENV_VARS)

"""Mini-UI Server — stdlib-only HTTP-Server für die Kunden-Oberfläche.

Port 8766 (nicht 8765 — das ist der Admin-Cockpit).
Zwei Endpunkte:
  GET /            → dashboard.html
  GET /api/status  → reporter.strukturiert() als JSON

Keine externen Abhängigkeiten. Starten: python server.py
"""
from __future__ import annotations

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_UI_DIR = Path(__file__).parent
_PRODUCT_ROOT = _UI_DIR.parent.parent
sys.path.insert(0, str(_PRODUCT_ROOT))

from product.agent.runner import AgentRunner
from product.bridge.engine_bridge import EngineBridge, EngineError
from product.closer.closer_adapter import CloserAdapter
from product.licensing.features import Feature
from product.licensing.license import LizenzDaten, feature_erlaubt
from product.operator.reporter import Reporter
from product.telegram.config import laden as config_laden

_CONFIG_PFAD = _PRODUCT_ROOT / "product" / "product_config.json"
_SMTP_PFAD = _PRODUCT_ROOT / "product" / "product_smtp.json"

PORT = 8767
_reporter: Reporter | None = None
_bridge: EngineBridge | None = None
_closer: CloserAdapter | None = None
_agent_runner: AgentRunner | None = None   # Agent-Läufe (Lese-Anbindung)
_lizenz: LizenzDaten | None = None   # None = Entwicklungsmodus, alle Features

# Admin-Token (aus Config geladen, leer = kein Schutz aktiv)
_ui_token: str = ""

# Kunden-Endpunkte: nie Token-Pflicht.
# Admin-Endpunkte: Token-Pflicht wenn _ui_token gesetzt.
_KUNDEN_ENDPUNKTE = {"/", "/index.html", "/api/status", "/api/leads",
                     "/api/agent/laeufe"}
_ADMIN_ENDPUNKTE  = {"/api/vorschau", "/api/setup/status",
                     "/api/setup/config", "/api/setup/smtp", "/api/freigabe",
                     "/api/agent/lauf", "/api/agent/freigeben",
                     "/api/closer/status", "/api/closer/log",
                     "/api/closer/starten", "/api/closer/stoppen"}


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass   # Keine Konsolen-Spam bei jedem Request

    def _ist_feature_aktiv(self, feature: Feature) -> bool:
        return feature_erlaubt(_lizenz, feature)

    def _403_feature(self, feature: Feature) -> None:
        body = json.dumps(
            {"ok": False, "meldung": f"Feature '{feature.value}' nicht in Ihrem Lizenz-Paket."},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ist_admin(self) -> bool:
        """True wenn kein Token konfiguriert ODER gültiger Token im Header."""
        if not _ui_token:
            return True
        auth = self.headers.get("X-Access-Token", "")
        return auth == _ui_token

    def _403(self) -> None:
        body = json.dumps(
            {"ok": False, "meldung": "Zugriff verweigert. Admin-Token fehlt oder ungültig."},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_html()
        elif self.path == "/api/status":
            self._serve_status()
        elif self.path == "/api/leads":
            self._serve_leads()
        elif self.path == "/api/agent/laeufe":
            self._serve_agent_laeufe()
        elif self.path.split("?", 1)[0] == "/api/agent/lauf":
            if not self._ist_admin():
                self._403(); return
            self._serve_agent_lauf()
        elif self.path == "/api/vorschau":
            if not self._ist_admin():
                self._403(); return
            self._serve_vorschau()
        elif self.path == "/api/setup/status":
            if not self._ist_admin():
                self._403(); return
            self._serve_setup_status()
        elif self.path == "/api/closer/status":
            if not self._ist_admin():
                self._403(); return
            self._serve_closer_status()
        elif self.path == "/api/closer/log":
            if not self._ist_admin():
                self._403(); return
            self._serve_closer_log()
        else:
            self._404()

    def do_POST(self):
        if self.path == "/api/freigabe":
            if not self._ist_admin():
                self._403(); return
            if not self._ist_feature_aktiv(Feature.FREIGABE):
                self._403_feature(Feature.FREIGABE); return
            self._handle_freigabe()
        elif self.path == "/api/agent/freigeben":
            if not self._ist_admin():
                self._403(); return
            if not self._ist_feature_aktiv(Feature.FREIGABE):
                self._403_feature(Feature.FREIGABE); return
            self._handle_agent_freigeben()
        elif self.path == "/api/setup/config":
            if not self._ist_admin():
                self._403(); return
            self._handle_setup_config()
        elif self.path == "/api/setup/smtp":
            if not self._ist_admin():
                self._403(); return
            self._handle_setup_smtp()
        elif self.path == "/api/closer/starten":
            if not self._ist_admin():
                self._403(); return
            if not self._ist_feature_aktiv(Feature.CLOSER):
                self._403_feature(Feature.CLOSER); return
            self._handle_closer_starten()
        elif self.path == "/api/closer/stoppen":
            if not self._ist_admin():
                self._403(); return
            self._handle_closer_stoppen()
        else:
            self._404()

    def _serve_html(self):
        pfad = _UI_DIR / "dashboard.html"
        if not pfad.exists():
            self.send_error(404, "dashboard.html nicht gefunden")
            return
        data = pfad.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_status(self):
        try:
            daten = _reporter.strukturiert() if _reporter else {}
        except Exception as e:
            daten = {"fehler": str(e)}
        self._json(daten)

    def _serve_leads(self):
        try:
            leads = _bridge.leads_lesen(limit=100) if _bridge else []
        except Exception:
            leads = []
        self._json({"leads": leads})

    def _serve_vorschau(self):
        try:
            mails = _bridge.vorschau_lesen(limit=30) if _bridge else []
        except Exception:
            mails = []
        self._json({"mails": mails, "anzahl": len(mails)})

    def _serve_agent_laeufe(self):
        """GET /api/agent/laeufe — Übersicht aller Agent-Läufe (Kampagnen-Fortschritt).

        Kundenfähig: nur Ziel, Status, Funnel-Zahlen, Schrittanzahl — keine Technik.
        """
        if not _agent_runner:
            self._json({"laeufe": [], "verfuegbar": False})
            return
        try:
            laeufe = _agent_runner.laeufe()
        except Exception:
            laeufe = []
        self._json({"laeufe": laeufe, "verfuegbar": True})

    def _serve_agent_lauf(self):
        """GET /api/agent/lauf?id=... — vollständiger Lauf (Admin, Maschinenraum)."""
        qs = parse_qs(urlparse(self.path).query)
        auftrags_id = (qs.get("id", [""])[0]).strip()
        if not auftrags_id:
            self._json({"ok": False, "meldung": "Parameter 'id' fehlt."})
            return
        if not _agent_runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        lauf = _agent_runner.lauf(auftrags_id)
        if lauf is None:
            self._json({"ok": False, "meldung": "Lauf nicht gefunden."})
            return
        self._json({"ok": True, "lauf": lauf})

    def _handle_freigabe(self):
        """POST /api/freigabe — ERST nach explizitem Nutzer-Modal aufrufbar.

        Liest optionalen limit-Parameter aus dem Request-Body.
        """
        import json as _json
        limit = 20
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                body = self.rfile.read(laenge)
                daten = _json.loads(body)
                limit = int(daten.get("limit", 20))
        except Exception:
            pass

        if not _bridge:
            self._json({"ok": False, "meldung": "Engine nicht verbunden."})
            return

        try:
            # Das Erreichen dieses Endpunkts SETZT den menschlichen Freigabe-Klick
            # voraus (Modal-Bestätigung) → bestaetigt=True.
            ergebnis = _bridge.freigabe_ausfuehren(limit=limit, bestaetigt=True)
            self._json({
                "ok": ergebnis.ok,
                "meldung": ergebnis.meldung,
                "gesendet": ergebnis.leads_sauber,
            })
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _handle_agent_freigeben(self):
        """POST /api/agent/freigeben — Versand eines Agent-Laufs nach Freigabe-Klick.

        Body: {auftrags_id, limit?}. Erreichen dieses Endpunkts = menschliche
        Bestätigung → runner.freigeben(..., bestaetigt=True). Der Runner prüft
        zusätzlich, dass der Lauf am harten Tor steht.
        """
        import json as _json
        auftrags_id = ""
        limit = 20
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
                auftrags_id = str(d.get("auftrags_id", "")).strip()
                limit = int(d.get("limit", 20))
        except Exception:
            pass

        if not auftrags_id:
            self._json({"ok": False, "meldung": "auftrags_id fehlt."})
            return
        if not _agent_runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        try:
            ergebnis = _agent_runner.freigeben(auftrags_id, limit=limit, bestaetigt=True)
            self._json(ergebnis)
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _serve_setup_status(self):
        """GET /api/setup/status — zeigt welche Config-Dateien vorhanden sind."""
        config_ok = _CONFIG_PFAD.exists()
        smtp_ok = _SMTP_PFAD.exists()
        owner_id = ""
        engine_ok = False
        if config_ok:
            try:
                import json as _json
                d = _json.loads(_CONFIG_PFAD.read_text(encoding="utf-8"))
                owner_id = str(d.get("owner_chat_id", ""))
                from pathlib import Path as _Path
                engine_dir = (_CONFIG_PFAD.parent / d.get("engine_dir", "../b2bbot")).resolve()
                engine_ok = engine_dir.exists()
            except Exception:
                pass
        self._json({
            "config_vorhanden": config_ok,
            "smtp_vorhanden": smtp_ok,
            "owner_id_gesetzt": bool(owner_id),
            "engine_gefunden": engine_ok,
        })

    def _handle_setup_config(self):
        """POST /api/setup/config — schreibt product_config.json.

        Nur über localhost erreichbar (Server bindet nur 127.0.0.1).
        Secrets werden NIEMALS geloggt.
        """
        import json as _json
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge == 0:
                self._json({"ok": False, "meldung": "Kein Body."})
                return
            body = self.rfile.read(laenge)
            d = _json.loads(body)
        except Exception as e:
            self._json({"ok": False, "meldung": f"Ungültiger Body: {e}"})
            return

        token = d.get("bot_token", "").strip()
        if not token:
            self._json({"ok": False, "meldung": "bot_token fehlt."})
            return
        owner = str(d.get("owner_chat_id", "")).strip()
        if not owner:
            self._json({"ok": False, "meldung": "owner_chat_id fehlt."})
            return

        config = {
            "_hinweis": "Erzeugt über Mini-UI Setup — nicht ins Git einchecken.",
            "bot_token": token,
            "owner_chat_id": owner,
            "engine_dir": d.get("engine_dir", "../b2bbot"),
            "data_dir": d.get("data_dir", "data"),
            "anthropic_api_key": d.get("anthropic_api_key", ""),
        }
        try:
            _CONFIG_PFAD.parent.mkdir(parents=True, exist_ok=True)
            _CONFIG_PFAD.write_text(
                _json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self._json({"ok": False, "meldung": f"Schreibfehler: {e}"})
            return
        # Kein Secret im Log — nur Erfolg bestätigen
        self._json({"ok": True, "meldung": "product_config.json gespeichert."})

    def _handle_setup_smtp(self):
        """POST /api/setup/smtp — schreibt product_smtp.json.

        Nur über localhost erreichbar. Passwort wird NIEMALS geloggt.
        """
        import json as _json
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge == 0:
                self._json({"ok": False, "meldung": "Kein Body."})
                return
            body = self.rfile.read(laenge)
            d = _json.loads(body)
        except Exception as e:
            self._json({"ok": False, "meldung": f"Ungültiger Body: {e}"})
            return

        host = d.get("smtp_host", "").strip()
        user = d.get("benutzername", "").strip()
        passwort = d.get("passwort", "")
        if not host or not user or not passwort:
            self._json({"ok": False, "meldung": "smtp_host, benutzername und passwort sind Pflicht."})
            return

        smtp_data = {
            "_hinweis": "SMTP-Credentials — niemals ins Git einchecken.",
            "smtp_host": host,
            "smtp_port": int(d.get("smtp_port", 587)),
            "benutzername": user,
            "passwort": passwort,
            "tls": bool(d.get("tls", True)),
            "imap_host": d.get("imap_host", ""),
            "imap_port": int(d.get("imap_port", 993)),
        }
        try:
            _SMTP_PFAD.parent.mkdir(parents=True, exist_ok=True)
            _SMTP_PFAD.write_text(
                _json.dumps(smtp_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self._json({"ok": False, "meldung": f"Schreibfehler: {e}"})
            return
        self._json({"ok": True, "meldung": "product_smtp.json gespeichert."})

    def _serve_closer_status(self):
        if not _closer:
            self._json({"laeuft": False, "closer_verfuegbar": False,
                        "meldung": "Closer nicht konfiguriert."})
            return
        self._json(_closer.status())

    def _serve_closer_log(self):
        if not _closer:
            self._json({"zeilen": []})
            return
        self._json({"zeilen": _closer.log_lesen(limit=50)})

    def _handle_closer_starten(self):
        if not _closer:
            self._json({"ok": False, "meldung": "Closer nicht konfiguriert."})
            return
        self._json(_closer.starten())

    def _handle_closer_stoppen(self):
        if not _closer:
            self._json({"ok": False, "meldung": "Closer nicht konfiguriert."})
            return
        self._json(_closer.stoppen())

    def _json(self, daten: dict | list):
        body = json.dumps(daten, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _404(self):
        self.send_error(404)


def _engine_dir_ermitteln() -> Path:
    """Engine-Dir: aus Config falls vorhanden, sonst Standardpfad daneben."""
    try:
        cfg = config_laden()
        return cfg.engine_dir
    except Exception:
        # Fallback: b2bbot liegt eine Ebene über product/
        return (_PRODUCT_ROOT / "b2bbot").resolve()


def main():
    global _reporter, _bridge, _ui_token, _closer, _lizenz, _agent_runner

    # Config + Lizenz laden (optional — leer = Entwicklungsmodus)
    data_dir = (_PRODUCT_ROOT / "product" / "data").resolve()
    api_key = ""
    try:
        cfg = config_laden()
        data_dir = cfg.data_dir
        api_key = cfg.anthropic_api_key or ""
        if cfg.ui_token:
            _ui_token = cfg.ui_token
            print("[ui] Admin-Token aktiv — Einrichtung/Freigabe geschützt.")
        if cfg.lizenz:
            _lizenz = cfg.lizenz
            print(f"[ui] Lizenz: {cfg.lizenz.zusammenfassung()}")
        else:
            print("[ui] Lizenz: Entwicklungsmodus — alle Features aktiv.")
    except Exception:
        pass

    # Closer-Adapter initialisieren (eigenständig, nie im B2B-Fluss)
    closer_dir = (_PRODUCT_ROOT / "ClouseAgent").resolve()
    _closer = CloserAdapter(closer_dir)
    if closer_dir.exists():
        print(f"[ui] Closer: {closer_dir}")
    else:
        print(f"[ui] Closer: nicht gefunden ({closer_dir}) — Tab deaktiviert.")

    engine_dir = _engine_dir_ermitteln()
    try:
        _bridge = EngineBridge(engine_dir)
        _reporter = Reporter(engine_dir)
        print(f"[ui] Engine: {engine_dir}")
    except EngineError as e:
        print(f"[ui] WARNUNG: {e}")
        print("[ui] UI startet ohne Engine — zeigt leere Daten.")

    # Agent-Anbindung (Lesen): zeigt Kampagnen-Läufe. Funktioniert auch ohne
    # Engine — der Lauf-Speicher braucht nur das data_dir.
    try:
        _agent_runner = AgentRunner(
            bridge=_bridge, data_dir=data_dir,
            reporter=_reporter, api_key=api_key or None,
        )
        print(f"[ui] Agent-Läufe: {Path(data_dir) / 'agent'}")
    except Exception as e:
        print(f"[ui] Agent-Anbindung nicht verfügbar: {e}")

    server = HTTPServer(("127.0.0.1", PORT), _Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"[ui] Mini-UI läuft: {url}")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ui] Gestoppt.")


if __name__ == "__main__":
    main()

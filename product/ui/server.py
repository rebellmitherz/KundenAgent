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
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_UI_DIR = Path(__file__).parent
_PRODUCT_ROOT = _UI_DIR.parent.parent
sys.path.insert(0, str(_PRODUCT_ROOT))

from product.agent.runner import AgentRunner
from product.bridge.engine_bridge import EngineBridge, EngineError
from product.operator.order_schema import Auftrag
from product.closer.closer_adapter import CloserAdapter
from product.licensing.features import Feature
from product.licensing.license import LizenzDaten, feature_erlaubt
from product.operator.reporter import Reporter
from product.telegram.config import laden as config_laden
from product.auth.sessions import (
    mandant_verifizieren, session_erstellen, session_loeschen,
    session_pruefen, sicherstellen as auth_sicherstellen,
    mandanten_lesen, mandant_anlegen, mandant_pw_setzen, mandant_loeschen,
    benutzername_gueltig, sichere_id,
)
from product.profile import store as profil_store

_CONFIG_PFAD = _PRODUCT_ROOT / "product" / "product_config.json"
_SMTP_PFAD = _PRODUCT_ROOT / "product" / "product_smtp.json"


def _vorhandenes_pdf(profil_id: str) -> str:
    """Bestehenden PDF-Pfad eines Profils zurückgeben (oder ''). Damit ein
    Profil-Speichern OHNE Upload den vorhandenen Anhang nicht verliert."""
    pid = str(profil_id or "").strip()
    if not pid:
        return ""
    try:
        for p in profil_store.laden()["profile"]:
            if p["id"] == profil_store._slug(pid):
                return p.get("pdf", "")
    except Exception:
        pass
    return ""


def _erstelle_mandant_runner(mandant_id: str) -> "AgentRunner | None":
    """Erstellt einen AgentRunner mit mandantenspezifischem data_dir."""
    if _bridge is None:
        return None
    # Defense-in-depth: mandant_id pfadsicher machen (Traversal-Schutz),
    # zusätzlich prüfen, dass der Zielpfad unter product/data/ bleibt.
    sichere = sichere_id(mandant_id)
    basis = (_PRODUCT_ROOT / "product" / "data").resolve()
    data_dir = (basis / sichere).resolve()
    if basis not in data_dir.parents:
        print(f"[ui] Abgelehnt: Mandant-Pfad ausserhalb data/ ({mandant_id!r}).")
        return None
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        return AgentRunner(
            bridge=_bridge,
            data_dir=data_dir,
            reporter=_reporter,
            api_key=_api_key_global or None,
        )
    except Exception as e:
        print(f"[ui] Mandant-Runner '{mandant_id}' konnte nicht erstellt werden: {e}")
        return None

PORT = 8767
_reporter: Reporter | None = None
_bridge: EngineBridge | None = None
_closer: CloserAdapter | None = None
_agent_runner: AgentRunner | None = None   # Admin-Runner (globaler data_dir)
_lizenz: LizenzDaten | None = None   # None = Entwicklungsmodus, alle Features
_mandant_runners: dict[str, AgentRunner] = {}   # Runner-Cache pro Mandant
_api_key_global: str = ""
_data_dir_global: str | None = None

# Admin-Token (aus Config geladen, leer = kein Schutz aktiv)
_ui_token: str = ""

# Länder für die Signal-Suche (DACH). Spiegelt signal_discovery._DACH.
_DACH = ("de", "at", "ch")

# Kunden-Endpunkte: nie Token-Pflicht.
# Admin-Endpunkte: Token-Pflicht wenn _ui_token gesetzt.
_KUNDEN_ENDPUNKTE = {"/", "/index.html", "/api/status", "/api/leads",
                     "/api/agent/laeufe", "/api/agent/antworten",
                     "/api/agent/nachfass-faellig", "/api/agent/funnel"}
_ADMIN_ENDPUNKTE  = {"/api/vorschau", "/api/setup/status",
                     "/api/setup/config", "/api/setup/smtp", "/api/freigabe",
                     "/api/agent/lauf", "/api/agent/freigeben",
                     "/api/agent/nachfassen", "/api/agent/auftrag",
                     "/api/agent/signal-suche", "/api/agent/signal-leads",
                     "/api/agent/signal-lead-loeschen", "/api/agent/signal-run-loeschen",
                     "/api/agent/signal-lead-aendern",
                     "/api/agent/termin-abschliessen", "/api/agent/antworten-abrufen",
                     "/api/agent/antwort-loeschen",
                     "/api/closer/status", "/api/closer/log",
                     "/api/closer/events", "/api/closer/skript",
                     "/api/closer/starten", "/api/closer/stoppen",
                     "/api/admin/profile", "/api/admin/profile/aktiv",
                     "/api/admin/profile/loeschen", "/api/admin/profile/pdf"}


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

    def _get_session_token(self) -> str:
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return ""
        c = SimpleCookie()
        try:
            c.load(cookie_header)
        except Exception:
            return ""
        morsel = c.get("session_token")
        return morsel.value if morsel else ""

    def _get_session(self) -> dict | None:
        return session_pruefen(self._get_session_token())

    def _get_runner(self) -> "AgentRunner | None":
        """Gibt den Runner für den aktuellen Mandanten zurück.

        Admin (Token-Auth oder role==admin) → globaler Runner.
        Kunde → mandantenspezifischer Runner mit eigenem data_dir.
        """
        s = self._get_session()
        if s is None or s.get("role") == "admin":
            return _agent_runner
        mandant_id = s["mandant_id"]
        if mandant_id not in _mandant_runners:
            _mandant_runners[mandant_id] = _erstelle_mandant_runner(mandant_id)
        return _mandant_runners[mandant_id]

    def _profil_aktiv_anwenden(self) -> None:
        """Spielt die Env des aktiven Angebot-Profils (Mailtext/Betreff/PDF) auf
        die geteilte Engine-Bridge — VOR jedem Such-/Freigabe-/Nachfass-Aufruf.

        Hinweis (bewusst, v1): Der Erstmail-Text + Betreff werden beim Suchlauf
        in die Pipeline gebacken (pro Lead fest). Der PDF-Anhang wird erst beim
        Senden angehängt. Solange ein Angebot von Suche bis Freigabe aktiv bleibt
        (normaler Ablauf), passt alles zusammen. Wechselt man das Angebot zwischen
        Suche und Freigabe eines NOCH offenen Stapels, folgt der PDF-Anhang dem
        dann aktiven Angebot (Text/Betreff bleiben am Lead fest)."""
        if _bridge is not None:
            try:
                _bridge.profil_setzen(profil_store.aktives_profil_env())
            except Exception as e:  # noqa: BLE001 — Profil darf den Lauf nie blockieren
                print(f"[ui] Profil-Env konnte nicht gesetzt werden: {e}")

    def _ist_eingeloggt(self) -> bool:
        if _ui_token and self.headers.get("X-Access-Token", "") == _ui_token:
            return True
        return self._get_session() is not None

    def _ist_admin(self) -> bool:
        if _ui_token and self.headers.get("X-Access-Token", "") == _ui_token:
            return True
        s = self._get_session()
        return s is not None and s.get("role") == "admin"

    def _redirect_login(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()

    def _401(self) -> None:
        body = json.dumps(
            {"ok": False, "meldung": "Nicht angemeldet."},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(401)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        if self.path in ("/login", "/login.html"):
            self._serve_login()
            return
        if not self._ist_eingeloggt():
            if self.path.startswith("/api/"):
                self._401()
            else:
                self._redirect_login()
            return
        if self.path in ("/", "/index.html"):
            self._serve_html()
        elif self.path == "/api/me":
            s = self._get_session()
            if s:
                self._json({"ok": True, "name": s["name"], "role": s["role"]})
            else:
                self._json({"ok": True, "name": "Admin", "role": "admin"})
        elif self.path == "/api/status":
            self._serve_status()
        elif self.path == "/api/leads":
            self._serve_leads()
        elif self.path == "/api/agent/laeufe":
            self._serve_agent_laeufe()
        elif self.path == "/api/agent/antworten":
            self._serve_agent_antworten()
        elif self.path == "/api/agent/signal-leads":
            self._serve_signal_leads()
        elif self.path == "/api/agent/nachfass-faellig":
            self._serve_agent_nachfass_faellig()
        elif self.path.split("?", 1)[0] == "/api/agent/funnel":
            self._serve_agent_funnel()
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
        elif self.path == "/api/closer/events":
            if not self._ist_admin():
                self._403(); return
            self._serve_closer_events()
        elif self.path == "/api/closer/skript":
            if not self._ist_admin():
                self._403(); return
            self._serve_closer_skript()
        elif self.path == "/api/admin/mandanten":
            if not self._ist_admin():
                self._403(); return
            self._serve_mandanten_list()
        elif self.path == "/api/admin/profile":
            if not self._ist_admin():
                self._403(); return
            self._serve_profile_list()
        else:
            self._404()

    def do_POST(self):
        if self.path == "/api/login":
            self._handle_login()
            return
        if self.path == "/api/logout":
            self._handle_logout()
            return
        if not self._ist_eingeloggt():
            self._401()
            return
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
        elif self.path == "/api/agent/nachfassen":
            if not self._ist_admin():
                self._403(); return
            if not self._ist_feature_aktiv(Feature.FREIGABE):
                self._403_feature(Feature.FREIGABE); return
            self._handle_agent_nachfassen()
        elif self.path == "/api/agent/auftrag":
            if not self._ist_admin():
                self._403(); return
            self._handle_agent_auftrag()
        elif self.path == "/api/agent/signal-suche":
            self._handle_agent_signal_suche()
        elif self.path == "/api/agent/signal-lead-loeschen":
            if not self._ist_admin():
                self._403(); return
            self._handle_signal_lead_loeschen()
        elif self.path == "/api/agent/signal-run-loeschen":
            if not self._ist_admin():
                self._403(); return
            self._handle_signal_run_loeschen()
        elif self.path == "/api/agent/signal-lead-aendern":
            if not self._ist_admin():
                self._403(); return
            self._handle_signal_lead_aendern()
        elif self.path == "/api/agent/termin-abschliessen":
            if not self._ist_admin():
                self._403(); return
            self._handle_agent_termin_abschliessen()
        elif self.path == "/api/agent/antworten-abrufen":
            if not self._ist_admin():
                self._403(); return
            self._handle_agent_antworten_abrufen()
        elif self.path == "/api/agent/antwort-loeschen":
            if not self._ist_admin():
                self._403(); return
            self._handle_agent_antwort_loeschen()
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
        elif self.path == "/api/admin/mandanten":
            if not self._ist_admin():
                self._403(); return
            self._handle_mandanten_create()
        elif self.path.startswith("/api/admin/mandanten/"):
            if not self._ist_admin():
                self._403(); return
            self._handle_mandanten_update()
        elif self.path == "/api/admin/profile":
            if not self._ist_admin():
                self._403(); return
            self._handle_profile_save()
        elif self.path == "/api/admin/profile/aktiv":
            if not self._ist_admin():
                self._403(); return
            self._handle_profile_aktiv()
        elif self.path == "/api/admin/profile/loeschen":
            if not self._ist_admin():
                self._403(); return
            self._handle_profile_loeschen()
        elif self.path.split("?", 1)[0] == "/api/admin/profile/pdf":
            if not self._ist_admin():
                self._403(); return
            self._handle_profile_pdf()
        else:
            self._404()

    def _serve_login(self):
        pfad = _UI_DIR / "login.html"
        if not pfad.exists():
            self.send_error(404, "login.html nicht gefunden")
            return
        data = pfad.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_login(self):
        import json as _json
        d = {}
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
        except Exception:
            pass
        benutzername = str(d.get("benutzername", "")).strip()
        passwort = str(d.get("passwort", ""))
        if not benutzername or not passwort:
            self._json({"ok": False, "meldung": "Benutzername und Passwort erforderlich."})
            return
        mandant = mandant_verifizieren(_PRODUCT_ROOT, benutzername, passwort)
        if not mandant:
            self._json({"ok": False, "meldung": "Ungültige Anmeldedaten."})
            return
        token = session_erstellen(mandant)
        body = _json.dumps({
            "ok": True,
            "name": mandant.get("name", benutzername),
            "role": mandant.get("role", "kunde"),
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Set-Cookie",
            f"session_token={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800",
        )
        self.end_headers()
        self.wfile.write(body)

    def _handle_logout(self):
        session_loeschen(self._get_session_token())
        body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Set-Cookie",
            "session_token=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
        )
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        s = self._get_session()
        rolle = s.get("role", "kunde") if s else "admin"  # Token-Auth = admin
        dateiname = "dashboard.html" if rolle == "admin" else "kunden_dashboard.html"
        pfad = _UI_DIR / dateiname
        if not pfad.exists():
            self.send_error(404, f"{dateiname} nicht gefunden")
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
        runner = self._get_runner()
        if not runner:
            self._json({"laeufe": [], "verfuegbar": False})
            return
        try:
            laeufe = runner.laeufe()
        except Exception:
            laeufe = []
        self._json({"laeufe": laeufe, "verfuegbar": True})

    def _serve_agent_antworten(self):
        """GET /api/agent/antworten — eingehende Antworten (read-only, kundenfähig).

        Hebt Terminwünsche hervor. Kein Versand, nur Lesen.
        """
        runner = self._get_runner()
        if not runner:
            self._json({"antworten": [], "termine": 0, "bericht": "", "verfuegbar": False})
            return
        try:
            antworten = runner.antworten(limit=30)
            termine = runner.termin_signale(limit=30)
            bericht = runner.antworten_bericht(limit=30)
        except Exception:
            antworten, termine, bericht = [], [], ""
        self._json({
            "antworten": antworten,
            "termine": len(termine),
            "bericht": bericht,
            "verfuegbar": True,
        })

    def _serve_agent_funnel(self):
        """GET /api/agent/funnel[?campaign=..] — Kampagnen-Trichter (read-only).

        Zeigt je Lead die Stufe + Zählung + kundenfähigen Bericht. Kein Versand.
        """
        runner = self._get_runner()
        if not runner:
            self._json({"funnel": {"gesamt": 0, "stufen": {}, "leads": []},
                        "bericht": "", "verfuegbar": False})
            return
        qs = parse_qs(urlparse(self.path).query)
        campaign = (qs.get("campaign", [""])[0]).strip() or None
        try:
            funnel = runner.funnel(campaign=campaign)
            bericht = runner.funnel_bericht(campaign=campaign)
        except Exception:
            funnel, bericht = {"gesamt": 0, "stufen": {}, "leads": []}, ""
        self._json({"funnel": funnel, "bericht": bericht, "verfuegbar": True})

    def _serve_agent_nachfass_faellig(self):
        """GET /api/agent/nachfass-faellig — wer ist fällig (read-only, kundenfähig)."""
        runner = self._get_runner()
        if not runner:
            self._json({"faellig": [], "anzahl": 0, "verfuegbar": False})
            return
        try:
            faellig = runner.nachfass_faellig(limit=50)
        except Exception:
            faellig = []
        self._json({"faellig": faellig, "anzahl": len(faellig), "verfuegbar": True})

    def _handle_agent_nachfassen(self):
        """POST /api/agent/nachfassen — Nachfass-Versand nach Freigabe-Klick.

        Body: {auftrags_id, limit?}. Erreichen = menschliche Bestätigung →
        runner.nachfassen(..., bestaetigt=True). Der Runner prüft zusätzlich,
        dass der Lauf bereits gesendet hat.
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
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        try:
            self._profil_aktiv_anwenden()
            ergebnis = runner.nachfassen(auftrags_id, limit=limit, bestaetigt=True)
            self._json(ergebnis)
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _handle_agent_auftrag(self):
        """POST /api/agent/auftrag — startet eine Lead-Kampagne aus der UI.

        Body: {zielgruppe, region, anzahl, angebot}. Der Agent läuft asynchron
        (Hintergrund-Thread), sucht und füllt selbst auf, STOPPT am harten Tor
        (Senden = Mensch). Antwort: {ok, auftrags_id}.
        """
        import json as _json
        d = {}
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
        except Exception:
            pass

        zielgruppe = str(d.get("zielgruppe", "")).strip()
        region = str(d.get("region", "")).strip()
        angebot = str(d.get("angebot", "")).strip()
        try:
            anzahl = int(d.get("anzahl", 0))
        except (TypeError, ValueError):
            anzahl = 0

        if not zielgruppe or not region:
            self._json({"ok": False, "meldung": "Zielgruppe und Region sind Pflicht."})
            return
        if anzahl <= 0:
            self._json({"ok": False, "meldung": "Bitte eine Lead-Anzahl > 0 angeben."})
            return
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return

        try:
            self._profil_aktiv_anwenden()
            auftrag = Auftrag(
                zielgruppe=zielgruppe, region=region,
                lead_anzahl=anzahl, angebot=angebot or "—",
            )
            auftrags_id = runner.starten_im_hintergrund(auftrag)
            self._json({
                "ok": True,
                "auftrags_id": auftrags_id,
                "meldung": f"Kampagne gestartet: {zielgruppe} · {region} · {anzahl} Leads.",
            })
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _handle_agent_signal_suche(self):
        """POST /api/agent/signal-suche — startet eine Signal-Suche (High-Intent).

        Body: {zielgruppe, region, anzahl, signal_typ}. Läuft asynchron, sucht
        Firmen anhand eines Kaufsignals statt flach nach Branche. KEIN Versand.
        Antwort: {ok, meldung}.
        """
        import json as _json
        d = {}
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
        except Exception:
            pass

        zielgruppe = str(d.get("zielgruppe", "")).strip()
        region = str(d.get("region", "")).strip()   # Stadt — jetzt OPTIONAL
        angebot = str(d.get("angebot", "")).strip()
        # Signal-Stapelung: "signale" (Liste) bevorzugt, sonst "signal_typ" (String).
        roh_sig = d.get("signale", d.get("signal_typ", "sales_hiring"))
        if isinstance(roh_sig, str):
            signale = [roh_sig.strip()] if roh_sig.strip() else []
        else:
            signale = [str(s).strip().lower() for s in (roh_sig or []) if str(s).strip()]
        signale = list(dict.fromkeys(signale)) or ["sales_hiring"]
        # LinkedIn-Quellen (Toggles). Pro nur wirksam mit APIFY_API_KEY (sonst 0 €).
        linkedin_web = bool(d.get("linkedin_web", False))
        linkedin_pro = bool(d.get("linkedin_pro", False))
        # Länder-Auswahl (DACH). Akzeptiert Liste ["de","at"] ODER String "dach"/"de".
        roh_land = d.get("laender", d.get("land", ["de"]))
        if isinstance(roh_land, str):
            roh_land = _DACH if roh_land.strip().lower() == "dach" else [roh_land]
        laender = tuple(str(x).strip().lower() for x in (roh_land or []) if str(x).strip())
        laender = tuple(l for l in laender if l in _DACH) or ("de",)
        try:
            anzahl = int(d.get("anzahl", 0))
        except (TypeError, ValueError):
            anzahl = 0

        from product.bridge.signal_discovery import SIGNAL_TYPES, ist_rollenwort
        unbekannt = [s for s in signale if s not in SIGNAL_TYPES]
        if unbekannt:
            self._json({"ok": False, "meldung": f"Unbekannter Signaltyp: {', '.join(unbekannt)}"})
            return
        if not zielgruppe:
            self._json({"ok": False, "meldung": "Zielbranche ist Pflicht."})
            return
        # Intake-Trennung (Premium-Gate, Schritt 5): die ZIELBRANCHE muss eine echte
        # Branche sein, kein Signal/keine Rolle. „Vertrieb" als Branche matcht jede
        # Firma → genau das macht die Ausgabe weich. Das Kaufsignal wählt man separat.
        if ist_rollenwort(zielgruppe):
            self._json({"ok": False, "meldung":
                f"„{zielgruppe}“ ist ein Signal/eine Rolle, keine Branche. Bitte die "
                "ZIELBRANCHE angeben (z. B. Maschinenbau, IT-Dienstleister, Handwerk, "
                "B2B-SaaS) — das Kaufsignal wählst du darunter per Checkbox."})
            return
        if anzahl <= 0:
            self._json({"ok": False, "meldung": "Bitte eine Lead-Anzahl > 0 angeben."})
            return
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        try:
            self._profil_aktiv_anwenden()
            auftrag = Auftrag(
                zielgruppe=zielgruppe, region=region,
                lead_anzahl=anzahl, angebot=angebot or "—",
            )
            runner.signal_suche_im_hintergrund(
                auftrag, signal_typ=signale, laender=laender,
                linkedin_web=linkedin_web, linkedin_pro=linkedin_pro)
            wo = region if region else (", ".join(l.upper() for l in laender))
            stapel = f" · {len(signale)} Signale gestapelt" if len(signale) > 1 else ""
            self._json({
                "ok": True,
                "meldung": f"Signal-Suche gestartet: {zielgruppe} · {wo}{stapel}. "
                           "Ergebnisse erscheinen, sobald der Lauf fertig ist.",
            })
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _serve_signal_leads(self):
        """GET /api/agent/signal-leads — Stand + Leads der Signal-Suche."""
        runner = self._get_runner()
        if not runner:
            self._json({"status": "keiner", "meldung": "Agent nicht verbunden.", "leads": []})
            return
        try:
            stand = runner.signal_status()
            runs = runner.signal_runs()
            # Flach für Abwärtskompatibilität (alte UI-Pfade); neu: runs (getaggt).
            leads = [l for r in runs for l in r.get("leads", [])]
            self._json({
                "status": stand.get("status", "keiner"),
                "meldung": stand.get("meldung", ""),
                "runs": runs,
                "leads": leads,
            })
        except Exception as e:
            self._json({"status": "fehler", "meldung": str(e), "runs": [], "leads": []})

    def _signal_body(self) -> dict:
        import json as _json
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
                return d if isinstance(d, dict) else {}
        except Exception:
            pass
        return {}

    def _handle_signal_lead_loeschen(self):
        """POST /api/agent/signal-lead-loeschen — einen Lead löschen. Body: {lead_id}."""
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."}); return
        lead_id = str(self._signal_body().get("lead_id", "")).strip()
        if not lead_id:
            self._json({"ok": False, "meldung": "lead_id fehlt."}); return
        n = runner.signal_lead_loeschen(lead_id)
        self._json({"ok": n > 0, "geloescht": n})

    def _handle_agent_antwort_loeschen(self):
        """POST /api/agent/antwort-loeschen — eine eingegangene Antwort löschen. Body: {id}."""
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."}); return
        reply_id = str(self._signal_body().get("id", "")).strip()
        if not reply_id:
            self._json({"ok": False, "meldung": "id fehlt."}); return
        n = runner.antwort_loeschen(reply_id)
        self._json({"ok": n > 0, "geloescht": n})

    def _handle_signal_run_loeschen(self):
        """POST /api/agent/signal-run-loeschen — ganze Suche löschen. Body: {run_id}."""
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."}); return
        run_id = str(self._signal_body().get("run_id", "")).strip()
        if not run_id:
            self._json({"ok": False, "meldung": "run_id fehlt."}); return
        n = runner.signal_run_loeschen(run_id)
        self._json({"ok": n > 0, "geloescht": n})

    def _handle_signal_lead_aendern(self):
        """POST /api/agent/signal-lead-aendern — Lead inline editieren.
        Body: {lead_id, fields:{company_name?,phone?,email?,contact_full_name?,notiz?}}."""
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."}); return
        d = self._signal_body()
        lead_id = str(d.get("lead_id", "")).strip()
        fields = d.get("fields") if isinstance(d.get("fields"), dict) else {}
        if not lead_id or not fields:
            self._json({"ok": False, "meldung": "lead_id oder fields fehlt."}); return
        n = runner.signal_lead_aendern(lead_id, fields)
        self._json({"ok": n > 0, "geaendert": n})

    def _handle_agent_termin_abschliessen(self):
        """POST /api/agent/termin-abschliessen — Termin als erledigt markieren.

        Body: {firma}. Agent-lokal (Engine unberührt). Antwort: {ok, meldung}.
        """
        import json as _json
        firma = ""
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
                firma = str(d.get("firma", "")).strip()
        except Exception:
            pass
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        try:
            self._json(runner.termin_abschliessen(firma))
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _handle_agent_antworten_abrufen(self):
        """POST /api/agent/antworten-abrufen — E: Postfach aktiv abrufen.

        Read-only zum Postfach (IMAP), kein Versand: die Bridge erzwingt alle
        Auto-Send-Gates auf AUS. Antwort: {ok, neu, gesamt, meldung}.
        """
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        try:
            self._json(runner.antworten_abrufen())
        except Exception as e:
            self._json({"ok": False, "meldung": str(e)})

    def _serve_agent_lauf(self):
        """GET /api/agent/lauf?id=... — vollständiger Lauf (Admin, Maschinenraum)."""
        qs = parse_qs(urlparse(self.path).query)
        auftrags_id = (qs.get("id", [""])[0]).strip()
        if not auftrags_id:
            self._json({"ok": False, "meldung": "Parameter 'id' fehlt."})
            return
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        lauf = runner.lauf(auftrags_id)
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

        # Serverseitige Obergrenze (Mini-Patch): erlaubt 1..50, sonst Default 20.
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 20

        if not _bridge:
            self._json({"ok": False, "meldung": "Engine nicht verbunden."})
            return

        try:
            # Das Erreichen dieses Endpunkts SETZT den menschlichen Freigabe-Klick
            # voraus (Modal-Bestätigung) → bestaetigt=True.
            self._profil_aktiv_anwenden()
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
        runner = self._get_runner()
        if not runner:
            self._json({"ok": False, "meldung": "Agent nicht verbunden."})
            return
        try:
            self._profil_aktiv_anwenden()
            ergebnis = runner.freigeben(auftrags_id, limit=limit, bestaetigt=True)
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

    def _serve_closer_events(self):
        if not _closer:
            self._json({"events": []})
            return
        self._json({"events": _closer.events_lesen(limit=80)})

    def _serve_closer_skript(self):
        if not _closer:
            self._json({"verfuegbar": False})
            return
        self._json(_closer.skript())

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

    def _serve_mandanten_list(self):
        mandanten = mandanten_lesen(_PRODUCT_ROOT)
        selbst = self._get_session()
        sichtbar = []
        for m in mandanten:
            sichtbar.append({
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "benutzername": m["benutzername"],
                "role": m.get("role", "kunde"),
                "ist_selbst": selbst and m["id"] == selbst["mandant_id"],
            })
        self._json({"ok": True, "mandanten": sichtbar})

    def _handle_mandanten_create(self):
        import json as _json
        d = {}
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
        except Exception:
            pass
        benutzername = str(d.get("benutzername", "")).strip()
        passwort = str(d.get("passwort", ""))
        name = str(d.get("name", "")).strip()
        if not benutzername or not passwort:
            self._json({"ok": False, "meldung": "Benutzername und Passwort erforderlich."})
            return
        if not benutzername_gueltig(benutzername):
            self._json({"ok": False, "meldung": "Benutzername: nur a-z, 0-9, - und _ (2-40 Zeichen, Kleinschreibung)."})
            return
        if len(passwort) < 6:
            self._json({"ok": False, "meldung": "Passwort muss mindestens 6 Zeichen sein."})
            return
        m = mandant_anlegen(_PRODUCT_ROOT, benutzername, passwort, name or benutzername, "kunde")
        if not m:
            self._json({"ok": False, "meldung": "Benutzername existiert bereits."})
            return
        self._json({
            "ok": True,
            "meldung": f"Kunde '{name or benutzername}' erstellt.",
            "mandant": {"id": m["id"], "name": m["name"], "benutzername": m["benutzername"]},
        })

    def _handle_mandanten_update(self):
        import json as _json
        path = self.path.split("?")[0]
        parts = path.rsplit("/", 1)
        if len(parts) != 2:
            self._json({"ok": False, "meldung": "Ungültiger Pfad."})
            return
        benutzername = parts[1].strip()
        d = {}
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
        except Exception:
            pass
        aktion = d.get("action", "").strip()
        if aktion == "pw":
            pw = str(d.get("passwort", ""))
            if not pw or len(pw) < 6:
                self._json({"ok": False, "meldung": "Passwort mindestens 6 Zeichen."})
                return
            if mandant_pw_setzen(_PRODUCT_ROOT, benutzername, pw):
                self._json({"ok": True, "meldung": f"Passwort für '{benutzername}' gesetzt."})
            else:
                self._json({"ok": False, "meldung": "Fehler beim Setzen des Passworts."})
        elif aktion == "delete":
            if mandant_loeschen(_PRODUCT_ROOT, benutzername):
                self._json({"ok": True, "meldung": f"Kunde '{benutzername}' gelöscht."})
            else:
                self._json({"ok": False, "meldung": "Kunde konnte nicht gelöscht werden."})
        else:
            self._json({"ok": False, "meldung": "Aktion nicht erkannt."})

    # --- Angebot-Profile (Multi-Offer) — alle Admin-only -------------------

    def _lese_json_body(self) -> dict:
        """Liest den Request-Body als JSON-Objekt (leer/kaputt → {})."""
        import json as _json
        try:
            laenge = int(self.headers.get("Content-Length", 0))
            if laenge > 0:
                d = _json.loads(self.rfile.read(laenge))
                return d if isinstance(d, dict) else {}
        except Exception:
            pass
        return {}

    def _serve_profile_list(self):
        """GET /api/admin/profile — alle Angebot-Profile + aktive ID."""
        try:
            data = profil_store.laden()
            self._json({"ok": True, "aktiv": data["aktiv"], "profile": data["profile"]})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "meldung": str(e)})

    def _handle_profile_save(self):
        """POST /api/admin/profile — Profil anlegen/aktualisieren (Upsert by id).

        Body: {id?, name, branche, stadt, lead_anzahl, betreff, mailtext}.
        Der PDF-Anhang wird separat über /api/admin/profile/pdf hochgeladen.
        """
        d = self._lese_json_body()
        name = str(d.get("name", "")).strip()
        if not name:
            self._json({"ok": False, "meldung": "Name ist Pflicht."})
            return
        try:
            data = profil_store.profil_speichern({
                "id": d.get("id", ""),
                "name": name,
                "branche": d.get("branche", ""),
                "stadt": d.get("stadt", ""),
                "lead_anzahl": d.get("lead_anzahl", 10),
                "betreff": d.get("betreff", ""),
                "mailtext": d.get("mailtext", ""),
                # pdf bewusst NICHT aus diesem Body übernehmen — Upload-Pfad ist
                # die einzige Quelle, sonst überschriebe ein Speichern ohne pdf
                # den bestehenden Anhang. Vorhandenen pdf-Pfad erhalten:
                "pdf": _vorhandenes_pdf(d.get("id", "")),
            })
            self._json({"ok": True, "aktiv": data["aktiv"], "profile": data["profile"]})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "meldung": str(e)})

    def _handle_profile_aktiv(self):
        """POST /api/admin/profile/aktiv — aktives Angebot umschalten. Body: {id}."""
        d = self._lese_json_body()
        pid = str(d.get("id", "")).strip()
        if not pid:
            self._json({"ok": False, "meldung": "id fehlt."})
            return
        try:
            data = profil_store.aktiv_setzen(pid)
            # Sofort auf die geteilte Bridge anwenden (nächster Lauf nutzt es ohnehin)
            self._profil_aktiv_anwenden()
            self._json({"ok": True, "aktiv": data["aktiv"], "profile": data["profile"]})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "meldung": str(e)})

    def _handle_profile_loeschen(self):
        """POST /api/admin/profile/loeschen — Profil entfernen. Body: {id}."""
        d = self._lese_json_body()
        pid = str(d.get("id", "")).strip()
        if not pid:
            self._json({"ok": False, "meldung": "id fehlt."})
            return
        try:
            data = profil_store.profil_loeschen(pid)
            self._json({"ok": True, "aktiv": data["aktiv"], "profile": data["profile"]})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "meldung": str(e)})

    def _handle_profile_pdf(self):
        """POST /api/admin/profile/pdf?id=<profil_id> — PDF-Anhang hochladen.

        Roher PDF-Body (application/pdf). Speichert unter product/data/
        _profile_assets/<id>.pdf und trägt den Pfad ins Profil ein.
        """
        from urllib.parse import urlparse as _urlparse, parse_qs as _parse_qs
        qs = _parse_qs(_urlparse(self.path).query)
        pid = (qs.get("id", [""])[0]).strip()
        if not pid:
            self._json({"ok": False, "meldung": "id (Query-Parameter) fehlt."})
            return
        try:
            laenge = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            laenge = 0
        if laenge <= 0:
            self._json({"ok": False, "meldung": "Leerer Upload."})
            return
        if laenge > 8 * 1024 * 1024:
            self._json({"ok": False, "meldung": "PDF zu groß (max. 8 MB)."})
            return
        daten = self.rfile.read(laenge)
        if not daten.startswith(b"%PDF"):
            self._json({"ok": False, "meldung": "Datei ist kein PDF."})
            return
        try:
            pfad = profil_store.pdf_speichern(pid, daten)
            # PDF-Pfad ins (bestehende) Profil eintragen
            data = profil_store.laden()
            ziel = next((p for p in data["profile"] if p["id"] == profil_store._slug(pid)), None)
            if ziel is None:
                self._json({"ok": False, "meldung": "Profil nicht gefunden — erst speichern."})
                return
            ziel["pdf"] = pfad
            data = profil_store.speichern(data)
            self._json({"ok": True, "pdf": pfad, "aktiv": data["aktiv"], "profile": data["profile"]})
        except Exception as e:  # noqa: BLE001
            self._json({"ok": False, "meldung": str(e)})

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
    global _api_key_global, _data_dir_global

    auth_sicherstellen(_PRODUCT_ROOT)

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
        # Aktives Angebot-Profil (Mailtext/Betreff/PDF) initial auf die Bridge.
        try:
            _bridge.profil_setzen(profil_store.aktives_profil_env())
            print(f"[ui] Aktives Angebot: {profil_store.aktives_profil()['name']}")
        except Exception as e:  # noqa: BLE001
            print(f"[ui] Angebot-Profil nicht geladen: {e}")
        print(f"[ui] Engine: {engine_dir}")
    except EngineError as e:
        print(f"[ui] WARNUNG: {e}")
        print("[ui] UI startet ohne Engine — zeigt leere Daten.")

    # Agent-Anbindung (Lesen): zeigt Kampagnen-Läufe. Funktioniert auch ohne
    # Engine — der Lauf-Speicher braucht nur das data_dir.
    _api_key_global = api_key
    _data_dir_global = str(data_dir)
    try:
        _agent_runner = AgentRunner(
            bridge=_bridge, data_dir=data_dir,
            reporter=_reporter, api_key=api_key or None,
        )
        print(f"[ui] Agent-Läufe (Admin): {Path(data_dir) / 'agent'}")
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

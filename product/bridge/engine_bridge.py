"""Bridge — einzige Verbindung zwischen Produktschicht und B2B-Engine.

V1: genau drei Aktionen (suchen, status_lesen, leads_lesen).
KEIN Send-, Approve- oder Reply-Pfad — diese existieren hier nicht.

Packaging-Regel: engine_dir konfigurierbar, nie hardcodiert.
Muster: analog telegram_seller/engine.py (Subprozess auf mine.py).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
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

    def _run(
        self,
        args: list[str],
        timeout: int = 3600,
        extra_env: Optional[dict] = None,
    ) -> tuple[int, str]:
        cmd = [sys.executable, "mine.py"] + args
        # extra_env wird NUR für diesen einen Subprozess gesetzt (Kopie der
        # Umgebung) — niemals global. So bleibt z. B. die Sende-Bestätigung
        # OUTREACH_SEND_CONFIRMED streng auf genau den einen Send-Aufruf begrenzt.
        env = None
        if extra_env:
            env = os.environ.copy()
            env.update(extra_env)
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.engine_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                env=env,
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

        # Scrape-Budget an die Auftragsgröße koppeln. Ohne diese Variable scrapt
        # die Engine pro Lauf mindestens 30 Websites (max(count, 30)) — bei nur
        # wenigen gewünschten Leads ist das massiv überdimensioniert und der
        # Hauptgrund für lange Laufzeiten / Hänger an toten Seiten. Wir setzen
        # ein faires Budget (genug Puffer zum Filtern, aber gedeckelt) scoped auf
        # genau diesen Such-Subprozess. Kein Versand, nur Suche.
        try:
            budget = min(max(int(auftrag.lead_anzahl) * 6, 12), 45)
        except (TypeError, ValueError):
            budget = 18

        # Obergrenze: nach 6 Minuten hart abbrechen statt bis zu 1 Stunde zu
        # blockieren. Eine tote/langsame Website darf den Lauf nicht einfrieren —
        # lieber ehrlich als Fehler melden (UI zeigt dann 'fehler' statt ewig
        # 'läuft'). Die Engine selbst sendet hierbei nichts (reine Suche).
        rc, ausgabe = self._run(
            [
                "-i", auftrag.zielgruppe,
                "-c", auftrag.region,
                "-n", str(auftrag.lead_anzahl),
                "--mode", "local",
            ],
            timeout=360,
            extra_env={
                "B2B_SCRAPE_BUDGET": str(budget),
                # Pro-Lead-LinkedIn-Suche via DuckDuckGo abschalten: sie macht je
                # Lead eine eigene SERP-Abfrage, wird nach wenigen Calls von
                # DuckDuckGo rate-limitet und HÄNGT dann (httpx ohne hartes
                # Timeout) — der dominante Grund für eingefrorene Läufe. LinkedIn-
                # URLs sind nur optionales Beiwerk; Firma/E-Mail/Telefon/
                # Ansprechpartner liefert die Suche auch ohne. Abschaltbar laut
                # Engine via LINKEDIN_SERP_RESOLVE=0.
                "LINKEDIN_SERP_RESOLVE": "0",
            },
        )

        if rc != 0:
            kurz = ausgabe[-500:] if ausgabe else ""
            if rc == -1 and "Zeit" in (ausgabe or ""):
                kurz = (
                    "Die Suche hat zu lange gedauert (über 6 Minuten) und wurde "
                    "abgebrochen. Meist hängt eine langsame Website. Bitte erneut "
                    "starten — oft läuft der nächste Versuch sauber durch."
                )
            auftrag.fehler_setzen(kurz)
            return EngineBrueckenErgebnis(ok=False, meldung=kurz)

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

    def _reply_queue_pfad(self) -> Path:
        return self._output_dir() / "reply_queue.json"

    # Sicherheits-Flags fuer den Antwort-Abruf (E). Alle harten Auto-Send-Gates
    # der Engine werden scoped auf AUS gezwungen — process-replies darf NUR
    # abrufen + klassifizieren + reply_queue schreiben, NIEMALS selbst senden.
    # Die Faehigkeit bleibt in der Engine (Flags umlegbar); unsere Produktregel
    # haelt sie hart aus. .env wird mit override=False geladen → diese Werte gewinnen.
    _ABRUF_SAFE_ENV = {
        "REPLY_DRY_RUN": "1",              # queue only, kein Auto-Reply-Versand
        "REPLY_AUTO_SEND": "false",
        "REPLY_AUTO_SEND_CONFIRMED": "false",
        "OUTREACH_SEND_CONFIRMED": "false",
        "OUTREACH_FULL_AUTO_CONFIRMED": "false",
    }

    def _reply_queue_anzahl(self) -> int:
        pfad = self._reply_queue_pfad()
        if not pfad.exists():
            return 0
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
            return len(data.get("items", []) if isinstance(data, dict) else [])
        except Exception:
            return 0

    def antworten_abrufen(self, limit: int = 30, timeout: int = 240) -> EngineBrueckenErgebnis:
        """E: Holt neue Antworten aktiv aus dem Postfach (IMAP) und klassifiziert.

        Ruft `mine.py --outreach process-replies`. FAIL-CLOSED gegen Versand:
        alle Auto-Send-Gates werden scoped auf AUS gezwungen (_ABRUF_SAFE_ENV) —
        es kann hier NICHTS gesendet werden, nur abgerufen + in reply_queue.json
        geschrieben. Read-only zum Postfach, kein SMTP.
        """
        vorher = self._reply_queue_anzahl()
        rc, out = self._run(
            ["--outreach", "process-replies", "--outreach-limit", str(limit)],
            timeout=timeout,
            extra_env=dict(self._ABRUF_SAFE_ENV),
        )
        if rc != 0:
            return EngineBrueckenErgebnis(ok=False, meldung=f"Abruf fehlgeschlagen:\n{out[-400:]}")
        nachher = self._reply_queue_anzahl()
        neu = max(0, nachher - vorher)
        return EngineBrueckenErgebnis(
            ok=True,
            leads_gefunden=neu,
            leads_sauber=nachher,
            meldung=(f"{neu} neue Antwort(en) abgerufen." if neu else "Keine neuen Antworten."),
            rohdaten={"neu": neu, "gesamt": nachher},
        )

    def _entry_key_firmen(self) -> dict:
        """Map entry_key → Firmenname aus der Pipeline (für hübsche Anzeige)."""
        pfad = self._pipeline_pfad()
        if not pfad.exists():
            return {}
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
            return {
                e.get("entry_key", ""): e.get("company_name", "")
                for e in data.get("entries", [])
                if e.get("entry_key")
            }
        except Exception:
            return {}

    @staticmethod
    def _firma_aus_email(email: str) -> str:
        """Fallback-Anzeigename aus der Absender-Domain."""
        if "@" in email:
            return email.split("@", 1)[1].strip()
        return email.strip()

    def antworten_lesen(self, limit: int = 30) -> list[dict]:
        """V2 (read-only): Liest eingehende Antworten aus reply_queue.json.

        REIN LESEND — kein mine.py-Aufruf, nichts das senden könnte. Gibt
        kundenfähige Felder zurück (Firma, Betreff, Auszug, Klassifizierung,
        Terminwunsch). Keine Roh-Mail, keine technischen IDs in der Anzeige.
        """
        pfad = self._reply_queue_pfad()
        if not pfad.exists():
            return []
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = data.get("items", []) if isinstance(data, dict) else []
        firmen = self._entry_key_firmen()

        out: list[dict] = []
        for it in items:
            ek = it.get("entry_key", "")
            firma = firmen.get(ek) or self._firma_aus_email(it.get("from_email", ""))
            out.append({
                "firma":        firma or "Unbekannt",
                "betreff":      it.get("inbound_subject", ""),
                "auszug":       it.get("inbound_snippet", ""),
                "klasse":       it.get("inbound_class", ""),
                "sentiment":    it.get("sentiment", ""),
                "terminwunsch": bool(it.get("appointment_ready")),
                "termin_grund": it.get("appointment_reason", ""),
                "kategorie":    it.get("reply_sales_category", ""),
                "entry_key":    ek,
                # Kontext: auf welche Mail wurde geantwortet, aus welchem Postfach
                "von":          it.get("from_email", ""),
                "postfach":     it.get("received_account", ""),
                "gesendet_am":  it.get("sent_at", ""),
                "auto_antwort": bool(it.get("is_auto_reply")),
            })
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _domain(email: str) -> str:
        """Kleingeschriebene Domain einer E-Mail ('a.b@Firma.DE' → 'firma.de'). Leer wenn keine."""
        email = (email or "").strip().lower()
        if "@" in email:
            return email.split("@", 1)[1].strip()
        return ""

    _LEERE_KAMPAGNE = {
        "entries": [], "antwort_keys": [], "termin_keys": [],
        "antwort_domains": [], "termin_domains": [],
        "antwort_ohne_bezug": 0, "termin_ohne_bezug": 0,
    }

    def kampagne_rohdaten(self, campaign: Optional[str] = None, limit: int = 1000) -> dict:
        """V2 (read-only): Rohdaten für die Trichter-Ansicht (Phase C + F2).

        Liest Pipeline + reply_queue. Klassifiziert NICHT (das macht die
        Agent-Schicht), sondern liefert je Lead die stufen-relevanten Felder plus
        die entry_keys/Domains, die geantwortet bzw. einen Termin haben. Kein Subprozess.

        F2 — Reply<->Funnel-Join robust: Antworten werden zusätzlich über die
        E-Mail-Domain mit der Pipeline verknüpft (fängt Fälle, in denen derselbe
        Lead über Kampagnen hinweg einen anderen entry_key bekam). Antworten, die
        zu KEINEM aktuellen Pipeline-Lead passen (frühere Kampagne), werden ehrlich
        als 'ohne Pipeline-Bezug' gezählt, statt unsichtbar zu verschwinden.

        campaign: optional auf eine Kampagne (contacted_in_campaigns) einschränken.
        """
        pfad = self._pipeline_pfad()
        if not pfad.exists():
            return dict(self._LEERE_KAMPAGNE)
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return dict(self._LEERE_KAMPAGNE)

        alle_eintraege = data.get("entries", [])
        # Für den Join: ALLE Pipeline-Keys/Domains (nicht nur die Kampagnen-Auswahl),
        # damit ein Domain-Treffer auch außerhalb des Kampagnenfilters greift.
        alle_keys = {e.get("entry_key", "") for e in alle_eintraege if e.get("entry_key")}
        alle_domains = {self._domain(e.get("email", "")) for e in alle_eintraege}
        alle_domains.discard("")

        # Antworten/Termine aus reply_queue (entry_key + Domain-Join)
        antwort_keys: set[str] = set()
        termin_keys: set[str] = set()
        antwort_domains: set[str] = set()
        termin_domains: set[str] = set()
        antwort_ohne_bezug = 0
        termin_ohne_bezug = 0
        rq = self._reply_queue_pfad()
        if rq.exists():
            try:
                items = json.loads(rq.read_text(encoding="utf-8")).get("items", [])
                for it in items:
                    ek = it.get("entry_key", "")
                    dom = self._domain(it.get("from_email_actual") or it.get("from_email", ""))
                    ist_termin = bool(it.get("appointment_ready"))
                    if ek:
                        antwort_keys.add(ek)
                        if ist_termin:
                            termin_keys.add(ek)
                    if dom:
                        antwort_domains.add(dom)
                        if ist_termin:
                            termin_domains.add(dom)
                    # Bezug zur AKTUELLEN Pipeline? (Key ODER Domain)
                    hat_bezug = (ek in alle_keys) or (dom in alle_domains)
                    if not hat_bezug:
                        antwort_ohne_bezug += 1
                        if ist_termin:
                            termin_ohne_bezug += 1
            except Exception:
                pass

        entries: list[dict] = []
        for e in alle_eintraege:
            if campaign:
                if campaign not in (e.get("contacted_in_campaigns") or []):
                    continue
            entries.append({
                "entry_key":       e.get("entry_key", ""),
                "firma":           e.get("company_name", ""),
                "ort":             e.get("city", ""),
                "ansprechpartner": e.get("contact_name", ""),
                "email":           e.get("email", ""),
                "gesendet":        bool(e.get("sent_message_id")),
                "bereit": (
                    (e.get("ready_to_send") or "").strip().lower() == "yes"
                    and not e.get("do_not_resend")
                ),
            })
            if len(entries) >= limit:
                break

        return {
            "entries": entries,
            "antwort_keys": sorted(antwort_keys),
            "termin_keys": sorted(termin_keys),
            "antwort_domains": sorted(antwort_domains),
            "termin_domains": sorted(termin_domains),
            "antwort_ohne_bezug": antwort_ohne_bezug,
            "termin_ohne_bezug": termin_ohne_bezug,
        }

    @staticmethod
    def _parse_zeit(wert: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat((wert or "").strip())
        except Exception:
            return None

    def followups_faellig(self, limit: int = 50, jetzt: Optional[datetime] = None) -> list[dict]:
        """V2 (read-only): Wer ist fürs Nachfassen fällig?

        REIN LESEND. Kriterien: erste Mail ist raus (sent_message_id), KEINE
        Antwort bisher (reply_status leer/none), nicht do_not_resend, und der
        Nachfass-Termin (next_followup_at) ist erreicht. So sieht der Mensch
        vor jeder Freigabe genau, was er nachfassen würde.
        """
        pfad = self._pipeline_pfad()
        if not pfad.exists():
            return []
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return []
        now = jetzt or datetime.now()
        out: list[dict] = []
        for e in data.get("entries", []):
            if e.get("do_not_resend"):
                continue
            if not e.get("sent_message_id"):
                continue
            if (e.get("reply_status") or "none").strip().lower() not in ("", "none"):
                continue
            nf = e.get("next_followup_at") or ""
            faellig_am = self._parse_zeit(nf)
            if faellig_am is None or faellig_am > now:
                continue
            out.append({
                "firma":              e.get("company_name", ""),
                "ansprechpartner":    e.get("contact_name", ""),
                "faellig_seit":       nf,
                "zuletzt_kontaktiert": e.get("last_contacted_at", ""),
                "stufe":              e.get("outreach_stage", ""),
                "entry_key":          e.get("entry_key", ""),
            })
            if len(out) >= limit:
                break
        return out

    def followup_ausfuehren(
        self, limit: int = 20, *, bestaetigt: bool = False
    ) -> EngineBrueckenErgebnis:
        """V2: Nachfassen (followups) — Versand-Pfad, hartes menschliches Tor.

        Wie freigabe_ausfuehren fail-closed: ohne bestaetigt=True kein Versand.
        Die Sende-Bestätigung an die Engine wird nur scoped auf diesen einen
        Aufruf gesetzt. Der Agent-Loop ruft das NIE.
        """
        if not bestaetigt:
            return EngineBrueckenErgebnis(
                ok=False,
                meldung=(
                    "Nachfassen ohne ausdrueckliche Freigabe abgelehnt. "
                    "Ein Mensch muss bestaetigt=True setzen (Freigabe-Klick)."
                ),
            )
        rc, out = self._run(
            ["--outreach", "followups", "--outreach-limit", str(limit)],
            timeout=300,
            extra_env={self._SEND_CONFIRM_ENV: "true"},
        )
        if rc != 0:
            return EngineBrueckenErgebnis(ok=False, meldung=f"Nachfassen fehlgeschlagen:\n{out[-400:]}")
        status = self.status_lesen()
        return EngineBrueckenErgebnis(
            ok=True,
            leads_sauber=status.get("sent_total", 0),
            meldung="Nachfassen ausgefuehrt.",
            rohdaten=status,
        )

    # Engine-eigenes hartes Tor: Ein echter SMTP-Versand feuert nur, wenn diese
    # Umgebungsvariable gesetzt ist. Ohne sie macht die Engine "kein SMTP, kein
    # Versand". Wir setzen sie ausschliesslich scoped auf den einen Send-Aufruf
    # und nur nach ausdruecklicher menschlicher Bestaetigung (bestaetigt=True).
    _SEND_CONFIRM_ENV = "OUTREACH_SEND_CONFIRMED"

    def freigabe_ausfuehren(
        self, limit: int = 20, *, bestaetigt: bool = False
    ) -> EngineBrueckenErgebnis:
        """V2: Approve + Send — der EINZIGE Versand-Pfad. Hartes menschliches Tor.

        Sicherheit (fail-closed):
          - Ohne bestaetigt=True wird NICHTS approved und NICHTS gesendet.
          - bestaetigt=True darf nur ein menschlicher Freigabe-Klick setzen
            (UI-Modal / ausdrueckliche Bestaetigung) — niemals der Agent-Loop.
          - Die Sende-Bestaetigung an die Engine wird nur scoped auf den Send-
            Subprozess gesetzt, nie global.
        Kein CRM-Push, kein Auto-Reply.
        """
        if not bestaetigt:
            return EngineBrueckenErgebnis(
                ok=False,
                meldung=(
                    "Versand ohne ausdrueckliche Freigabe abgelehnt. "
                    "Ein Mensch muss bestaetigt=True setzen (Freigabe-Klick)."
                ),
            )

        # Harte Obergrenze (Mini-Patch): nie weniger als 1, nie mehr als 50 Mails
        # pro Freigabe — schuetzt den realen Versand unabhaengig vom Aufrufer.
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 20

        # Schritt 1: Approve (markiert nur approved_for_send — kein SMTP).
        rc1, out1 = self._run(
            ["--outreach", "approve", "--outreach-limit", str(limit)],
            timeout=120,
        )
        if rc1 != 0:
            return EngineBrueckenErgebnis(ok=False, meldung=f"Approve fehlgeschlagen:\n{out1[-400:]}")

        # Schritt 2: Send — Sende-Bestaetigung nur fuer genau diesen Aufruf.
        rc2, out2 = self._run(
            ["--outreach", "send", "--outreach-limit", str(limit)],
            timeout=300,
            extra_env={self._SEND_CONFIRM_ENV: "true"},
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

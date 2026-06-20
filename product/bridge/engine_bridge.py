"""Bridge — einzige Verbindung zwischen Produktschicht und B2B-Engine.

V1: genau drei Aktionen (suchen, status_lesen, leads_lesen).
KEIN Send-, Approve- oder Reply-Pfad — diese existieren hier nicht.

Packaging-Regel: engine_dir konfigurierbar, nie hardcodiert.
Muster: analog telegram_seller/engine.py (Subprozess auf mine.py).
"""
from __future__ import annotations

import json
import hashlib
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


# Sammel-Postfächer — eine persönliche Adresse ist mehr wert als info@.
_GENERISCHE_MAIL_PREFIXES = (
    "info", "kontakt", "mail", "office", "hello", "hallo", "post",
    "contact", "service", "support", "willkommen", "anfrage",
)


def _website_bereinigt(url: str) -> str:
    """Tracking-Query (utm_*) aus der Website-URL fürs UI entfernen."""
    u = (url or "").strip()
    if "?" in u and "utm_" in u.split("?", 1)[1].lower():
        return u.split("?", 1)[0]
    return u


def _lead_begruendung(e: dict) -> tuple[list[str], str]:
    """Bildet kurze, deterministische Gründe + nächsten Schritt aus
    VORHANDENEN Pipeline-Feldern. Keine neue Bewertung, keine KI —
    nur lesbar machen, was Scoring/Suche bereits entschieden haben.
    """
    gruende: list[str] = []

    score = int(e.get("score") or 0)
    if score >= 70:
        gruende.append(f"Sehr gute Passung (Score {score})")
    elif score >= 40:
        gruende.append(f"Solide Passung (Score {score})")
    elif score > 0:
        gruende.append(f"Schwache Passung (Score {score})")

    telefon = (e.get("phone") or e.get("contact_phone") or "").strip()
    if telefon:
        gruende.append("Telefon vorhanden — direkt anrufbar")

    ansprechpartner = (e.get("contact_name") or "").strip()
    email = (e.get("email") or "").strip().lower()
    if ansprechpartner:
        gruende.append(f"Ansprechpartner: {ansprechpartner}")
    elif email:
        prefix = email.split("@", 1)[0]
        if prefix in _GENERISCHE_MAIL_PREFIXES:
            gruende.append("Nur Sammel-Adresse (z. B. info@) — Anruf wirkt besser")
        else:
            gruende.append("Persönliche E-Mail-Adresse gefunden")

    sendbar = (e.get("ready_to_send") or "").strip().lower() == "yes"
    if sendbar:
        schritt = "Mail-Entwurf liegt bereit — im Freigabe-Tab prüfen"
    elif telefon:
        schritt = "Anrufen — Nummer liegt vor"
    elif email:
        schritt = "Kontakt per E-Mail prüfen"
    else:
        schritt = "Website manuell prüfen"

    return gruende[:3], schritt


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
        # Angebot-Profil-Env (Multi-Offer): PROFILE_FIRST_TOUCH_* (Mailtext/
        # Betreff/PDF) des aktuell aktiven Angebots. Wird in JEDEN Engine-Aufruf
        # eingespeist (siehe _run). Leer = Engine-Default. Der Sender bleibt
        # IMMER der Engine-.env-Sender — Profile ändern NUR die Erstmail-Inhalte.
        self._profil_env: dict[str, str] = {}

    def profil_setzen(self, env: dict[str, str] | None) -> None:
        """Setzt die Profil-Override-Env für ALLE folgenden Engine-Aufrufe dieses
        Bridge-Objekts. Erwartet das Ergebnis von store.aktives_profil_env().
        Leeres/None dict = Engine-Default (bisheriges Verhalten)."""
        self._profil_env = dict(env or {})

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
        #
        # Merge-Reihenfolge: Profil-Env als BASIS, call-spezifische extra_env
        # GEWINNT. Damit können Safety-Flags (OUTREACH_SEND_CONFIRMED, Abruf-
        # Gates) nie versehentlich von einem Profil überschrieben werden — das
        # Profil enthält ohnehin nur PROFILE_FIRST_TOUCH_* (kein Overlap).
        merged: dict[str, str] = dict(self._profil_env)
        if extra_env:
            merged.update(extra_env)
        env = None
        if merged:
            env = os.environ.copy()
            env.update(merged)
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

        # Run-Isolation: nur Leads DIESER Kampagne zählen — sonst rutschen
        # alte Probelauf-Leads aus der kumulativen Pipeline in die Anzeige
        # ("14/10 versandbereit" bei 10 bestellten Leads).
        campaign_id = self._aktuelle_campaign_id()
        status = self.status_lesen(campaign_id=campaign_id)
        status["campaign_id"] = campaign_id
        return EngineBrueckenErgebnis(
            ok=True,
            leads_gefunden=status.get("pipeline_total", 0),
            leads_sauber=status.get("sendable", 0),
            meldung="Suche abgeschlossen.",
            rohdaten=status,
        )

    # --- Signal-Suche (High-Intent-Targeting) -----------------------------

    def suchen_per_signal(
        self,
        auftrag: Auftrag,
        signal_typ: str = "sales_hiring",
        *,
        cached_report: Optional[str] = None,
        laender=("de",),
    ) -> EngineBrueckenErgebnis:
        """Sucht Firmen anhand eines Kaufsignals statt flach nach Branche.

        Ablauf (alles read-only/aufbereitend, KEIN Versand):
          1. Signal-Discovery (broad) → Firmen, die das Signal zeigen.
          2. Website-Auflösung je Firma.
          3. mine.py --mode enrich → scrape + score + contact_quality + intent.
          4. Job-Signal als erstklassiges Feld an jeden Lead heften.

        Das Job-Signal (warum die Firma getargetet wurde) wird bewusst
        angeheftet — die website-basierte Intent-Bewertung der Engine würde
        es sonst überschreiben.
        """
        import csv as _csv
        import tempfile
        from product.bridge import signal_discovery as _sd

        self._pruefen(auftrag, ErlaubteAktion.SUCHEN_AUFBEREITEN)
        auftrag.starten()

        # Discovery-Breite an die Zielmenge koppeln (gedeckelt). Der frühere feste
        # 6er-Query-Cap war der Hauptgrund, warum eine Suche real nur ~5–12 Leads
        # brachte — egal wie viele bestellt waren. Jede Query = 1 SERPER-Call (Cent-
        # Bereich); die Preview-Auflösung läuft jetzt parallel mit Budget, darum ist
        # mehr Breite gefahrlos. Für 50 Leads braucht es deutlich mehr Roh-Treffer.
        try:
            ziel = max(int(auftrag.lead_anzahl), 1)
        except (TypeError, ValueError):
            ziel = 10
        disc_queries = min(max(ziel + 4, 10), 30)

        try:
            firmen = _sd.discover_with_websites(
                self.engine_dir,
                industry=auftrag.zielgruppe,
                city=auftrag.region,
                signal_type=signal_typ,
                max_companies=ziel,
                cached_report=cached_report,
                laender=laender,
                max_queries=disc_queries,
                max_results_per_query=5,
            )
        except Exception as exc:  # noqa: BLE001
            kurz = f"Signal-Discovery fehlgeschlagen: {exc}"
            auftrag.fehler_setzen(kurz)
            return EngineBrueckenErgebnis(ok=False, meldung=kurz)

        mit_website = [f for f in firmen if f.website]
        if not mit_website:
            kurz = "Keine Firmen mit Signal + auflösbarer Website gefunden."
            auftrag.fehler_setzen(kurz)
            return EngineBrueckenErgebnis(
                ok=False, meldung=kurz,
                rohdaten={"discovery": [f.als_dict() for f in firmen]},
            )

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8-sig", newline="",
        )
        tmp_path = tmp.name
        tmp.close()
        try:
            _sd.build_enrich_csv(
                mit_website, tmp_path,
                industry=auftrag.zielgruppe, city=auftrag.region,
            )
            # Breite Signale (z.B. sales_hiring) finden viele Firmen → viele
            # Websites zum Scrapen. 10 Min reichten dafür nicht (Abbruch mitten
            # im Lauf, alles verworfen). 20 Min Puffer, damit breite Suchen
            # sauber durchlaufen statt zu sterben.
            rc, ausgabe = self._run(
                ["--input-csv", tmp_path, "--mode", "enrich"],
                timeout=1200,
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if rc != 0:
            kurz = (ausgabe[-500:] if ausgabe else "enrich fehlgeschlagen")
            auftrag.fehler_setzen(kurz)
            return EngineBrueckenErgebnis(ok=False, meldung=kurz)

        leads = self._enrich_leads_lesen(ausgabe)
        self._signal_an_leads_heften(leads, mit_website, signal_typ)
        # Kontakt-Anreicherung (Weg-2-Tiefe): Telefon aus bereits gescraptem Text
        # + persönlicher Mail-Vorschlag. Defensiv, kein Auto-Send, kein Live-Lookup.
        self._signal_kontakt_anreichern(leads)
        # Kontakt-Pflicht (Emilio): Ein Lead ohne JEDE Kontaktmöglichkeit (weder
        # E-Mail NOCH Telefon) ist für Outreach wertlos → vor Personalisierung und
        # Schreiben aussortieren, damit er gar nicht erst auftaucht.
        def _hat_kontakt(l: dict) -> bool:
            email = (l.get("email") or l.get("contact_email") or "").strip()
            phone = (l.get("phone") or l.get("phone_clean") or l.get("contact_phone") or "").strip()
            return bool(email or phone)
        _vorher = len(leads)
        leads = [l for l in leads if _hat_kontakt(l)]
        if len(leads) < _vorher:
            print(f"[signal] {_vorher - len(leads)} Leads ohne E-Mail/Telefon verworfen "
                  f"({len(leads)} mit Kontakt bleiben).", flush=True)
        # Kaufbereitschafts-Analyse (1k-Produkt): je Lead Score + Stufe + Gründe +
        # Beleg aus den vorhandenen Feldern verdichten (deterministisch, kein Netz).
        self._signal_readiness_bewerten(leads)
        # Verkaufspsychologische Personalisierung — NUR hier (Signal-Suche):
        # je Lead einen Aufhänger ans Lead-Feld heften + Vorschau-Mail rendern.
        # Defensiv: ein Fehler (z. B. fehlender OpenAI-Key) darf die Suche nie
        # kippen — ohne Key/Signal bleibt es eine saubere generische Mail.
        self._signal_leads_personalisieren(leads)
        self._signal_leads_schreiben(leads, auftrag, signal_typ, laender)

        mit_signal = sum(1 for l in leads if l.get("entdeckt_per_signal"))
        return EngineBrueckenErgebnis(
            ok=True,
            leads_gefunden=len(leads),
            leads_sauber=sum(1 for l in leads if int(l.get("contact_quality_score") or 0) >= 40),
            meldung=f"Signal-Suche abgeschlossen: {len(leads)} Leads, {mit_signal} mit Signal.",
            rohdaten={
                "leads": leads,
                "discovery": [f.als_dict() for f in firmen],
                "signal_typ": signal_typ,
            },
        )

    def _enrich_leads_lesen(self, enrich_ausgabe: str) -> list[dict]:
        """Liest leads.json des enrich-Laufs (Pfad aus '[enrich] output -> ...')."""
        pfad = ""
        for line in (enrich_ausgabe or "").splitlines():
            if "[enrich] output ->" in line:
                pfad = line.split("->", 1)[1].strip()
        kandidaten = []
        if pfad:
            kandidaten.append(Path(pfad))
        kandidaten.append(self._output_dir() / "latest" / "leads.json")
        for p in kandidaten:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
            except Exception:
                continue
        return []

    @staticmethod
    def _host(url: str) -> str:
        from urllib.parse import urlparse
        h = urlparse(url if "://" in (url or "") else f"https://{url}").netloc.lower()
        return h[4:] if h.startswith("www.") else h

    def _signal_an_leads_heften(self, leads: list[dict], firmen: list, signal_typ: str) -> None:
        """Heftet das Job-Signal (Discovery) an die passenden Leads."""
        by_host = {self._host(f.website): f for f in firmen if f.website}
        by_name = {(f.firma or "").casefold().strip(): f for f in firmen}
        for lead in leads:
            f = by_host.get(self._host(lead.get("website", "")))
            if f is None:
                f = by_name.get((lead.get("company_name") or "").casefold().strip())
            if f is None:
                continue
            lead["entdeckt_per_signal"] = signal_typ
            lead["signal_titel"] = f.signal_titel
            lead["signal_quelle_url"] = f.quelle_url
            lead["signal_fit_score"] = f.fit_score

    def _signal_kontakt_anreichern(self, leads: list[dict]) -> None:
        """Reichert Kontaktdaten an (Telefon aus bereits gescraptem Text +
        persönlicher Mail-Vorschlag). Live-SERPER-Suche aktiv wenn
        SERPER_API_KEY gesetzt (~1 Query je Lead ohne Nummer)."""
        try:
            import os
            from product.bridge import signal_contact_enrich as _ce
            serper_key = os.environ.get("SERPER_API_KEY", "").strip()
            sucher = _ce.make_serper_telefon_sucher(serper_key) if serper_key else None
            _ce.anreichern(leads, telefon_sucher=sucher)
        except Exception:
            pass

    def _signal_readiness_bewerten(self, leads: list[dict]) -> None:
        """Heftet je Signal-Lead die Kaufbereitschafts-Analyse an (Score/Stufe/
        Gründe/Beleg). Defensiv: ein Fehler darf die Suche nie kippen."""
        try:
            from product.bridge import signal_readiness as _r
            _r.anreichern(leads)
        except Exception:
            pass

    def _aktives_profil_id(self) -> str:
        """ID des aktuell aktiven Angebot-Profils (für die Aufhänger-Wahl)."""
        try:
            from product.profile import store
            return str(store.aktives_profil().get("id", ""))
        except Exception:
            return ""

    def _signal_leads_personalisieren(self, leads: list[dict]) -> None:
        """Heftet pro Signal-Lead einen Aufhänger an + rendert die Vorschau-Mail.

        Komplett defensiv: jede Ausnahme (fehlender OpenAI-Key, Engine-Import,
        Netzfehler) wird geschluckt — die Signal-Suche läuft immer weiter, im
        Zweifel mit leerem Aufhänger (= saubere generische Mail).
        """
        try:
            from product.personalization import signal_outreach as _so
            from product.personalization.aufhaenger import standard_llm as _std_llm
            angebot = _so.angebot_aus_profil_id(self._aktives_profil_id())
            # Website-Angebot: echte Seite je Lead prüfen → Schwächen treiben den
            # Aufhänger. Defensiv: tote/langsame Seite überspringen, nie crashen.
            if angebot == "website":
                from product.personalization import website_check as _wc
                for lead in leads:
                    web = (lead.get("website") or "").strip()
                    if not web:
                        continue
                    try:
                        lead["website_schwaechen"] = _wc.pruefe_website(web)
                    except Exception:
                        lead["website_schwaechen"] = []
            _so.personalisiere_und_rendere(
                leads, angebot, self.engine_dir, dict(self._profil_env),
                llm=_std_llm(),
            )
        except Exception:
            for lead in leads:
                lead.setdefault("aufhaenger", "")

    def _signal_leads_schreiben(
        self, leads: list[dict], auftrag: Auftrag, signal_typ: str, laender=("de",)
    ) -> Path:
        """Schreibt die Signal-Leads. Zwei Ziele:
        1) ``signal_leads.json`` = letzter Lauf (Kompatibilität: der CRM-Connector
           liest diese Datei).
        2) ``signal_runs.json`` = Suchen-Speicher (jede Suche getaggt + löschbar).
        """
        out = self._output_dir() / "latest" / "signal_leads.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "auftrag_id": auftrag.auftrags_id,
            "zielgruppe": auftrag.zielgruppe,
            "region": auftrag.region,
            "laender": list(laender or []),
            "signal_typ": signal_typ,
            "anzahl": len(leads),
            "mit_signal": sum(1 for l in leads if l.get("entdeckt_per_signal")),
            "leads": leads,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # In den Suchen-Speicher anhängen (getaggt, löschbar). Defensiv.
        try:
            from product.bridge import signal_store as _store
            _store.append_run(
                self._output_dir(),
                run_id=auftrag.auftrags_id,
                meta={
                    "generated_at": payload["generated_at"],
                    "zielgruppe": auftrag.zielgruppe,
                    "region": auftrag.region,
                    "laender": list(laender or []),
                    "signal_typ": signal_typ,
                    "label": _store.run_label({**payload}),
                },
                leads=leads,
            )
        except Exception:
            pass
        return out

    # --- Signal-Status (für asynchrone UI-Anzeige) ------------------------

    def _signal_status_pfad(self) -> Path:
        return self._output_dir() / "latest" / "signal_status.json"

    def signal_status_schreiben(self, status: str, meldung: str = "", extra: Optional[dict] = None) -> None:
        """Schreibt den aktuellen Stand der Signal-Suche (laeuft|fertig|fehler)."""
        p = self._signal_status_pfad()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status,
            "meldung": meldung,
            "aktualisiert_am": datetime.now().isoformat(timespec="seconds"),
        }
        if extra:
            payload.update(extra)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def signal_status_lesen(self) -> dict:
        try:
            return json.loads(self._signal_status_pfad().read_text(encoding="utf-8"))
        except Exception:
            return {"status": "keiner", "meldung": ""}

    @property
    def _SIGNAL_LABELS(self) -> dict:
        # Quelle der Wahrheit: signal_discovery.SIGNAL_LABELS (lazy → kein Zyklus).
        from product.bridge import signal_discovery as _sd
        return _sd.SIGNAL_LABELS

    def _signal_lead_ui(self, l: dict) -> dict:
        """Bildet einen rohen Signal-Lead in die UI-fertige Form ab (inkl. lead_id)."""
        e = {
            "score": l.get("contact_quality_score", 0),
            "phone": l.get("phone", ""),
            "contact_name": l.get("contact_full_name") or l.get("managing_director") or "",
            "email": l.get("email", ""),
            "ready_to_send": l.get("ready_to_send", ""),
        }
        gruende, schritt = _lead_begruendung(e)
        sig = (l.get("entdeckt_per_signal") or "").strip()
        if sig:
            gruende.insert(0, f"Signal: {self._SIGNAL_LABELS.get(sig, sig)}")
        return {
            "lead_id": l.get("lead_id", ""),
            "run_id": l.get("run_id", ""),
            "firma": l.get("company_name", ""),
            "email": l.get("email", ""),
            "telefon": l.get("phone") or l.get("contact_phone") or "",
            "ansprechpartner": e["contact_name"],
            "website": _website_bereinigt(l.get("website", "")),
            "score": l.get("contact_quality_score", 0),
            "ort": l.get("city", ""),
            "signal": sig,
            "signal_label": self._SIGNAL_LABELS.get(sig, sig),
            "signal_titel": l.get("signal_titel", ""),
            "signal_quelle_url": l.get("signal_quelle_url", ""),
            "aufhaenger": l.get("aufhaenger", ""),
            "kaufbereitschaft_score": l.get("kaufbereitschaft_score", 0),
            "kaufbereitschaft_stufe": l.get("kaufbereitschaft_stufe", ""),
            "kaufbereitschaft_gruende": l.get("kaufbereitschaft_gruende", []),
            "kaufbereitschaft_beleg_url": l.get("kaufbereitschaft_beleg_url", "") or l.get("signal_quelle_url", ""),
            "notiz": l.get("notiz", ""),
            "mail_betreff": (l.get("personalisierte_mail") or {}).get("betreff", ""),
            "mail_body": (l.get("personalisierte_mail") or {}).get("body", ""),
            "persoenliche_mail_vorschlag": l.get("persoenliche_mail_vorschlag", ""),
            "gruende": gruende[:3],
            "naechster_schritt": schritt,
        }

    def signal_leads_lesen(self) -> list[dict]:
        """Liest die Signal-Leads des LETZTEN Laufs UI-fertig (Kompatibilität)."""
        try:
            data = json.loads(self._signal_leads_pfad_signal().read_text(encoding="utf-8"))
        except Exception:
            return []
        return [self._signal_lead_ui(l) for l in data.get("leads", [])]

    def signal_runs_lesen(self) -> list[dict]:
        """Alle gespeicherten Suchen, neueste zuerst, je mit Etikett + UI-Leads.

        Migriert beim ersten Mal den letzten Einzellauf (signal_leads.json) in den
        Store, damit ein bestehender Treffer nicht „verschwindet"."""
        from product.bridge import signal_store as _store
        try:
            einzel = json.loads(self._signal_leads_pfad_signal().read_text(encoding="utf-8"))
        except Exception:
            einzel = None
        try:
            _store.migrate_einzeldatei(self._output_dir(), einzel)
        except Exception:
            pass
        runs = _store.list_runs(self._output_dir())
        out: list[dict] = []
        for r in runs:
            leads = [self._signal_lead_ui(l) for l in r.get("leads", [])]
            out.append({
                "run_id": r.get("run_id", ""),
                "label": r.get("label") or _store.run_label(r),
                "zielgruppe": r.get("zielgruppe", ""),
                "region": r.get("region", ""),
                "laender": r.get("laender", []),
                "signal_typ": r.get("signal_typ", ""),
                "generated_at": r.get("generated_at", ""),
                "anzahl": len(leads),
                "leads": leads,
            })
        return out

    def signal_lead_loeschen(self, lead_id: str) -> int:
        from product.bridge import signal_store as _store
        return _store.delete_lead(self._output_dir(), lead_id)

    def signal_run_loeschen(self, run_id: str) -> int:
        from product.bridge import signal_store as _store
        return _store.delete_run(self._output_dir(), run_id)

    def signal_lead_aendern(self, lead_id: str, fields: dict) -> int:
        from product.bridge import signal_store as _store
        return _store.update_lead(self._output_dir(), lead_id, fields)

    def _signal_leads_pfad_signal(self) -> Path:
        return self._output_dir() / "latest" / "signal_leads.json"

    def _aktuelle_campaign_id(self) -> str:
        """Kampagnen-ID des letzten Engine-Laufs (aus latest/campaign_manifest.json).

        Leer, wenn kein Manifest existiert — dann verhalten sich alle
        kampagnen-gefilterten Leser wie bisher (global).
        """
        manifest = self._output_dir() / "latest" / "campaign_manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return str(data.get("campaign_id") or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _entry_in_kampagne(e: dict, campaign_id: str) -> bool:
        """True, wenn der Pipeline-Eintrag zu dieser Kampagne gehört.

        Run-Isolation: alte Probelauf-Leads dürfen nicht in der Zählung
        oder Freigabe-Vorschau eines aktuellen Laufs auftauchen.
        """
        if not campaign_id:
            return True
        return campaign_id in (
            e.get("campaign_id"),
            e.get("first_seen_campaign_id"),
            e.get("last_campaign_id"),
        )

    def status_lesen(self, campaign_id: str | None = None) -> dict:
        """Liest Statusdaten direkt aus Engine-Output-Dateien (kein mine.py-Aufruf).

        campaign_id gesetzt → zählt nur Einträge dieser Kampagne
        (Run-Isolation). None/leer → globale Zählung wie bisher.
        """
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
                entries = [
                    e for e in data.get("entries", [])
                    if self._entry_in_kampagne(e, campaign_id or "")
                ]
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
                gruende, schritt = _lead_begruendung(e)
                out.append({
                    "firma": e.get("company_name", ""),
                    "email": e.get("email", ""),
                    "telefon": e.get("phone") or e.get("contact_phone") or "",
                    "ansprechpartner": e.get("contact_name", ""),
                    "website": _website_bereinigt(e.get("website", "")),
                    "score": e.get("score", 0),
                    "ort": e.get("city", ""),
                    "gruende": gruende,
                    "naechster_schritt": schritt,
                })
                if len(out) >= limit:
                    break
            return out
        except Exception:
            return []

    # ----------------------------------------------------------------- V2

    def vorschau_lesen(self, limit: int = 30, campaign_id: str | None = None) -> list[dict]:
        """V2: Liest Mail-Vorschau (noch nicht gesendete, sendbare Eintraege).

        Gibt subject + body zurueck — keine Secrets, keine Admin-Felder.
        Kein mine.py-Aufruf, nur Datei-Lesen.

        Run-Isolation: Default (None) = NUR die aktuelle Kampagne aus dem
        letzten Lauf — alte Probelauf-Leads duerfen nicht zur Freigabe
        vorbereitet werden. campaign_id="" erzwingt explizit alle.
        """
        if campaign_id is None:
            campaign_id = self._aktuelle_campaign_id()
        pipeline = self._pipeline_pfad()
        if not pipeline.exists():
            return []
        # Anhang der Erstmail (Engine: _first_touch_attachments) — fuer die
        # Vorschau nur den Dateinamen anzeigen, wenn die Datei wirklich existiert.
        anhang_pfad = self.engine_dir.parent / "assets" / "Rebellsystem.pdf"
        anhang = anhang_pfad.name if anhang_pfad.exists() else ""
        try:
            data = json.loads(pipeline.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            out = []
            for e in entries:
                # Nur sendbare, noch nicht gesendete Eintraege dieser Kampagne
                if not self._entry_in_kampagne(e, campaign_id):
                    continue
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
                    "anhang":          anhang,
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
                "id":           self._antwort_id(it),
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
    def _antwort_id(item: dict) -> str:
        """Stabile, HTML-sichere ID je Antwort (für gezieltes Löschen)."""
        basis = str(item.get("message_id") or "") or "|".join(
            str(item.get(k, "")) for k in ("entry_key", "from_email", "inbound_subject", "sent_at"))
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]

    def antwort_loeschen(self, reply_id: str) -> int:
        """Entfernt eine eingegangene Antwort aus reply_queue.json (rein lokal,
        kein IMAP-Eingriff, kein Versand). Gibt die Anzahl entfernter Einträge
        zurück; idempotent (unbekannte ID → 0)."""
        reply_id = (reply_id or "").strip()
        if not reply_id:
            return 0
        pfad = self._reply_queue_pfad()
        if not pfad.exists():
            return 0
        try:
            data = json.loads(pfad.read_text(encoding="utf-8"))
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        items = data.get("items", [])
        rest = [it for it in items if self._antwort_id(it) != reply_id]
        entfernt = len(items) - len(rest)
        if entfernt:
            data["items"] = rest
            pfad.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return entfernt

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

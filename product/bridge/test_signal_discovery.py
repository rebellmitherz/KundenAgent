"""Smoke-Tests für Signal-Discovery + Bridge-Anbindung (deterministisch, kein Netz).

Der Live-Pfad (SERPER-Discovery + Website-Auflösung + mine.py enrich) wurde
manuell verifiziert (siehe CODE_AGENT_HANDOFF). Diese Tests sichern die
deterministische Glue-Logik ab, ohne Limits zu verbrauchen:
  - Fit-Scoring gegen echte Auftrags-Parameter
  - Discovery aus Cache-Report
  - Enrich-CSV bauen
  - Job-Signal an Leads heften (Host-/Namens-Match)
  - leads.json-Pfad aus enrich-Ausgabe lesen

Standalone:  python product/bridge/test_signal_discovery.py
Pytest:      pytest product/bridge/test_signal_discovery.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from product.bridge import signal_discovery as sd
from product.bridge.engine_bridge import EngineBridge

ENGINE_DIR = Path(__file__).resolve().parents[2] / "b2bbot"


def test_fit_bewerten_signal_und_stadt():
    score, status = sd._fit_bewerten(
        "Brodax Consulting GmbH", "Junior Sales Manager Hamburg",
        industry="Unternehmensberatung", city="Hamburg", signal_type="sales_hiring",
    )
    # Signal (sales) + Stadt (hamburg) treffen → >= 0.6
    assert score >= 0.6, score
    assert status in ("target_fit", "maybe_fit"), status


def test_fit_bewerten_ohne_treffer_verwirft():
    score, status = sd._fit_bewerten(
        "Irgendwas GmbH", "Bürokauffrau", industry="Steuerberater",
        city="Bonn", signal_type="sales_hiring",
    )
    assert status == "discard", (score, status)


def test_fit_bewerten_ats_plattform_hart_verwerfen():
    # softgarden ist der ATS-/e-recruiting-Anbieter, der die Anzeige HOSTET —
    # nie der Interessent. Realer A3-Müll-Lead (Name kommt verschmutzt rein).
    score, status = sd._fit_bewerten(
        "Beiträge liegt ausschließlich bei der softgarden e-recruiting GmbH",
        "Key Account Manager:in – Media Sales (m/w/d)",
        industry="Marketing", city="Berlin", signal_type="sales_hiring",
    )
    assert status == "discard" and score == 0.0, (score, status)


def test_fit_bewerten_grossmarke_hart_verwerfen():
    # Ströer = Groß-Konzern (realer A3-Lead, „Name "-Präfix + Müll-Mail).
    score, status = sd._fit_bewerten(
        "Name Ströer Media Deutschland GmbH",
        "Vertriebsmitarbeiter Außendienst Neukundenakquise (m/w/d)",
        industry="Marketing", city="Berlin", signal_type="sales_hiring",
    )
    assert status == "discard" and score == 0.0, (score, status)


def test_fit_bewerten_recruiting_hart_verwerfen():
    # Personaldienstleister vermitteln Personal, kaufen keinen Akquise-Bot → HART raus.
    score, status = sd._fit_bewerten(
        "XY Personalvermittlung GmbH", "Sales Manager Hamburg",
        industry="Unternehmensberatung", city="Hamburg", signal_type="sales_hiring",
    )
    assert status == "discard" and score == 0.0, (score, status)


def test_fit_bewerten_agentur_hart_verwerfen():
    # Vertriebs-/Akquise-Agentur (real: "Compris Sales") ist kein Käufer → HART raus.
    for firma in ("Compris Sales", "ABC Telemarketing GmbH", "XY Vertriebsagentur"):
        score, status = sd._fit_bewerten(
            firma, "Sales Manager gesucht",
            industry="IT", city="Ludwigsburg", signal_type="sales_hiring",
        )
        assert status == "discard" and score == 0.0, (firma, score, status)


def test_fit_bewerten_kmu_mit_vertrieb_bleibt():
    # Ein echtes KMU ohne Agentur-/Recruiter-Marker bleibt (kein Fehl-Discard).
    for firma in ("Müller Maschinenbau GmbH", "Bautzen Sanitär-Heinze GmbH", "Sanitär Schmidt"):
        _, status = sd._fit_bewerten(
            firma, "Vertriebsmitarbeiter (m/w/d)",
            industry="Maschinenbau", city="", signal_type="sales_hiring",
        )
        assert status != "discard", (firma, status)


def test_fit_bewerten_echte_firma_bleibt():
    # Medialabel = echte kleine Agentur → NICHT verwerfen (kept, wenn auch low).
    score, status = sd._fit_bewerten(
        "Medialabel", "Account Manager (m/w/d) - Job bei der Firma Medialabel GmbH in ...",
        industry="Marketing", city="Berlin", signal_type="sales_hiring",
    )
    assert status != "discard", (score, status)


# ─── Inkrement 2: Signal-Breite (2 → 6) ──────────────────────────────────────

def test_signal_taxonomie_zwei_gruppen():
    # Zwei getrennte Gruppen: 6 Vertriebs- + 6 Versicherungs-Signale (additiv).
    assert len(sd._VERTRIEBS_SIGNAL_TYPES) == 6
    assert len(sd._VERSICHERUNGS_SIGNAL_TYPES) == 6
    assert len(sd.SIGNAL_TYPES) == 12
    # keine Überschneidung der beiden Welten
    assert not (set(sd._VERTRIEBS_SIGNAL_TYPES) & set(sd._VERSICHERUNGS_SIGNAL_TYPES))
    # jeder Typ hat Begriffe (Fit) UND ein Label
    assert set(sd.SIGNAL_TYPES) <= set(sd._SIGNAL_BEGRIFFE)
    assert all(t in sd.SIGNAL_LABELS for t in sd.SIGNAL_TYPES)


def test_versicherungs_signale_haben_keywords_und_label():
    # Alle vs_-Signale müssen Discovery-Keywords + Label tragen (sonst leere Suche).
    for st in sd._VERSICHERUNGS_SIGNAL_TYPES:
        assert sd._SIGNAL_KEYWORDS.get(st), st
        assert st in sd.SIGNAL_LABELS, st


def test_build_signal_queries_versicherung():
    # Versicherungs-Signale laufen über dieselbe Jobportal-Discovery (mit Zielort).
    for st in sd._VERSICHERUNGS_SIGNAL_TYPES:
        qs = sd._build_signal_queries("Logistik", "Leipzig", st)
        assert qs, st
        assert all("Leipzig" in q for q in qs), (st, qs[:2])
        assert len(qs) == len({q.casefold() for q in qs}), st  # dedupe


def test_fit_bewerten_vs_hiring():
    score, status = sd._fit_bewerten(
        "Echte Logistik GmbH", "Lagermitarbeiter (m/w/d) Vollzeit gesucht",
        industry="Logistik", city="Leipzig", signal_type="vs_hiring",
    )
    assert score >= 0.6 and status in ("target_fit", "maybe_fit"), (score, status)


def test_build_signal_queries_neue_signale():
    for st in ("appointment_setter", "marketing_hiring", "leadership_hiring", "new_location"):
        qs = sd._build_signal_queries("Marketing", "Berlin", st)
        assert qs, st
        assert all("Berlin" in q for q in qs), (st, qs[:2])
        assert len(qs) == len({q.casefold() for q in qs}), st  # dedupe


def test_build_signal_queries_unbekannt_wirft():
    try:
        sd._build_signal_queries("Marketing", "Berlin", "voodoo_signal")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_build_signal_queries_delegiert_an_engine():
    # sales_hiring → bewährter Engine-Builder (read-only Import, kein Netz).
    with sd._engine_context(ENGINE_DIR):
        qs = sd._build_signal_queries("Unternehmensberatung", "Hamburg", "sales_hiring")
    assert qs and any("stepstone" in q.lower() for q in qs)


def test_fit_bewerten_neues_signal_appointment_setter():
    score, status = sd._fit_bewerten(
        "Frische Agentur GmbH", "Sales Development Representative (SDR) Berlin",
        industry="Marketing", city="Berlin", signal_type="appointment_setter",
    )
    assert score >= 0.6 and status in ("target_fit", "maybe_fit"), (score, status)


# ─── Schritt 5: Zielbranche vom Signal trennen ──────────────────────────────
def test_ist_rollenwort_erkennt_rollen():
    for r in ("Vertrieb", "vertrieb", "Sales", "Außendienst", "Kaltakquise",
              "SDR", "Sales Manager", "Vertrieb im B2B"):
        assert sd.ist_rollenwort(r) is True, r


def test_ist_rollenwort_echte_branche_false():
    for b in ("Maschinenbau", "IT-Dienstleister", "Handwerk", "B2B-SaaS",
              "Vertriebsberatung", "Steuerberater", "Marketing", "Logistik"):
        assert sd.ist_rollenwort(b) is False, b


def test_ist_rollenwort_leer_false():
    assert sd.ist_rollenwort("") is False
    assert sd.ist_rollenwort("   ") is False


def test_fit_rollenwort_als_branche_kein_icp_credit():
    # „Vertrieb" als Branche darf den ICP-Fit NICHT hochziehen (nur Signal zählt).
    titel = "Vertriebsmitarbeiter Außendienst (m/w/d)"
    als_branche = sd._fit_bewerten("Echte Firma GmbH", titel,
                                   industry="Vertrieb", city="", signal_type="sales_hiring")[0]
    echte_branche = sd._fit_bewerten("Echte Firma GmbH", "Maschinenbau " + titel,
                                     industry="Maschinenbau", city="", signal_type="sales_hiring")[0]
    # Mit echter, passender Branche ist der Fit höher als mit dem Rollenwort „Vertrieb".
    assert echte_branche > als_branche, (echte_branche, als_branche)


def test_discover_aus_cache():
    report = {
        "results": [
            {"company_name": "Brodax Consulting GmbH", "company_name_valid": True,
             "title": "Junior Sales Manager Hamburg", "url": "https://stepstone.de/x"},
            {"company_name": "-", "company_name_valid": False, "title": "", "url": ""},
        ]
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(report, fh)
        p = fh.name
    try:
        firmen = sd.discover_companies(
            ENGINE_DIR, "Unternehmensberatung", "Hamburg", "sales_hiring",
            cached_report=p,
        )
    finally:
        Path(p).unlink(missing_ok=True)
    assert len(firmen) == 1
    assert firmen[0].firma == "Brodax Consulting GmbH"
    assert firmen[0].quelle_url == "https://stepstone.de/x"


def test_build_enrich_csv_nur_mit_website():
    firmen = [
        sd.SignalFirma(firma="A GmbH", website="https://a.de/", signal_titel="Sales Manager"),
        sd.SignalFirma(firma="B GmbH", website="", signal_titel="Vertrieb"),  # ohne Website → raus
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
        p = fh.name
    try:
        n = sd.build_enrich_csv(firmen, p, industry="Beratung", city="Hamburg")
        assert n == 1, n
        text = Path(p).read_text(encoding="utf-8-sig")
        assert "A GmbH" in text
        assert "B GmbH" not in text
        assert "Sales Manager" in text  # Signal in notes
    finally:
        Path(p).unlink(missing_ok=True)


def test_signal_an_leads_heften_per_host_und_name():
    b = EngineBridge(engine_dir=ENGINE_DIR)
    firmen = [
        sd.SignalFirma(firma="Brodax Consulting GmbH", website="https://brodax-consulting.de/",
                       signal_titel="Junior Sales Manager", quelle_url="https://stepstone.de/job1", fit_score=0.6),
        sd.SignalFirma(firma="Podia GmbH", website="https://www.podia.de/",
                       signal_titel="Sales Manager", quelle_url="https://stepstone.de/job2", fit_score=0.3),
    ]
    leads = [
        {"company_name": "Brodax Consulting", "website": "https://brodax-consulting.de/impressum"},  # Host-Match
        {"company_name": "Podia GmbH", "website": ""},  # Namens-Match
        {"company_name": "Fremd AG", "website": "https://fremd.de"},  # kein Match
    ]
    b._signal_an_leads_heften(leads, firmen, "sales_hiring")
    assert leads[0]["entdeckt_per_signal"] == "sales_hiring"
    assert leads[0]["signal_quelle_url"] == "https://stepstone.de/job1"
    assert leads[1]["entdeckt_per_signal"] == "sales_hiring"  # per Name
    assert "entdeckt_per_signal" not in leads[2]


def test_enrich_leads_lesen_aus_pfad():
    b = EngineBridge(engine_dir=ENGINE_DIR)
    leads = [{"company_name": "X GmbH", "contact_quality_score": 70}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(leads, fh)
        p = fh.name
    try:
        ausgabe = f"[enrich] done | leads=1\n[enrich] output -> {p}\n"
        gelesen = b._enrich_leads_lesen(ausgabe)
        assert len(gelesen) == 1
        assert gelesen[0]["company_name"] == "X GmbH"
    finally:
        Path(p).unlink(missing_ok=True)


def test_signal_status_roundtrip(tmp=None):
    import tempfile as _tf
    b = EngineBridge(engine_dir=ENGINE_DIR)
    d = Path(_tf.mkdtemp())
    b._output_dir = lambda: d  # type: ignore[assignment]
    assert b.signal_status_lesen()["status"] == "keiner"
    b.signal_status_schreiben("laeuft", "Suche läuft…")
    assert b.signal_status_lesen()["status"] == "laeuft"
    b.signal_status_schreiben("fertig", "ok", extra={"anzahl": 3})
    s = b.signal_status_lesen()
    assert s["status"] == "fertig" and s.get("anzahl") == 3


def test_signal_leads_lesen_mapping():
    import tempfile as _tf
    b = EngineBridge(engine_dir=ENGINE_DIR)
    d = Path(_tf.mkdtemp())
    b._output_dir = lambda: d  # type: ignore[assignment]
    (d / "latest").mkdir(parents=True, exist_ok=True)
    report = {"leads": [{
        "company_name": "Brodax Consulting", "website": "https://brodax-consulting.de/",
        "contact_quality_score": 53, "email": "info@brodax-consulting.de", "phone": "+49551",
        "city": "Hamburg", "entdeckt_per_signal": "sales_hiring",
        "signal_titel": "Junior Sales Manager", "signal_quelle_url": "https://stepstone.de/job1",
    }]}
    (d / "latest" / "signal_leads.json").write_text(json.dumps(report), encoding="utf-8")
    leads = b.signal_leads_lesen()
    assert len(leads) == 1
    l = leads[0]
    assert l["firma"] == "Brodax Consulting"
    assert l["signal_label"] == "Stellt Vertrieb ein"
    assert l["signal_quelle_url"] == "https://stepstone.de/job1"
    # info@ → Grund "Sammel-Adresse"; Signal-Grund steht an erster Stelle
    assert l["gruende"][0].startswith("Signal:")


# ─── Geografie: Stadt optional + DACH (Weg-2-Tiefe Nachtrag) ─────────────────

def test_laender_normalisieren():
    assert sd._laender_normalisieren(None) == ("de",)
    assert sd._laender_normalisieren([]) == ("de",)
    assert sd._laender_normalisieren(["XX", "fr"]) == ("de",)   # nur DACH, sonst Default
    assert sd._laender_normalisieren(["AT", "ch", "ch"]) == ("at", "ch")  # dedupe + lower


def test_build_queries_dach_spannt_alle_laender():
    q = sd._build_signal_queries("Dachdecker", "", "appointment_setter", ("de", "at", "ch"))
    assert any("stepstone.de" in x for x in q)
    assert any("stepstone.at" in x or "karriere.at" in x for x in q)
    assert any("jobs.ch" in x for x in q)
    # ohne Stadt: Base = nur Branche (keine Stadt im Query)
    assert all("Dachdecker" in x for x in q)


def test_build_queries_sales_ohne_stadt_nutzt_produkt_builder():
    # sales_hiring ohne Stadt/außerhalb DE → Produkt-Builder (kein Engine-Import nötig)
    q = sd._build_signal_queries("IT-Dienstleister", "", "sales_hiring", ("at",))
    assert q and any("karriere.at" in x for x in q)


def test_build_queries_branche_egal_signal_only():
    # „Branche egal": ohne Zielbranche UND ohne Stadt wird signal-only gesucht — die
    # Query kommt trotzdem (Portal + Kaufsignal-Keyword), KEIN Abbruch (früher: raise).
    q = sd._build_signal_queries("", "", "sales_hiring", ("de",))
    assert q, "leere Branche darf keine Exception werfen, sondern signal-only suchen"
    assert any("stepstone.de" in x for x in q)


def test_build_queries_branche_egal_mit_stadt():
    # Branche egal + Stadt: die Stadt bleibt als Filter erhalten, nur die Branche entfällt.
    q = sd._build_signal_queries("", "Berlin", "appointment_setter", ("de",))
    assert q and all("Berlin" in x for x in q)


def test_fit_ohne_stadt_rebalanciert():
    # Starker Branchen+Signal-Treffer ohne Stadt erreicht target_fit (Stadt-Gewicht umverteilt).
    score, status = sd._fit_bewerten(
        "Becker Dachdecker GmbH", "SDR / Telefonakquise gesucht",
        industry="Dachdecker", city="", signal_type="appointment_setter",
    )
    assert status == "target_fit" and score >= 0.9, (score, status)


def test_fit_mit_stadt_unveraendert():
    # Regression: der DE+Stadt-Pfad bleibt exakt wie vorher (0.4/0.3/0.3).
    score, _ = sd._fit_bewerten(
        "Müller Elektrotechnik GmbH", "Vertriebsmitarbeiter SDR Köln",
        industry="Elektriker", city="Köln", signal_type="appointment_setter",
    )
    assert score == 0.6, score


# ─── Volumen-Hebel: mehr Portale + parallele Preview-Auflösung ───────────────

def test_de_portale_erweitert():
    de = sd._PORTAL_TEMPLATES_BY_LAND["de"]
    blob = " ".join(de).lower()
    for dom in ("stepstone", "indeed", "yourfirm", "meinestadt", "jobware", "monster",
                "stellenanzeigen", "kimeta", "jobvector"):
        assert dom in blob, dom
    # Xing/LinkedIn werden vom Resolver hart übersprungen → dürfen NICHT rein.
    assert "xing" not in blob and "linkedin" not in blob


# ─── Signal-Stapelung ────────────────────────────────────────────────────────

def test_firmen_vereinen_union_nicht_schnitt():
    a1 = sd.SignalFirma(firma="Alpha GmbH", signal_titel="Vertrieb", fit_score=0.6,
                        fit_status="target_fit", signal_typ="sales_hiring")
    a2 = sd.SignalFirma(firma="alpha gmbh", signal_titel="SDR", fit_score=0.9,
                        fit_status="target_fit", signal_typ="appointment_setter", signal_alter_tage=5)
    b = sd.SignalFirma(firma="Beta GmbH", signal_titel="Außendienst", fit_score=0.7,
                       fit_status="target_fit", signal_typ="sales_hiring")
    out = sd._firmen_vereinen([("sales_hiring", [a1, b]), ("appointment_setter", [a2])])
    # Union: 2 Firmen (NICHT Schnittmenge=1)
    assert len(out) == 2
    # Mehrfach-Signal-Firma ganz oben, stärkster Treffer = Primär
    assert out[0].firma == "Alpha GmbH" and out[0].signal_count == 2
    assert out[0].signal_typ == "appointment_setter"     # höherer Fit gewinnt
    assert out[0].signal_alter_tage == 5
    assert out[0].signale == ["appointment_setter", "sales_hiring"]
    assert len(out[0].signal_belege) == 2
    assert out[1].firma == "Beta GmbH" and out[1].signal_count == 1


def test_discover_multi_signal_einzel_ist_alter_pfad(monkeypatch=None):
    # Bei genau einem Signal darf kein Stapelungs-Overhead entstehen.
    calls = {"single": 0, "multi": 0}
    orig = sd.discover_with_websites
    sd.discover_with_websites = lambda *a, **k: (calls.__setitem__("single", calls["single"]+1) or [])
    try:
        sd.discover_multi_signal("b2bbot", "Handel", "", ["sales_hiring"], max_companies=5)
    finally:
        sd.discover_with_websites = orig
    assert calls["single"] == 1


def test_discover_multi_signal_cache_stapelt():
    rep = {"results": [
        {"company_name": "Alpha Vertrieb GmbH", "company_name_valid": True,
         "title": "Sales Manager (m/w/d)", "url": "https://stepstone.de/j1", "date": "vor 3 Tagen"},
        {"company_name": "Beta Solutions GmbH", "company_name_valid": True,
         "title": "SDR Outbound Terminierung", "url": "https://stepstone.de/j2"},
    ]}
    import os
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)   # Windows: offenen fd schließen, sonst sperrt unlink (WinError 32)
    Path(path).write_text(json.dumps(rep), encoding="utf-8")
    orig = sd.resolve_website
    sd.resolve_website = lambda *a, **k: ("https://example.de", 0.9)
    try:
        firmen = sd.discover_multi_signal(
            "b2bbot", "Handel", "", ["sales_hiring", "appointment_setter"],
            max_companies=10, cached_report=path)
    finally:
        sd.resolve_website = orig
        Path(path).unlink()
    by = {f.firma: f for f in firmen}
    # Union = beide Firmen. Nur die SDR-Firma matcht beide Signale → count=2.
    assert len(firmen) == 2
    assert by["Beta Solutions GmbH"].signal_count == 2
    assert by["Alpha Vertrieb GmbH"].signal_count == 1
    assert firmen[0].firma == "Beta Solutions GmbH"     # Heißgrad oben
    assert by["Alpha Vertrieb GmbH"].signal_alter_tage == 3   # Frische geparst


# ─── LinkedIn-Quellen ────────────────────────────────────────────────────────

def test_linkedin_company_from_title():
    f = sd._linkedin_company_from_title
    assert f("Müller Vertrieb GmbH hiring Sales Manager in Berlin | LinkedIn") == "Müller Vertrieb GmbH"
    assert f("Acme GmbH sucht Vertriebsmitarbeiter (m/w/d) | LinkedIn") == "Acme GmbH"
    assert f("Sales Development Representative at Beta AG | LinkedIn") == "Beta AG"
    assert f("Vertriebsleiter bei Gamma Solutions - LinkedIn") == "Gamma Solutions"
    assert f("Titel ganz ohne erkennbares Muster") == ""


def test_apify_pro_ohne_key_ist_leer_und_kostenlos():
    # Ohne APIFY_API_KEY darf NIE ein Call passieren → leere Liste, 0 €.
    assert sd._apify_pro_firmen("Vertrieb", "Berlin", "sales_hiring", api_key="") == []


def test_linkedin_such_url_format():
    # Eingabeformat des curious_coder-Actors: LinkedIn-Jobs-Such-URL.
    u_de = sd._linkedin_such_url("Vertriebsmitarbeiter", "", ["de"])
    assert "linkedin.com/jobs/search" in u_de
    assert "keywords=Vertriebsmitarbeiter" in u_de
    assert "location=Germany" in u_de            # ohne Stadt → Land
    u_at = sd._linkedin_such_url("SDR", "", ["at"])
    assert "location=Austria" in u_at
    u_city = sd._linkedin_such_url("SDR", "Hamburg", ["de"])
    assert "location=Hamburg" in u_city          # mit Stadt → Stadt


# ─── Such-Transparenz (Operator-Coverage) ────────────────────────────────────

def test_quellen_namen_listet_portale_und_linkedin():
    q = sd.quellen_namen(["de"], linkedin_web=True)
    for name in ("Stepstone", "Indeed", "Kimeta", "Jobvector", "LinkedIn-Web"):
        assert name in q, name
    assert "LinkedIn-Pro" not in q          # Pro nur wenn linkedin_pro=True
    assert sd.quellen_namen(["de"], linkedin_pro=True)[-1] == "LinkedIn-Pro"


def test_discover_multi_signal_fuellt_diagnostik():
    rep = {"results": [
        {"company_name": "Alpha GmbH", "company_name_valid": True, "title": "Sales Manager", "url": "https://stepstone.de/j1"},
        {"company_name": "Beta GmbH", "company_name_valid": True, "title": "SDR Terminierung", "url": "https://stepstone.de/j2"},
    ]}
    import os
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    Path(path).write_text(json.dumps(rep), encoding="utf-8")
    orig = sd.resolve_website
    sd.resolve_website = lambda *a, **k: ("https://x.de", 0.9)
    diag: dict = {}
    try:
        sd.discover_multi_signal("b2bbot", "Handel", "", ["sales_hiring", "appointment_setter"],
                                 max_companies=10, cached_report=path, diagnostik=diag)
    finally:
        sd.resolve_website = orig
        Path(path).unlink()
    assert diag["signale"] == ["sales_hiring", "appointment_setter"]
    assert set(diag["pro_signal"]) == {"sales_hiring", "appointment_setter"}
    assert diag["quellen"] and "Stepstone" in diag["quellen"]


def test_resolve_candidates_paart_korrekt_und_parallel():
    cands = [{"url": f"u{i}", "title": f"t{i}"} for i in range(6)]

    def fake(c):
        return {"company_name_valid": True,
                "company_name_extracted": c["url"].upper(),
                "original_title": c["title"]}

    pairs = sd._resolve_candidates(cands, fake, max_workers=4, wall_budget_s=10)
    assert len(pairs) == 6
    # Jedes Paar bleibt korrekt zugeordnet (Kandidat ↔ sein Resolved).
    for cand, res in pairs:
        assert res["company_name_extracted"] == cand["url"].upper()


def test_resolve_candidates_schluckt_fehler():
    cands = [{"url": "ok"}, {"url": "boom"}]

    def fake(c):
        if c["url"] == "boom":
            raise RuntimeError("netzfehler")
        return {"company_name_valid": True, "company_name_extracted": "OK"}

    pairs = sd._resolve_candidates(cands, fake, max_workers=2, wall_budget_s=10)
    # Fehler-Kandidat fällt raus, der gute bleibt — Lauf lebt weiter.
    assert len(pairs) == 1 and pairs[0][1]["company_name_extracted"] == "OK"


def test_resolve_candidates_leer():
    assert sd._resolve_candidates([], lambda c: c, max_workers=4, wall_budget_s=5) == []


# ─── Suchen-Speicher: Provenance + Löschen (ganze Suche / einzeln) + Edit ────

def test_store_append_list_und_label():
    import tempfile as _tf
    from product.bridge import signal_store as store
    d = Path(_tf.mkdtemp())
    store.append_run(d, run_id="r1", meta={"zielgruppe": "Dachdecker", "region": "Köln",
                     "laender": ["de"], "signal_typ": "appointment_setter",
                     "generated_at": "2026-06-17T15:50:00"}, leads=[{"company_name": "A"}, {"company_name": "B"}])
    store.append_run(d, run_id="r2", meta={"zielgruppe": "IT", "region": "", "laender": ["de", "at"],
                     "signal_typ": "sales_hiring", "generated_at": "2026-06-17T16:00:00"}, leads=[{"company_name": "C"}])
    runs = store.list_runs(d)
    assert [r["run_id"] for r in runs] == ["r2", "r1"]            # neueste zuerst
    assert runs[1]["leads"][0]["lead_id"] == "r1#0"               # stabile lead_id
    assert "IT" in store.run_label(runs[0]) and "AT" in store.run_label(runs[0])


def test_store_delete_lead_und_run():
    import tempfile as _tf
    from product.bridge import signal_store as store
    d = Path(_tf.mkdtemp())
    store.append_run(d, run_id="r1", meta={}, leads=[{"company_name": "A"}, {"company_name": "B"}])
    assert store.delete_lead(d, "r1#0") == 1
    namen = [l["company_name"] for r in store.list_runs(d) for l in r["leads"]]
    assert namen == ["B"]
    store.append_run(d, run_id="r2", meta={}, leads=[{"company_name": "C"}])
    assert store.delete_run(d, "r2") == 1
    assert [r["run_id"] for r in store.list_runs(d)] == ["r1"]


def test_store_update_lead_nur_erlaubte_felder():
    import tempfile as _tf
    from product.bridge import signal_store as store
    d = Path(_tf.mkdtemp())
    store.append_run(d, run_id="r1", meta={}, leads=[{"company_name": "A"}])
    store.update_lead(d, "r1#0", {"phone": "+49221", "notiz": "callback", "score": 999})
    l = store.list_runs(d)[0]["leads"][0]
    assert l["phone"] == "+49221" and l["notiz"] == "callback"
    assert "score" not in l                                       # nicht-erlaubtes Feld ignoriert


def test_store_migrate_einzeldatei_einmalig():
    import tempfile as _tf
    from product.bridge import signal_store as store
    d = Path(_tf.mkdtemp())
    payload = {"auftrag_id": "alt1", "zielgruppe": "Handwerker", "region": "Köln",
               "signal_typ": "appointment_setter", "generated_at": "2026-06-17T15:50:00",
               "leads": [{"company_name": "Swarovski"}]}
    assert store.migrate_einzeldatei(d, payload) is True
    assert store.migrate_einzeldatei(d, payload) is False         # nicht doppelt
    assert store.list_runs(d)[0]["run_id"] == "alt1"


def test_bridge_runs_loeschen_und_aendern():
    import tempfile as _tf
    from product.bridge import signal_store as store
    b = EngineBridge(engine_dir=ENGINE_DIR)
    d = Path(_tf.mkdtemp())
    b._output_dir = lambda: d  # type: ignore[assignment]
    store.append_run(d, run_id="r1", meta={"zielgruppe": "Dachdecker", "signal_typ": "appointment_setter"},
                     leads=[{"company_name": "A", "contact_quality_score": 50,
                             "entdeckt_per_signal": "appointment_setter"}])
    runs = b.signal_runs_lesen()
    assert len(runs) == 1 and runs[0]["leads"][0]["lead_id"] == "r1#0"
    assert b.signal_lead_aendern("r1#0", {"phone": "+49221"}) == 1
    assert b.signal_runs_lesen()[0]["leads"][0]["telefon"] == "+49221"
    assert b.signal_run_loeschen("r1") == 1
    assert b.signal_runs_lesen() == []


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"== {ok}/{len(fns)} grün ==")
    return ok == len(fns)


if __name__ == "__main__":
    import sys
    sys.exit(0 if _run_all() else 1)

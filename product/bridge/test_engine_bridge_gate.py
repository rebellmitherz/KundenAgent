"""Tests für die Premium-Gate-Ausgabepolitik in engine_bridge (Schritt 4).

Testet die reinen, netzfreien Helfer `_uebersuch_roh_ziel` (Über-Suchen) und
`_gate_ausgabe` (REJECT raus, PREMIUM zuerst, Zielmenge der besten) — ohne die
Engine/den Subprozess zu starten.
"""
from __future__ import annotations

from product.bridge import engine_bridge as eb
from product.bridge import premium_gate as pg


def _premium(**over) -> dict:
    """Ein Lead, der das Premium-Gate als PREMIUM passiert (Zielbranche Maschinenbau)."""
    lead = {
        "entdeckt_per_signal": "sales_hiring",
        "signal_quelle_url": "https://stepstone.de/job/1",
        "website": "https://www.echte-firma.de",
        "company_name": "Echte Maschinenbau GmbH",
        "contact_full_name": "Anna Beispiel",
        "email": "anna.beispiel@echte-firma.de",
        "phone": "+49 151 23456789",
        "ready_to_send": "yes",
        "email_quality_rank": "A",
        "signal_alter_tage": 7,
        "industry": "Maschinenbau",
        "kaufbereitschaft_score": 80,
    }
    lead.update(over)
    return lead


# ── Über-Suchen ─────────────────────────────────────────────────────────────
def test_uebersuch_default_dreifach(monkeypatch):
    monkeypatch.delenv("SIGNAL_UEBERSUCH_FAKTOR", raising=False)
    monkeypatch.delenv("SIGNAL_UEBERSUCH_MAX", raising=False)
    assert eb._uebersuch_roh_ziel(10) == 30
    assert eb._uebersuch_roh_ziel(50) == 80          # 150 auf Cap 80 gedeckelt


def test_uebersuch_faktor_aus(monkeypatch):
    monkeypatch.setenv("SIGNAL_UEBERSUCH_FAKTOR", "1")
    assert eb._uebersuch_roh_ziel(10) == 10          # Faktor 1 = altes Verhalten


def test_uebersuch_env_steuerbar(monkeypatch):
    monkeypatch.setenv("SIGNAL_UEBERSUCH_FAKTOR", "2")
    monkeypatch.setenv("SIGNAL_UEBERSUCH_MAX", "100")
    assert eb._uebersuch_roh_ziel(20) == 40


def test_uebersuch_defensiv_bei_muell(monkeypatch):
    monkeypatch.setenv("SIGNAL_UEBERSUCH_FAKTOR", "abc")
    assert eb._uebersuch_roh_ziel(10) == 30          # fällt auf Default 3 zurück


# ── Gate-Ausgabe ────────────────────────────────────────────────────────────
def test_gate_ausgabe_wirft_reject_raus():
    leads = [_premium(), _premium(website="")]       # 2. = keine echte Website = REJECT
    aus, z = eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau")
    assert z[pg.PREMIUM] == 1 and z[pg.REJECT] == 1
    assert len(aus) == 1
    assert all(l.get("premium_klasse") != pg.REJECT for l in aus)


def test_gate_ausgabe_premium_zuerst():
    leads = [
        _premium(ready_to_send="no", company_name="Review GmbH"),   # → REVIEW
        _premium(company_name="Premium GmbH"),                      # → PREMIUM
    ]
    aus, _ = eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau")
    assert aus[0]["company_name"] == "Premium GmbH"
    assert aus[0]["premium_klasse"] == pg.PREMIUM


def test_gate_ausgabe_nur_premium():
    leads = [_premium(ready_to_send="no"), _premium()]
    aus, _ = eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau", nur_premium=True)
    assert len(aus) == 1 and aus[0]["premium_klasse"] == pg.PREMIUM


def test_gate_ausgabe_cap_haelt_alle_premium():
    # Zielmenge < Premium-Zahl → ALLE Premium kommen trotzdem durch (nie kappen unter Premium).
    leads = [_premium(company_name=f"Maschinenbau {i} GmbH") for i in range(5)]
    aus, z = eb._gate_ausgabe(leads, ziel=2, zielbranche="Maschinenbau")
    assert z[pg.PREMIUM] == 5
    assert len(aus) == 5


def test_gate_ausgabe_liefert_zielmenge_der_besten():
    # 1 Premium + 4 Review, ziel=3 → Premium + 2 beste Review (nach Score) = 3.
    leads = [_premium()] + [
        _premium(ready_to_send="no", company_name=f"Review {i} GmbH",
                 kaufbereitschaft_score=50 - i)
        for i in range(4)
    ]
    aus, _ = eb._gate_ausgabe(leads, ziel=3, zielbranche="Maschinenbau")
    assert len(aus) == 3
    assert aus[0]["premium_klasse"] == pg.PREMIUM
    # die zwei besten Review (Score 50, 49) vor den schwächeren (48, 47).
    assert aus[1]["kaufbereitschaft_score"] == 50
    assert aus[2]["kaufbereitschaft_score"] == 49


def test_gate_ausgabe_taggt_jeden_lead():
    leads = [_premium(), _premium(ready_to_send="no"), _premium(website="")]
    eb._gate_ausgabe(leads, ziel=10, zielbranche="Maschinenbau")
    for l in leads:
        assert l.get("premium_klasse") in (pg.PREMIUM, pg.REVIEW, pg.REJECT)


# ── „Branche egal" / breiter ICP (Regel 7 greift nicht, Boden bleibt) ────────
def test_gate_ausgabe_ohne_breit_leere_zielbranche_nur_review():
    # Normalfall: ohne Zielbranche → Regel 7 „unbestimmt" → höchstens REVIEW.
    leads = [_premium()]
    aus, z = eb._gate_ausgabe(leads, ziel=10, zielbranche="")
    assert z[pg.PREMIUM] == 0 and z[pg.REVIEW] == 1
    assert aus[0]["premium_klasse"] == pg.REVIEW


def test_gate_ausgabe_branche_egal_macht_premium():
    # „Branche egal" (icp_breit=True): derselbe Lead ohne Zielbranche wird PREMIUM —
    # das Kaufsignal qualifiziert, nicht die enge Branche.
    leads = [_premium()]
    aus, z = eb._gate_ausgabe(leads, ziel=10, zielbranche="", icp_breit=True)
    assert z[pg.PREMIUM] == 1
    assert aus[0]["premium_klasse"] == pg.PREMIUM


def test_gate_ausgabe_branche_egal_haelt_harte_regeln():
    # Auch im breiten ICP bleibt der Qualitäts-Boden: ein Lead ohne echte Website
    # fliegt weiter raus (Regel 3). „Branche egal" ≠ „Qualität egal".
    leads = [_premium(website="")]
    aus, z = eb._gate_ausgabe(leads, ziel=10, zielbranche="", icp_breit=True)
    assert z[pg.REJECT] == 1 and len(aus) == 0


# ── Eskalations-Helfer (Teil 2: länger/breiter suchen bis genug PREMIUM) ──────
def test_signal_max_stufen_default_und_cap(monkeypatch):
    monkeypatch.delenv("SIGNAL_MAX_STUFEN", raising=False)
    assert eb._signal_max_stufen() == 2
    monkeypatch.setenv("SIGNAL_MAX_STUFEN", "9")
    assert eb._signal_max_stufen() == 3          # hart auf 3 gedeckelt
    monkeypatch.setenv("SIGNAL_MAX_STUFEN", "0")
    assert eb._signal_max_stufen() == 1          # mind. 1
    monkeypatch.setenv("SIGNAL_MAX_STUFEN", "xx")
    assert eb._signal_max_stufen() == 2          # defensiv → Default


def test_signal_ziel_premium_default_und_env(monkeypatch):
    monkeypatch.delenv("SIGNAL_ZIEL_PREMIUM", raising=False)
    assert eb._signal_ziel_premium(20) == 20     # Default = bestellte Menge
    monkeypatch.setenv("SIGNAL_ZIEL_PREMIUM", "5")
    assert eb._signal_ziel_premium(20) == 5
    monkeypatch.setenv("SIGNAL_ZIEL_PREMIUM", "abc")
    assert eb._signal_ziel_premium(20) == 20     # defensiv → Default


def test_stufen_plan_stadt_dann_deutschlandweit():
    assert eb._stufen_plan("Berlin", 2) == ["Berlin", ""]


def test_stufen_plan_ohne_stadt_nur_deutschlandweit():
    assert eb._stufen_plan("", 2) == [""]
    assert eb._stufen_plan("   ", 2) == [""]


def test_stufen_plan_kuerzt_auf_max():
    assert eb._stufen_plan("Berlin", 1) == ["Berlin"]   # nur Stadt, kein DE-weit


def test_hat_kontakt():
    assert eb._hat_kontakt({"email": "a@b.de"})
    assert eb._hat_kontakt({"phone": "+49 30 1"})
    assert not eb._hat_kontakt({"email": "", "phone": ""})
    assert not eb._hat_kontakt({})


# ── Eskalations-Schleife (mit gestubbter Stufe, ohne Netz) ───────────────────
class _FakeFirma:
    def __init__(self, name="X", website="https://x.de"):
        self.firma, self.website = name, website
    def als_dict(self):
        return {"firma": self.firma}


class _FakeAuftrag:
    def __init__(self, region, ziel=2, zielgruppe="Maschinenbau"):
        self.region, self.lead_anzahl, self.zielgruppe = region, ziel, zielgruppe
        self.angebot = ""
    def starten(self):
        pass
    def fehler_setzen(self, m):
        self.fehler = m


def _stub_bridge(stufen_ergebnisse):
    """EngineBruecke ohne __init__ (kein mine.py nötig); Stufe + Downstream gestubbt."""
    b = object.__new__(eb.EngineBridge)
    b.engine_dir = __import__("pathlib").Path(".")
    calls = []

    def fake_stufe(auftrag, signal_typen, *, ort, roh_ziel, cached_report, laender,
                   linkedin_web, linkedin_pro, seen_hosts, such_diag):
        calls.append(ort)
        return stufen_ergebnisse.pop(0) if stufen_ergebnisse else ([], [])

    b._signal_stufe = fake_stufe
    b._pruefen = lambda *a, **k: None
    b._signal_leads_personalisieren = lambda *a, **k: None
    b._signal_briefing_erstellen = lambda *a, **k: None
    b._signal_leads_schreiben = lambda *a, **k: None
    return b, calls


def test_eskalation_stoppt_wenn_genug_premium(monkeypatch):
    # Stadt-Stufe liefert genug PREMIUM → KEINE deutschlandweite Nachsuche (spart Geld).
    monkeypatch.delenv("SIGNAL_ZIEL_PREMIUM", raising=False)
    monkeypatch.delenv("SIGNAL_MAX_STUFEN", raising=False)
    b, calls = _stub_bridge([([_premium(), _premium()], [_FakeFirma(), _FakeFirma()])])
    res = b.suchen_per_signal(_FakeAuftrag("Berlin", ziel=2), "sales_hiring")
    assert res.ok and res.leads_sauber == 2
    assert calls == ["Berlin"]          # nur Stufe 1, nicht ausgeweitet


def test_eskalation_weitet_deutschlandweit_aus(monkeypatch):
    # Stadt-Stufe liefert zu wenig → automatisch deutschlandweit nachgesucht,
    # Leads akkumulieren über die Stufen.
    monkeypatch.delenv("SIGNAL_ZIEL_PREMIUM", raising=False)
    monkeypatch.delenv("SIGNAL_MAX_STUFEN", raising=False)
    b, calls = _stub_bridge([
        ([_premium()], [_FakeFirma("A")]),        # Stufe 1 (Berlin): 1 PREMIUM < 2
        ([_premium()], [_FakeFirma("B")]),        # Stufe 2 (DE-weit): +1 → 2 ≥ 2
    ])
    res = b.suchen_per_signal(_FakeAuftrag("Berlin", ziel=2), "sales_hiring")
    assert res.ok and res.leads_sauber == 2
    assert calls == ["Berlin", ""]      # Stadt → deutschlandweit


def test_eskalation_ohne_stadt_nur_eine_stufe(monkeypatch):
    # Ohne Stadt gibt es nur die deutschlandweite Stufe — auch wenn zu wenig PREMIUM,
    # wird nicht weiter ausgeweitet (kein weiterer Ort übrig).
    monkeypatch.delenv("SIGNAL_ZIEL_PREMIUM", raising=False)
    monkeypatch.delenv("SIGNAL_MAX_STUFEN", raising=False)
    b, calls = _stub_bridge([([_premium()], [_FakeFirma()])])
    res = b.suchen_per_signal(_FakeAuftrag("", ziel=5), "sales_hiring")
    assert res.ok and res.leads_sauber == 1
    assert calls == [""]

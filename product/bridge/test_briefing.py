"""Tests für product.bridge.briefing."""
from __future__ import annotations

import pytest
from product.bridge import briefing as br


# ─── Hilfsfunktion ────────────────────────────────────────────────────────────

def _lead(signal: str = "sales_hiring", aufhaenger: str = "", **extra) -> dict:
    base = {
        "company_name": "Testfirma GmbH",
        "city": "Hamburg",
        "entdeckt_per_signal": signal,
        "aufhaenger": aufhaenger,
        "description": "Spezialist für industrielle Automatisierung.",
    }
    base.update(extra)
    return base


# ─── einwaende_fuer_signal ────────────────────────────────────────────────────

def test_einwaende_bekanntes_signal():
    e = br.einwaende_fuer_signal("sales_hiring")
    assert len(e) == 2
    assert all("frage" in x and "antwort" in x for x in e)


def test_einwaende_alle_signale():
    for sig in [
        "sales_hiring", "appointment_setter", "growth_expansion",
        "marketing_hiring", "leadership_hiring", "new_location",
    ]:
        e = br.einwaende_fuer_signal(sig)
        assert len(e) == 2, f"Kein Einwand-Paar für {sig}"


def test_einwaende_fallback_unbekannt():
    e = br.einwaende_fuer_signal("unbekannt_xyz")
    assert len(e) == 2


def test_einwaende_leer():
    e = br.einwaende_fuer_signal("")
    assert len(e) == 2


def test_einwaende_grossschreibung_ignoriert():
    e = br.einwaende_fuer_signal("SALES_HIRING")
    assert len(e) == 2
    assert e[0]["frage"] == br.einwaende_fuer_signal("sales_hiring")[0]["frage"]


# ─── firmen_kurzprofil ────────────────────────────────────────────────────────

def test_kurzprofil_deterministisch_mit_beschreibung():
    kp = br.firmen_kurzprofil(_lead("sales_hiring"))
    assert "Automatisierung" in kp or "Testfirma" in kp or "Vertrieb" in kp.lower()
    assert len(kp) > 20


def test_kurzprofil_ohne_beschreibung():
    lead = _lead("growth_expansion", description="")
    kp = br.firmen_kurzprofil(lead)
    assert len(kp) > 10
    assert "Hamburg" in kp or "wächst" in kp.lower()


def test_kurzprofil_ohne_alles():
    kp = br.firmen_kurzprofil({"company_name": "", "entdeckt_per_signal": ""})
    assert len(kp) > 5


def test_kurzprofil_llm_verwendet():
    aufgerufen: list[str] = []

    def fake_llm(prompt: str) -> str:
        aufgerufen.append(prompt)
        return "Fake-Profil aus LLM."

    kp = br.firmen_kurzprofil(_lead(), llm=fake_llm)
    assert kp == "Fake-Profil aus LLM."
    assert aufgerufen, "LLM wurde nicht aufgerufen"


def test_kurzprofil_llm_fehler_fallback():
    def kaputtes_llm(prompt: str) -> str:
        raise RuntimeError("kein Key")

    kp = br.firmen_kurzprofil(_lead(), llm=kaputtes_llm)
    assert len(kp) > 10


def test_kurzprofil_llm_leer_fallback():
    kp = br.firmen_kurzprofil(_lead(), llm=lambda _: "")
    assert len(kp) > 10


def test_kurzprofil_branche_als_liste():
    lead = _lead(description="", industry=["Handel", "E-Commerce", "Logistik", "Extra"])
    kp = br.firmen_kurzprofil(lead)
    assert "Handel" in kp or "E-Commerce" in kp or "Logistik" in kp


# ─── briefing_erstellen ──────────────────────────────────────────────────────

def test_briefing_felder_vorhanden():
    b = br.briefing_erstellen(_lead(aufhaenger="Mein Opener."))
    assert set(b) == {"kurzprofil", "opener", "einwaende"}


def test_briefing_opener_wird_gelesen():
    b = br.briefing_erstellen(_lead(aufhaenger="Bester Opener!"))
    assert b["opener"] == "Bester Opener!"


def test_briefing_opener_leer_wenn_kein_aufhaenger():
    b = br.briefing_erstellen(_lead())
    assert b["opener"] == ""


def test_briefing_einwaende_passend():
    b = br.briefing_erstellen(_lead("new_location"))
    assert b["einwaende"] == br.einwaende_fuer_signal("new_location")


def test_briefing_ohne_signal():
    lead = {"company_name": "NoSignal AG", "entdeckt_per_signal": ""}
    b = br.briefing_erstellen(lead)
    assert len(b["einwaende"]) == 2


# ─── anreichern ──────────────────────────────────────────────────────────────

def test_anreichern_heftet_briefing():
    leads = [_lead("sales_hiring", aufhaenger="Opener"), _lead("marketing_hiring")]
    br.anreichern(leads)
    for lead in leads:
        assert "briefing" in lead
        assert "kurzprofil" in lead["briefing"]
        assert "einwaende" in lead["briefing"]
        assert isinstance(lead["briefing"]["einwaende"], list)


def test_anreichern_leer():
    br.anreichern([])  # Kein Crash


def test_anreichern_llm_durchgereicht():
    aufgerufen: list[str] = []

    def zaehlendes_llm(p: str) -> str:
        aufgerufen.append(p)
        return "LLM-Profil."

    leads = [_lead()]
    br.anreichern(leads, llm=zaehlendes_llm)
    assert aufgerufen
    assert leads[0]["briefing"]["kurzprofil"] == "LLM-Profil."


def test_anreichern_defensiv_bei_kaputtem_lead():
    leads: list[dict] = [_lead(), {}]
    br.anreichern(leads)
    assert "briefing" in leads[0]
    assert "briefing" in leads[1]

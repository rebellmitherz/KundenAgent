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


# ─── einwaende_fuer_lead / einwaende_fuer_signal ──────────────────────────────

def test_einwaende_struktur_vollstaendig():
    e = br.einwaende_fuer_signal("sales_hiring")
    assert len(e) >= 3
    for x in e:
        assert {"frage", "antwort", "ziel", "naechster_schritt"} <= set(x)
        assert x["antwort"] and x["naechster_schritt"]


def test_einwaende_alle_signale_liefern_mehrere():
    for sig in [
        "sales_hiring", "appointment_setter", "growth_expansion",
        "marketing_hiring", "leadership_hiring", "new_location",
    ]:
        e = br.einwaende_fuer_signal(sig)
        assert len(e) >= 3, f"Zu wenige Einwände für {sig}"


def test_einwaende_fallback_unbekannt():
    assert len(br.einwaende_fuer_signal("unbekannt_xyz")) >= 3


def test_einwaende_leer():
    assert len(br.einwaende_fuer_signal("")) >= 3


def test_einwaende_grossschreibung_ignoriert():
    assert (br.einwaende_fuer_signal("SALES_HIRING")[0]["frage"]
            == br.einwaende_fuer_signal("sales_hiring")[0]["frage"])


def test_einwaende_top_ist_signal_spezifisch():
    # sales_hiring → interner Aufbau ist der wahrscheinlichste Einwand
    assert "intern" in br.einwaende_fuer_lead(_lead("sales_hiring"))[0]["frage"].lower()
    # new_location → kein akuter Bedarf
    assert "bedarf" in br.einwaende_fuer_lead(_lead("new_location"))[0]["frage"].lower()


def test_einwaende_variieren_pro_firma():
    # Gleiches Signal, verschiedene Firmen → nicht alle bekommen dasselbe „Weitere"-Set.
    namen = ["Alpha GmbH", "Beta AG", "Gamma KG", "Delta SE", "Omega Werke"]
    sets = {
        tuple(x["frage"] for x in br.einwaende_fuer_lead(_lead("sales_hiring", company_name=n))[1:])
        for n in namen
    }
    assert len(sets) >= 2
    # Der Top (wahrscheinlichster) bleibt über alle Firmen stabil.
    tops = {br.einwaende_fuer_lead(_lead("sales_hiring", company_name=n))[0]["frage"] for n in namen}
    assert len(tops) == 1


def test_einwaende_interpolation_firma_und_angebot():
    e = br.einwaende_fuer_lead(_lead("new_location", company_name="Muster AG"), angebot="SEO-Pakete")
    text = " ".join(x["antwort"] + " " + x["naechster_schritt"] for x in e)
    assert "Muster AG" in text       # {firma} wird interpoliert
    assert "SEO-Pakete" in text       # {angebot_phrase} (new_location-Top = kein_bedarf)


def test_einwaende_keine_offenen_platzhalter():
    e = br.einwaende_fuer_lead(_lead("growth_expansion", company_name="X GmbH"), angebot="Webdesign")
    for x in e:
        for feld in ("antwort", "ziel", "naechster_schritt"):
            assert "{" not in x[feld] and "}" not in x[feld]


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


def test_briefing_einwaende_lead_spezifisch():
    b = br.briefing_erstellen(_lead("new_location", company_name="Standort GmbH"))
    assert len(b["einwaende"]) >= 3
    # Top passend zum Signal (new_location → kein akuter Bedarf)
    assert "bedarf" in b["einwaende"][0]["frage"].lower()


def test_briefing_angebot_fliesst_in_einwaende():
    b = br.briefing_erstellen(_lead("new_location"), angebot="Photovoltaik-Anlagen")
    text = " ".join(e["antwort"] for e in b["einwaende"])
    assert "Photovoltaik-Anlagen" in text


def test_briefing_ohne_signal():
    lead = {"company_name": "NoSignal AG", "entdeckt_per_signal": ""}
    b = br.briefing_erstellen(lead)
    assert len(b["einwaende"]) >= 3


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


# ─── LLM-Verfeinerung der Einwände (Top-Einwand individuell) ──────────────────

def test_einwaende_llm_verfeinert_top_antwort():
    def fake_llm(prompt: str) -> str:
        return "Individuell auf die Firma zugeschnittene Antwort vom LLM."

    ohne = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"))
    mit = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"), llm=fake_llm)
    # Top-Antwort ist jetzt die LLM-Variante, Frage/Reihenfolge bleiben gleich.
    assert mit[0]["antwort"] == "Individuell auf die Firma zugeschnittene Antwort vom LLM."
    assert mit[0]["antwort"] != ohne[0]["antwort"]
    assert mit[0]["frage"] == ohne[0]["frage"]


def test_einwaende_llm_nur_top_verfeinert():
    def fake_llm(prompt: str) -> str:
        return "LLM-Antwort."

    mit = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"), llm=fake_llm)
    # Nur der Top-Einwand wird verfeinert (1 Call/Lead) — die „Weiteren" bleiben deterministisch.
    assert mit[0]["antwort"] == "LLM-Antwort."
    assert all(e["antwort"] != "LLM-Antwort." for e in mit[1:])


def test_einwaende_llm_fehler_fallback_deterministisch():
    def kaputtes_llm(prompt: str) -> str:
        raise RuntimeError("Quota")

    ohne = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"))
    mit = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"), llm=kaputtes_llm)
    assert mit[0]["antwort"] == ohne[0]["antwort"]  # unverändert, kein Crash


def test_einwaende_llm_leere_antwort_fallback():
    ohne = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"))
    mit = br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"), llm=lambda _: "")
    assert mit[0]["antwort"] == ohne[0]["antwort"]  # zu kurz → deterministisch


def test_briefing_erstellen_reicht_llm_an_einwaende():
    def fake_llm(prompt: str) -> str:
        # Kurzprofil-Prompt nicht abfälschen, nur Einwand-Verfeinerung markieren.
        return "EINWAND-LLM" if "Einwand:" in prompt else "Kurzprofil vom LLM."

    b = br.briefing_erstellen(_lead("sales_hiring", company_name="Acme GmbH"), llm=fake_llm)
    assert b["einwaende"][0]["antwort"] == "EINWAND-LLM"


def test_einwand_prompt_erdet_gegen_recruiting_drift():
    # A: der Einwand-Prompt muss den Anti-Recruiting-Guardrail + Produktkontext tragen,
    # damit der LLM den Anlass (Stellenanzeige) nicht mit dem Angebot verwechselt.
    prompts: list[str] = []

    def spy_llm(prompt: str) -> str:
        prompts.append(prompt)
        return "Neu formulierte Antwort auf die Firma bezogen."

    br.einwaende_fuer_lead(_lead("sales_hiring", company_name="Acme GmbH"), llm=spy_llm)
    assert prompts, "LLM wurde nicht aufgerufen"
    p = prompts[0].lower()
    assert "recruiting" in p and "kaufsignal" in p
    assert "kernaussage" in p  # Vorlagen-Kernaussage soll erhalten bleiben


def test_einwand_prompt_versicherung_hat_eigenen_kontext():
    prompts: list[str] = []

    def spy_llm(prompt: str) -> str:
        prompts.append(prompt)
        return "Neu formulierte Versicherungs-Antwort."

    br.einwaende_fuer_lead(_lead("vs_cyber", company_name="Acme GmbH"), llm=spy_llm)
    assert prompts
    assert "versicherung" in prompts[0].lower()

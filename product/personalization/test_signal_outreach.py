"""Tests für signal_outreach — Aufhänger heften + Mail rendern (Engine gemockt).

    PYTHONUTF8=1 python product/personalization/test_signal_outreach.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from product.personalization import signal_outreach as so  # noqa: E402

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}")


# Angebot-Ableitung aus Profil-ID
check("website-Profil → website", so.angebot_aus_profil_id("rebellsystem_website") == "website")
check("akquise-Profil → akquise", so.angebot_aus_profil_id("akquise_termine") == "akquise")
check("default → kundenagent", so.angebot_aus_profil_id("rebellsystem") == "kundenagent")

# personalisiere() setzt lead['aufhaenger'] für alle Leads
leads = [
    {"company_name": "A GmbH", "entdeckt_per_signal": "sales_hiring", "signal_titel": "Sales Manager"},
    {"company_name": "B GmbH"},  # kein Signal
]
n = so.personalisiere(leads, "kundenagent")
check("alle Leads haben aufhaenger-Feld", all("aufhaenger" in l for l in leads))
check("Lead mit Signal personalisiert", bool(leads[0]["aufhaenger"]))
check("Lead ohne Signal leer", leads[1]["aufhaenger"] == "")
check("Zähler korrekt", n == 1)

# rendere_mail() nutzt injizierten Builder, Profil-Env wird gesetzt + zurückgesetzt
os.environ.pop("PROFILE_FIRST_TOUCH_BODY", None)
gesehen = {}

def fake_builder(lead):
    gesehen["body_env"] = os.environ.get("PROFILE_FIRST_TOUCH_BODY")
    return {"first_email_subject": "Betreff X", "first_email_body": "Hallo\n\n" + lead.get("aufhaenger", "")}

leads[0]["aufhaenger"] = "Mir ist aufgefallen, dass Sie Vertrieb einstellen."
mail = so.rendere_mail(leads[0], "C:/dummy", {"PROFILE_FIRST_TOUCH_BODY": "{aufhaenger}"}, _builder=fake_builder)
check("Mail gerendert", mail.get("betreff") == "Betreff X" and "Mir ist aufgefallen" in mail.get("body", ""))
check("Profil-Env war im Builder gesetzt", gesehen.get("body_env") == "{aufhaenger}")
check("Profil-Env danach zurückgesetzt", os.environ.get("PROFILE_FIRST_TOUCH_BODY") is None)

# rendere_mail() defensiv: Builder wirft → {}
def kaputt(lead):
    raise RuntimeError("engine down")

check("Builder-Fehler → {}", so.rendere_mail(leads[0], "C:/dummy", {}, _builder=kaputt) == {})

# rendere_mail() leerer Body → {}
check("leerer Body → {}", so.rendere_mail(leads[0], "C:/dummy", {},
                                          _builder=lambda l: {"first_email_body": "  "}) == {})

# personalisiere_und_rendere() setzt beide Felder
leads2 = [{"company_name": "C GmbH", "entdeckt_per_signal": "sales_hiring", "signal_titel": "SDR"}]
so.personalisiere_und_rendere(leads2, "akquise", "C:/dummy", {"PROFILE_FIRST_TOUCH_BODY": "{aufhaenger}"},
                              _builder=fake_builder)
check("kombiniert: aufhaenger gesetzt", bool(leads2[0].get("aufhaenger")))
check("kombiniert: personalisierte_mail gesetzt", "body" in leads2[0].get("personalisierte_mail", {}))

print(f"\n== {ok} OK / {fail} FAIL ==")
sys.exit(1 if fail else 0)

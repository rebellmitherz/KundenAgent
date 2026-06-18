"""Tests für die Signal-Personalisierung. Deterministisch, kein Netz, kein API.

Direkt ausführbar:  PYTHONUTF8=1 python product/personalization/test_aufhaenger.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from product.personalization.aufhaenger import (  # noqa: E402
    aufhaenger_angle,
    aufhaenger_text,
)

_ok = 0
_fail = 0


def check(name: str, bedingung: bool) -> None:
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {name}")
    else:
        _fail += 1
        print(f"  FAIL {name}")


# 1) Kein Signal → leerer Aufhänger (= generische Mail)
check("kein Signal → ''", aufhaenger_text({}, "kundenagent") == "")
check("leeres Signal-Feld → ''", aufhaenger_text({"entdeckt_per_signal": ""}, "akquise") == "")

# 2) sales_hiring → Regel erkennt hiring_sales
a = aufhaenger_angle({"entdeckt_per_signal": "sales_hiring", "signal_titel": "Sales Manager"}, "kundenagent")
check("sales_hiring erkannt", a is not None and a.typ == "hiring_sales")
check("Fakt Stellentitel übernommen", a is not None and a.fakten.get("stellentitel") == "Sales Manager")

# 3) Ohne LLM → deterministischer Fallback-Satz
txt = aufhaenger_text({"entdeckt_per_signal": "sales_hiring", "signal_titel": "Sales Manager"}, "akquise")
check("Fallback enthält 'Vertrieb'", "Vertrieb" in txt)
check("Fallback ist nicht leer", len(txt) > 20)

# 4) growth_expansion → growth
g = aufhaenger_angle({"entdeckt_per_signal": "growth_expansion", "signal_titel": "Neuer Standort"}, "akquise")
check("growth erkannt", g is not None and g.typ == "growth")

# 4b) NEU (Weg-2-Tiefe): die 4 zusätzlichen Signaltypen liefern eigene Aufhänger
for _sig, _typ in [
    ("appointment_setter", "outbound_setup"),
    ("marketing_hiring", "marketing_invest"),
    ("leadership_hiring", "sales_leadership"),
    ("new_location", "new_location"),
]:
    _n = aufhaenger_angle({"entdeckt_per_signal": _sig, "signal_titel": "X"}, "kundenagent")
    check(f"{_sig} → Aufhänger {_typ}", _n is not None and _n.typ == _typ)
    check(f"{_sig} Fallback nicht leer",
          len(aufhaenger_text({"entdeckt_per_signal": _sig, "signal_titel": "X"}, "akquise")) > 20)

# 5) Mit (Fake-)LLM → dessen Text wird genutzt
def fake_llm(prompt: str) -> str:
    assert "BELEGTE FAKTEN" in prompt  # Prompt sauber aufgebaut
    return "Ich sehe, dass Sie gerade Vertrieb aufbauen."

txt2 = aufhaenger_text({"entdeckt_per_signal": "sales_hiring", "signal_titel": "SDR"}, "kundenagent", llm=fake_llm)
check("LLM-Satz wird genutzt", txt2 == "Ich sehe, dass Sie gerade Vertrieb aufbauen.")

# 6) LLM wirft → Fallback greift, kein Crash
def kaputtes_llm(prompt: str) -> str:
    raise RuntimeError("api down")

txt3 = aufhaenger_text({"entdeckt_per_signal": "sales_hiring", "signal_titel": "x"}, "kundenagent", llm=kaputtes_llm)
check("LLM-Fehler → Fallback", "Vertrieb" in txt3)

# 7) LLM liefert leer → Fallback greift
txt4 = aufhaenger_text({"entdeckt_per_signal": "sales_hiring", "signal_titel": "x"}, "akquise", llm=lambda p: "  ")
check("LLM leer → Fallback", "Vertrieb" in txt4)

# 8) Website-Schwächen (Phase 2 vorbereitet) → benennt die Punkte
w = aufhaenger_text({"website_schwaechen": ["langsam_mobil", "kein_cta"]}, "website")
check("Website: langsam mobil benannt", "langsam" in w.lower())
check("Website: CTA benannt", "anfrage" in w.lower())

# 9) Website ohne Schwächen → ''
check("Website ohne Schwächen → ''", aufhaenger_text({"website_schwaechen": []}, "website") == "")

# 10) Unbekanntes Angebot → ''
check("unbekanntes Angebot → ''", aufhaenger_text({"entdeckt_per_signal": "sales_hiring"}, "irgendwas") == "")

# 11) Aufhänger-Längen-Schutz (kein Roman)
langer = aufhaenger_text({"entdeckt_per_signal": "sales_hiring"}, "kundenagent", llm=lambda p: "Satz. " * 200)
check("Längenschutz greift (<=400)", len(langer) <= 400)

print(f"\n== {_ok} OK / {_fail} FAIL ==")
sys.exit(1 if _fail else 0)

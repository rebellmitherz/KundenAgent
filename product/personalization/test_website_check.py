"""Tests für den Website-Detektor. Fetch gemockt → kein Netz.

    PYTHONUTF8=1 python product/personalization/test_website_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from product.personalization import website_check as wc  # noqa: E402

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}")


def fetch(final_url, html, elapsed=0.5, okv=True):
    return lambda url: {"ok": okv, "final_url": final_url, "html": html, "elapsed": elapsed}


GESUND = (
    '<html><head><meta name="viewport" content="width=device-width">'
    '<title>X</title></head><body>'
    '<a href="/kontakt">Kontakt</a> <a href="mailto:x@y.de">Mail</a>'
    '<a href="/impressum">Impressum</a>'
    '<footer>© 2026 Firma</footer></body></html>'
)

# 1) Gesunde Seite → keine Schwächen
check("gesunde Seite → []", wc.pruefe_website("https://gut.de", _fetch=fetch("https://gut.de", GESUND), jahr=2026) == [])

# 2) http → kein_ssl
s = wc.pruefe_website("http://alt.de", _fetch=fetch("http://alt.de", GESUND), jahr=2026)
check("http → kein_ssl", "kein_ssl" in s)

# 3) kein viewport → nicht_mobil
s = wc.pruefe_website("https://x.de", _fetch=fetch("https://x.de", GESUND.replace('<meta name="viewport" content="width=device-width">', "")), jahr=2026)
check("kein viewport → nicht_mobil", "nicht_mobil" in s)

# 4) kein Kontakt/mailto/Formular → kein_cta
nackt = '<html><head><meta name="viewport" content="x"></head><body><p>Nur Text. Impressum</p><footer>© 2026</footer></body></html>'
s = wc.pruefe_website("https://x.de", _fetch=fetch("https://x.de", nackt), jahr=2026)
check("kein CTA → kein_cta", "kein_cta" in s)

# 5) kein Impressum → kein_impressum
s = wc.pruefe_website("https://x.de", _fetch=fetch("https://x.de", GESUND.replace("Impressum", "Über uns").replace("/impressum", "/ueber")), jahr=2026)
check("kein Impressum → kein_impressum", "kein_impressum" in s)

# 6) altes Copyright → veraltet
s = wc.pruefe_website("https://x.de", _fetch=fetch("https://x.de", GESUND.replace("© 2026", "© 2019")), jahr=2026)
check("altes © → veraltet", "veraltet" in s)
check("aktuelles © → nicht veraltet", "veraltet" not in wc.pruefe_website("https://x.de", _fetch=fetch("https://x.de", GESUND), jahr=2026))

# 7) langsam → langsam_mobil
s = wc.pruefe_website("https://x.de", _fetch=fetch("https://x.de", GESUND, elapsed=6.0), jahr=2026)
check("langsame Antwort → langsam_mobil", "langsam_mobil" in s)

# 8) nicht erreichbar → [] (nichts behaupten)
check("unerreichbar → []", wc.pruefe_website("https://tot.de", _fetch=fetch("", "", okv=False)) == [])

# 9) leere URL → []
check("leere URL → []", wc.pruefe_website("", _fetch=fetch("", "", okv=False)) == [])

print(f"\n== {ok} OK / {fail} FAIL ==")
sys.exit(1 if fail else 0)

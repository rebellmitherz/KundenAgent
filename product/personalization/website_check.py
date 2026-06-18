"""Website-Detektor — findet konkrete, belegbare Schwächen einer Seite.

Liefert kurze Schwäche-Codes (siehe `_WEBSITE_SCHWAECHE_LABEL` in aufhaenger.py),
aus denen der Aufhänger für das Website-Angebot gebaut wird. Es wird NICHTS
erfunden: Ist die Seite nicht erreichbar oder gibt es keinen klaren Befund, kommt
eine leere Liste zurück → generische Mail.

Nur stdlib (urllib), kein Fremd-Paket. Der Fetch ist injizierbar (`_fetch`) →
offline testbar, kein Netz im Test.
"""
from __future__ import annotations

import re
import ssl
import time
import urllib.request
from typing import Callable, Optional

# Schwäche-Codes — müssen zu _WEBSITE_SCHWAECHE_LABEL in aufhaenger.py passen.
CODES = ("kein_ssl", "nicht_mobil", "kein_cta", "kein_impressum", "veraltet", "langsam_mobil")

_UA = "Mozilla/5.0 (compatible; RebellsystemWebCheck/1.0)"


def _default_fetch(url: str, timeout: float = 8.0) -> dict:
    """Holt die Seite. Gibt {final_url, html, elapsed, ok} zurück (ok=False bei Fehler)."""
    u = (url or "").strip()
    if not u:
        return {"ok": False}
    if "://" not in u:
        u = "https://" + u
    req = urllib.request.Request(u, headers={"User-Agent": _UA})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Befund zählt, nicht Zertifikatsgüte
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            roh = resp.read(400_000)  # Deckel: erste ~400 KB reichen für die Befunde
            final = resp.geturl()
        html = roh.decode("utf-8", errors="replace")
        return {"ok": True, "final_url": final, "html": html, "elapsed": time.monotonic() - start}
    except Exception:
        return {"ok": False}


def pruefe_website(
    url: str,
    *,
    _fetch: Optional[Callable[[str], dict]] = None,
    jahr: Optional[int] = None,
    langsam_ab: float = 4.0,
) -> list[str]:
    """Prüft eine Website und gibt die gefundenen Schwäche-Codes zurück (max. sinnvoll)."""
    fetch = _fetch or _default_fetch
    res = fetch(url) or {}
    if not res.get("ok"):
        return []  # nicht erreichbar → nichts behaupten

    final = (res.get("final_url") or "").lower()
    low = (res.get("html") or "").lower()
    elapsed = float(res.get("elapsed") or 0.0)
    schwaechen: list[str] = []

    # 1) Kein HTTPS (final nach Redirects)
    if final.startswith("http://"):
        schwaechen.append("kein_ssl")

    # 2) Nicht mobil-optimiert (kein viewport-Meta)
    if "viewport" not in low:
        schwaechen.append("nicht_mobil")

    # 3) Kein klarer Call-to-Action (kein mailto/tel/Kontakt-Link/Formular)
    hat_cta = (
        "mailto:" in low
        or "tel:" in low
        or "<form" in low
        or re.search(r'href=["\'][^"\']*(kontakt|contact|anfrage|angebot|termin|booking|calendly)', low) is not None
    )
    if not hat_cta:
        schwaechen.append("kein_cta")

    # 4) Kein Impressum auffindbar
    if re.search(r"(impressum|imprint|legal-notice|rechtliches)", low) is None:
        schwaechen.append("kein_impressum")

    # 5) Veraltet (Copyright-Jahr ≥ 2 Jahre alt)
    jahre = re.findall(r"(?:©|&copy;|copyright)\D{0,12}(20\d{2})", low)
    if jahre:
        try:
            neuestes = max(int(j) for j in jahre)
            cur = jahr if jahr is not None else time.localtime().tm_year
            if cur - neuestes >= 2:
                schwaechen.append("veraltet")
        except ValueError:
            pass

    # 6) Langsam (Antwortzeit über Schwelle)
    if elapsed >= langsam_ab:
        schwaechen.append("langsam_mobil")

    return schwaechen

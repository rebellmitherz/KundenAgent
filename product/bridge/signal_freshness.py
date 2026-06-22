"""Signal-Frische — wie alt ist die Stellenanzeige hinter dem Kaufsignal?

Warum diese Schicht existiert
------------------------------
Ein Kaufsignal („Firma stellt Vertrieb ein") ist nur so lange *kaufbereit*, wie
die Anzeige AKTUELL ist. Eine 4 Monate alte Anzeige bedeutet meist: Stelle
besetzt → kein akuter Bedarf mehr → der Lead ist wertlos, und schlimmer noch,
der „Stellenanzeige ansehen"-Beleg-Link führt den Käufer auf eine abgelaufene
Seite. Damit ein Lead *beweisbar* 20 € wert ist, muss das System eine 3-Tage-
Anzeige von einer 6-Monats-Anzeige unterscheiden können.

Diese Schicht liest das Anzeigendatum aus dem, was Discovery ohnehin hat (SERP-
``date``-Feld, Snippet, Titel) — **rein deterministisch, kein Netz** — und liefert:
Alter in Tagen, ein kundenlesbares Label („vor 3 Tagen") und einen Score-Faktor
für die Kaufbereitschaft. Defensiv: unbekanntes Datum → kein Abschlag (kein
Beweis, dass es alt ist — lieber nicht bestrafen).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

# Monatsnamen DE + EN (auch Abkürzungen) → Monatszahl.
_MONATE = {
    "januar": 1, "jan": 1, "february": 2, "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mar": 3, "march": 3, "april": 4, "apr": 4,
    "mai": 5, "may": 5, "juni": 6, "jun": 6, "july": 7, "juli": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "october": 10, "oct": 10, "okt": 10,
    "november": 11, "nov": 11, "dezember": 12, "december": 12, "dec": 12, "dez": 12,
}

# Relative Angaben: „vor 3 Tagen" / „3 days ago" (auch Wochen/Monate/Jahre/Stunden).
_REL_RE = re.compile(
    r"vor\s+(\d+)\s*(tag|tage|tagen|woche|wochen|monat|monate|monaten|jahr|jahre|jahren|stunde|stunden|minute|minuten)"
    r"|(\d+)\+?\s*(day|days|week|weeks|month|months|year|years|hour|hours|minute|minutes)\s+ago",
    re.I,
)
_TAGE_PRO = {
    "tag": 1, "tage": 1, "tagen": 1, "day": 1, "days": 1,
    "woche": 7, "wochen": 7, "week": 7, "weeks": 7,
    "monat": 30, "monate": 30, "monaten": 30, "month": 30, "months": 30,
    "jahr": 365, "jahre": 365, "jahren": 365, "year": 365, "years": 365,
    "stunde": 0, "stunden": 0, "hour": 0, "hours": 0,
    "minute": 0, "minuten": 0, "minutes": 0,
}

# Absolute Daten in mehreren Schreibweisen.
_DATE_ISO_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")          # 2026-03-12
_DATE_DOT_RE = re.compile(r"\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\b")   # 12.03.2026
_DATE_DE_TXT_RE = re.compile(r"\b(\d{1,2})\.?\s+([A-Za-zäöüÄÖÜ]+)\.?\s+(\d{4})\b")  # 12. März 2026
_DATE_EN_TXT_RE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b")     # Mar 12, 2026


def _heute(heute: Optional[date]) -> date:
    return heute or date.today()


def parse_relativ(text: str) -> Optional[int]:
    """Alter in Tagen aus relativer Angabe; ``None`` wenn keine erkannt.

    Erkennt „heute/today", „gestern/yesterday", „vorgestern" und „vor N …"/
    „N … ago" (Tage/Wochen/Monate/Jahre; Stunden/Minuten → 0 Tage = heute).
    """
    t = (text or "").lower()
    if not t:
        return None
    if re.search(r"\b(heute|today|gerade eben|just now|just posted|new)\b", t):
        return 0
    if re.search(r"\b(gestern|yesterday)\b", t):
        return 1
    if re.search(r"\bvorgestern\b", t):
        return 2
    m = _REL_RE.search(t)
    if m:
        if m.group(1):                       # deutscher Zweig
            n, einheit = int(m.group(1)), m.group(2)
        else:                                # englischer Zweig
            n, einheit = int(m.group(3)), m.group(4)
        return n * _TAGE_PRO.get(einheit, 1)
    return None


def parse_absolut(text: str) -> Optional[date]:
    """Erstes plausibles absolutes Datum aus Freitext; ``None`` wenn keins."""
    t = text or ""
    m = _DATE_ISO_RE.search(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = _DATE_DOT_RE.search(t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    m = _DATE_DE_TXT_RE.search(t)
    if m:
        mon = _MONATE.get(m.group(2).lower())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                pass
    m = _DATE_EN_TXT_RE.search(t)
    if m:
        mon = _MONATE.get(m.group(1).lower())
        if mon:
            try:
                return date(int(m.group(3)), mon, int(m.group(2)))
            except ValueError:
                pass
    return None


def signal_alter_tage(text: str, *, heute: Optional[date] = None) -> Optional[int]:
    """Bestes Alter in Tagen aus Freitext (relativ bevorzugt, sonst absolut).

    ``None`` = kein Datum erkennbar (= unbekannt, NICHT alt). Negative Deltas
    (Datum in der Zukunft = vermutlich Fehlparse) werden auf 0 geklemmt; absurd
    alte Treffer (>10 Jahre) gelten als Fehlparse und werden verworfen.
    """
    rel = parse_relativ(text)
    if rel is not None:
        return max(0, rel)
    d = parse_absolut(text)
    if d is not None:
        delta = (_heute(heute) - d).days
        if -2 <= delta <= 3650:
            return max(0, delta)
    return None


def frische_text(tage: Optional[int]) -> str:
    """Kundenlesbares Label: „heute" / „vor 3 Tagen" / „vor 2 Wochen" / …"""
    if tage is None:
        return ""
    if tage <= 0:
        return "heute"
    if tage == 1:
        return "gestern"
    if tage < 7:
        return f"vor {tage} Tagen"
    if tage < 14:
        return "vor 1 Woche"
    if tage < 31:
        return f"vor {tage // 7} Wochen"
    if tage < 61:
        return "vor 1 Monat"
    if tage < 365:
        return f"vor {max(1, tage // 30)} Monaten"
    return "über 1 Jahr"


def frische_faktor(tage: Optional[int]) -> float:
    """Multiplikativer Kaufbereitschafts-Faktor (0.5–1.0) nach Anzeigenalter.

    Frisch (≤14 Tage) oder unbekannt → 1.0 (kein Abschlag). Danach gestaffelt
    runter; >90 Tage = Stelle vermutlich besetzt → harter Abschlag. Multiplikativ,
    damit das Signal nie ins Negative kippt, aber die Stufe (hoch/mittel) sinkt.
    """
    if tage is None or tage <= 14:
        return 1.0
    if tage <= 30:
        return 0.92
    if tage <= 60:
        return 0.80
    if tage <= 90:
        return 0.65
    return 0.50


def ist_veraltet(tage: Optional[int]) -> bool:
    """True, wenn das Signal alt genug ist, um den Käufer zu warnen (>90 Tage)."""
    return isinstance(tage, int) and tage > 90

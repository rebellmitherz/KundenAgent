"""CSV-Export der Signal-Leads für externes Kontakt-Enrichment (Clay/Findymail/…).

Tool-agnostische Grenze: der KundenAgent liefert genau die Spalten, die ein
Enrichment-Tool als INPUT braucht (Name + Domain treiben die Trefferquote), plus
eine ``lead_id`` als Schlüssel für den späteren Merge-back. Was das Tool NICHT
bekommt, ist alles Interne (Briefing, Einwände, Mail) — das bleibt im Lead und
wird beim Merge wieder mit den angereicherten Kontaktdaten zusammengeführt.

Reine Lese-/Schreib-Logik: kein Gate, kein b2bbot, keine API, keine Kosten.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse

# Spalten-Vertrag (Reihenfolge = CSV-Reihenfolge). ``lead_id`` ist der Join-Key.
CLAY_SPALTEN = [
    "lead_id",
    "company_name",
    "domain",
    "first_name",
    "last_name",
    "full_name",
    "city",
    "linkedin_url",
    "signal",
    "signal_quelle_url",
    "role_email",       # vorhandene (oft generische) Mail vom Impressum — Kontext fürs Tool
    "central_phone",    # Zentrale aus dem Impressum — Clay soll die Durchwahl finden
]


def domain_aus_website(url: str) -> str:
    """``https://www.itebo.de/unternehmen`` → ``itebo.de``. Leer bei Unsinn."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    try:
        host = urlparse(u).netloc.strip().lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]  # Port abschneiden, falls vorhanden


# Rollen-/Abteilungs-/Funktions-Postfächer: gelten NICHT als persönliche Mail.
# Bewusst LOKAL für die Anreicherungs-Entscheidung — NICHT das globale
# ``_ist_generisch`` (das hängt am Premium-Gate). Emilio 2026-07-01: Abteilungs-
# Adressen wie ``technik@`` dürfen nicht als „Entscheider-Mail" durchgehen.
_ROLLEN_WORTE = {
    "info", "kontakt", "contact", "service", "kundenservice", "support", "office",
    "buero", "büro", "mail", "email", "zentrale", "empfang", "sekretariat",
    "verwaltung", "buchhaltung", "rechnung", "rechnungen", "einkauf", "bestellung",
    "vertrieb", "sales", "marketing", "presse", "pr", "karriere", "jobs", "job",
    "bewerbung", "recruiting", "hr", "personal", "datenschutz", "privacy", "hinweis",
    "gruppe", "group", "team", "shop", "store", "redaktion", "online", "webmaster",
    "admin", "noreply", "reply", "hallo", "hello", "moin", "willkommen", "post",
    "technik", "technical", "it", "edv", "geschaeftsfuehrung", "gf", "vorstand",
    "leitung", "netzanschluss", "netzanschluesse", "tankstelle", "tankstellen",
    "filiale", "standort", "zentraleinkauf", "mailbox",
}


def ist_persoenliche_mail(addr: str) -> bool:
    """Heuristik: sieht die lokale Adresse (vor ``@``) nach einer PERSON aus?

    persönlich       = zwei Namensteile (``vorname.nachname`` / ``t.heyen`` /
                       ``mueller-schmidt``) und KEIN Teil ist ein Rollenwort.
    NICHT persönlich  = Rollen-/Abteilungswort (``info``, ``technik``, ``gf`` …)
                       ODER Einzel-Token ohne Namens-Trenner (``duesseldorf``).
    Konservativ Richtung Qualität: im Zweifel NICHT persönlich → der Lead geht in
    die Anreicherung (lieber einmal zu viel angereichert als eine Abteilungs-
    Adresse als Entscheider-Mail ausgeliefert).
    """
    local = (addr or "").split("@", 1)[0].strip().lower()
    if not local:
        return False
    tokens = [t for t in re.split(r"[._\-]+", local) if t]
    if any(t in _ROLLEN_WORTE for t in tokens):
        return False
    return len(tokens) >= 2


def hat_persoenliche_mail(lead: dict) -> bool:
    """True, wenn der Lead schon eine persönliche Mail (echter Personen-Name) hat.

    Solche Leads brauchen keine Anreicherung/Clay mehr → sie werden aus der
    Clay-Input-CSV herausgehalten. Nutzt die strengere ``ist_persoenliche_mail``
    (Rollen-/Abteilungs-Postfächer zählen NICHT), damit z. B. ``technik@`` nicht
    fälschlich als „fertig" gilt.
    """
    mail = (lead.get("email") or "").strip()
    return bool(mail) and ist_persoenliche_mail(mail)


def namen_split(full: str) -> tuple[str, str]:
    """``Udo Wenker`` → ``("Udo", "Wenker")``. Ein Token → Vorname, Rest leer."""
    teile = [t for t in (full or "").strip().split() if t]
    if not teile:
        return "", ""
    if len(teile) == 1:
        return teile[0], ""
    return teile[0], teile[-1]


def _ansprechpartner(lead: dict) -> str:
    return (
        lead.get("contact_full_name")
        or lead.get("managing_director")
        or lead.get("ansprechpartner")
        or ""
    ).strip()


def lead_zu_clay_zeile(lead: dict, *, index: int = 0) -> dict:
    """Baut aus einem Lead eine Clay-Input-Zeile (nur die Vertragsspalten)."""
    full = _ansprechpartner(lead)
    vor, nach = namen_split(full)
    firma = (
        lead.get("canonical_company_name")
        or lead.get("company_name_clean")
        or lead.get("company_name")
        or ""
    ).strip()
    lead_id = (lead.get("lead_id") or "").strip()
    if not lead_id:
        run = (lead.get("run_id") or "run").strip()
        lead_id = f"{run}#{index}"
    return {
        "lead_id": lead_id,
        "company_name": firma,
        "domain": domain_aus_website(lead.get("website") or ""),
        "first_name": vor,
        "last_name": nach,
        "full_name": full,
        "city": (lead.get("city") or lead.get("city_detected") or "").strip(),
        "linkedin_url": (lead.get("linkedin_person_url") or "").strip(),
        "signal": (lead.get("entdeckt_per_signal") or "").strip(),
        "signal_quelle_url": (lead.get("signal_quelle_url") or "").strip(),
        "role_email": (lead.get("email") or "").strip(),
        "central_phone": (lead.get("phone") or lead.get("telefon") or "").strip(),
    }


def lade_leads(pfad: str | Path) -> list[dict]:
    """Liest Leads aus einer JSON-Datei: entweder ``{"leads": [...]}`` (Engine-Lauf)
    oder eine reine Liste ``[...]``."""
    data = json.loads(Path(pfad).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("leads") or [])
    if isinstance(data, list):
        return list(data)
    return []


def leads_zu_csv(leads: list[dict], ziel: str | Path) -> int:
    """Schreibt die Clay-Input-CSV. Gibt die Zahl geschriebener Zeilen zurück.

    ``utf-8-sig`` (BOM) → Excel/Clay erkennen Umlaute korrekt.
    """
    ziel = Path(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    zeilen = [lead_zu_clay_zeile(l, index=i) for i, l in enumerate(leads or [])]
    with open(ziel, "w", encoding="utf-8-sig", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=CLAY_SPALTEN)
        schreiber.writeheader()
        for z in zeilen:
            schreiber.writerow(z)
    return len(zeilen)

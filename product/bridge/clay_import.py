"""Merge-back der Clay/Findymail-angereicherten CSV auf die bestehenden Leads.

Gegenstück zu ``clay_export``. Der KundenAgent hat die reichen Lead-Objekte
(Briefing, Einwände, Mail, Score, ``premium_klasse``) — Clay liefert NUR
Kontaktdaten (persönliche Mail, Mail-Status, Durchwahl/Mobil). Dieser Merge
führt beides zusammen, OHNE die Premium-Felder zu berühren.

HARTE REGELN (aus LESSONS_LEARNED):
- NIEMALS ``import_cli.py`` — das würde Briefing/Einwände/Mail/Score zerstören.
- Nur die Kontaktfelder werden geschrieben; alles Interne bleibt unangetastet.
- Match primär über die **Domain** (stabiler Business-Key; ``lead_id`` aus
  ``latest/signal_leads.json`` ist oft leer → positionsbasierter Fallback wäre
  fragil). ``lead_id``/Firmenname sind Zusatz-Bestätigung.

Robust gegen Clays reale Spaltennamen: ``_ALIASES`` deckt gängige Namen ab
(Work/Personal Email, Mobile/Direct Dial, Email Status). Nutzt Clay einen
exotischen Namen, ergänzt man dort EINE Zeile — kein Umbau nötig.

Reine Lese-/Merge-Logik: kein b2bbot, keine API, keine Kosten.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from product.bridge.clay_export import domain_aus_website
from product.bridge.signal_contact_enrich import _ist_generisch, ist_plausible_telefonnummer

# ─── Spalten-Aliase: internes Feld → mögliche (normalisierte) Clay-Header ────
# Normalisierung: lower + alnum, Rest zu "_". "Work Email" → "work_email".
_ALIASES: dict[str, tuple[str, ...]] = {
    "personal_email": (
        "personal_email", "work_email", "professional_email", "business_email",
        "verified_email", "email", "email_address", "found_email", "clay_email",
    ),
    "email_status": (
        "email_status", "email_verification", "email_verification_status",
        "verification_status", "email_state", "status", "verified", "deliverability",
    ),
    "mobile_phone": (
        "mobile_phone", "mobile_number", "mobile", "direct_dial", "direct_phone",
        "direct_number", "phone_number", "phone", "cell_phone", "personal_phone",
    ),
    "verified_name": (
        "verified_name", "full_name_verified", "contact_name", "person_name",
    ),
    "lead_id": ("lead_id",),
    "domain": ("domain", "company_domain", "website"),
    "company_name": ("company_name", "company", "firma"),
}


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (h or "").strip().lower()).strip("_")


def spalten_map(header: list[str]) -> dict[str, str]:
    """Ordnet interne Feldnamen den ECHTEN CSV-Spalten zu (per Alias).

    Gibt ``{internes_feld: original_spaltenname}`` — nur für gefundene Felder.
    Der erste passende Alias in Header-Reihenfolge gewinnt.
    """
    norm_zu_orig: dict[str, str] = {}
    for orig in header:
        norm_zu_orig.setdefault(_norm_header(orig), orig)
    ergebnis: dict[str, str] = {}
    for feld, aliase in _ALIASES.items():
        for alias in aliase:
            if alias in norm_zu_orig:
                ergebnis[feld] = norm_zu_orig[alias]
                break
    return ergebnis


def lade_enriched_csv(pfad: str | Path) -> tuple[list[dict], dict[str, str]]:
    """Liest die angereicherte CSV. Gibt (Zeilen, spalten_map) zurück.

    Toleriert BOM (utf-8-sig) und Semikolon-Trenner (Excel-DE)."""
    text = Path(pfad).read_text(encoding="utf-8-sig")
    trenner = ";" if (text.splitlines()[0].count(";") > text.splitlines()[0].count(",")) else ","
    zeilen = list(csv.DictReader(text.splitlines(), delimiter=trenner))
    header = list(zeilen[0].keys()) if zeilen else []
    return zeilen, spalten_map(header)


def _lead_domain(lead: dict) -> str:
    return domain_aus_website(lead.get("website") or lead.get("company_domain") or "")


def _zeile_domain(zeile: dict, smap: dict[str, str]) -> str:
    roh = (zeile.get(smap.get("domain", "")) or "").strip()
    return domain_aus_website(roh) if roh else ""


def _hat_persoenliche_mail(lead: dict) -> bool:
    mail = (lead.get("email") or "").strip()
    return bool(mail) and not _ist_generisch(mail)


def ist_auslieferbar(lead: dict) -> bool:
    """v1-Kanal-Gate (Emilios Latte für die erste Runde): auslieferbar, wenn eine
    persönliche Mail ODER eine plausible Telefonnummer (Durchwahl/Mobil ODER
    Zentrale) vorliegt. Durchwahl-Pflicht kommt erst nach dem ersten Kunden.
    """
    if _hat_persoenliche_mail(lead):
        return True
    for feld in ("mobile_phone", "direct_dial", "phone", "phone_clean"):
        if ist_plausible_telefonnummer(lead.get(feld) or ""):
            return True
    return False


def merge_kontakt(leads: list[dict], enriched: list[dict], smap: dict[str, str]) -> dict:
    """Merged Clay-Kontaktdaten per Domain in die Leads (in-place). NUR Kontaktfelder.

    Premium-Felder (briefing/einwaende/personalisierte_mail/premium_klasse/score)
    bleiben unangetastet. Gibt eine kleine Statistik zurück.
    """
    stats = {"gematcht": 0, "pers_mail_gesetzt": 0, "mobil_gesetzt": 0,
             "name_ergaenzt": 0, "ohne_match": 0}
    # Index der Leads nach Domain (erster Treffer gewinnt).
    nach_domain: dict[str, dict] = {}
    for l in leads:
        d = _lead_domain(l)
        if d:
            nach_domain.setdefault(d, l)

    for zeile in enriched:
        d = _zeile_domain(zeile, smap)
        lead = nach_domain.get(d) if d else None
        if not lead:
            stats["ohne_match"] += 1
            continue
        stats["gematcht"] += 1

        def _wert(feld: str) -> str:
            return (zeile.get(smap.get(feld, "")) or "").strip()

        pers_mail = _wert("personal_email")
        if pers_mail and "@" in pers_mail and not _ist_generisch(pers_mail):
            lead["clay_personal_email"] = pers_mail
            status = _wert("email_status")
            if status:
                lead["clay_email_status"] = status
            # Nur wenn die vorhandene Mail generisch/leer ist, auf die persönliche heben.
            if not _hat_persoenliche_mail(lead):
                lead["email"] = pers_mail
                lead["is_generic_email"] = False
                lead["email_type"] = "persönliche E-Mail (Clay-Enrichment)"
                lead["email_source_type"] = "clay_enrichment"
            stats["pers_mail_gesetzt"] += 1

        mobil = _wert("mobile_phone")
        if mobil and ist_plausible_telefonnummer(mobil):
            lead["mobile_phone"] = mobil
            lead["direct_dial"] = mobil
            lead["has_direct_dial"] = True
            stats["mobil_gesetzt"] += 1

        vname = _wert("verified_name")
        if vname and not (lead.get("contact_full_name") or "").strip():
            lead["contact_full_name"] = vname
            lead["managing_director"] = lead.get("managing_director") or vname
            lead["safe_salutation"] = f"Guten Tag {vname.split()[-1]}," if vname.split() else lead.get("safe_salutation")
            stats["name_ergaenzt"] += 1

    return stats


def merge_und_filtern(leads: list[dict], enriched: list[dict], smap: dict[str, str]) -> tuple[list[dict], dict]:
    """Vollständiger Merge-back: Kontaktdaten mergen, dann Leads OHNE nutzbaren
    Kanal aussortieren. Gibt (auslieferbare_leads, stats) zurück."""
    stats = merge_kontakt(leads, enriched, smap)
    auslieferbar = [l for l in leads if ist_auslieferbar(l)]
    stats["eingang"] = len(leads)
    stats["auslieferbar"] = len(auslieferbar)
    stats["aussortiert_kein_kanal"] = len(leads) - len(auslieferbar)
    return auslieferbar, stats


def lade_leads(pfad: str | Path) -> list[dict]:
    """Liest Leads aus JSON (``{"leads": [...]}`` oder reine Liste)."""
    data = json.loads(Path(pfad).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("leads") or [])
    return list(data) if isinstance(data, list) else []

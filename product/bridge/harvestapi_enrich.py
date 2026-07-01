"""harvestapi-Mail-Anreicherung — persönliche E-Mail (+ Ansprechpartner) je Lead.

Zweck (Emilio, 2026-07-01): Der KundenAgent holt für Leads MIT LinkedIn-URL die
verifizierte persönliche Mail direkt selbst über den Apify-Actor
``harvestapi/linkedin-profile-scraper`` (Free-Plan-API, pay-per-result ~$0,008/Profil).
So entfällt der manuelle Clay-Schritt für diese Leads; nur die URL-losen gehen noch
an Clay.

Bewusste Grenzen (aus dem Test an echten Leads):
- **NUR** persönliche Mail (+ Name als Ansprechpartner-Bestätigung) wird übernommen —
  der Actor liefert ein Riesen-JSON (Skills, Werdegang …), davon wird alles verworfen.
- **KEIN Telefon** — Telefon ist Sache des Agenten (Zentrale aus Impressum).
- **Domain-Gate:** eine gefundene Mail wird nur übernommen, wenn ihre Domain zur
  Firmendomain des Leads passt (verhindert Mails am falschen Arbeitgeber laut LinkedIn).
- **harvestapi findet NICHT den Entscheider** — es liest nur das Profil, dessen URL der
  Agent schon gefunden hat. Namensqualität = URL-Qualität.
- Defensiv: kein API-Key / Actor-Fehler → Lauf läuft ohne Anreicherung weiter (nie Crash).

Testbar: der Actor-Aufruf ist über ``runner`` injizierbar — Tests hängen nicht am Netz.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

# Root in den Pfad, damit auch der Standalone-Aufruf (py …/harvestapi_enrich.py) geht.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from product.bridge.clay_export import domain_aus_website
from product.bridge.linkedin_profil import _apify_key
from product.bridge.signal_contact_enrich import _ist_generisch

# Der funktionierende Free-API-Actor (dev_fusion ist auf Free API-gesperrt).
_ACTOR = os.environ.get("APIFY_HARVEST_ACTOR", "harvestapi~linkedin-profile-scraper")
# Modus MIT Mail-Suche (der „no email"-Modus wäre $4/1k ohne Mail).
_MODE_EMAIL = "Profile details + email search ($10 per 1k)"


def _norm_li(url: str) -> str:
    """LinkedIn-URL auf den stabilen Teil ``/in/<slug>`` normalisieren.

    Robust gegen Länder-Subdomain (``de.`` vs ``www.``), Schema, Query, Slash.
    """
    u = (url or "").strip().lower().split("?")[0].rstrip("/")
    i = u.find("/in/")
    return u[i:] if i >= 0 else u


def _email_domain(addr: str) -> str:
    addr = (addr or "").strip().lower()
    return addr.split("@", 1)[1] if "@" in addr else ""


def _rang(e: dict) -> tuple:
    """Sortierschlüssel: valide/zustellbare, nicht-catch-all, nicht-frei, hoher Score zuerst."""
    return (
        1 if (e.get("status") or "").lower() == "valid" else 0,
        1 if e.get("deliverable") else 0,
        0 if e.get("catchAllDomain") else 1,
        0 if e.get("free") else 1,
        int(e.get("qualityScore") or 0),
    )


def beste_email(emails: list[dict], lead_domain: str = "") -> dict | None:
    """Beste brauchbare Mail aus harvestapis ``emails``-Liste — oder None.

    Filtert: gültige Adresse, nicht generisch, und (wenn ``lead_domain`` gesetzt)
    Domain == Firmendomain. Sortiert die Verbleibenden nach Qualität.
    """
    kandidaten = []
    for e in emails or []:
        addr = (e.get("email") or "").strip()
        if "@" not in addr or _ist_generisch(addr):
            continue
        if lead_domain and _email_domain(addr) != lead_domain:
            continue
        kandidaten.append(e)
    if not kandidaten:
        return None
    return sorted(kandidaten, key=_rang, reverse=True)[0]


def _hat_persoenliche_mail(lead: dict) -> bool:
    mail = (lead.get("email") or "").strip()
    return bool(mail) and not _ist_generisch(mail)


def _actor_runner(urls: list[str], key: str) -> list[dict]:
    """Echter Apify-Aufruf (run-sync). Nur im echten Lauf — in Tests injiziert."""
    url = (
        f"https://api.apify.com/v2/acts/{_ACTOR}/run-sync-get-dataset-items"
        f"?token={key}&timeout=300"
    )
    payload = json.dumps({
        "queries": list(urls),
        "profileScraperMode": _MODE_EMAIL,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=310) as r:
        return json.loads(r.read().decode())


def emails_fuer_leads(
    leads: list[dict],
    *,
    runner=None,
    key: str | None = None,
    nur_domain_treffer: bool = True,
) -> dict:
    """Reichert Leads MIT LinkedIn-URL um persönliche Mail (+ Name) an. In-place.

    Übernimmt NUR Mail + Ansprechpartner-Name; kein Telefon, keine Profil-Details.
    Leads, die schon eine persönliche Mail haben, werden übersprungen.
    Gibt eine Statistik zurück. Wirft nie — Fehler landen in ``stats['fehler']``.
    """
    stats = {"kandidaten": 0, "mail_gesetzt": 0, "name_ergaenzt": 0,
             "ohne_treffer": 0, "uebersprungen_hat_mail": 0}

    kand = []
    for l in leads or []:
        if not (l.get("linkedin_person_url") or "").strip():
            continue
        if _hat_persoenliche_mail(l):
            stats["uebersprungen_hat_mail"] += 1
            continue
        kand.append(l)
    stats["kandidaten"] = len(kand)
    if not kand:
        return stats

    key = key or _apify_key()
    if not key:
        stats["fehler"] = "kein APIFY_API_KEY — harvestapi übersprungen"
        return stats

    urls = [(l.get("linkedin_person_url") or "").strip() for l in kand]
    runner = runner or _actor_runner
    try:
        items = runner(urls, key)
    except Exception as exc:  # noqa: BLE001
        stats["fehler"] = f"harvestapi-Aufruf fehlgeschlagen: {exc}"
        return stats

    by: dict[str, dict] = {}
    for it in (items or []):
        k = _norm_li(it.get("linkedinUrl") or it.get("inputUrl") or "")
        if k:
            by.setdefault(k, it)

    for l in kand:
        it = by.get(_norm_li(l.get("linkedin_person_url") or "")) or {}
        lead_domain = domain_aus_website(l.get("website") or "") if nur_domain_treffer else ""
        best = beste_email(it.get("emails") or [], lead_domain)
        if best:
            addr = (best.get("email") or "").strip()
            l["harvestapi_personal_email"] = addr
            l["harvestapi_email_status"] = (best.get("status") or "").strip()
            l["harvestapi_email_quality"] = best.get("qualityScore")
            l["email"] = addr
            l["is_generic_email"] = False
            l["email_type"] = "persönliche E-Mail (harvestapi)"
            l["email_source_type"] = "harvestapi_enrichment"
            stats["mail_gesetzt"] += 1
        else:
            stats["ohne_treffer"] += 1

        vname = ((it.get("firstName") or "") + " " + (it.get("lastName") or "")).strip()
        if vname and not (l.get("contact_full_name") or "").strip():
            l["contact_full_name"] = vname
            l["managing_director"] = l.get("managing_director") or vname
            stats["name_ergaenzt"] += 1

    return stats


# ─── Optionaler Standalone-Aufruf (manuelle Nach-Anreicherung) ───────────────
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "b2bbot" / "output" / "latest" / "signal_leads.json"


def main(argv: list[str] | None = None) -> int:
    """CLI: reichert die Leads des letzten Laufs an und schreibt die JSON zurück."""
    import sys
    argv = sys.argv if argv is None else argv
    pfad = Path(argv[1]) if len(argv) > 1 else _DEFAULT
    if not pfad.exists():
        print(f"[harvestapi] Quelle nicht gefunden: {pfad}")
        return 1
    data = json.loads(pfad.read_text(encoding="utf-8"))
    leads = data.get("leads") if isinstance(data, dict) else data
    if not leads:
        print(f"[harvestapi] Keine Leads in {pfad}.")
        return 1
    stats = emails_fuer_leads(leads)
    if isinstance(data, dict):
        data["leads"] = leads
        pfad.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[harvestapi] {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

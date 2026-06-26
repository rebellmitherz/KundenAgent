"""LinkedIn-Profil-Anreicherung je Lead (Opt-in, defensiv).

Zwei Stufen:
  1. URL-Suche  — Serper-Suche ``site:linkedin.com/in/ "Name" "Firma"``
                  (1 Query je Lead mit Ansprechpartner + fehlender URL, ~$0.001)
  2. Profil-Scrape — Apify ``apify/linkedin-profile-scraper``
                     (Foto + Titel + Tenure, ~$0.005 je Profil)
                     AUS per Default; feuert nur wenn APIFY_API_KEY gesetzt.

Ergebnis je Lead:
    lead["linkedin_profil"] = {
        "url":          str,   # linkedin.com/in/... (leer wenn nicht gefunden)
        "foto_url":     str,   # CDN-URL des Profilfotos (leer wenn nicht gescrapt)
        "titel":        str,   # aktuelle Position ("Head of Sales")
        "firma_li":     str,   # Firma laut LinkedIn-Profil
        "seit":         str,   # "2021" oder "Jan 2021"
        "tenure_jahre": int,   # gerundete Betriebszugehörigkeit in Jahren
        "scrape_ok":    bool,
    }

b2bbot bleibt read-only. Liegt im product/-Layer.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from typing import Any

# Apify-Actor für Profil-Scraping — per Env-Var wechselbar.
_APIFY_PROFILE_ACTOR = os.environ.get(
    "APIFY_LINKEDIN_PROFILE_ACTOR",
    "apify~linkedin-profile-scraper",
)

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _env_datei() -> str:
    return str(
        ((__import__("pathlib").Path(__file__).resolve().parent.parent.parent) / "b2bbot" / ".env")
    )


def _serper_key() -> str:
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if key:
        return key
    try:
        for line in open(_env_datei(), encoding="utf-8"):
            if line.startswith("SERPER_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _apify_key() -> str:
    key = os.environ.get("APIFY_API_KEY", "").strip()
    if key:
        return key
    try:
        for line in open(_env_datei(), encoding="utf-8"):
            if line.startswith("APIFY_API_KEY="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _tenure_jahre(start: str) -> int:
    """Berechnet Betriebszugehörigkeit in ganzen Jahren aus 'YYYY' oder 'YYYY-MM'."""
    if not start:
        return 0
    m = re.search(r"(\d{4})", start)
    if not m:
        return 0
    try:
        return max(0, date.today().year - int(m.group(1)))
    except Exception:
        return 0


def _leeres_profil(url: str = "") -> dict:
    return {
        "url": url, "foto_url": "", "titel": "",
        "firma_li": "", "seit": "", "tenure_jahre": 0, "scrape_ok": False,
    }


# ─── Stufe 1: URL-Suche via Serper ───────────────────────────────────────────

def _linkedin_url_suchen(name: str, firma: str, *, serper_key: str) -> str:
    """1 Serper-Query: site:linkedin.com/in/ 'Name' 'Firma' → erste passende URL."""
    if not serper_key or not name:
        return ""
    query = f'site:linkedin.com/in/ "{name}" "{firma}"' if firma else f'site:linkedin.com/in/ "{name}"'
    payload = json.dumps({"q": query, "gl": "de", "hl": "de", "num": 3}).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        for item in (data.get("organic") or []):
            link = str(item.get("link") or "")
            if "linkedin.com/in/" in link.lower():
                # Kein linkedin.com/in/search, nur echte Profile
                clean = link.split("?")[0].rstrip("/")
                if "/in/" in clean and clean.count("/") >= 4:
                    return clean
    except Exception:
        pass
    return ""


# ─── Stufe 2: Profil-Scrape via Apify ────────────────────────────────────────

def _profil_scrapen(profil_url: str, *, apify_key: str) -> dict:
    """Apify LinkedIn-Profil-Scraper → Foto, Titel, Tenure. ~$0.005 je Profil."""
    if not apify_key or not profil_url:
        return {}
    actor = _APIFY_PROFILE_ACTOR.strip() or "apify~linkedin-profile-scraper"
    payload = json.dumps({
        "profileUrls": [profil_url],
        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }).encode()
    url = (
        f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
        f"?token={apify_key}&timeout=120"
    )
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=130) as r:
            items = json.loads(r.read().decode())
        if not isinstance(items, list) or not items:
            return {}
        p: dict[str, Any] = items[0] if isinstance(items[0], dict) else {}
    except Exception as exc:
        print(f"[linkedin-profil] Apify-Fehler: {exc}", flush=True)
        return {}

    # Foto — verschiedene Feldnamen je Actor-Version
    foto = str(
        p.get("profilePicture") or p.get("photo") or
        p.get("profilePictureUrl") or p.get("pictureUrl") or ""
    ).strip()

    # Aktueller Job
    erfahrungen = p.get("experiences") or p.get("positions") or []
    erste: dict = erfahrungen[0] if isinstance(erfahrungen, list) and erfahrungen else {}
    titel = str(
        p.get("headline") or erste.get("title") or erste.get("jobTitle") or
        p.get("jobTitle") or ""
    ).strip()
    firma_li = str(
        erste.get("companyName") or erste.get("company") or p.get("company") or ""
    ).strip()

    # Start-Datum der aktuellen Position
    seit_raw = str(
        erste.get("startDate") or erste.get("start") or
        erste.get("dateRange", {}).get("start") if isinstance(erste.get("dateRange"), dict) else "" or ""
    ).strip()
    seit = re.sub(r"[^\d\-/]", "", seit_raw)[:7]  # "2021-03" oder "2021"

    return {
        "foto_url": foto,
        "titel": titel,
        "firma_li": firma_li,
        "seit": seit,
        "tenure_jahre": _tenure_jahre(seit),
    }


# ─── Öffentliche API ──────────────────────────────────────────────────────────

def profil_anreichern(
    lead: dict,
    *,
    serper_key: str = "",
    apify_key: str = "",
    scrape: bool = True,
) -> dict:
    """Reichert einen Lead mit LinkedIn-Profildaten an. Gibt das Profil-Dict zurück.

    ``scrape=False`` → nur URL-Suche, kein Apify-Call (0 Apify-Kosten).
    """
    name = (
        lead.get("contact_full_name") or lead.get("managing_director") or
        lead.get("ansprechpartner") or ""
    ).strip()
    firma = (lead.get("company_name") or "").strip()

    # URL schon bekannt?
    url = (lead.get("linkedin_person_url") or "").strip()

    # Stufe 1: URL suchen
    if not url and name:
        sk = serper_key or _serper_key()
        url = _linkedin_url_suchen(name, firma, serper_key=sk)

    if not url:
        profil = _leeres_profil()
        lead["linkedin_profil"] = profil
        return profil

    profil = _leeres_profil(url)

    # Stufe 2: Profil scrapen (opt-in)
    if scrape:
        ak = apify_key or _apify_key()
        if ak:
            scraped = _profil_scrapen(url, apify_key=ak)
            if scraped:
                profil.update(scraped)
                profil["scrape_ok"] = True

    lead["linkedin_profil"] = profil
    lead["linkedin_person_url"] = url  # auch direkt am Lead für Kompatibilität
    return profil


def anreichern(
    leads: list[dict],
    *,
    serper_key: str = "",
    apify_key: str = "",
    scrape: bool = True,
    nur_mit_ansprechpartner: bool = True,
) -> dict:
    """Reichert alle Leads mit LinkedIn-Profildaten an. Defensiv: ein Fehler kippt nie.

    ``nur_mit_ansprechpartner=True`` (Default): überspringt Leads ohne Namen
    → spart Serper-Queries für Leads, bei denen wir ohnehin nichts finden würden.

    Gibt Statistik zurück: {url_gefunden, scrape_ok, uebersprungen}.
    """
    stats = {"url_gefunden": 0, "scrape_ok": 0, "uebersprungen": 0}
    for lead in leads or []:
        try:
            name = (
                lead.get("contact_full_name") or lead.get("managing_director") or
                lead.get("ansprechpartner") or ""
            ).strip()
            if nur_mit_ansprechpartner and not name:
                stats["uebersprungen"] += 1
                lead.setdefault("linkedin_profil", _leeres_profil())
                continue
            p = profil_anreichern(lead, serper_key=serper_key, apify_key=apify_key, scrape=scrape)
            if p.get("url"):
                stats["url_gefunden"] += 1
            if p.get("scrape_ok"):
                stats["scrape_ok"] += 1
        except Exception:
            lead.setdefault("linkedin_profil", _leeres_profil())
            stats["uebersprungen"] += 1
    return stats

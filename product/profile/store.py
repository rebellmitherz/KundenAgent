"""Angebot-Profile (Multi-Offer) — Speicher + aktives Profil.

Erlaubt mehrere Akquise-Angebote unter EINEM Account (z. B. eigenes B2B-Angebot
+ Termin-Akquise für zwei weitere Kunden). Je Profil:
  - eigener Erstmail-Text + Betreff + PDF-Anhang
  - eigene Such-Vorbelegung (Branche / Stadt / Lead-Anzahl)

Der SENDER bleibt IMMER derselbe (Engine-.env, Michaels Mails). Ein Profil
ändert NUR Mailtext/Betreff/PDF + die Vorbelegung der Suche — niemals den
Absender. Leere Text-/PDF-Felder = Engine-Default (= bisheriges Verhalten).

Mechanik: aktives Profil → `aktives_profil_env()` → PROFILE_FIRST_TOUCH_*-Env →
engine_bridge speist sie in JEDEN Engine-Aufruf ein. Die Hooks in
b2bbot/modules/outreach_pipeline.py lesen sie (additiv, env-gated).

Persistenz:
  product/product_profiles.json          (gitignored, kein Secret)
  product/data/_profile_assets/<id>.pdf  (gitignored)
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

_PRODUCT_ROOT = Path(__file__).resolve().parents[2]
_PFAD = _PRODUCT_ROOT / "product" / "product_profiles.json"
_ASSET_DIR = _PRODUCT_ROOT / "product" / "data" / "_profile_assets"

# Grenzen — schützen Persistenz + UI vor Müll/Größenexplosion.
_MAX_PROFILE = 12
_MAX_TEXT = 8000
_MAX_NAME = 80
_DEFAULT_ID = "rebellsystem"


def _slug(roh: str) -> str:
    """Pfad-/dateisichere Profil-ID aus freiem Text. Nur [a-z0-9_-]."""
    s = unicodedata.normalize("NFKD", (roh or "")).encode("ascii", "ignore").decode()
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:40] or "profil"


def _leeres_profil(profil_id: str = _DEFAULT_ID, name: str = "") -> dict[str, Any]:
    return {
        "id": profil_id,
        "name": name or "Mein B2B-Angebot",
        "branche": "",
        "stadt": "",
        "lead_anzahl": 10,
        "betreff": "",   # leer = Engine-Default-Betreff
        "mailtext": "",  # leer = Engine-Default-Mailtext
        "pdf": "",       # leer = Engine-Default-PDF (assets/Rebellsystem.pdf)
    }


def _default_struktur() -> dict[str, Any]:
    """Erststart: ein Profil (eigenes B2B), alle Override-Felder leer →
    exakt das bisherige Engine-Verhalten. Michael kann es umbenennen/füllen."""
    return {"aktiv": _DEFAULT_ID, "profile": [_leeres_profil()]}


def _normalisiere_profil(roh: dict[str, Any], *, fallback_id: str = "") -> dict[str, Any]:
    """Bringt ein (auch fremdes) Profil-Dict in die kanonische, begrenzte Form."""
    p = _leeres_profil()
    pid = _slug(str(roh.get("id") or fallback_id or roh.get("name") or ""))
    p["id"] = pid or _slug(fallback_id) or "profil"
    name = str(roh.get("name") or "").strip()[:_MAX_NAME]
    p["name"] = name or p["name"]
    p["branche"] = str(roh.get("branche") or "").strip()[:_MAX_NAME]
    p["stadt"] = str(roh.get("stadt") or "").strip()[:_MAX_NAME]
    try:
        p["lead_anzahl"] = max(1, min(int(roh.get("lead_anzahl") or 10), 100))
    except (TypeError, ValueError):
        p["lead_anzahl"] = 10
    p["betreff"] = str(roh.get("betreff") or "").strip()[:_MAX_NAME * 4]
    p["mailtext"] = str(roh.get("mailtext") or "")[:_MAX_TEXT]
    p["pdf"] = str(roh.get("pdf") or "").strip()
    return p


# --------------------------------------------------------------- Laden/Speichern

def laden() -> dict[str, Any]:
    """Gesamte Profil-Struktur lesen (selbstheilend bei fehlend/kaputt)."""
    if not _PFAD.exists():
        return _default_struktur()
    try:
        data = json.loads(_PFAD.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_struktur()
    rohliste = data.get("profile") if isinstance(data, dict) else None
    if not isinstance(rohliste, list) or not rohliste:
        return _default_struktur()
    profile: list[dict[str, Any]] = []
    gesehen: set[str] = set()
    for i, roh in enumerate(rohliste[:_MAX_PROFILE]):
        if not isinstance(roh, dict):
            continue
        p = _normalisiere_profil(roh, fallback_id=f"profil_{i}")
        while p["id"] in gesehen:          # ID-Kollision auflösen
            p["id"] = f"{p['id']}_{i}"
        gesehen.add(p["id"])
        profile.append(p)
    if not profile:
        return _default_struktur()
    aktiv = str((data.get("aktiv") if isinstance(data, dict) else "") or "")
    if aktiv not in {p["id"] for p in profile}:
        aktiv = profile[0]["id"]
    return {"aktiv": aktiv, "profile": profile}


def speichern(data: dict[str, Any]) -> dict[str, Any]:
    """Struktur normalisieren + atomar schreiben. Gibt die gespeicherte Form zurück."""
    profile = [
        _normalisiere_profil(p, fallback_id=f"profil_{i}")
        for i, p in enumerate((data.get("profile") or [])[:_MAX_PROFILE])
        if isinstance(p, dict)
    ]
    if not profile:
        profile = _default_struktur()["profile"]
    # Doppelte IDs eindeutig machen
    gesehen: set[str] = set()
    for i, p in enumerate(profile):
        while p["id"] in gesehen:
            p["id"] = f"{p['id']}_{i}"
        gesehen.add(p["id"])
    aktiv = str(data.get("aktiv") or "")
    if aktiv not in {p["id"] for p in profile}:
        aktiv = profile[0]["id"]
    out = {"aktiv": aktiv, "profile": profile}
    _PFAD.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PFAD.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PFAD)
    return out


# --------------------------------------------------------------- Profil-Aktionen

def aktives_profil() -> dict[str, Any]:
    data = laden()
    aktiv = data["aktiv"]
    for p in data["profile"]:
        if p["id"] == aktiv:
            return p
    return data["profile"][0]


def aktiv_setzen(profil_id: str) -> dict[str, Any]:
    data = laden()
    pid = _slug(profil_id)
    if pid in {p["id"] for p in data["profile"]}:
        data["aktiv"] = pid
        return speichern(data)
    return data


def profil_speichern(profil: dict[str, Any]) -> dict[str, Any]:
    """Upsert eines Profils anhand der ID. Neue ID = neues Profil."""
    data = laden()
    neu = _normalisiere_profil(profil, fallback_id=profil.get("name", ""))
    ersetzt = False
    for i, p in enumerate(data["profile"]):
        if p["id"] == neu["id"]:
            data["profile"][i] = neu
            ersetzt = True
            break
    if not ersetzt:
        if len(data["profile"]) >= _MAX_PROFILE:
            raise ValueError(f"Maximal {_MAX_PROFILE} Profile erlaubt.")
        data["profile"].append(neu)
    return speichern(data)


def profil_loeschen(profil_id: str) -> dict[str, Any]:
    """Profil entfernen. Das letzte Profil kann nicht gelöscht werden."""
    data = laden()
    pid = _slug(profil_id)
    rest = [p for p in data["profile"] if p["id"] != pid]
    if not rest:
        return data  # nie das letzte Profil löschen
    if data["aktiv"] == pid:
        data["aktiv"] = rest[0]["id"]
    data["profile"] = rest
    return speichern(data)


# --------------------------------------------------------------- Env-Brücke

def profil_env(profil: dict[str, Any]) -> dict[str, str]:
    """Übersetzt ein Profil in PROFILE_FIRST_TOUCH_*-Env. Nur nicht-leere Felder
    werden gesetzt — leeres Feld = Engine-Default greift."""
    env: dict[str, str] = {}
    betreff = (profil.get("betreff") or "").strip()
    mailtext = profil.get("mailtext") or ""
    pdf = (profil.get("pdf") or "").strip()
    if betreff:
        env["PROFILE_FIRST_TOUCH_SUBJECT"] = betreff
    if mailtext.strip():
        env["PROFILE_FIRST_TOUCH_BODY"] = mailtext
    if pdf:
        env["PROFILE_FIRST_TOUCH_PDF"] = pdf
    return env


def aktives_profil_env() -> dict[str, str]:
    """Env-Overrides des aktuell aktiven Profils (für engine_bridge.profil_setzen)."""
    return profil_env(aktives_profil())


# --------------------------------------------------------------- Asset (PDF)

def asset_pfad(profil_id: str) -> Path:
    """Zielpfad für das hochgeladene PDF eines Profils (absolut)."""
    _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    return (_ASSET_DIR / f"{_slug(profil_id)}.pdf").resolve()


def pdf_speichern(profil_id: str, daten: bytes) -> str:
    """Speichert ein hochgeladenes PDF, gibt den absoluten Pfad als String zurück."""
    ziel = asset_pfad(profil_id)
    ziel.write_bytes(daten)
    return str(ziel)

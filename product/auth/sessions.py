"""Session-Verwaltung und Mandanten-Authentifizierung.

Kein externer Abhängigkeit — nur stdlib.
Sessions leben im Arbeitsspeicher (Neustart = re-login).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path

_SESSIONS: dict[str, dict] = {}
_SESSION_TTL = 8 * 3600  # 8 Stunden

# Erlaubte Benutzernamen: Kleinbuchstaben, Ziffern, Bindestrich, Unterstrich.
# Wird als Verzeichnisname (product/data/<id>/) verwendet → muss pfadsicher sein.
_BENUTZERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def benutzername_gueltig(name: str) -> bool:
    """True, wenn der Benutzername pfadsicher ist (2–40 Zeichen, [a-z0-9_-])."""
    return bool(_BENUTZERNAME_RE.match(name or ""))


def sichere_id(roh: str) -> str:
    """Reduziert einen String defensiv auf pfadsichere Zeichen.

    Letzte Verteidigungslinie für Pfad-Bau (Traversal-Schutz). Niemals leer:
    fällt auf einen Hash zurück, wenn nichts Sicheres übrig bleibt.
    """
    bereinigt = re.sub(r"[^a-z0-9_-]", "", (roh or "").lower())
    return bereinigt or "x" + hashlib.sha256((roh or "").encode()).hexdigest()[:12]


def _mandanten_pfad(product_root: Path) -> Path:
    return product_root / "product" / "mandanten.json"


def sicherstellen(product_root: Path) -> None:
    """Erstellt mandanten.json mit Standard-Admin falls nicht vorhanden."""
    pfad = _mandanten_pfad(product_root)
    if pfad.exists():
        return
    pw_hash = "sha256:" + hashlib.sha256(b"admin123").hexdigest()
    standard = {
        "_hinweis": "Login-Daten — nicht ins Git einchecken.",
        "mandanten": [
            {
                "id": "admin",
                "name": "Admin",
                "benutzername": "admin",
                "password_hash": pw_hash,
                "role": "admin",
            }
        ],
    }
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(standard, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[auth] mandanten.json erstellt. Standard-Login: admin / admin123 — BITTE ÄNDERN!")


def mandant_verifizieren(product_root: Path, benutzername: str, passwort: str) -> dict | None:
    pfad = _mandanten_pfad(product_root)
    if not pfad.exists():
        return None
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except Exception:
        return None
    pw_hash = "sha256:" + hashlib.sha256(passwort.encode()).hexdigest()
    for m in daten.get("mandanten", []):
        kennung = m.get("benutzername") or m.get("id", "")
        if kennung != benutzername:
            continue
        if m.get("password_hash") == pw_hash:
            return m
        # Klartext-Fallback nur für Ersteinrichtung
        if m.get("passwort") == passwort:
            return m
    return None


def session_erstellen(mandant: dict) -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {
        "mandant_id": mandant["id"],
        "name": mandant.get("name", mandant["id"]),
        "role": mandant.get("role", "kunde"),
        "expires_at": time.time() + _SESSION_TTL,
    }
    return token


def session_pruefen(token: str) -> dict | None:
    s = _SESSIONS.get(token)
    if not s:
        return None
    if time.time() > s["expires_at"]:
        del _SESSIONS[token]
        return None
    return s


def session_loeschen(token: str) -> None:
    _SESSIONS.pop(token, None)


def mandanten_lesen(product_root: Path) -> list[dict]:
    """Liest alle Mandanten aus mandanten.json."""
    pfad = _mandanten_pfad(product_root)
    if not pfad.exists():
        return []
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        return daten.get("mandanten", [])
    except Exception:
        return []


def mandant_anlegen(product_root: Path, benutzername: str, passwort: str,
                    name: str = "", role: str = "kunde") -> dict | None:
    """Erstellt einen neuen Mandanten."""
    pfad = _mandanten_pfad(product_root)
    if not pfad.exists():
        sicherstellen(product_root)
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not benutzername_gueltig(benutzername):
        return None
    mandanten = daten.get("mandanten", [])
    if any(m.get("benutzername") == benutzername for m in mandanten):
        return None
    pw_hash = "sha256:" + hashlib.sha256(passwort.encode()).hexdigest()
    mandant = {
        "id": benutzername,
        "name": name or benutzername,
        "benutzername": benutzername,
        "password_hash": pw_hash,
        "role": role,
    }
    mandanten.append(mandant)
    daten["mandanten"] = mandanten
    try:
        pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
        return mandant
    except Exception:
        return None


def mandant_pw_setzen(product_root: Path, benutzername: str, neues_passwort: str) -> bool:
    """Setzt das Passwort eines Mandanten."""
    pfad = _mandanten_pfad(product_root)
    if not pfad.exists():
        return False
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except Exception:
        return False
    mandanten = daten.get("mandanten", [])
    for m in mandanten:
        if m.get("benutzername") == benutzername:
            m["password_hash"] = "sha256:" + hashlib.sha256(neues_passwort.encode()).hexdigest()
            daten["mandanten"] = mandanten
            try:
                pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
                return True
            except Exception:
                return False
    return False


def mandant_loeschen(product_root: Path, benutzername: str) -> bool:
    """Löscht einen Mandanten."""
    pfad = _mandanten_pfad(product_root)
    if not pfad.exists():
        return False
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except Exception:
        return False
    mandanten = daten.get("mandanten", [])
    orig_len = len(mandanten)
    mandanten = [m for m in mandanten if m.get("benutzername") != benutzername]
    if len(mandanten) == orig_len:
        return False
    daten["mandanten"] = mandanten
    try:
        pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False

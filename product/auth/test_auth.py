"""Tests für F8 — Mandanten-Auth & Sessions.

Beweist OHNE echten Server: Benutzernamen-Validierung (pfadsicher),
Sanitizing (Traversal-Schutz), Session-Lebenszyklus, Mandanten-CRUD und
Passwort-Hashing. Aufruf: PYTHONUTF8=1 python product/auth/test_auth.py

Kernaussagen:
  - Nur [a-z0-9_-] (2-40) als Benutzername; ../, Slashes, Grossbuchstaben raus.
  - sichere_id() entfernt Traversal-Zeichen, wird nie leer.
  - Login verifiziert gegen Hash; falsches PW scheitert.
  - Sessions laufen ab; loeschen invalidiert sofort.
  - CRUD: anlegen (dedupe), PW setzen, loeschen.
"""
from __future__ import annotations

import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import product.auth.sessions as s


# ─── Mini-Framework (wie im Projekt) ─────────────────────────────────────────
_ok = 0
_fail = 0


def test(name, fn):
    global _ok, _fail
    try:
        fn()
        print(f"  ✓ {name}")
        _ok += 1
    except Exception as e:
        print(f"  ✗ {name}\n    {e}")
        traceback.print_exc()
        _fail += 1


def _temp_root() -> Path:
    """Frisches product_root mit product/-Unterordner."""
    d = Path(tempfile.mkdtemp())
    (d / "product").mkdir(parents=True, exist_ok=True)
    return d


# ─── Benutzername-Validierung ────────────────────────────────────────────────
def t_gueltige_namen():
    for gut in ["acme", "acme-gmbh", "kunde_01", "a1", "x" * 40]:
        assert s.benutzername_gueltig(gut), f"sollte gültig sein: {gut!r}"


def t_ungueltige_namen():
    for schlecht in ["", "a", "A", "ACME", "../etc", "a/b", "a.b", "a b",
                     "ä", "x" * 41, "_start", "-start"]:
        assert not s.benutzername_gueltig(schlecht), f"sollte ungültig sein: {schlecht!r}"


def t_sichere_id_entfernt_traversal():
    assert s.sichere_id("../../etc/passwd") == "etcpasswd"
    assert s.sichere_id("acme/../boss") == "acmeboss"
    assert s.sichere_id("ACME-01") == "acme-01"


def t_sichere_id_nie_leer():
    out = s.sichere_id("../")          # nach Bereinigung leer → Hash-Fallback
    assert out and out.startswith("x") and len(out) > 1


# ─── CRUD ────────────────────────────────────────────────────────────────────
def t_anlegen_und_verifizieren():
    root = _temp_root()
    m = s.mandant_anlegen(root, "acme", "geheim123", "ACME GmbH", "kunde")
    assert m and m["id"] == "acme" and m["role"] == "kunde"
    # richtiges PW
    v = s.mandant_verifizieren(root, "acme", "geheim123")
    assert v and v["benutzername"] == "acme"
    # falsches PW
    assert s.mandant_verifizieren(root, "acme", "falsch") is None


def t_anlegen_lehnt_ungueltigen_namen_ab():
    root = _temp_root()
    assert s.mandant_anlegen(root, "../boss", "geheim123") is None
    assert s.mandant_anlegen(root, "ACME", "geheim123") is None


def t_anlegen_dedupe():
    root = _temp_root()
    assert s.mandant_anlegen(root, "acme", "geheim123")
    assert s.mandant_anlegen(root, "acme", "anders123") is None  # Name vergeben


def t_pw_setzen():
    root = _temp_root()
    s.mandant_anlegen(root, "acme", "altpw123")
    assert s.mandant_pw_setzen(root, "acme", "neupw123")
    assert s.mandant_verifizieren(root, "acme", "neupw123")
    assert s.mandant_verifizieren(root, "acme", "altpw123") is None
    assert not s.mandant_pw_setzen(root, "gibtsnicht", "neupw123")


def t_loeschen():
    root = _temp_root()
    s.mandant_anlegen(root, "acme", "geheim123")
    assert s.mandant_loeschen(root, "acme")
    assert s.mandant_verifizieren(root, "acme", "geheim123") is None
    assert not s.mandant_loeschen(root, "acme")  # schon weg


def t_hash_kein_klartext():
    root = _temp_root()
    s.mandant_anlegen(root, "acme", "geheim123")
    inhalt = (root / "product" / "mandanten.json").read_text(encoding="utf-8")
    assert "geheim123" not in inhalt, "Passwort darf NICHT im Klartext stehen"
    assert "sha256:" in inhalt


# ─── Sessions ────────────────────────────────────────────────────────────────
def t_session_lifecycle():
    tok = s.session_erstellen({"id": "acme", "name": "ACME", "role": "kunde"})
    sess = s.session_pruefen(tok)
    assert sess and sess["mandant_id"] == "acme" and sess["role"] == "kunde"
    s.session_loeschen(tok)
    assert s.session_pruefen(tok) is None


def t_session_ablauf():
    tok = s.session_erstellen({"id": "acme", "name": "ACME", "role": "kunde"})
    # TTL künstlich in die Vergangenheit setzen
    s._SESSIONS[tok]["expires_at"] = time.time() - 1
    assert s.session_pruefen(tok) is None


def t_session_unbekannt():
    assert s.session_pruefen("gibt-es-nicht") is None
    assert s.session_pruefen("") is None


# ─── Runner ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n=== F8 — Mandanten-Auth & Sessions ===\n")
    test("gültige Benutzernamen akzeptiert", t_gueltige_namen)
    test("ungültige Benutzernamen abgelehnt", t_ungueltige_namen)
    test("sichere_id entfernt Traversal", t_sichere_id_entfernt_traversal)
    test("sichere_id nie leer (Hash-Fallback)", t_sichere_id_nie_leer)
    test("anlegen + verifizieren (PW-Hash)", t_anlegen_und_verifizieren)
    test("anlegen lehnt ungültigen Namen ab", t_anlegen_lehnt_ungueltigen_namen_ab)
    test("anlegen dedupe", t_anlegen_dedupe)
    test("PW setzen", t_pw_setzen)
    test("löschen", t_loeschen)
    test("Passwort nie im Klartext", t_hash_kein_klartext)
    test("Session-Lebenszyklus", t_session_lifecycle)
    test("Session-Ablauf", t_session_ablauf)
    test("Session unbekannt/leer", t_session_unbekannt)

    print(f"\n{'=' * 40}")
    gesamt = _ok + _fail
    print(f"Ergebnis: {_ok}/{gesamt} grün", end="")
    if _fail:
        print(f"  |  {_fail} FEHLER ← bitte prüfen")
        sys.exit(1)
    else:
        print("  ✅")

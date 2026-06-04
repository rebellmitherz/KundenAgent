"""Installations-Checker für Hermes Sales Operator.

Läuft auf Kundenseite beim ersten Start oder auf Anforderung.
Prüft: Python-Version, Pflicht-Dateien, Engine-Pfad, Schreibrechte.
Gibt strukturierten Bericht zurück — kein Secret, kein Key.

Aufruf:
    python product/packaging/check_install.py
    python product/packaging/check_install.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PRODUCT_DIR = Path(__file__).parent.parent
_ROOT = _PRODUCT_DIR.parent

# Projekt-Root ins sys.path damit product.* importierbar ist
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Pflicht-Dateien relativ zu product/
_PFLICHT_DATEIEN = [
    "__init__.py",
    "version.py",
    "start_operator.bat",
    "product_config.example.json",
    "operator/order_schema.py",
    "operator/intake.py",
    "operator/confirm.py",
    "bridge/engine_bridge.py",
    "telegram/bot.py",
    "telegram/config.py",
    "telegram/dialog.py",
    "ui/server.py",
    "ui/dashboard.html",
    "setup/onboarding.py",
    "setup/smtp_store.py",
    "licensing/license.py",
    "licensing/features.py",
    "closer/closer_adapter.py",
]

# Engine-Pflicht-Dateien relativ zum Installations-Root
_ENGINE_DATEIEN = [
    "b2bbot/mine.py",
]


# ── Einzelne Prüfungen ───────────────────────────────────────────────────────

def check_python() -> dict:
    v = sys.version_info
    from product.version import MIN_PYTHON
    ok = (v.major, v.minor) >= MIN_PYTHON
    return {
        "name": "Python-Version",
        "ok": ok,
        "detail": f"{v.major}.{v.minor}.{v.micro}",
        "hinweis": "" if ok else f"Mindestens Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} benötigt.",
    }


def check_pflicht_dateien() -> dict:
    fehlend = [d for d in _PFLICHT_DATEIEN if not (_PRODUCT_DIR / d).exists()]
    ok = len(fehlend) == 0
    return {
        "name": "Produkt-Dateien",
        "ok": ok,
        "detail": f"{len(_PFLICHT_DATEIEN) - len(fehlend)}/{len(_PFLICHT_DATEIEN)} vorhanden",
        "hinweis": ("Fehlend: " + ", ".join(fehlend)) if fehlend else "",
    }


def check_engine() -> dict:
    fehlend = [d for d in _ENGINE_DATEIEN if not (_ROOT / d).exists()]
    ok = len(fehlend) == 0
    engine_dir = _ROOT / "b2bbot"
    return {
        "name": "Engine (b2bbot)",
        "ok": ok,
        "detail": str(engine_dir),
        "hinweis": ("Fehlend: " + ", ".join(fehlend)) if fehlend else "",
    }


def check_schreibrechte() -> dict:
    """Prüft ob Daten-Verzeichnis beschreibbar ist."""
    data_dir = _PRODUCT_DIR / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        test_pfad = data_dir / ".write_test"
        test_pfad.write_text("test")
        test_pfad.unlink()
        ok = True
        detail = str(data_dir)
        hinweis = ""
    except Exception as e:
        ok = False
        detail = str(data_dir)
        hinweis = f"Keine Schreibrechte: {e}"
    return {
        "name": "Schreibrechte (data/)",
        "ok": ok,
        "detail": detail,
        "hinweis": hinweis,
    }


def check_config() -> dict:
    """Prüft ob product_config.json vorhanden ist (ohne Inhalt zu lesen)."""
    config_pfad = _PRODUCT_DIR / "product_config.json"
    ok = config_pfad.exists()
    return {
        "name": "Konfiguration",
        "ok": ok,
        "detail": str(config_pfad),
        "hinweis": "" if ok else "Noch nicht eingerichtet. Starte setup/onboarding.py.",
    }


def check_version() -> dict:
    try:
        from product.version import VERSION, BUILD_DATE
        return {
            "name": "Versions-Manifest",
            "ok": True,
            "detail": f"v{VERSION} ({BUILD_DATE})",
            "hinweis": "",
        }
    except Exception as e:
        return {
            "name": "Versions-Manifest",
            "ok": False,
            "detail": "",
            "hinweis": str(e),
        }


# ── Gesamtbericht ────────────────────────────────────────────────────────────

def installation_pruefen() -> dict:
    """Führt alle Checks aus und gibt Gesamtbericht zurück."""
    checks = [
        check_python(),
        check_version(),
        check_pflicht_dateien(),
        check_engine(),
        check_schreibrechte(),
        check_config(),
    ]
    alle_ok = all(c["ok"] for c in checks)
    kritisch_ok = all(
        c["ok"] for c in checks
        if c["name"] not in {"Konfiguration"}  # Config ist optional beim ersten Start
    )
    return {
        "gesamt_ok": alle_ok,
        "startbereit": kritisch_ok,
        "checks": checks,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes Sales Operator — Installations-Check")
    parser.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    args = parser.parse_args(argv)

    bericht = installation_pruefen()

    if args.json:
        print(json.dumps(bericht, ensure_ascii=False, indent=2))
        return 0 if bericht["startbereit"] else 1

    # Lesbare Ausgabe
    print()
    print("═" * 54)
    print(f"  {bericht['checks'][0]['detail'] if bericht['checks'] else '?'}")
    try:
        from product.version import version_string
        print(f"  {version_string()}")
    except Exception:
        pass
    print("═" * 54)
    for c in bericht["checks"]:
        symbol = "✓" if c["ok"] else "✗"
        print(f"  {symbol}  {c['name']:<28}  {c['detail']}")
        if c["hinweis"]:
            print(f"     → {c['hinweis']}")
    print("─" * 54)
    if bericht["startbereit"]:
        print("  ✓ Installation OK — Operator startbereit.")
        if not bericht["gesamt_ok"]:
            print("  ! Einrichtung (product_config.json) noch ausstehend.")
            print("    → start_operator.bat öffnen oder setup/onboarding.py starten.")
    else:
        print("  ✗ Installation unvollständig. Bitte Hinweise oben beachten.")
    print()
    return 0 if bericht["startbereit"] else 1


if __name__ == "__main__":
    sys.exit(main())

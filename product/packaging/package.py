"""Package-Skript — baut ZWEI strikt getrennte Pakete (SaaS-sicher).

Aufruf (vom Installations-Root):
    python product/packaging/package.py            # baut BEIDE Pakete
    python product/packaging/package.py --typ kunde
    python product/packaging/package.py --typ betreiber
    python product/packaging/package.py --output C:/Lieferung/

Die beiden Paket-Arten werden NIE vermischt:

1) BETREIBER-PAKET  →  dist/rebellsystem-operator-v{version}.zip
   Vollständig lauffähiges System NUR für den internen Betreiber/Admin.
   NIEMALS an Kunden ausliefern.
     INHALT:  product/ (ohne Tests/keygen/Secrets) + b2bbot/ (Engine) +
              start_operator.bat, start_ui.bat, requirements.txt, SETUP.md
     RAUS:    product_config.json/product_smtp.json/mandanten.json (Secrets),
              keygen.py, jede .env*, output/, data/, **/__pycache__/, *.pyc, Tests

2) KUNDEN-/SAAS-PAKET  →  dist/rebellsystem-saas-v{version}.zip
   SaaS-sicher: enthält KEINEN Quellcode aus dem Repo — ausschließlich
   generierte Onboarding-/Konfig-/Doku-/Manifest-Artefakte. Dadurch ist
   strukturell garantiert, dass nichts Proprietäres durchrutscht:
     KEINE Engine / kein b2bbot, KEIN proprietärer Code (Akquise/Reply/
     Follow-up/CRM/Handoff), KEIN Betreiber-Dashboard (Setup/SMTP/Token/
     Engine-Felder), KEINE Secrets, KEINE .env, KEINE Output-Daten.
   Bis ein echtes Kunden-Frontend + Connector gebaut ist, ist das Kundenpaket
   bewusst ein reines Onboarding-/Konfigurations-Paket.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent

# Projekt-Root ins sys.path, damit `python product/packaging/package.py` direkt
# (als Skript) läuft — sonst schlägt `from product.version import VERSION` fehl.
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Ausschluss-Regeln ────────────────────────────────────────────────────────

# Exakte Dateinamen die nie ins Paket kommen
_AUSSCHLUSS_NAMEN: frozenset[str] = frozenset({
    "product_config.json",
    "product_smtp.json",
    "mandanten.json",      # Mandanten-Register (Kunden-Secrets) — nie ins Paket
    ".env",
    ".env.local",
    "keygen.py",
    "operator.lock",
    "bot.lock",
    ".DS_Store",
    "Thumbs.db",
})

# Verzeichnis-Namen die komplett übersprungen werden
_AUSSCHLUSS_DIRS: frozenset[str] = frozenset({
    "__pycache__",
    ".git",
    ".claude",
    "output",
    "data",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    ".idea",
    ".vscode",
})

# Datei-Suffixe die nie ins Paket kommen
_AUSSCHLUSS_SUFFIXE: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".pyd", ".suo", ".user",
})

# Muster die übersprungen werden (Dateiname startswith)
_TEST_MUSTER = ("test_",)


def _ausgeschlossen(pfad: Path, root: Path) -> bool:
    """True wenn diese Datei/Verzeichnis aus dem Paket ausgeschlossen wird."""
    name = pfad.name
    if name in _AUSSCHLUSS_NAMEN:
        return True
    # Jede Umgebungs-Datei (.env, .env.local, .env.example, …) bleibt draußen.
    if name.startswith(".env"):
        return True
    if pfad.suffix in _AUSSCHLUSS_SUFFIXE:
        return True
    if pfad.is_dir() and name in _AUSSCHLUSS_DIRS:
        return True
    # Keine Test-Dateien aus product/ ins Kundenpaket
    if pfad.is_file() and any(name.startswith(m) for m in _TEST_MUSTER):
        rel = pfad.relative_to(root)
        if rel.parts[0] == "product":
            return True
    return False


# ── ZIP-Erstellung ────────────────────────────────────────────────────────────

def _verzeichnis_zu_zip(
    quelle: Path,
    zf: zipfile.ZipFile,
    root: Path,
    zip_prefix: str,
) -> tuple[int, int]:
    """Fügt ein Verzeichnis rekursiv zum ZIP hinzu. Gibt (hinzugefügt, übersprungen) zurück."""
    hinzugefuegt = 0
    uebersprungen = 0
    for pfad in sorted(quelle.rglob("*")):
        # Prüfe ob irgendein Elternteil ausgeschlossen ist
        eltern_ausgeschlossen = any(
            p.name in _AUSSCHLUSS_DIRS
            for p in pfad.parents
            if p != quelle.parent
        )
        if eltern_ausgeschlossen:
            continue
        if _ausgeschlossen(pfad, root):
            uebersprungen += 1
            continue
        if pfad.is_file():
            rel = pfad.relative_to(root)
            arcname = f"{zip_prefix}/{rel}".replace("\\", "/")
            zf.write(pfad, arcname)
            hinzugefuegt += 1
    return hinzugefuegt, uebersprungen


def _datei_zu_zip(pfad: Path, root: Path, zf: zipfile.ZipFile, zip_prefix: str) -> None:
    """Fügt eine einzelne Datei zum ZIP hinzu."""
    rel = pfad.relative_to(root)
    arcname = f"{zip_prefix}/{rel}".replace("\\", "/")
    zf.write(pfad, arcname)


# ── Paket-Inhalte ─────────────────────────────────────────────────────────────

def _erstelle_setup_md(version: str) -> str:
    return f"""\
# Rebellsystem Sales Operator — Einrichtung

Version: {version}

## Voraussetzungen

- Windows 10/11 (64-bit)
- Python 3.10 oder neuer: https://www.python.org/downloads/
- Telegram-Account + eigener Bot (kostenlos via @BotFather)

## Erste Schritte

1. **Doppelklick auf `start_operator.bat`**
   - Beim ersten Start öffnet sich automatisch der Einrichtungs-Assistent
   - Folge den Anweisungen im Fenster
   - Du benötigst: Telegram Bot-Token + deine Chat-ID

2. **Telegram-Bot finden**
   - Öffne Telegram und suche den Bot, den du bei @BotFather erstellt hast
   - Schreib ihm eine Nachricht — er antwortet, sobald der Operator läuft

3. **Mini-UI öffnen (optional)**
   - Doppelklick auf `start_ui.bat`
   - Öffnet http://127.0.0.1:8767 im Browser

## Lizenz-Schlüssel eingeben

Falls du einen Lizenz-Schlüssel erhalten hast:
- Starte den Einrichtungs-Assistenten: `start_operator.bat`
- Oder trage den Schlüssel direkt in `product_config.json` unter `"license_key"` ein

## Probleme?

- Installations-Prüfung: `python product/packaging/check_install.py`
- Konfiguration zurücksetzen: `product_config.json` löschen und `start_operator.bat` neu starten

## Wichtige Hinweise

- `product_config.json` enthält deinen Bot-Token — nie an andere weitergeben
- Die Mini-UI ist nur über 127.0.0.1 erreichbar (nur du siehst sie)
- Kein automatisches Senden — jede Aktion erfordert deine ausdrückliche Bestätigung
"""


def _erstelle_requirements_txt() -> str:
    return """\
# Rebellsystem Sales Operator — Abhängigkeiten
#
# Pflicht:
requests>=2.28
python-dotenv>=1.0

# Optional (für KI-Assistent im Operator):
# anthropic>=0.20

# Optional (für Live Sales Coach):
# openai>=1.0
# pyaudio>=0.2
"""


def _erstelle_start_ui_bat() -> str:
    return """\
@echo off
:: Rebellsystem Sales Operator — Mini-UI starten
:: Oeffnet http://127.0.0.1:8767 im Browser

setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden.
    pause
    exit /b 1
)

echo Mini-UI startet auf http://127.0.0.1:8767 ...
python product\\ui\\server.py

pause
"""


def _erstelle_manifest(version: str, paket_name: str, stats: dict) -> dict:
    """Manifest des BETREIBER-Pakets (vollständig lauffähig, interner Gebrauch)."""
    return {
        "paket": paket_name,
        "paket_typ": "betreiber",
        "hinweis": (
            "BETREIBER-PAKET — vollständig lauffähig, NUR für internen "
            "Betreiber/Admin-Gebrauch. NIEMALS an Kunden ausliefern."
        ),
        "version": version,
        "erstellt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dateien_gesamt": stats.get("gesamt", 0),
        "dateien_uebersprungen": stats.get("uebersprungen", 0),
        "komponenten": [
            "operator", "bridge", "telegram", "ui",
            "setup", "licensing", "closer", "packaging", "engine (b2bbot)",
        ],
        "nicht_enthalten": [
            "product_config.json (Secrets)",
            "product_smtp.json (Secrets)",
            "mandanten.json (Kunden-Secrets)",
            "product/licensing/keygen.py (Seller-only)",
            ".env* (Umgebungs-Dateien)",
            "product/data/, output/ (Laufzeit-/Output-Daten)",
            "**/__pycache__/ (temporäre Dateien)",
        ],
    }


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def paket_erstellen(output_dir: Path | None = None) -> Path:
    """Erstellt das BETREIBER-Paket (vollständig lauffähig, interner Gebrauch).

    Enthält product/ + die Engine (b2bbot/), aber keine Secrets/.env/keygen/
    output. NIEMALS an Kunden ausliefern — dafür gibt es kunden_paket_erstellen().
    Gibt den Pfad zur ZIP-Datei zurück."""
    from product.version import VERSION

    paket_name = f"rebellsystem-operator-v{VERSION}"
    ziel_dir = output_dir or (_ROOT / "dist")
    ziel_dir.mkdir(parents=True, exist_ok=True)

    zip_pfad = ziel_dir / f"{paket_name}.zip"

    print(f"\n  Erstelle BETREIBER-Paket: {zip_pfad.name}")
    print(f"  Quelle:         {_ROOT}")

    gesamt = 0
    uebersprungen = 0

    with zipfile.ZipFile(zip_pfad, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:

        # 1. product/ (ohne Tests, ohne keygen.py, ohne Secrets)
        product_dir = _ROOT / "product"
        if product_dir.exists():
            h, u = _verzeichnis_zu_zip(product_dir, zf, _ROOT, paket_name)
            gesamt += h; uebersprungen += u
            print(f"  product/:       {h} Dateien ({u} übersprungen)")

        # 2. b2bbot/ (Engine — ohne .env, ohne output/, ohne .git)
        engine_dir = _ROOT / "b2bbot"
        if engine_dir.exists():
            h, u = _verzeichnis_zu_zip(engine_dir, zf, _ROOT, paket_name)
            gesamt += h; uebersprungen += u
            print(f"  b2bbot/:        {h} Dateien ({u} übersprungen)")
        else:
            print(f"  b2bbot/:        nicht gefunden — wird übersprungen")

        # 3. Einzelne Wurzel-Dateien
        for datei_name in ("start_operator.bat",):
            pfad = _ROOT / datei_name
            if pfad.exists():
                zf.write(pfad, f"{paket_name}/{datei_name}")
                gesamt += 1

        # 4. Generierte Dateien
        zf.writestr(f"{paket_name}/start_ui.bat", _erstelle_start_ui_bat())
        zf.writestr(f"{paket_name}/requirements.txt", _erstelle_requirements_txt())
        zf.writestr(f"{paket_name}/SETUP.md", _erstelle_setup_md(VERSION))

        # 5. Manifest
        manifest = _erstelle_manifest(VERSION, paket_name, {
            "gesamt": gesamt, "uebersprungen": uebersprungen,
        })
        zf.writestr(
            f"{paket_name}/MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    groesse_mb = zip_pfad.stat().st_size / 1_048_576
    print(f"\n  ✓ {zip_pfad.name} ({groesse_mb:.1f} MB)")
    print(f"    {gesamt} Dateien, {uebersprungen} übersprungen")
    return zip_pfad


# ── Kunden-/SaaS-Paket (rein generiert — KEIN Quellcode aus dem Repo) ──────────

def _erstelle_kunden_readme(version: str) -> str:
    return f"""\
# Rebellsystem — SaaS-Onboarding

Version: {version}

Dies ist das **Kunden-Onboarding-Paket** der Rebellsystem-Akquise-Plattform.
Es enthält bewusst **keine** Software, die bei dir lokal läuft:

- **kein** Engine-/Akquise-Code
- **keine** Zugangsdaten oder Secrets
- **keine** Betreiber-Werkzeuge

Die Plattform läuft als Service beim Betreiber. Du arbeitest später über ein
eigenes Kunden-Frontend bzw. einen Connector mit deiner isolierten Instanz —
dieser Teil wird separat bereitgestellt.

## Was du hier findest

- `konfiguration.example.json` — Vorlage für deine Onboarding-Angaben
  (Lizenzschlüssel, Zielgruppen-/Regions-Vorbelegung, Anzeige-Einstellungen).
- `MANIFEST.json` — was dieses Paket enthält und was bewusst nicht.

## Nächste Schritte

1. Fülle `konfiguration.example.json` mit deinen Wunsch-Vorgaben aus und
   schicke sie deinem Ansprechpartner.
2. Du erhältst deinen Zugang zur Plattform (Telegram und/oder Web).
3. Dein Akquise-Agent wird isoliert für dich eingerichtet.

## Wichtig

- Es wird **nie automatisch** versendet — jede Aktion (Senden, Termin) braucht
  deine ausdrückliche Freigabe.
- Du siehst nur deine eigenen Daten. Kein Zugriff auf andere Mandanten.
"""


def _erstelle_kunden_konfig() -> str:
    """Kunden-Onboarding-Vorlage — NUR kundenseitige Felder, KEINE Betreiber-/
    Engine-/SMTP-/Token-Felder."""
    vorlage = {
        "lizenzschluessel": "",
        "anzeige_name": "",
        "standard_zielgruppe": "",
        "standard_region": "",
        "branche": "",
        "benachrichtigung": {
            "kanal": "telegram",
            "sprache": "de",
        },
        "_hinweis": (
            "Onboarding-Vorlage. Keine Zugangsdaten/Secrets hier eintragen — "
            "die werden separat und sicher mit dem Betreiber abgestimmt."
        ),
    }
    return json.dumps(vorlage, ensure_ascii=False, indent=2)


def _erstelle_kunden_manifest(version: str) -> dict:
    """Manifest des KUNDEN-/SAAS-Pakets (SaaS-sicher, ohne Quellcode)."""
    return {
        "paket": f"rebellsystem-saas-v{version}",
        "paket_typ": "kunde",
        "hinweis": (
            "KUNDEN-/SAAS-PAKET — SaaS-sicher. Enthält keinen Quellcode, keine "
            "Engine, kein Betreiber-Dashboard, keine Secrets. Reines Onboarding-/"
            "Konfigurations-Paket bis ein echtes Kunden-Frontend/Connector folgt."
        ),
        "version": version,
        "erstellt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "enthalten": [
            "README.md (Onboarding)",
            "konfiguration.example.json (Kunden-Vorlage)",
            "MANIFEST.json",
        ],
        "nicht_enthalten": [
            "b2bbot / Engine-Code",
            "ClouseAgent / Closer-Code",
            "proprietäre Akquise-/Reply-/Follow-up-/CRM-/Handoff-Logik",
            "Betreiber-Dashboard (Setup/SMTP/Token/Engine-Felder)",
            "interne Bot-Dateien",
            "Secrets / .env / Output-Daten / Lizenzgenerator",
            "jeglicher .py-Quellcode",
        ],
    }


def kunden_paket_erstellen(output_dir: Path | None = None) -> Path:
    """Erstellt das KUNDEN-/SAAS-Paket. SaaS-sicher: schreibt ausschließlich
    generierte Artefakte ins ZIP — es wird KEINE Repo-Datei kopiert, daher kann
    strukturell nichts Proprietäres durchrutschen."""
    from product.version import VERSION

    paket_name = f"rebellsystem-saas-v{VERSION}"
    ziel_dir = output_dir or (_ROOT / "dist")
    ziel_dir.mkdir(parents=True, exist_ok=True)
    zip_pfad = ziel_dir / f"{paket_name}.zip"

    print(f"\n  Erstelle KUNDEN-Paket:    {zip_pfad.name}")

    with zipfile.ZipFile(zip_pfad, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(f"{paket_name}/README.md", _erstelle_kunden_readme(VERSION))
        zf.writestr(f"{paket_name}/konfiguration.example.json", _erstelle_kunden_konfig())
        zf.writestr(
            f"{paket_name}/MANIFEST.json",
            json.dumps(_erstelle_kunden_manifest(VERSION), ensure_ascii=False, indent=2),
        )

    groesse_kb = zip_pfad.stat().st_size / 1024
    print(f"  ✓ {zip_pfad.name} ({groesse_kb:.1f} KB, nur generierte Artefakte)")
    return zip_pfad


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebellsystem — Pakete erstellen (Betreiber + Kunde, strikt getrennt)"
    )
    parser.add_argument("--output", type=Path, default=None,
                        help="Ziel-Verzeichnis (Standard: ./dist/)")
    parser.add_argument("--typ", choices=("beide", "betreiber", "kunde"),
                        default="beide", help="Welche(s) Paket(e) bauen (Standard: beide)")
    args = parser.parse_args(argv)

    try:
        gebaut: list[Path] = []
        if args.typ in ("beide", "betreiber"):
            gebaut.append(paket_erstellen(args.output))
        if args.typ in ("beide", "kunde"):
            gebaut.append(kunden_paket_erstellen(args.output))
        print("\n  Fertig:")
        for p in gebaut:
            print(f"    - {p}")
        return 0
    except Exception as e:
        print(f"\n  ! Fehler: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

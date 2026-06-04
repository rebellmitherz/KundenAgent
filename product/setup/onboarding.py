"""Geführtes Erststart-Onboarding für Hermes Sales Operator.

Erzeugt product_config.json und optional product_smtp.json sicher lokal.

Sicherheitsregeln:
  - Secrets (bot_token, api_key, SMTP-Passwort) nie ausgeben/loggen.
  - getpass() statt input() für alle geheimen Felder → kein Terminal-Echo.
  - Nur letzten 4 Zeichen eines Tokens in der Zusammenfassung zeigen.
  - Kein Netzwerk-Zugriff, kein Telegram-Chat.

Aufruf:
  python setup/onboarding.py
  python setup/onboarding.py --config /pfad/zur/product_config.json
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from getpass import getpass
from pathlib import Path

_PRODUCT_DIR = Path(__file__).parent.parent
_CONFIG_DEFAULT = _PRODUCT_DIR / "product_config.json"
_SMTP_DEFAULT = _PRODUCT_DIR / "product_smtp.json"

# Keine externen Importe — stdlib only.


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _eingabe(prompt: str, default: str = "", pflicht: bool = True) -> str:
    """Liest Texteingabe. Leer + Default → Default. Leer ohne Default → Fehler."""
    hint = f" [{default}]" if default else ""
    while True:
        wert = input(f"  {prompt}{hint}: ").strip()
        if wert:
            return wert
        if default:
            return default
        if not pflicht:
            return ""
        print("    ! Pflichtfeld — bitte ausfüllen.")


def _geheim(prompt: str, pflicht: bool = True) -> str:
    """Liest Passwort/Token ohne Echo (getpass). Leer + pflicht → Schleife."""
    while True:
        wert = getpass(f"  {prompt}: ")
        if wert:
            return wert
        if not pflicht:
            return ""
        print("    ! Pflichtfeld — bitte ausfüllen.")


def _maskieren(wert: str) -> str:
    """Zeigt nur die letzten 4 Zeichen eines Secrets."""
    if not wert:
        return "—"
    if len(wert) <= 4:
        return "****"
    return "••••" + wert[-4:]


def _ja_nein(frage: str, default_ja: bool = False) -> bool:
    hint = "[J/n]" if default_ja else "[j/N]"
    while True:
        antwort = input(f"  {frage} {hint}: ").strip().lower()
        if not antwort:
            return default_ja
        if antwort in ("j", "ja", "y", "yes"):
            return True
        if antwort in ("n", "nein", "no"):
            return False
        print("    ! Bitte j oder n eingeben.")


def _pfad_pruefen(pfad: Path) -> str:
    """Gibt '✓ gefunden' oder '✗ nicht gefunden' zurück."""
    return "✓ gefunden" if pfad.exists() else "✗ nicht gefunden"


# ── Haupt-Wizard ─────────────────────────────────────────────────────────────

def setup_config(ziel: Path) -> bool:
    """Interaktiver Wizard für product_config.json.
    Gibt True zurück wenn gespeichert, False wenn abgebrochen.
    """
    print()
    print("═" * 58)
    print("  Hermes Sales Operator — Ersteinrichtung")
    print("═" * 58)

    if ziel.exists():
        print(f"\n  Hinweis: {ziel.name} existiert bereits.")
        if not _ja_nein("Überschreiben?", default_ja=False):
            print("  → Abgebrochen. Bestehende Config bleibt erhalten.")
            return False

    # ── Schritt 1: Telegram ──────────────────────────────────────────────
    print()
    print("  Schritt 1/4 — Telegram-Bot")
    print("  Erstelle deinen Bot unter @BotFather → /newbot → Token kopieren.")
    print("  Das Token wird NICHT angezeigt (kein Echo).")
    token = _geheim("Bot-Token (von @BotFather)")

    print()
    print("  Deine eigene Telegram-Chat-ID (nur Zahlen).")
    print("  Tipp: Schreib @userinfobot eine Nachricht → gibt deine ID aus.")
    owner = _eingabe("Eigene Chat-ID")

    # ── Schritt 2: Engine-Pfad ───────────────────────────────────────────
    print()
    print("  Schritt 2/4 — Engine-Pfad")
    print("  Standard: eine Ebene über dem product/-Ordner → ../b2bbot")
    engine_rel = _eingabe("Pfad zur b2bbot-Engine", default="../b2bbot")
    engine_abs = (_PRODUCT_DIR / engine_rel).resolve()
    print(f"    → Absolut: {engine_abs}  ({_pfad_pruefen(engine_abs)})")

    # ── Schritt 3: Datenpfad ─────────────────────────────────────────────
    print()
    print("  Schritt 3/4 — Datenpfad")
    print("  Hier werden Aufträge, Leads und Logs gespeichert.")
    data_rel = _eingabe("Datenpfad (relativ zu product/)", default="data")
    data_abs = (_PRODUCT_DIR / data_rel).resolve()
    print(f"    → Absolut: {data_abs}")

    # ── Schritt 4: Optionales ────────────────────────────────────────────
    print()
    print("  Schritt 4/4 — Optionale Features")
    print("  Anthropic API Key aktiviert den KI-Assistenten im Operator.")
    print("  Leer lassen = KI nicht aktiviert (deterministischer Modus).")
    api_key = _geheim("Anthropic API Key (leer = überspringen)", pflicht=False)

    # ── UI-Token (Admin-Schutz für Mini-UI) ──────────────────────────────
    print()
    print("  Admin-Token für Mini-UI (Einrichtung & Freigabe schützen).")
    print("  [ENTER] = Token automatisch erzeugen   |   'nein' = kein Schutz")
    tok_antwort = input("  UI-Token generieren? [J/n]: ").strip().lower()
    if tok_antwort in ("", "j", "ja", "y", "yes"):
        ui_token = secrets.token_urlsafe(16)
        print(f"  → Token: {ui_token}")
        print("  !! Jetzt notieren — wird danach nicht mehr angezeigt !!")
    else:
        ui_token = ""
        print("  → Kein UI-Token. Mini-UI ohne Schutz (nur 127.0.0.1).")

    # ── Zusammenfassung ──────────────────────────────────────────────────
    print()
    print("  ── Zusammenfassung ─────────────────────────────────")
    print(f"  Bot-Token:  {_maskieren(token)}")
    print(f"  Chat-ID:    {owner}")
    print(f"  Engine:     {engine_abs}  ({_pfad_pruefen(engine_abs)})")
    print(f"  Daten:      {data_abs}")
    print(f"  KI-Key:     {'konfiguriert (' + _maskieren(api_key) + ')' if api_key else 'nicht konfiguriert'}")
    print(f"  UI-Token:   {'aktiv (' + _maskieren(ui_token) + ')' if ui_token else 'nicht gesetzt'}")
    print()

    if not _ja_nein("Alles korrekt — Config speichern?", default_ja=True):
        print("  → Abgebrochen. Keine Datei wurde geschrieben.")
        return False

    # ── Schreiben ────────────────────────────────────────────────────────
    config = {
        "_hinweis": "Automatisch erzeugt durch setup/onboarding.py — nicht ins Git einchecken.",
        "bot_token": token,
        "owner_chat_id": owner,
        "engine_dir": engine_rel,
        "data_dir": data_rel,
        "anthropic_api_key": api_key,
        "ui_token": ui_token,
    }
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✓ {ziel.name} gespeichert.")
    return True


def setup_smtp(ziel: Path) -> bool:
    """Optionaler SMTP/IMAP-Wizard für späteren Versand (V2-Feature).
    Schreibt product_smtp.json.
    """
    print()
    print("  ── SMTP-Konfiguration (für E-Mail-Versand) ─────────")
    print("  Dieses Feature wird in V2 benötigt. Jetzt konfigurieren?")

    if not _ja_nein("SMTP jetzt einrichten?", default_ja=False):
        print("  → Übersprungen. Kann später mit: python setup/onboarding.py --smtp nachgeholt werden.")
        return False

    if ziel.exists():
        print(f"\n  Hinweis: {ziel.name} existiert bereits.")
        if not _ja_nein("Überschreiben?", default_ja=False):
            return False

    print()
    print("  SMTP-Server (Ausgang):")
    smtp_host = _eingabe("SMTP-Host", default="smtp.gmail.com")
    smtp_port = _eingabe("SMTP-Port", default="587")
    smtp_user = _eingabe("Benutzername (E-Mail-Adresse)")
    print("  SMTP-Passwort (kein Echo):")
    smtp_pass = _geheim("SMTP-Passwort")
    tls = _ja_nein("TLS/STARTTLS verwenden?", default_ja=True)

    print()
    print("  IMAP-Server (Eingang, optional):")
    imap_host = _eingabe("IMAP-Host (leer = überspringen)", default="", pflicht=False)
    imap_port = "993"
    if imap_host:
        imap_port = _eingabe("IMAP-Port", default="993")

    print()
    print("  ── SMTP-Zusammenfassung ────────────────────────────")
    print(f"  Host:       {smtp_host}:{smtp_port}  TLS={tls}")
    print(f"  Benutzer:   {smtp_user}")
    print(f"  Passwort:   {_maskieren(smtp_pass)}")
    if imap_host:
        print(f"  IMAP:       {imap_host}:{imap_port}")
    print()

    if not _ja_nein("SMTP-Config speichern?", default_ja=True):
        print("  → Abgebrochen.")
        return False

    smtp_data = {
        "_hinweis": "SMTP-Credentials — niemals ins Git einchecken.",
        "smtp_host": smtp_host,
        "smtp_port": int(smtp_port),
        "benutzername": smtp_user,
        "passwort": smtp_pass,
        "tls": tls,
        "imap_host": imap_host,
        "imap_port": int(imap_port) if imap_host else 993,
    }
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(json.dumps(smtp_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {ziel.name} gespeichert.")
    return True


# ── Entry-Point ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hermes Sales Operator — Ersteinrichtung",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_CONFIG_DEFAULT,
        help=f"Pfad zur Config-Datei (Standard: {_CONFIG_DEFAULT})",
    )
    parser.add_argument(
        "--smtp",
        action="store_true",
        help="Nur SMTP-Konfiguration ausführen (Config überspringen)",
    )
    parser.add_argument(
        "--smtp-datei",
        type=Path,
        default=_SMTP_DEFAULT,
        help=f"Pfad zur SMTP-Datei (Standard: {_SMTP_DEFAULT})",
    )
    args = parser.parse_args(argv)

    try:
        if args.smtp:
            ok = setup_smtp(args.smtp_datei)
        else:
            ok = setup_config(args.config)
            if ok:
                setup_smtp(args.smtp_datei)

        if ok:
            print()
            print("  ✓ Einrichtung abgeschlossen.")
            print("  Starte den Operator: start_operator.bat")
            print()
        return 0 if ok else 1

    except KeyboardInterrupt:
        print("\n\n  Abgebrochen.")
        return 1
    except Exception as e:
        print(f"\n  ! Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

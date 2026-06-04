"""Konfiguration für den Kunden-Telegram-Bot.

Lädt aus product_config.json (nicht aus .env).
Keine Secrets werden geloggt oder angezeigt.

Packaging-Regeln:
  - Alle Pfade relativ zur Config-Datei aufgelöst → absolut gespeichert.
  - Kein hardcodierter Nutzerpfad.
  - Kein Key wird je ausgegeben (auch nicht im Fehlerfall).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from product.licensing.license import LizenzDaten, lizenz_laden

# Config liegt direkt im product/-Ordner
_CONFIG_BEISPIEL = Path(__file__).parent.parent / "product_config.example.json"
_CONFIG_PFAD_DEFAULT = Path(__file__).parent.parent / "product_config.json"


@dataclass
class OperatorConfig:
    bot_token: str
    owner_chat_id: str
    engine_dir: Path
    data_dir: Path
    anthropic_api_key: str = ""   # optional — nie loggen
    ui_token: str = ""            # optional — schützt Admin-Tabs in der Mini-UI
    license_key: str = ""         # optional — leer = Entwicklungsmodus (alle Features)
    lizenz: LizenzDaten | None = None  # geladen beim Start, nie loggen

    @property
    def orders_dir(self) -> Path:
        return self.data_dir / "orders"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"


def laden(config_pfad: Path | None = None) -> OperatorConfig:
    pfad = Path(config_pfad) if config_pfad else _CONFIG_PFAD_DEFAULT

    if not pfad.exists():
        raise FileNotFoundError(
            f"Config nicht gefunden: {pfad}\n"
            f"Kopiere {_CONFIG_BEISPIEL.name} nach {pfad.name} und fuelle die Felder aus."
        )

    try:
        d = json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Config-Datei ungültig (kein gültiges JSON): {e}") from e

    token = d.get("bot_token", "").strip()
    if not token:
        raise ValueError("bot_token fehlt in der Config-Datei.")

    owner = str(d.get("owner_chat_id", "")).strip()

    # Pfade relativ zur Config-Datei auflösen
    basis = pfad.parent
    engine_dir = (basis / d.get("engine_dir", "../b2bbot")).resolve()
    data_dir = (basis / d.get("data_dir", "data")).resolve()

    # Optionaler API-Key: erst aus Config, dann aus Umgebung — nie loggen
    api_key = d.get("anthropic_api_key", "").strip() or os.environ.get("ANTHROPIC_API_KEY", "")

    ui_token = d.get("ui_token", "").strip()
    license_key = d.get("license_key", "").strip()
    lizenz = lizenz_laden(license_key)  # None wenn kein Key → Entwicklungsmodus

    return OperatorConfig(
        bot_token=token,
        owner_chat_id=owner,
        engine_dir=engine_dir,
        data_dir=data_dir,
        anthropic_api_key=api_key,
        ui_token=ui_token,
        license_key=license_key,
        lizenz=lizenz,
    )

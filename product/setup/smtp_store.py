"""SMTP/IMAP-Konfiguration laden und speichern.

Liest aus product_smtp.json (neben product_config.json).
Secrets werden NIEMALS geloggt oder ausgegeben.

Verwendung:
  from product.setup.smtp_store import smtp_laden, SmtpConfig
  cfg = smtp_laden()   # raises FileNotFoundError wenn nicht vorhanden
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_PRODUCT_DIR = Path(__file__).parent.parent
_SMTP_DEFAULT = _PRODUCT_DIR / "product_smtp.json"


@dataclass
class SmtpConfig:
    smtp_host: str
    smtp_port: int
    benutzername: str
    passwort: str          # nie loggen
    tls: bool = True
    imap_host: str = ""
    imap_port: int = 993

    def hat_imap(self) -> bool:
        return bool(self.imap_host)

    def zusammenfassung(self) -> str:
        """Zeigt Config OHNE Passwort — für Logs/UI sicher."""
        imap = f"  IMAP: {self.imap_host}:{self.imap_port}" if self.hat_imap() else ""
        return (
            f"SMTP: {self.smtp_host}:{self.smtp_port} "
            f"(TLS={self.tls}, user={self.benutzername}){imap}"
        )


def smtp_laden(pfad: Path | None = None) -> SmtpConfig:
    """Lädt SMTP-Config. Raises FileNotFoundError wenn nicht vorhanden."""
    p = Path(pfad) if pfad else _SMTP_DEFAULT
    if not p.exists():
        raise FileNotFoundError(
            f"SMTP-Config nicht gefunden: {p}\n"
            "Richte SMTP ein mit: python setup/onboarding.py --smtp"
        )
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"SMTP-Config ungültig: {e}") from e

    host = d.get("smtp_host", "").strip()
    if not host:
        raise ValueError("smtp_host fehlt in der SMTP-Config.")
    user = d.get("benutzername", "").strip()
    if not user:
        raise ValueError("benutzername fehlt in der SMTP-Config.")
    passwort = d.get("passwort", "")
    if not passwort:
        raise ValueError("passwort fehlt in der SMTP-Config.")

    return SmtpConfig(
        smtp_host=host,
        smtp_port=int(d.get("smtp_port", 587)),
        benutzername=user,
        passwort=passwort,
        tls=bool(d.get("tls", True)),
        imap_host=d.get("imap_host", ""),
        imap_port=int(d.get("imap_port", 993)),
    )


def smtp_vorhanden(pfad: Path | None = None) -> bool:
    """True wenn SMTP-Config-Datei existiert und lesbar ist."""
    try:
        smtp_laden(pfad)
        return True
    except (FileNotFoundError, ValueError):
        return False

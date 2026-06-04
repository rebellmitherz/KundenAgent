"""Tests für product/setup/onboarding.py und smtp_store.py.

Keine echten Credentials. Alle input()/getpass()-Aufrufe werden gemockt.
Ausführen:
    PYTHONUTF8=1 python product/setup/test_onboarding.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Projekt-Root ins sys.path
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from product.setup.onboarding import (
    _maskieren,
    _ja_nein,
    setup_config,
    setup_smtp,
    main,
)
from product.setup.smtp_store import SmtpConfig, smtp_laden, smtp_vorhanden


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _ok(label: str) -> None:
    print(f"  ✓ {label}")

def _fail(label: str, detail: str = "") -> None:
    print(f"  ✗ {label}: {detail}")
    raise AssertionError(label)


# ── 1. _maskieren ────────────────────────────────────────────────────────────

class TestMaskieren(unittest.TestCase):

    def test_leer(self):
        assert _maskieren("") == "—", "leer sollte — sein"

    def test_kurz(self):
        assert _maskieren("ab") == "****"

    def test_normal(self):
        m = _maskieren("ABCDEFGH1234")
        assert m.endswith("1234"), f"erwartet ...1234, got {m}"
        assert m.startswith("•"), f"erwartet ••...1234, got {m}"
        assert "ABCDEFGH" not in m

    def test_genau_vier(self):
        assert _maskieren("abcd") == "****"


# ── 2. _ja_nein ──────────────────────────────────────────────────────────────

class TestJaNein(unittest.TestCase):

    def _yn(self, eingabe: str, default_ja: bool = False) -> bool:
        with patch("builtins.input", return_value=eingabe):
            return _ja_nein("Frage?", default_ja=default_ja)

    def test_ja(self):
        assert self._yn("j") is True

    def test_ja_lang(self):
        assert self._yn("ja") is True

    def test_nein(self):
        assert self._yn("n") is False

    def test_leer_default_nein(self):
        assert self._yn("", default_ja=False) is False

    def test_leer_default_ja(self):
        assert self._yn("", default_ja=True) is True

    def test_y_englisch(self):
        assert self._yn("y") is True


# ── 3. setup_config ──────────────────────────────────────────────────────────

class TestSetupConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ziel = Path(self.tmp.name) / "product_config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, inputs: list[str], secrets: list[str]) -> bool:
        """Führt setup_config mit vorbereiteten Antworten aus."""
        inputs_iter = iter(inputs)
        secrets_iter = iter(secrets)
        with (
            patch("builtins.input", side_effect=lambda p="": next(inputs_iter, "")),
            patch("product.setup.onboarding.getpass", side_effect=lambda p="": next(secrets_iter, "")),
        ):
            return setup_config(self.ziel)

    def test_normal_flow(self):
        """Vollständiger Happy-Path: alle Felder ausgefüllt, bestätigt."""
        ok = self._run(
            inputs=[
                "123456789",          # Chat-ID
                "../b2bbot",          # Engine-Pfad
                "data",               # Datenpfad
                "j",                  # Bestätigen
            ],
            secrets=[
                "testtoken12345",     # Bot-Token (getpass)
                "",                   # API-Key (leer = überspringen)
            ],
        )
        assert ok is True
        assert self.ziel.exists(), "Config-Datei wurde nicht erzeugt"
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["bot_token"] == "testtoken12345"
        assert d["owner_chat_id"] == "123456789"
        assert d["engine_dir"] == "../b2bbot"
        assert d["data_dir"] == "data"
        assert d["anthropic_api_key"] == ""

    def test_abbruch(self):
        """Nutzer sagt Nein bei Bestätigung → kein Schreiben."""
        ok = self._run(
            inputs=["123456789", "../b2bbot", "data", "nein", "n"],
            #                                               ^         ^
            #                                     ui_token?=nein  speichern?=n
            secrets=["testtoken12345", ""],
        )
        assert ok is False
        assert not self.ziel.exists(), "Config darf bei Abbruch nicht erzeugt werden"

    def test_ueberschreiben_abgelehnt(self):
        """Existierende Config + Nein → bleibt erhalten."""
        self.ziel.write_text('{"bot_token":"alt"}', encoding="utf-8")
        ok = self._run(
            inputs=["n"],   # Überschreiben? → nein
            secrets=[],
        )
        assert ok is False
        # Alte Config unverändert
        assert json.loads(self.ziel.read_text())["bot_token"] == "alt"

    def test_ueberschreiben_bestaetigt(self):
        """Existierende Config + Ja → wird überschrieben."""
        self.ziel.write_text('{"bot_token":"alt"}', encoding="utf-8")
        ok = self._run(
            inputs=["j",              # Überschreiben?
                    "987654321",      # Chat-ID
                    "../b2bbot",
                    "data",
                    "j"],             # Speichern?
            secrets=["neuertoken999", ""],
        )
        assert ok is True
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["bot_token"] == "neuertoken999"

    def test_mit_api_key(self):
        """Optionaler Anthropic-Key wird gespeichert."""
        ok = self._run(
            inputs=["111", "../b2bbot", "data", "j"],
            secrets=["tok123", "sk-ant-testkey"],
        )
        assert ok is True
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["anthropic_api_key"] == "sk-ant-testkey"

    def test_kein_token_pflichtfeld(self):
        """Leeres Token mit Pflichtfeld-Schleife: zweite Eingabe liefert Token."""
        # Erste getpass-Antwort = leer → Schleife, zweite = Token
        ok = self._run(
            inputs=["123", "../b2bbot", "data", "j"],
            secrets=["", "validtoken"],   # erst leer, dann ausgefüllt
        )
        assert ok is True
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["bot_token"] == "validtoken"


# ── 4. setup_smtp ────────────────────────────────────────────────────────────

class TestSetupSmtp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ziel = Path(self.tmp.name) / "product_smtp.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, inputs: list[str], secrets: list[str]) -> bool:
        inputs_iter = iter(inputs)
        secrets_iter = iter(secrets)
        with (
            patch("builtins.input", side_effect=lambda p="": next(inputs_iter, "")),
            patch("product.setup.onboarding.getpass", side_effect=lambda p="": next(secrets_iter, "")),
        ):
            return setup_smtp(self.ziel)

    def test_smtp_ueberspringen(self):
        ok = self._run(inputs=["n"], secrets=[])
        assert ok is False
        assert not self.ziel.exists()

    def test_smtp_normal(self):
        ok = self._run(
            inputs=[
                "j",                    # SMTP einrichten?
                "smtp.gmail.com",       # Host
                "587",                  # Port
                "test@example.com",     # User
                "y",                    # TLS
                "",                     # IMAP leer = überspringen
                "j",                    # Speichern?
            ],
            secrets=["geheimspass123"],
        )
        assert ok is True
        assert self.ziel.exists()
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["smtp_host"] == "smtp.gmail.com"
        assert d["smtp_port"] == 587
        assert d["benutzername"] == "test@example.com"
        assert d["passwort"] == "geheimspass123"
        assert d["tls"] is True
        assert d["imap_host"] == ""

    def test_smtp_mit_imap(self):
        ok = self._run(
            inputs=[
                "j",
                "smtp.example.com",
                "465",
                "user@example.com",
                "j",
                "imap.example.com",     # IMAP-Host
                "993",                  # IMAP-Port
                "j",
            ],
            secrets=["secretpass"],
        )
        assert ok is True
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["imap_host"] == "imap.example.com"
        assert d["imap_port"] == 993


# ── 5. SmtpConfig + smtp_laden ────────────────────────────────────────────────

class TestSmtpStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfad = Path(self.tmp.name) / "product_smtp.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _schreib(self, daten: dict) -> None:
        self.pfad.write_text(json.dumps(daten), encoding="utf-8")

    def test_laden_ok(self):
        self._schreib({
            "smtp_host": "smtp.test.de",
            "smtp_port": 587,
            "benutzername": "a@b.de",
            "passwort": "secret",
            "tls": True,
            "imap_host": "",
            "imap_port": 993,
        })
        cfg = smtp_laden(self.pfad)
        assert isinstance(cfg, SmtpConfig)
        assert cfg.smtp_host == "smtp.test.de"
        assert cfg.benutzername == "a@b.de"
        assert cfg.passwort == "secret"
        assert cfg.tls is True
        assert cfg.hat_imap() is False

    def test_fehlt(self):
        try:
            smtp_laden(self.pfad)
            assert False, "Sollte FileNotFoundError werfen"
        except FileNotFoundError:
            pass

    def test_ungueltig_json(self):
        self.pfad.write_text("keine json{{{", encoding="utf-8")
        try:
            smtp_laden(self.pfad)
            assert False, "Sollte ValueError werfen"
        except ValueError:
            pass

    def test_host_fehlt(self):
        self._schreib({"smtp_host": "", "benutzername": "x", "passwort": "y"})
        try:
            smtp_laden(self.pfad)
            assert False, "Sollte ValueError werfen"
        except ValueError as e:
            assert "smtp_host" in str(e).lower()

    def test_zusammenfassung_kein_passwort(self):
        self._schreib({
            "smtp_host": "smtp.test.de", "smtp_port": 587,
            "benutzername": "user@test.de", "passwort": "geheim",
            "tls": True, "imap_host": "", "imap_port": 993,
        })
        cfg = smtp_laden(self.pfad)
        z = cfg.zusammenfassung()
        assert "geheim" not in z, "Passwort darf nicht in Zusammenfassung erscheinen"
        assert "user@test.de" in z

    def test_vorhanden_true(self):
        self._schreib({
            "smtp_host": "smtp.x.de", "smtp_port": 587,
            "benutzername": "a@b.de", "passwort": "p",
            "tls": True, "imap_host": "", "imap_port": 993,
        })
        assert smtp_vorhanden(self.pfad) is True

    def test_vorhanden_false(self):
        assert smtp_vorhanden(self.pfad) is False


# ── 6. main() CLI ────────────────────────────────────────────────────────────

class TestMain(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_main_smtp_only(self):
        """--smtp Flag: überspringt Config-Wizard."""
        smtp_pfad = Path(self.tmp.name) / "smtp.json"
        with (
            patch("builtins.input", return_value="n"),   # SMTP überspringen
            patch("product.setup.onboarding.getpass", return_value=""),
        ):
            rc = main(["--smtp", "--smtp-datei", str(smtp_pfad)])
        # Abbruch = exit code 1, kein Crash
        assert rc in (0, 1)

    def test_main_keyboard_interrupt(self):
        """KeyboardInterrupt → sauberer Exit mit Code 1."""
        with patch("product.setup.onboarding.setup_config", side_effect=KeyboardInterrupt):
            rc = main(["--config", str(Path(self.tmp.name) / "cfg.json")])
        assert rc == 1


# ── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 58)
    print("  Schritt 9 — Onboarding-Tests")
    print("=" * 58)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestMaskieren, TestJaNein, TestSetupConfig,
                TestSetupSmtp, TestSmtpStore, TestMain]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print(f"  ALLE {result.testsRun} Tests GRUEN")
    else:
        print(f"  {len(result.failures)} Fehler, {len(result.errors)} Errors")
    sys.exit(0 if result.wasSuccessful() else 1)

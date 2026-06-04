"""Tests für Admin/Kunde-Trennung (Schritt 10).

Prüft:
  - Token-Check in _ist_admin()
  - 403 auf Admin-Endpunkte ohne Token
  - 200 auf Kunden-Endpunkte ohne Token
  - ui_token in Config geladen
  - onboarding schreibt ui_token

Ausführen:
    PYTHONUTF8=1 python product/setup/test_trennung.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, MagicMock

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from product.telegram.config import laden as config_laden, OperatorConfig


# ── 1. Config: ui_token wird geladen ────────────────────────────────────────

class TestConfigUiToken(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pfad = Path(self.tmp.name) / "product_config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _schreib(self, daten: dict) -> None:
        self.pfad.write_text(json.dumps(daten), encoding="utf-8")

    def test_ui_token_geladen(self):
        self._schreib({
            "bot_token": "tok123",
            "owner_chat_id": "111",
            "engine_dir": ".",
            "data_dir": "data",
            "ui_token": "mein-geheimer-token",
        })
        cfg = config_laden(self.pfad)
        assert cfg.ui_token == "mein-geheimer-token"

    def test_ui_token_leer_wenn_fehlt(self):
        self._schreib({
            "bot_token": "tok123",
            "owner_chat_id": "111",
            "engine_dir": ".",
            "data_dir": "data",
        })
        cfg = config_laden(self.pfad)
        assert cfg.ui_token == ""

    def test_ui_token_leer_string(self):
        self._schreib({
            "bot_token": "tok123",
            "owner_chat_id": "111",
            "engine_dir": ".",
            "data_dir": "data",
            "ui_token": "",
        })
        cfg = config_laden(self.pfad)
        assert cfg.ui_token == ""


# ── 2. Server: _ist_admin() Logik ───────────────────────────────────────────

class TestIstAdmin(unittest.TestCase):
    """Testet die _ist_admin-Methode durch direkte Instanziierung."""

    def _handler(self, token_in_config: str, token_in_header: str):
        """Erzeugt einen minimalen Handler-Stub."""
        import product.ui.server as srv
        old_token = srv._ui_token
        srv._ui_token = token_in_config
        try:
            handler = object.__new__(srv._Handler)
            handler.headers = {"X-Access-Token": token_in_header} if token_in_header else {}
            result = handler._ist_admin()
        finally:
            srv._ui_token = old_token
        return result

    def test_kein_token_konfiguriert_immer_admin(self):
        """Kein Token in Config → immer admin (localhost-only Schutz reicht)."""
        assert self._handler("", "") is True
        assert self._handler("", "irgendwas") is True

    def test_token_konfiguriert_richtig(self):
        assert self._handler("geheim123", "geheim123") is True

    def test_token_konfiguriert_falsch(self):
        assert self._handler("geheim123", "falsch") is False

    def test_token_konfiguriert_kein_header(self):
        assert self._handler("geheim123", "") is False


# ── 3. Server: Endpunkt-Klassifizierung ─────────────────────────────────────

class TestEndpunktKlassen(unittest.TestCase):

    def test_kunden_endpunkte_definiert(self):
        import product.ui.server as srv
        for ep in ["/", "/index.html", "/api/status", "/api/leads"]:
            assert ep in srv._KUNDEN_ENDPUNKTE, f"{ep} fehlt in _KUNDEN_ENDPUNKTE"

    def test_admin_endpunkte_definiert(self):
        import product.ui.server as srv
        for ep in ["/api/vorschau", "/api/setup/status",
                   "/api/setup/config", "/api/setup/smtp", "/api/freigabe"]:
            assert ep in srv._ADMIN_ENDPUNKTE, f"{ep} fehlt in _ADMIN_ENDPUNKTE"

    def test_keine_ueberschneidung(self):
        import product.ui.server as srv
        overlap = srv._KUNDEN_ENDPUNKTE & srv._ADMIN_ENDPUNKTE
        assert not overlap, f"Endpunkte in beiden Mengen: {overlap}"


# ── 4. Onboarding: ui_token in Config geschrieben ────────────────────────────

class TestOnboardingUiToken(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ziel = Path(self.tmp.name) / "product_config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, inputs: list[str], secrets_: list[str]) -> bool:
        inputs_iter = iter(inputs)
        secrets_iter = iter(secrets_)
        with (
            patch("builtins.input", side_effect=lambda p="": next(inputs_iter, "")),
            patch("product.setup.onboarding.getpass", side_effect=lambda p="": next(secrets_iter, "")),
        ):
            from product.setup.onboarding import setup_config
            return setup_config(self.ziel)

    def test_token_generiert(self):
        ok = self._run(
            inputs=[
                "123",           # Chat-ID
                "../b2bbot",     # Engine-Pfad
                "data",          # Datenpfad
                "",              # UI-Token generieren? [ENTER = ja]
                "j",             # Speichern?
            ],
            secrets_=["tok456", ""],
        )
        assert ok is True
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert "ui_token" in d
        assert len(d["ui_token"]) >= 16, "Generierter Token sollte mindestens 16 Zeichen haben"

    def test_token_nicht_generiert(self):
        ok = self._run(
            inputs=[
                "123",
                "../b2bbot",
                "data",
                "nein",          # Kein UI-Token
                "j",
            ],
            secrets_=["tok456", ""],
        )
        assert ok is True
        d = json.loads(self.ziel.read_text(encoding="utf-8"))
        assert d["ui_token"] == ""

    def test_token_einzigartig(self):
        """Zwei Läufe erzeugen verschiedene Token."""
        ziel2 = Path(self.tmp.name) / "cfg2.json"
        self._run(["123", ".", "data", "", "j"], ["t1", ""])
        from product.setup.onboarding import setup_config
        # zweiter Lauf in frischem Ziel
        inputs2 = iter(["123", ".", "data", "", "j"])
        secrets2 = iter(["t2", ""])
        with (
            patch("builtins.input", side_effect=lambda p="": next(inputs2, "")),
            patch("product.setup.onboarding.getpass", side_effect=lambda p="": next(secrets2, "")),
        ):
            setup_config(ziel2)
        t1 = json.loads(self.ziel.read_text())["ui_token"]
        t2 = json.loads(ziel2.read_text())["ui_token"]
        assert t1 != t2, "Zwei generierte Token müssen verschieden sein"


# ── Runner ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 58)
    print("  Schritt 10 — Admin/Kunde-Trennung Tests")
    print("=" * 58)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestConfigUiToken, TestIstAdmin,
                TestEndpunktKlassen, TestOnboardingUiToken]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print(f"  ALLE {result.testsRun} Tests GRUEN")
    else:
        print(f"  {len(result.failures)} Fehler, {len(result.errors)} Errors")
    sys.exit(0 if result.wasSuccessful() else 1)

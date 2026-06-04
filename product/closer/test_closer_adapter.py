"""Tests für product/closer/closer_adapter.py (Schritt 11).

Kein echtes ClouseAgent gestartet. Alle Subprocess-Aufrufe werden gemockt.
Ausführen:
    PYTHONUTF8=1 python product/closer/test_closer_adapter.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

from product.closer.closer_adapter import CloserAdapter, _enthaelt_secret


# ── 1. _enthaelt_secret ─────────────────────────────────────────────────────

class TestEnthaeltSecret(unittest.TestCase):

    def test_openai_key(self):
        assert _enthaelt_secret("OPENAI_API_KEY=sk-...") is True

    def test_anthropic_key(self):
        assert _enthaelt_secret("Using ANTHROPIC_API_KEY for auth") is True

    def test_normal_zeile(self):
        assert _enthaelt_secret("KAUFSIGNAL erkannt: Interesse") is False

    def test_leer(self):
        assert _enthaelt_secret("") is False

    def test_case_insensitiv(self):
        assert _enthaelt_secret("openai_api_key found") is True


# ── 2. Status ohne laufenden Prozess ────────────────────────────────────────

class TestStatusOhneProzess(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = CloserAdapter(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_gestoppt(self):
        s = self.adapter.status()
        assert s["laeuft"] is False
        assert s["pid"] is None

    def test_closer_nicht_verfuegbar(self):
        s = self.adapter.status()
        assert s["closer_verfuegbar"] is False

    def test_closer_verfuegbar_wenn_app_vorhanden(self):
        (Path(self.tmp.name) / "app.py").write_text("# stub")
        s = self.adapter.status()
        assert s["closer_verfuegbar"] is True

    def test_stoppen_wenn_nicht_laeuft(self):
        r = self.adapter.stoppen()
        assert r["ok"] is False

    def test_log_leer(self):
        assert self.adapter.log_lesen() == []


# ── 3. Starten — app.py fehlt ───────────────────────────────────────────────

class TestStartenOhneApp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = CloserAdapter(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_starten_ohne_app(self):
        r = self.adapter.starten()
        assert r["ok"] is False
        assert "app.py" in r["meldung"].lower() or "nicht gefunden" in r["meldung"].lower()


# ── 4. Starten mit gemocktem Subprozess ─────────────────────────────────────

class TestStartenMock(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.closer_dir = Path(self.tmp.name)
        (self.closer_dir / "app.py").write_text("# stub")
        self.adapter = CloserAdapter(self.closer_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _mock_prozess(self, exit_code=None):
        """Erzeugt einen Popen-Mock der noch läuft (poll() = None)."""
        p = MagicMock()
        p.pid = 12345
        p.poll.return_value = exit_code   # None = läuft noch
        p.stdout = StringIO("Zeile 1\nZeile 2\n")
        return p

    def test_starten_ok(self):
        mock_p = self._mock_prozess()
        with patch("subprocess.Popen", return_value=mock_p):
            r = self.adapter.starten()
        assert r["ok"] is True
        assert r["pid"] == 12345

    def test_starten_zweimal_verhindert(self):
        mock_p = self._mock_prozess()
        with patch("subprocess.Popen", return_value=mock_p):
            self.adapter.starten()
            r2 = self.adapter.starten()
        assert r2["ok"] is False
        assert "läuft bereits" in r2["meldung"].lower()

    def test_status_laeuft_nach_start(self):
        mock_p = self._mock_prozess()
        with patch("subprocess.Popen", return_value=mock_p):
            self.adapter.starten()
        s = self.adapter.status()
        assert s["laeuft"] is True
        assert s["pid"] == 12345

    def test_stoppen_nach_start(self):
        mock_p = self._mock_prozess()
        mock_p.wait.return_value = 0
        with patch("subprocess.Popen", return_value=mock_p):
            self.adapter.starten()
        r = self.adapter.stoppen()
        assert r["ok"] is True
        mock_p.terminate.assert_called_once()

    def test_status_gestoppt_nach_stoppen(self):
        mock_p = self._mock_prozess()
        mock_p.wait.return_value = 0
        with patch("subprocess.Popen", return_value=mock_p):
            self.adapter.starten()
        self.adapter.stoppen()
        s = self.adapter.status()
        assert s["laeuft"] is False

    def test_oserror_beim_starten(self):
        with patch("subprocess.Popen", side_effect=OSError("Gerät nicht gefunden")):
            r = self.adapter.starten()
        assert r["ok"] is False
        assert "fehlgeschlagen" in r["meldung"].lower()


# ── 5. Log-Puffer ────────────────────────────────────────────────────────────

class TestLogPuffer(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.closer_dir = Path(self.tmp.name)
        (self.closer_dir / "app.py").write_text("# stub")
        self.adapter = CloserAdapter(self.closer_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_log_lesen_limit(self):
        for i in range(50):
            self.adapter._log.append(f"Zeile {i}")
        assert len(self.adapter.log_lesen(limit=10)) == 10
        assert len(self.adapter.log_lesen(limit=100)) == 50

    def test_log_filtert_secrets(self):
        from product.closer.closer_adapter import _enthaelt_secret
        zeile_ok = "KAUFSIGNAL: Interesse gezeigt"
        zeile_bad = "OPENAI_API_KEY=sk-geheim"
        assert not _enthaelt_secret(zeile_ok)
        assert _enthaelt_secret(zeile_bad)

    def test_log_puffer_max_200(self):
        for i in range(250):
            self.adapter._log.append(f"Z{i}")
        assert len(self.adapter._log) == 200


# ── 6. Server-Endpunkte-Liste ────────────────────────────────────────────────

class TestServerEndpunkte(unittest.TestCase):

    def test_closer_endpunkte_in_admin_set(self):
        import product.ui.server as srv
        for ep in ["/api/closer/status", "/api/closer/log",
                   "/api/closer/starten", "/api/closer/stoppen"]:
            assert ep in srv._ADMIN_ENDPUNKTE, f"{ep} fehlt in _ADMIN_ENDPUNKTE"

    def test_closer_nicht_in_kunden_set(self):
        import product.ui.server as srv
        for ep in ["/api/closer/status", "/api/closer/starten"]:
            assert ep not in srv._KUNDEN_ENDPUNKTE


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 58)
    print("  Schritt 11 — Closer-Adapter Tests")
    print("=" * 58)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestEnthaeltSecret, TestStatusOhneProzess,
                TestStartenOhneApp, TestStartenMock,
                TestLogPuffer, TestServerEndpunkte]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    print()
    if result.wasSuccessful():
        print(f"  ALLE {result.testsRun} Tests GRUEN")
    else:
        print(f"  {len(result.failures)} Fehler, {len(result.errors)} Errors")
    sys.exit(0 if result.wasSuccessful() else 1)
